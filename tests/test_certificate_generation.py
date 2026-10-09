"""Certificate PDFs generated from the course template (issue, regenerate, lazy download)."""
import account_helpers
import certificate_helpers
from certificate_helpers import CERT_TEMPLATE_KEY, issue, pdf_text

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
make_lessons = account_helpers.make_lessons
complete = account_helpers.complete
earned = account_helpers.earned
cert_s3 = certificate_helpers.cert_s3
templated = certificate_helpers.templated


def test_issuing_generates_the_pdf_from_the_template(client, cert_s3, templated, admin_headers):
    account, _, course, _ = templated
    body = issue(client, admin_headers, account.actor_id, course.id).get_json()
    assert body["has_file"] is True and body["can_download"] is True
    data, content_type = cert_s3.objects[f"certificates/{body['cert_number']}.pdf"]
    assert content_type == "application/pdf"
    text = pdf_text(data)
    assert body["cert_number"] in text and "Bat Dorj" in text
    assert body["issued_at"][:4] in text and "#" not in text


def test_without_a_template_the_file_stays_a_staff_upload(client, cert_s3, earned,
                                                          admin_headers):
    account, headers, course, _ = earned
    body = issue(client, admin_headers, account.actor_id, course.id).get_json()
    assert body["has_file"] is False and body["can_download"] is False
    resp = client.get(f"/me/certificates/{body['cert_number']}/download", headers=headers)
    assert resp.status_code == 404 and resp.get_json()["error"] == "certificate_file_missing"


def test_first_download_generates_a_pdf_issued_before_the_template(
        client, db, cert_s3, earned, admin_headers):
    account, headers, course, _ = earned
    number = issue(client, admin_headers, account.actor_id, course.id).get_json()["cert_number"]
    course.cert_template_key = CERT_TEMPLATE_KEY
    db.session.commit()
    resp = client.get(f"/me/certificates/{number}/download", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["url"] == f"https://s3.test/certificates/{number}.pdf?expires=300"
    assert f"certificates/{number}.pdf" in cert_s3.objects


def test_staff_regenerate(client, db, cert_s3, templated, admin_headers):
    account, _, course, _ = templated
    cert = issue(client, admin_headers, account.actor_id, course.id).get_json()
    key = f"certificates/{cert['cert_number']}.pdf"
    del cert_s3.objects[key]
    resp = client.post(f"/admin/certificates/{cert['id']}/generate", headers=admin_headers)
    assert resp.status_code == 200 and resp.get_json()["has_file"] is True
    assert key in cert_s3.objects
    assert client.post("/admin/certificates/999/generate",
                       headers=admin_headers).status_code == 404


def test_regenerate_errors(client, db, cert_s3, templated, admin_headers):
    account, _, course, _ = templated
    cert_id = issue(client, admin_headers, account.actor_id, course.id).get_json()["id"]
    url = f"/admin/certificates/{cert_id}/generate"

    cert_s3.fail.add("upload")
    resp = client.post(url, headers=admin_headers)
    assert resp.status_code == 502 and resp.get_json()["error"] == "storage_error"
    cert_s3.fail.clear()

    from app.storage import read_template
    read_template.cache_clear()
    cert_s3.objects[CERT_TEMPLATE_KEY] = (b"not a pdf", "application/pdf")
    resp = client.post(url, headers=admin_headers)
    assert resp.status_code == 409 and resp.get_json()["error"] == "certificate_template_invalid"

    course.cert_template_key = None
    db.session.commit()
    resp = client.post(url, headers=admin_headers)
    assert resp.status_code == 409 and resp.get_json()["error"] == "certificate_template_missing"


def test_a_generation_failure_does_not_block_issuing(client, cert_s3, templated, admin_headers):
    account, _, course, _ = templated
    cert_s3.fail.add("download")
    resp = issue(client, admin_headers, account.actor_id, course.id)
    assert resp.status_code == 201 and resp.get_json()["has_file"] is False


def test_regenerate_needs_cohort_manage(client, make_staff, make_student):
    for headers in (make_staff("finance")[1], make_student()[1]):
        assert client.post("/admin/certificates/1/generate", headers=headers).status_code == 403
