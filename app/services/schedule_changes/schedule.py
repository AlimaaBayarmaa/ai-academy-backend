"""A teacher's dated sessions: their own cohorts' (``regular``) plus the ones they
accepted to cover (``covering``). The original teacher keeps a handed-over
session as ``regular``, with ``covered_by`` naming who teaches it."""
from app.extensions import db
from app.models import ClassSession, Cohort, ScheduleChangeRequest, Teacher
from app.services.schedules import parse_range, range_meta

from .serialize import ASSIGNMENT_COVERING, ASSIGNMENT_REGULAR, session_brief, teacher_brief


def _in_range(query, from_date, to_date):
    if from_date and to_date:
        query = query.filter(ClassSession.session_date >= from_date,
                             ClassSession.session_date <= to_date)
    return query


def _covering_rows(teacher_id, from_date=None, to_date=None) -> list:
    query = (
        db.session.query(ScheduleChangeRequest, ClassSession)
        .join(ClassSession, ScheduleChangeRequest.class_session_id == ClassSession.id)
        .filter(ScheduleChangeRequest.status == "accepted",
                ScheduleChangeRequest.recipient_teacher_id == teacher_id)
    )
    return _in_range(query, from_date, to_date).all()


def _covering_entry(req, session) -> dict:
    cohort = db.session.get(Cohort, session.cohort_id)
    original = db.session.get(Teacher, cohort.teacher_id) if cohort.teacher_id else None
    return {**session_brief(session), "assignment_type": ASSIGNMENT_COVERING,
            "request_id": req.id, "original_teacher": teacher_brief(original),
            "covered_by": None}


def covering_sessions(teacher_id) -> list:
    rows = _covering_rows(teacher_id)
    entries = [_covering_entry(req, s) for req, s in rows]
    return sorted(entries, key=lambda e: (e["date"], e["start_time"] or "", e["id"]))


def my_sessions(account, raw_from=None, raw_to=None) -> dict:
    from_date, to_date = parse_range(raw_from, raw_to)
    me = account.actor_id
    own = _in_range(
        ClassSession.query.join(Cohort, ClassSession.cohort_id == Cohort.id)
        .filter(Cohort.teacher_id == me), from_date, to_date,
    ).all()
    handed = {
        req.class_session_id: req
        for req in ScheduleChangeRequest.query.filter(
            ScheduleChangeRequest.status == "accepted",
            ScheduleChangeRequest.class_session_id.in_([s.id for s in own] or [0]),
        ).all()
    }
    items = [
        {**session_brief(s), "assignment_type": ASSIGNMENT_REGULAR, "request_id": None,
         "original_teacher": None,
         "covered_by": teacher_brief(handed[s.id].recipient) if s.id in handed else None}
        for s in own
    ]
    items += [_covering_entry(req, s) for req, s in _covering_rows(me, from_date, to_date)]
    items.sort(key=lambda e: (e["date"], e["start_time"] or "", e["id"]))
    return {**range_meta(from_date, to_date), "items": items}
