"""A class's certificates at once, the student's certificate list, the QR page, names."""
from datetime import date

import account_helpers
import certificate_helpers
from certificate_helpers import CERT_TEMPLATE_KEY

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
make_lessons = account_helpers.make_lessons
complete = account_helpers.complete
earned = account_helpers.earned
cert_s3 = certificate_helpers.cert_s3


def _class(make_student, make_course, make_cohort, enroll, make_lessons, complete,
           make_ledger):
    """A cohort with one eligible student, one who is not, and one already certified."""
    course = make_course(title_en="Leaders", cert_template_key=CERT_TEMPLATE_KEY)
    cohort = make_cohort(course=course)
    lessons = make_lessons(course, 1)
    students = []
    for done in (True, False, True):
        account, headers = make_student(last_name="Дорж")
        enr = enroll(account.actor_id, cohort)
        make_ledger(enr, due=100, paid=100)
        if done:
            complete(enr, lessons)
        students.append((account, headers))
    return course, cohort, students


def _issue_class(client, headers, cohort, **payload):
    return client.post(f"/admin/cohorts/{cohort.id}/certificates", headers=headers,
                       json=payload)


def test_issue_a_whole_class(client, cert_s3, admin_headers, make_student, make_course,
                             make_cohort, enroll, make_lessons, complete, make_ledger):
    course, cohort, students = _class(make_student, make_course, make_cohort, enroll,
                                      make_lessons, complete, make_ledger)
    ready, behind, certified = (a.actor_id for a, _ in students)
    certificate_helpers.issue(client, admin_headers, certified, course.id)

    body = _issue_class(client, admin_headers, cohort).get_json()
    assert body["cohort_id"] == cohort.id and body["course_id"] == course.id
    assert [c["student_id"] for c in body["issued"]] == [ready]
    assert body["issued"][0]["has_file"] is True
    assert [c["student_id"] for c in body["existing"]] == [certified]
    [skip] = body["skipped"]
    assert skip["student_id"] == behind and skip["error"] == "not_eligible"
    assert skip["requirements"]["lessons_completed"]["done"] is False

    again = _issue_class(client, admin_headers, cohort).get_json()
    assert again["issued"] == [] and len(again["existing"]) == 2

    forced = _issue_class(client, admin_headers, cohort, force=True,
                          student_ids=[behind]).get_json()
    assert [c["student_id"] for c in forced["issued"]] == [behind]
    assert forced["existing"] == [] and forced["skipped"] == []


def test_issue_class_validation(client, make_cohort, admin_headers, make_staff):
    cohort = make_cohort()
    resp = _issue_class(client, admin_headers, cohort, student_ids="1")
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_student_ids"
    resp = client.post("/admin/cohorts/999999/certificates", headers=admin_headers, json={})
    assert resp.status_code == 404 and resp.get_json()["error"] == "cohort_not_found"
    assert _issue_class(client, make_staff("finance")[1], cohort).status_code == 403


def test_my_certificates_one_card_per_course(client, cert_s3, admin_headers, earned,
                                             make_course, make_cohort, enroll):
    account, headers, course, enr = earned
    other = make_course(title_en="Other")
    enroll(account.actor_id, make_cohort(course=other))
    certificate_helpers.issue(client, admin_headers, account.actor_id, course.id)

    cards = client.get("/me/certificates", headers=headers).get_json()["certificates"]
    by_course = {c["course"]["id"]: c for c in cards}
    assert set(by_course) == {course.id, other.id}
    mine = by_course[course.id]
    assert mine["status"] == "issued" and mine["cohort"]["id"] == enr.cohort_id
    assert mine["certificate"]["cert_number"].startswith("AIAA-")
    assert set(mine["requirements"]) == {"lessons_completed", "quizzes_passed",
                                         "payment_cleared"}
    assert by_course[other.id]["status"] == "not_eligible"
    assert by_course[other.id]["certificate"] is None


def test_my_certificates_keeps_an_issued_one_after_the_enrollment_ends(
        client, db, cert_s3, admin_headers, earned):
    account, headers, course, enr = earned
    certificate_helpers.issue(client, admin_headers, account.actor_id, course.id)
    enr.status = "cancelled"
    db.session.commit()
    [card] = client.get("/me/certificates", headers=headers).get_json()["certificates"]
    assert card["status"] == "issued" and card["cohort"] is None


def test_my_certificates_access(client, make_student, make_teacher):
    assert client.get("/me/certificates", headers=make_student()[1]).get_json() == {
        "certificates": []}
    assert client.get("/me/certificates").status_code == 401
    assert client.get("/me/certificates", headers=make_teacher()[1]).status_code == 403


def test_the_qr_opens_an_html_page(client, cert_s3, admin_headers, earned):
    account, _, course, _ = earned
    cert = certificate_helpers.issue(client, admin_headers, account.actor_id,
                                     course.id).get_json()
    html = {"Accept": "text/html,application/xhtml+xml"}
    page = client.get(cert["verify_url"].removeprefix("http://testserver"), headers=html)
    assert page.status_code == 200 and page.mimetype == "text/html"
    assert "Verified certificate" in page.get_data(as_text=True)
    assert "Bat Dorj" in page.get_data(as_text=True)
    hidden = client.get(f"/certificates/verify/{cert['cert_number']}", headers=html)
    assert "Bat Dorj" not in hidden.get_data(as_text=True)
    missing = client.get("/certificates/verify/AIAA-2026-99999", headers=html)
    assert missing.status_code == 404 and "not found" in missing.get_data(as_text=True)


def test_names_and_dates_print_in_english():
    from app.services.certificates.pdf import full_name, long_date, transliterate

    assert full_name("Болор-Эрдэнэ", "Батцэнгэл") == "Bolor-Erdene Battsengel"
    assert full_name("Цэцэг (Asral egch)", "Өлзий /Uugii") == "Tsetseg Olzii"
    assert transliterate("Khas-Erdene") == "Khas-Erdene"
    assert long_date(date(2026, 10, 9)) == "October 9, 2026"


def test_the_sample_qr_is_found_and_replaced():
    import io

    from pypdf import PdfReader

    from app import pdftools
    from app.services.certificates.pdf import qr

    data = certificate_helpers.cert_template_pdf()
    page = PdfReader(io.BytesIO(data)).pages[0]
    box = qr.find_box(page, pdftools.read_pages(data)[0], 842, 595)
    assert [round(v) for v in box] == [90, 90, 161, 161]
    plain = certificate_helpers.cert_template_pdf(qr=False)
    assert qr.find_box(PdfReader(io.BytesIO(plain)).pages[0],
                       pdftools.read_pages(plain)[0], 842, 595) is None
