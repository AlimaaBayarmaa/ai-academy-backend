"""Edge cases from review: odd templates, re-uploads, shared XObjects, old links."""
import io

import account_helpers
import admin_course_helpers
import certificate_helpers
from certificate_helpers import CERT_TEMPLATE_KEY, issue, pdf_text

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
make_lessons = account_helpers.make_lessons
complete = account_helpers.complete
earned = account_helpers.earned
cert_s3 = certificate_helpers.cert_s3
templated = certificate_helpers.templated
s3 = admin_course_helpers.s3
editor = admin_course_helpers.editor


def _shapes(data):
    from pdfminer.layout import LTCurve, LTFigure, LTRect

    from app import pdftools

    def walk(items):
        for item in items:
            if isinstance(item, LTFigure):
                yield from walk(item)
            elif isinstance(item, (LTRect, LTCurve)):
                yield item

    return list(walk(pdftools.read_pages(data)[0]))


def test_an_unexpected_fill_error_keeps_the_issue_and_answers_409(
        client, cert_s3, templated, admin_headers, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("/XObject")

    monkeypatch.setattr("app.services.certificates.generation.fill_certificate", broken)
    account, _, course, _ = templated
    resp = issue(client, admin_headers, account.actor_id, course.id)
    assert resp.status_code == 201 and resp.get_json()["has_file"] is False
    resp = client.post(f"/admin/certificates/{resp.get_json()['id']}/generate",
                       headers=admin_headers)
    assert resp.status_code == 409 and resp.get_json()["error"] == "certificate_template_invalid"


def test_reuploading_a_template_under_the_same_name_is_a_new_version(
        client, db, s3, editor, make_course):
    course = make_course()
    before = course.updated_at
    for _ in range(2):
        resp = admin_course_helpers._upload(client, editor, course.id)
        assert resp.status_code == 200
    db.session.refresh(course)
    assert course.updated_at > before


def test_a_non_ascii_code_is_just_a_wrong_code(client, cert_s3, earned, admin_headers):
    account, _, course, _ = earned
    number = issue(client, admin_headers, account.actor_id, course.id).get_json()["cert_number"]
    resp = client.get(f"/certificates/verify/{number}?code=%C3%A9")
    assert resp.status_code == 200 and resp.get_json()["details_hidden"] is True


def test_links_stored_before_the_code_still_show_the_name(client, db, cert_s3, earned,
                                                          admin_headers):
    from app.models import Certificate

    account, headers, course, _ = earned
    number = issue(client, admin_headers, account.actor_id, course.id).get_json()["cert_number"]
    row = Certificate.query.filter_by(cert_number=number).one()
    row.verify_url = f"http://testserver/certificates/verify/{number}"  # an old row
    db.session.commit()
    url = client.get(f"/me/courses/{course.slug}/certificate",
                     headers=headers).get_json()["certificate"]["verify_url"]
    assert client.get(url.removeprefix("http://testserver")).get_json()["student_name"]


def _form_template(times=1, with_outline=True) -> bytes:
    """``#date`` drawn inside a Form XObject (as Canva does), optionally with its
    visible outline as a filled shape, and the form drawn ``times`` times."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(842, 595))
    c.beginForm("cert")
    c.setFont("Helvetica-BoldOblique", 17)
    c.drawString(400, 40, "#date")
    if with_outline:
        c.rect(402, 42, 30, 8, stroke=0, fill=1)  # stands in for the glyph outlines
    c.endForm()
    for n in range(times):
        c.saveState()
        c.translate(0, 300 * n)
        c.doForm("cert")
        c.restoreState()
    c.save()
    return buf.getvalue()


def _fill(template):
    from datetime import date

    from app.services.certificates.pdf import fill_certificate

    return fill_certificate(template, number="AIAA-2026-00001", first_name="Bat",
                            last_name="Dorj", issued_on=date(2026, 10, 9),
                            verify_url="https://x/verify")


def test_outlines_inside_a_form_xobject_are_erased():
    assert len(_shapes(_form_template())) == 1
    out = _fill(_form_template())
    assert _shapes(out) == [] and "#date" not in pdf_text(out)
    assert "October 9, 2026" in pdf_text(out)


def test_a_form_drawn_twice_is_cleaned_once_everywhere():
    text = pdf_text(_fill(_form_template(times=2, with_outline=False)))
    assert "#date" not in text and text.count("October 9, 2026") == 2


def test_contracts_keep_line_art_under_a_placeholder():
    from datetime import date

    from reportlab.pdfgen import canvas

    from app.services.contracts import fields
    from app.services.contracts.pdf import fill_contract

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.setFont("Helvetica", 11)
    c.drawString(40, 780, "#last_name")
    c.rect(40, 777, 50, 1, stroke=0, fill=1)  # the field's underline
    c.save()
    values = fields.build_values(fields.clean({"last_name": "Дорж"}), contract_number="1",
                                 programme="P", finance={"total_paid": 0, "balance": 0,
                                                         "discount_percent": 0},
                                 today=date(2026, 10, 9))
    out = fill_contract(buf.getvalue(), values)
    dark = [s for s in _shapes(out) if s.non_stroking_color in (0, (0,), (0, 0, 0))]
    assert len(dark) == 1


def test_a_class_parses_the_template_once(client, cert_s3, admin_headers, make_student,
                                          make_course, make_cohort, enroll, monkeypatch):
    from app import pdftools
    from app.services.certificates import generation

    generation._LAYOUTS.clear()
    calls = []
    real = pdftools.read_pages
    monkeypatch.setattr(pdftools, "read_pages", lambda data: calls.append(1) or real(data))
    course = make_course(cert_template_key=CERT_TEMPLATE_KEY, price_amount=0)
    cohort = make_cohort(course=course)
    for _ in range(3):
        enroll(make_student()[0].actor_id, cohort)
    body = client.post(f"/admin/cohorts/{cohort.id}/certificates", headers=admin_headers,
                       json={"force": True}).get_json()
    assert len(body["issued"]) == 3 and all(c["has_file"] for c in body["issued"])
    assert len(calls) == 1


def test_a_held_certificate_shows_even_for_a_non_public_course(client, db, cert_s3, earned,
                                                               admin_headers):
    account, headers, course, _ = earned
    issue(client, admin_headers, account.actor_id, course.id)
    course.status = "draft"
    db.session.commit()
    [card] = client.get("/me/certificates", headers=headers).get_json()["certificates"]
    assert card["status"] == "issued"
