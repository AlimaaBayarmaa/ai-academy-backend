"""Lookups, timing and clash rules shared by requests, eligibility and the schedule.

Session dates and "HH:MM" times are Ulaanbaatar wall-clock (like attendance). A
session without an end time is taken to last :data:`DEFAULT_MINUTES`.
"""
from datetime import datetime, time

from app.extensions import db
from app.models import AuthAccount, ClassSession, Cohort, ScheduleChangeRequest, Teacher
from app.services.attendance import clock
from app.services.errors import ServiceError
from app.services.params import get_by_id, parse_id
from app.timeutil import LOCAL_TZ

DEFAULT_MINUTES = 60
MAX_TEXT_LENGTH = 500


def own_session(account, session_id) -> ClassSession:
    """A session of a cohort the calling teacher teaches; anything else is 404."""
    session = get_by_id(ClassSession, session_id)
    cohort = db.session.get(Cohort, session.cohort_id) if session else None
    if cohort is None or cohort.teacher_id != account.actor_id:
        raise ServiceError(404, "session_not_found")
    return session


def active_teacher(teacher_id):
    """A teacher whose login is active, or ``None``."""
    pk = parse_id(teacher_id)
    if pk is None:
        return None
    return (
        Teacher.query.join(AuthAccount, db.and_(AuthAccount.actor_type == "teacher",
                                                AuthAccount.actor_id == Teacher.id))
        .filter(Teacher.id == pk, AuthAccount.is_active.is_(True))
        .first()
    )


def account_id_of(teacher_id):
    account = AuthAccount.query.filter_by(actor_type="teacher", actor_id=teacher_id).first()
    return account.id if account else None


def text(value, field):
    """An optional free-text field: ``None``/blank -> ``None``; at most 500 characters."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError(400, f"invalid_{field}")
    value = value.strip()
    if len(value) > MAX_TEXT_LENGTH:
        raise ServiceError(400, f"{field}_too_long", max_length=MAX_TEXT_LENGTH)
    return value or None


# ----------------------------------------------------------------- timing
def _minutes(hhmm: str) -> int:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return hours * 60 + minutes


def interval(session) -> tuple:
    """(start, end) in minutes after local midnight."""
    start = _minutes(session.start_time) if session.start_time else 0
    end = _minutes(session.end_time) if session.end_time else start + DEFAULT_MINUTES
    return start, end


def has_started(session) -> bool:
    """True once the session's local start time has come (no request may act after)."""
    start = clock.local_start(session.session_date, session.start_time) or datetime.combine(
        session.session_date, time(0), tzinfo=LOCAL_TZ)
    return clock.local_now() >= start


def overlaps(a, b) -> bool:
    if a.session_date != b.session_date:
        return False
    a_start, a_end = interval(a)
    b_start, b_end = interval(b)
    return a_start < b_end and b_start < a_end


# ----------------------------------------------------------------- clashes
def teaching_on(teacher_ids, day) -> list:
    """(teacher_id, session) for every session these teachers teach that day:
    their own cohorts' sessions plus the ones they accepted to cover."""
    ids = list(teacher_ids)
    if not ids:
        return []
    own = (
        db.session.query(Cohort.teacher_id, ClassSession)
        .join(Cohort, ClassSession.cohort_id == Cohort.id)
        .filter(Cohort.teacher_id.in_(ids), ClassSession.session_date == day)
        .all()
    )
    covering = (
        db.session.query(ScheduleChangeRequest.recipient_teacher_id, ClassSession)
        .join(ClassSession, ScheduleChangeRequest.class_session_id == ClassSession.id)
        .filter(ScheduleChangeRequest.status == "accepted",
                ScheduleChangeRequest.recipient_teacher_id.in_(ids),
                ClassSession.session_date == day)
        .all()
    )
    return list(own) + list(covering)


def busy_teachers(teacher_ids, session) -> set:
    """The teachers among ``teacher_ids`` already teaching at the session's time."""
    return {
        teacher_id for teacher_id, other in teaching_on(teacher_ids, session.session_date)
        if other.id != session.id and overlaps(other, session)
    }


def clashes(teacher_id, session) -> list:
    """Ids of the teacher's sessions that overlap ``session``."""
    return sorted(
        other.id for _, other in teaching_on([teacher_id], session.session_date)
        if other.id != session.id and overlaps(other, session)
    )
