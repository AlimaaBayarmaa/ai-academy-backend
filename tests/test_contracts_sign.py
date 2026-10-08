"""POST /me/contracts/<id>/sign — agree, draw a signature, get the signed PDF."""
import account_helpers
import contract_helpers
import pytest
from contract_helpers import good_form, guardian, pdf_text, sign, signature_png, stored

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
s3 = contract_helpers.s3
contract_course = contract_helpers.contract_course
signer = contract_helpers.signer


def _error(resp):
    return resp.status_code, resp.get_json()["error"]


def test_signing_stores_the_pdf_and_signature_and_freezes_the_money(client, db, s3, signer):
    from app.models import StudentLedger

    _, headers, enr, contract_id = signer(client=client)
    resp = sign(client, headers, contract_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "signed" and body["signed_at"] is not None
    assert body["can_sign"] is False and body["can_view"] is True
    assert body["document_url"] == f"/me/contracts/{contract_id}/download"
    assert body["form"]["register"] == "УБ12345678"  # letters upper-cased

    number = body["contract_number"]
    pdf_key, data = stored(s3, contract_id, ".pdf")
    sig_key, _ = stored(s3, contract_id, "_signature.png")
    assert pdf_key.startswith(f"contracts/{contract_id}/{number}_")
    assert s3.objects[pdf_key][1] == "application/pdf" and s3.objects[sig_key][1] == "image/png"
    text = pdf_text(data)
    assert number in text and "ДОРЖ" in text and "400,000" in text and "#signature" not in text

    # Later payments do not rewrite what was signed.
    ledger = StudentLedger.query.filter_by(enrollment_id=enr.id).one()
    ledger.total_paid, ledger.balance = 1_000_000, 0
    db.session.commit()
    finance = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()["finance"]
    assert finance["total_paid"] == 400_000.0 and finance["balance"] == 600_000.0

    link = client.get(f"/me/contracts/{contract_id}/download", headers=headers).get_json()
    assert link["url"] == f"https://s3.test/{pdf_key}?expires=300" and link["expires_at"]


def test_signing_twice_is_409_and_preview_is_closed(client, signer):
    _, headers, _, contract_id = signer(client=client)
    assert sign(client, headers, contract_id).status_code == 200
    assert _error(sign(client, headers, contract_id)) == (409, "already_signed")
    resp = client.post(f"/me/contracts/{contract_id}/preview", headers=headers, json={})
    assert _error(resp) == (409, "already_signed")


def test_cancelled_enrollment_cannot_sign(client, db, signer):
    _, headers, enr, contract_id = signer(client=client)
    enr.status = "cancelled"
    db.session.commit()
    assert _error(sign(client, headers, contract_id)) == (409, "contract_cancelled")


@pytest.mark.parametrize("agreed", [False, None, "yes"])
def test_agreement_is_required(client, signer, agreed):
    _, headers, _, contract_id = signer(client=client)
    resp = sign(client, headers, contract_id, agreed=agreed)
    assert _error(resp) == (400, "agreement_required")


@pytest.mark.parametrize("signature,code", [
    ("", "signature_required"),
    ("not-base64!!", "invalid_signature"),
    ("data:image/png;base64,aGVsbG8=", "invalid_signature"),
])
def test_signature_must_be_an_image(client, signer, signature, code):
    _, headers, _, contract_id = signer(client=client)
    assert _error(sign(client, headers, contract_id, signature=signature)) == (400, code)


def test_field_errors_are_listed_per_field(client, signer):
    _, headers, _, contract_id = signer(client=client)
    form = good_form(last_name="Dorj", register="AB12345678", phone="9911",
                     email="nope", final_payment_date="2001-01-01", address="")
    resp = sign(client, headers, contract_id, form=form)
    assert _error(resp) == (400, "invalid_fields")
    assert resp.get_json()["fields"] == {
        "last_name": "cyrillic_only", "register": "invalid_format", "phone": "invalid_format",
        "email": "invalid_format", "final_payment_date": "out_of_range", "address": "required",
    }


def test_payment_date_must_fall_before_the_cohort_ends(client, signer):
    _, headers, _, contract_id = signer(client=client)
    resp = sign(client, headers, contract_id, form=good_form(final_payment_date="2030-01-01"))
    assert resp.get_json()["fields"] == {"final_payment_date": "out_of_range"}


def test_junior_needs_the_guardian_block(client, signer):
    _, headers, _, contract_id = signer(level="junior", client=client)
    resp = sign(client, headers, contract_id)
    assert set(resp.get_json()["fields"]) == {
        "guardian_relation", "guardian_last_name", "guardian_first_name", "guardian_register"}
    resp = sign(client, headers, contract_id, form=good_form(**guardian()))
    assert resp.status_code == 200
    assert resp.get_json()["form"]["guardian_register"] == "УБ87654321"


def test_nothing_owed_means_no_payment_date(client, signer):
    _, headers, _, contract_id = signer(due=1_000_000, paid=1_000_000, client=client)
    resp = sign(client, headers, contract_id, form=good_form(final_payment_date=""))
    assert resp.status_code == 200


def test_storage_failure_leaves_it_pending(client, s3, signer):
    _, headers, _, contract_id = signer(client=client)
    s3.fail.add("upload")
    assert _error(sign(client, headers, contract_id)) == (502, "storage_error")
    body = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()
    assert body["status"] == "pending" and body["can_sign"] is True


def test_oversized_signature_is_413(client, signer):
    _, headers, _, contract_id = signer(client=client)
    huge = "data:image/png;base64," + "A" * (3 * 1024 * 1024)
    assert _error(sign(client, headers, contract_id, signature=huge)) == (
        413, "signature_too_large")


def test_signature_without_data_url_prefix_is_accepted(client, signer):
    _, headers, _, contract_id = signer(client=client)
    bare = signature_png().split(",", 1)[1]
    assert sign(client, headers, contract_id, signature=bare).status_code == 200


def test_an_ended_cohort_does_not_cap_the_payment_date(client, db, signer):
    from datetime import date, timedelta

    _, headers, enr, contract_id = signer(client=client)
    enr.cohort.end_date = date.today() - timedelta(days=1)
    db.session.commit()
    body = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()
    assert body["rules"]["final_payment_date_max"] is None
    assert sign(client, headers, contract_id).status_code == 200


def test_a_blank_signature_pad_is_refused(client, signer):
    _, headers, _, contract_id = signer(client=client)
    blank = signature_png(ink=None)
    assert _error(sign(client, headers, contract_id, signature=blank)) == (
        400, "empty_signature")


def test_a_huge_canvas_is_scaled_down(client, s3, signer):
    import io

    from PIL import Image

    _, headers, _, contract_id = signer(client=client)
    png = signature_png(4000, 2000, ink=(100, 900, 3900, 1100))
    assert sign(client, headers, contract_id, signature=png).status_code == 200
    _, data = stored(s3, contract_id, "_signature.png")
    small = Image.open(io.BytesIO(data))
    assert small.width * small.height <= 600_000 and small.mode == "RGBA"


def test_signed_contract_offers_download_not_preview_and_keeps_email_case(client, s3, signer):
    _, headers, _, contract_id = signer(client=client)
    body = sign(client, headers, contract_id, form=good_form(email="Bat.Dorj@Mail.mn")).get_json()
    assert body["document"]["preview"] is None
    assert body["document"]["download"] == f"/me/contracts/{contract_id}/download"
    _, data = stored(s3, contract_id, ".pdf")
    assert "Bat.Dorj@Mail.mn" in pdf_text(data)


def test_a_png_declaring_huge_dimensions_is_refused_before_decoding(client, signer):
    import base64

    _, headers, _, contract_id = signer(client=client)
    header = (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
              + (20000).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00" + b"\x00" * 64)
    bomb = "data:image/png;base64," + base64.b64encode(header).decode()
    assert _error(sign(client, headers, contract_id, signature=bomb)) == (
        413, "signature_too_large")


def test_a_jpeg_is_not_a_signature(client, signer):
    _, headers, _, contract_id = signer(client=client)
    jpeg = signature_png(fmt="jpeg")
    assert _error(sign(client, headers, contract_id, signature=jpeg)) == (
        400, "invalid_signature")
