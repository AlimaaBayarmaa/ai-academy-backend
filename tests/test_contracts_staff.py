"""/admin/contracts — staff list, detail, download and reset (``cohort:manage``)."""
import account_helpers
import contract_helpers
import pytest
from contract_helpers import sign

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
s3 = contract_helpers.s3
contract_course = contract_helpers.contract_course
signer = contract_helpers.signer


def test_list_materialises_and_filters(client, signer, admin_headers):
    a, _, enr_a, _ = signer()
    _, headers_b, enr_b, contract_b = signer(client=client)
    assert sign(client, headers_b, contract_b).status_code == 200

    # Unfiltered: only contracts that exist — a's has not been created yet.
    rows = client.get("/admin/contracts", headers=admin_headers).get_json()["contracts"]
    assert [r["enrollment_id"] for r in rows] == [enr_b.id]

    signed = client.get("/admin/contracts?status=signed",
                        headers=admin_headers).get_json()["contracts"]
    [row] = signed
    assert row["id"] == contract_b and row["has_file"] is True
    assert row["form_data"]["register"] == "УБ12345678" and row["balance"] == 600_000.0
    assert row["student_name"] == "Bat Дорж"

    by_course = client.get(f"/admin/contracts?course_id={enr_a.course_id}",
                           headers=admin_headers).get_json()["contracts"]
    assert [r["student_id"] for r in by_course] == [a.actor_id]


def test_bad_filters_are_400(client, admin_headers):
    resp = client.get("/admin/contracts?status=done", headers=admin_headers)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_status"
    resp = client.get("/admin/contracts?course_id=x", headers=admin_headers)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_course_id"


def test_detail_and_download(client, signer, admin_headers):
    _, headers, _, contract_id = signer(client=client)
    resp = client.get(f"/admin/contracts/{contract_id}/download", headers=admin_headers)
    assert resp.status_code == 409
    sign(client, headers, contract_id)
    body = client.get(f"/admin/contracts/{contract_id}", headers=admin_headers).get_json()
    assert body["status"] == "signed"
    link = client.get(f"/admin/contracts/{contract_id}/download",
                      headers=admin_headers).get_json()
    assert link["url"].startswith("https://s3.test/contracts/")
    assert client.get("/admin/contracts/999999", headers=admin_headers).status_code == 404


def test_reset_lets_the_student_sign_again(client, s3, signer, admin_headers):
    _, headers, _, contract_id = signer(client=client)
    sign(client, headers, contract_id)
    signed_keys = [k for k in s3.objects if k.startswith("contracts/")]

    resp = client.post(f"/admin/contracts/{contract_id}/reset", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "pending" and body["signed_at"] is None and body["has_file"] is False
    assert sorted(s3.deleted) == sorted(signed_keys)

    detail = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()
    assert detail["can_sign"] is True and detail["form"]["register"] == "УБ12345678"
    assert sign(client, headers, contract_id).status_code == 200

    resp = client.post(f"/admin/contracts/{contract_id}/reset", headers=admin_headers)
    assert resp.status_code == 200
    resp = client.post(f"/admin/contracts/{contract_id}/reset", headers=admin_headers)
    assert resp.status_code == 409 and resp.get_json()["error"] == "not_signed"


def test_staff_permission_required(client, make_staff, make_student, make_teacher):
    for headers in (make_staff("finance")[1], make_student()[1], make_teacher()[1]):
        assert client.get("/admin/contracts", headers=headers).status_code == 403


def test_reset_keeps_the_file_when_the_database_write_fails(client, db, s3, signer,
                                                            admin_headers, monkeypatch):
    _, headers, _, contract_id = signer(client=client)
    sign(client, headers, contract_id)

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db.session, "commit", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/admin/contracts/{contract_id}/reset", headers=admin_headers)
    monkeypatch.undo()
    assert s3.deleted == []


def test_a_resign_writes_new_files_the_reset_cannot_delete(client, s3, signer, admin_headers):
    _, headers, _, contract_id = signer(client=client)
    sign(client, headers, contract_id)
    first = {k for k in s3.objects if k.startswith("contracts/")}
    client.post(f"/admin/contracts/{contract_id}/reset", headers=admin_headers)
    sign(client, headers, contract_id)
    second = {k for k in s3.objects if k.startswith("contracts/")}
    assert len(second) == 2 and not first & second


def test_a_removed_template_still_lets_a_cancellation_through(client, db, signer,
                                                              admin_headers):
    _, headers, enr, contract_id = signer(client=client)
    enr.cohort.course.contract_template_key = None
    enr.status = "cancelled"
    db.session.commit()
    [row] = client.get("/me/contracts", headers=headers).get_json()["contracts"]
    assert row["status"] == "cancelled"
