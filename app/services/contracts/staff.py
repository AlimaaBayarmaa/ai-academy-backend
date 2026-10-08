"""Staff side (``/admin/contracts``): see who signed, fetch the PDF, reset a signing.

A filtered list (course / cohort / student) first creates the contracts its
enrollments are due; the unfiltered list shows only contracts that already exist.

Reset is the ``ai-asia-contract`` "delete the signed marker" step: a signed
contract goes back to ``pending`` so the student can sign again (e.g. a typo in
the register number). The old PDF and signature are removed from S3.
"""
from __future__ import annotations

import contextlib

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import CONTRACT_STATUSES, StudentContract
from app.storage import S3StorageError, delete_object
from app.timeutil import utcnow

from ..errors import ServiceError
from ..params import get_by_id, parse_id, parse_limit
from . import core
from .student import NEWEST_FIRST, download_link

STAFF_LOADS = (selectinload(StudentContract.course), selectinload(StudentContract.cohort),
               selectinload(StudentContract.student))


def _filter_id(name, value):
    if value in (None, ""):
        return None
    pk = parse_id(value)
    if pk is None:
        raise ServiceError(400, f"invalid_{name}")
    return pk


def list_contracts(*, course_id=None, cohort_id=None, student_id=None, status=None,
                   limit=None) -> list:
    ids = {name: _filter_id(name, value) for name, value in
           (("course_id", course_id), ("cohort_id", cohort_id), ("student_id", student_id))}
    if status not in (None, "") and status not in CONTRACT_STATUSES:
        raise ServiceError(400, "invalid_status", allowed=list(CONTRACT_STATUSES))
    if any(pk is not None for pk in ids.values()):
        # Scoped only: an unfiltered list would re-check every enrollment on each view.
        core.sync(**ids)
    q = StudentContract.query.options(*STAFF_LOADS)
    for name, pk in ids.items():
        if pk is not None:
            q = q.filter(getattr(StudentContract, name) == pk)
    if status:
        q = q.filter(StudentContract.status == status)
    rows = q.order_by(*NEWEST_FIRST)
    return [c.to_staff_dict() for c in rows.limit(parse_limit(limit))]


def get_contract(contract_id) -> StudentContract:
    contract = get_by_id(StudentContract, contract_id)
    if contract is None:
        raise ServiceError(404, "contract_not_found")
    return contract


def download(contract_id) -> dict:
    return download_link(get_contract(contract_id))


def reset(contract_id) -> StudentContract:
    pk = parse_id(contract_id)
    contract = (db.session.get(StudentContract, pk, with_for_update=True)
                if pk is not None else None)
    if contract is None:
        raise ServiceError(404, "contract_not_found")
    if contract.status != "signed":
        raise ServiceError(409, "not_signed")
    old_keys = (contract.file_key, contract.signature_key)
    # Back to the enrollment's state: cancelled if it is no longer active.
    if contract.enrollment.status == "active":
        contract.status, contract.cancelled_at = "pending", None
    else:
        contract.status, contract.cancelled_at = "cancelled", utcnow()
    contract.signed_at = None
    contract.file_key = contract.signature_key = contract.template_key = None
    contract.total_due = contract.total_paid = contract.balance = None
    contract.discount_percent = None
    db.session.commit()
    # Only once the row no longer points at them; a failed delete just leaves an orphan.
    for key in old_keys:
        if key:
            with contextlib.suppress(S3StorageError):
                delete_object(key)
    return contract
