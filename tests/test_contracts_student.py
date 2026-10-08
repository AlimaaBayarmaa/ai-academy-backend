"""GET /me/contracts[/<id>], preview and download — the student's view of their contracts."""
import account_helpers
import contract_helpers
from contract_helpers import pdf_text

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
s3 = contract_helpers.s3
contract_course = contract_helpers.contract_course
signer = contract_helpers.signer


def _list(client, headers):
    return client.get("/me/contracts", headers=headers).get_json()["contracts"]


def test_enrollment_in_a_course_with_a_template_gets_a_pending_contract(client, signer):
    _, headers, enr, _ = signer()
    [row] = _list(client, headers)
    assert row["status"] == "pending" and row["enrollment_id"] == enr.id
    assert row["contract_number"].startswith("AIAA-C-") and row["contract_number"][-5:] == "00001"
    assert row["can_view"] is True and row["can_sign"] is True and row["is_current"] is True
    assert row["course"]["title"]["mn"] == "Удирдагчид" and row["cohort"]["id"] == enr.cohort_id
    assert row["signed_at"] is None and row["document_url"] is None
    # Listing again does not make a second one.
    assert [r["id"] for r in _list(client, headers)] == [row["id"]]


def test_no_contract_without_a_pdf_template(client, s3, make_student, make_course, make_cohort,
                                            enroll):
    account, headers = make_student()
    enroll(account.actor_id, make_cohort(course=make_course()))
    enroll(account.actor_id, make_cohort(course=make_course(
        contract_template_key="courses/9/contract_template.docx")))
    assert _list(client, headers) == []


def test_numbers_count_up_across_students(client, signer):
    numbers = [_list(client, signer()[1])[0]["contract_number"][-5:] for _ in range(3)]
    assert numbers == ["00001", "00002", "00003"]


def test_cancelled_enrollment_cancels_a_pending_contract_and_reactivation_restores_it(
        client, db, signer):
    _, headers, enr, contract_id = signer(client=client)
    enr.status = "cancelled"
    db.session.commit()
    [row] = _list(client, headers)
    assert row["status"] == "cancelled" and row["cancelled_at"] is not None
    assert row["can_sign"] is False and row["can_view"] is False and row["is_current"] is False
    enr.status = "active"
    db.session.commit()
    [row] = _list(client, headers)
    assert row["status"] == "pending" and row["cancelled_at"] is None


def test_detail_prefills_the_form_and_states_the_rules(client, signer):
    account, headers, enr, contract_id = signer(client=client)
    body = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()
    form = body["form"]
    assert (form["last_name"], form["first_name"]) == ("Дорж", "Bat")
    assert form["phone"] == "99112233" and form["email"] == account.email
    assert form["register"] == "" and form["guardian_relation"] == ""
    assert body["rules"]["guardian_required"] is False
    assert body["rules"]["final_payment_date_required"] is True
    assert body["rules"]["final_payment_date_max"] == enr.cohort.end_date.isoformat()
    assert body["finance"] == {"total_due": 1_000_000.0, "total_paid": 400_000.0,
                               "balance": 600_000.0, "discount_percent": 0, "currency": "MNT"}
    assert body["document"] == {"format": "pdf", "preview": f"/me/contracts/{contract_id}/preview",
                                "download": None}


def test_junior_contract_needs_a_guardian_and_prefills_the_parent_phone(client, db, signer):
    from app.models import Student

    account, headers, _, contract_id = signer(level="junior", client=client)
    db.session.get(Student, account.actor_id).parent_phone = "88001122"
    db.session.commit()
    body = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()
    assert body["rules"]["guardian_required"] is True
    assert body["form"]["phone"] == "88001122"


def test_discount_is_off_the_list_price_and_no_ledger_means_the_full_price(client, signer):
    _, headers, _, contract_id = signer(due=800_000, paid=800_000, client=client)
    finance = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()["finance"]
    assert finance["discount_percent"] == 20 and finance["balance"] == 0
    _, headers, _, contract_id = signer(due=None, client=client)
    finance = client.get(f"/me/contracts/{contract_id}", headers=headers).get_json()["finance"]
    assert (finance["total_due"], finance["total_paid"], finance["balance"]) == (
        1_000_000.0, 0.0, 1_000_000.0)


def test_another_students_contract_is_404(client, signer, make_student):
    _, _, _, contract_id = signer(client=client)
    _, other = make_student()
    for method, path in (("get", ""), ("post", "/preview"), ("post", "/sign"),
                         ("get", "/download")):
        resp = getattr(client, method)(f"/me/contracts/{contract_id}{path}", headers=other,
                                       json={})
        assert resp.status_code == 404 and resp.get_json()["error"] == "contract_not_found"
    assert client.get("/me/contracts/abc", headers=other).status_code == 404


def test_students_only(client, make_teacher, admin_headers):
    assert client.get("/me/contracts").status_code == 401
    assert client.get("/me/contracts", headers=make_teacher()[1]).status_code == 403
    assert client.get("/me/contracts", headers=admin_headers).status_code == 403


def test_preview_fills_the_template_without_saving(client, s3, signer):
    _, headers, _, contract_id = signer(client=client)
    resp = client.post(f"/me/contracts/{contract_id}/preview", headers=headers,
                       json={"form": {"last_name": "Дорж", "register": "уб12345678"}})
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    text = pdf_text(resp.data)
    assert "ДОРЖ" in text and "УБ12345678" in text and "УДИРДАГЧИД" in text
    assert "600,000₮" in text or "600,000" in text
    assert "#last_name" not in text and "#signature" not in text
    assert [k for k in s3.objects if k.startswith("contracts/")] == []


def test_preview_without_a_template_object_is_a_storage_error(client, s3, signer):
    _, headers, _, contract_id = signer(client=client)
    s3.fail.add("download")
    resp = client.post(f"/me/contracts/{contract_id}/preview", headers=headers, json={})
    assert resp.status_code == 502 and resp.get_json()["error"] == "storage_error"


def test_a_template_that_is_not_a_pdf_is_409(client, s3, signer):
    _, headers, _, contract_id = signer(client=client)
    s3.objects[contract_helpers.TEMPLATE_KEY] = (b"not a pdf", "application/pdf")
    resp = client.post(f"/me/contracts/{contract_id}/preview", headers=headers, json={})
    assert resp.status_code == 409 and resp.get_json()["error"] == "contract_template_invalid"


def test_download_before_signing_is_409(client, signer):
    _, headers, _, contract_id = signer(client=client)
    resp = client.get(f"/me/contracts/{contract_id}/download", headers=headers)
    assert resp.status_code == 409 and resp.get_json()["error"] == "not_signed"
