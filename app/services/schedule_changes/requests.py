"""Sending a request, and reading the ones a teacher sent or received.

Only the cohort's own teacher may send one, for a session that has not started,
to another active teacher who is free at that time. A session has at most one
pending request; resending the same one (a network retry) returns it unchanged
instead of creating a second request or notification.
"""
import logging

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import SCHEDULE_CHANGE_STATUSES, ClassSession, ScheduleChangeRequest
from app.services.errors import ServiceError
from app.services.notifications import notify
from app.services.params import parse_id, parse_limit
from app.timeutil import utcnow

from . import rules
from .serialize import request_dict, session_brief

log = logging.getLogger(__name__)
KIND_REQUEST = "schedule_change_request"
DIRECTIONS = ("sent", "received")


def _notify_recipient(req) -> None:
    session = session_brief(req.session)
    sender = f"{req.sender.first_name} {req.sender.last_name or ''}".strip()
    notify(
        [a for a in [rules.account_id_of(req.recipient_teacher_id)] if a],
        kind=KIND_REQUEST,
        title="Цаг солих хүсэлт",
        body=f"{sender} таныг {session['date']} {session['start_time']} цагийн "
             f"«{session['title']}» хичээлийг орлон заахыг хүслээ.",
        data={"request_id": req.id, "session_id": req.class_session_id},
    )


def create(account, data) -> tuple:
    """``(payload, created)`` — ``created`` is False for an idempotent retry."""
    me = account.actor_id
    if data.get("session_id") in (None, ""):
        raise ServiceError(400, "session_id_required")
    session = rules.own_session(account, data["session_id"])
    if data.get("recipient_teacher_id") in (None, ""):
        raise ServiceError(400, "recipient_required")
    if parse_id(data["recipient_teacher_id"]) == me:
        raise ServiceError(400, "cannot_request_self")
    recipient = rules.active_teacher(data["recipient_teacher_id"])
    if recipient is None:
        raise ServiceError(404, "recipient_not_found")
    message = rules.text(data.get("message"), "message")
    if rules.has_started(session):
        raise ServiceError(409, "session_started")

    open_req = ScheduleChangeRequest.query.filter(
        ScheduleChangeRequest.class_session_id == session.id,
        ScheduleChangeRequest.status.in_(("pending", "accepted")),
    ).first()
    if open_req is not None:
        if open_req.status == "accepted":
            raise ServiceError(409, "session_already_covered", request_id=open_req.id)
        if open_req.recipient_teacher_id == recipient.id and open_req.message == message:
            return request_dict(open_req), False
        raise ServiceError(409, "request_pending", request_id=open_req.id)
    if rules.clashes(recipient.id, session):
        raise ServiceError(409, "recipient_busy")

    now = utcnow()
    req = ScheduleChangeRequest(
        class_session_id=session.id, sender_teacher_id=me, recipient_teacher_id=recipient.id,
        status="pending", message=message, created_at=now, updated_at=now,
    )
    db.session.add(req)
    try:
        db.session.flush()
    except IntegrityError:  # a concurrent request for this session won
        db.session.rollback()
        raise ServiceError(409, "request_pending") from None
    _notify_recipient(req)  # commits the request together with the notification
    db.session.commit()
    log.info("schedule change %s: teacher %s -> %s for session %s",
             req.id, me, recipient.id, session.id)
    return request_dict(req), True


def expire_started(teacher_id) -> None:
    """Pending requests (sent or received) whose session has started become ``expired``."""
    rows = (
        ScheduleChangeRequest.query.join(ClassSession)
        .filter(ScheduleChangeRequest.status == "pending",
                db.or_(ScheduleChangeRequest.sender_teacher_id == teacher_id,
                       ScheduleChangeRequest.recipient_teacher_id == teacher_id))
        .all()
    )
    expired = [r for r in rows if rules.has_started(r.session)]
    now = utcnow()
    for row in expired:
        row.status, row.resolved_at, row.updated_at = "expired", now, now
    if expired:
        db.session.commit()


def list_requests(account, *, direction, status=None, limit=None, before_id=None) -> dict:
    if direction not in DIRECTIONS:
        raise ServiceError(400, "invalid_direction", allowed=list(DIRECTIONS))
    if status not in (None, "") and status not in SCHEDULE_CHANGE_STATUSES:
        raise ServiceError(400, "invalid_status", allowed=list(SCHEDULE_CHANGE_STATUSES))
    me = account.actor_id
    expire_started(me)
    column = (ScheduleChangeRequest.sender_teacher_id if direction == "sent"
              else ScheduleChangeRequest.recipient_teacher_id)
    query = ScheduleChangeRequest.query.filter(column == me)
    if status:
        query = query.filter(ScheduleChangeRequest.status == status)
    if before_id not in (None, ""):
        before = parse_id(before_id)
        if before is None:
            raise ServiceError(400, "invalid_before_id")
        query = query.filter(ScheduleChangeRequest.id < before)
    rows = query.order_by(ScheduleChangeRequest.id.desc()).limit(
        parse_limit(limit, default=50, maximum=100)).all()
    return {"direction": direction, "items": [request_dict(r) for r in rows]}


def party_request(account, request_id, *, lock=False) -> ScheduleChangeRequest:
    """A request the caller sent or received; anyone else gets 404."""
    pk = parse_id(request_id)
    query = ScheduleChangeRequest.query.filter_by(id=pk)
    row = (query.with_for_update() if lock else query).first() if pk is not None else None
    me = account.actor_id
    if row is None or me not in (row.sender_teacher_id, row.recipient_teacher_id):
        raise ServiceError(404, "request_not_found")
    return row


def get(account, request_id) -> dict:
    expire_started(account.actor_id)
    return request_dict(party_request(account, request_id))
