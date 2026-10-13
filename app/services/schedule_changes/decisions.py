"""Accept / reject (the recipient) and cancel (the sender).

Each decision locks the request row, so two taps — or two devices — resolve it
once: repeating the decision already made returns the request unchanged, a
different decision is ``409 request_already_resolved``. Acceptance also locks
the recipient's teacher row so two acceptances cannot double-book them.
"""
import logging

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Teacher
from app.services.errors import ServiceError
from app.services.notifications import notify
from app.timeutil import utcnow

from . import rules
from .requests import party_request
from .serialize import request_dict, session_brief

log = logging.getLogger(__name__)
KIND_RESPONSE = "schedule_change_response"
_TITLES = {"accepted": "Цаг солих хүсэлтийг зөвшөөрлөө",
           "rejected": "Цаг солих хүсэлтээс татгалзлаа"}


def _open(account, request_id, wanted, *, by):
    """The locked request, or ``None`` when ``wanted`` is already its status."""
    row = party_request(account, request_id, lock=True)
    me = account.actor_id
    if by == "recipient" and row.recipient_teacher_id != me:
        raise ServiceError(403, "not_recipient")
    if by == "sender" and row.sender_teacher_id != me:
        raise ServiceError(403, "not_sender")
    if row.status == wanted:
        db.session.rollback()
        return None
    if row.status != "pending":
        db.session.rollback()
        raise ServiceError(409, "request_already_resolved", current_status=row.status)
    if rules.has_started(row.session):
        _resolve(row, "expired", None)
        db.session.commit()
        raise ServiceError(409, "session_started")
    return row


def _resolve(row, status, teacher_id) -> None:
    now = utcnow()
    row.status, row.resolved_at, row.updated_at = status, now, now
    row.resolved_by_teacher_id = teacher_id


def _notify_sender(row) -> None:
    session = session_brief(row.session)
    recipient = f"{row.recipient.first_name} {row.recipient.last_name or ''}".strip()
    notify(
        [a for a in [rules.account_id_of(row.sender_teacher_id)] if a],
        kind=KIND_RESPONSE,
        title=_TITLES[row.status],
        body=f"{recipient}: {session['date']} {session['start_time']} «{session['title']}»",
        data={"request_id": row.id, "session_id": row.class_session_id, "status": row.status},
    )


def accept(account, request_id) -> dict:
    me = account.actor_id
    row = _open(account, request_id, "accepted", by="recipient")
    if row is None:
        return get_fresh(account, request_id)
    db.session.query(Teacher).filter_by(id=me).with_for_update().one()
    clashing = rules.clashes(me, row.session)
    if clashing:
        db.session.rollback()
        raise ServiceError(409, "schedule_conflict", session_ids=clashing)
    _resolve(row, "accepted", me)
    try:
        db.session.flush()
    except IntegrityError:  # the session already has a covering teacher
        db.session.rollback()
        raise ServiceError(409, "session_already_covered") from None
    _notify_sender(row)
    db.session.commit()
    log.info("schedule change %s accepted by teacher %s", row.id, me)
    return request_dict(row)


def reject(account, request_id, data) -> dict:
    reason = rules.text(data.get("reason"), "reason")
    row = _open(account, request_id, "rejected", by="recipient")
    if row is None:
        return get_fresh(account, request_id)
    _resolve(row, "rejected", account.actor_id)
    row.reason = reason
    _notify_sender(row)
    db.session.commit()
    log.info("schedule change %s rejected by teacher %s", row.id, account.actor_id)
    return request_dict(row)


def cancel(account, request_id) -> dict:
    row = _open(account, request_id, "cancelled", by="sender")
    if row is None:
        return get_fresh(account, request_id)
    _resolve(row, "cancelled", account.actor_id)
    db.session.commit()
    log.info("schedule change %s cancelled by teacher %s", row.id, account.actor_id)
    return request_dict(row)


def get_fresh(account, request_id) -> dict:
    return request_dict(party_request(account, request_id))
