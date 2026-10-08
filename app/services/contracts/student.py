"""The student's side: list, detail, preview, sign, download (``/me/contracts``).

Same four steps as the ``ai-asia-contract`` web page — check details, preview
the PDF, agree + draw a signature, get the signed PDF — over JSON. Another
student's contract answers 404, like every other ``/me`` resource.
"""
from __future__ import annotations

import io
import uuid
from datetime import timedelta

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import ACTOR_STUDENT, AuthAccount, StudentContract
from app.storage import S3StorageError, build_key, presigned_url, upload_fileobj
from app.timeutil import iso, utcnow

from ..errors import ServiceError
from ..learning.path import today as ub_today  # the Ulaanbaatar calendar day
from ..params import parse_id
from . import core, fields
from .pdf import MAX_DECODE_PIXELS, SignatureError, prepare_signature

# Relationships every listed contract serialises — loaded in one go, not per row.
LIST_LOADS = (selectinload(StudentContract.course), selectinload(StudentContract.cohort),
              selectinload(StudentContract.enrollment))
NEWEST_FIRST = (StudentContract.created_at.desc(), StudentContract.id.desc())
# selectin, not joined: Postgres refuses FOR UPDATE across an outer join.
OWN_LOADS = LIST_LOADS + (selectinload(StudentContract.student),)
DOWNLOAD_TTL = 300  # seconds a pre-signed link stays valid
MAX_SIGNATURE_BYTES = 2 * 1024 * 1024


def _summary(contract: StudentContract) -> dict:
    data = contract.to_dict()
    signed = contract.has_document
    template = core.has_pdf_template(contract.course)
    data.update({
        "can_view": signed or (contract.status == "pending" and template),
        "can_sign": contract.status == "pending" and template
        and contract.enrollment.status == "active",
        "is_current": contract.status != "cancelled",
        "document_url": f"/me/contracts/{contract.id}/download" if signed else None,
    })
    return data


def list_contracts(student_id: int) -> dict:
    core.sync(student_id=student_id)
    rows = (StudentContract.query.filter_by(student_id=student_id).options(*LIST_LOADS)
            .order_by(*NEWEST_FIRST))
    return {"contracts": [_summary(c) for c in rows]}


def _own(student_id, contract_id, *, lock=False) -> StudentContract:
    """The student's contract, or 404 — someone else's included."""
    pk = parse_id(contract_id)
    contract = (db.session.get(StudentContract, pk, options=OWN_LOADS, with_for_update=lock)
                if pk is not None else None)
    if contract is None or contract.student_id != student_id:
        raise ServiceError(404, "contract_not_found")
    return contract


def _prefill(contract: StudentContract) -> dict:
    """What the form opens with: the profile, then the account email."""
    s = contract.student
    account = AuthAccount.query.filter_by(actor_type=ACTOR_STUDENT, actor_id=s.id).first()
    junior = contract.course.level == "junior"
    return fields.clean({
        "last_name": s.last_name, "first_name": s.first_name,
        "phone": (s.parent_phone if junior else None) or s.phone,
        "email": account.email if account is not None else None,
    })


def detail(student_id, contract_id) -> dict:
    core.sync(student_id=student_id)
    return _detail(_own(student_id, contract_id))


def _detail(contract: StudentContract) -> dict:
    money = core.finance(contract)
    data = _summary(contract)
    data.update({
        "form": fields.clean(contract.form_data) if contract.form_data else _prefill(contract),
        "rules": core.rules(contract, money, ub_today()),
        "finance": money,
        "document": {"format": "pdf",
                     "preview": f"/me/contracts/{contract.id}/preview"
                     if contract.status == "pending" else None,
                     "download": data["document_url"]},
    })
    return data


def _ensure_signable(contract: StudentContract) -> None:
    if contract.status == "signed":
        raise ServiceError(409, "already_signed")
    if contract.status == "cancelled" or contract.enrollment.status != "active":
        raise ServiceError(409, "contract_cancelled")


def preview(student_id, contract_id, payload: dict) -> bytes:
    """The PDF filled with whatever the form holds so far — unsigned, not saved."""
    contract = _own(student_id, contract_id)
    _ensure_signable(contract)
    form = fields.clean(payload.get("form"))
    return core.render(contract, form, core.finance(contract), ub_today())


def sign(student_id, contract_id, payload: dict) -> dict:
    contract = _own(student_id, contract_id, lock=True)
    _ensure_signable(contract)
    if payload.get("agreed") is not True:
        raise ServiceError(400, "agreement_required")
    raw_signature = payload.get("signature")
    if not raw_signature:
        raise ServiceError(400, "signature_required")
    if len(str(raw_signature)) > MAX_SIGNATURE_BYTES * 4 // 3 + 64:
        raise ServiceError(413, "signature_too_large", max_bytes=MAX_SIGNATURE_BYTES)
    try:
        signature = prepare_signature(raw_signature)
    except SignatureError as exc:
        if str(exc) == "too_large":
            raise ServiceError(413, "signature_too_large",
                               max_pixels=MAX_DECODE_PIXELS) from None
        raise ServiceError(400, f"{exc}_signature") from None

    today = ub_today()
    money = core.finance(contract)
    form = fields.clean(payload.get("form"))
    errors = fields.validate(form, core.rules(contract, money, today), today)
    if errors:
        raise ServiceError(400, "invalid_fields", fields=errors)

    pdf = core.render(contract, form, money, today, signature)
    # A fresh name per signing: a staff reset deletes the previous files after its
    # commit, and must never hit the ones a quick re-sign has just written.
    signed_at = utcnow()
    base = build_key("contracts", str(contract.id),
                     f"{contract.contract_number}_{signed_at:%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}")
    pdf_key, sig_key = f"{base}.pdf", f"{base}_signature.png"
    try:
        upload_fileobj(io.BytesIO(signature), sig_key, "image/png")
        upload_fileobj(io.BytesIO(pdf), pdf_key, "application/pdf")
    except S3StorageError:
        db.session.rollback()
        raise ServiceError(502, "storage_error") from None

    contract.status, contract.signed_at = "signed", signed_at
    contract.form_data = form
    contract.total_due, contract.total_paid = money["total_due"], money["total_paid"]
    contract.balance, contract.discount_percent = money["balance"], money["discount_percent"]
    contract.template_key = contract.course.contract_template_key
    contract.file_key, contract.signature_key = pdf_key, sig_key
    db.session.commit()
    return _detail(contract)


def download_link(contract: StudentContract) -> dict:
    if not contract.has_document:
        raise ServiceError(409, "not_signed")
    try:
        url = presigned_url(contract.file_key, expires=DOWNLOAD_TTL)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    return {"url": url, "expires_at": iso(utcnow() + timedelta(seconds=DOWNLOAD_TTL))}


def download(student_id, contract_id) -> dict:
    return download_link(_own(student_id, contract_id))

