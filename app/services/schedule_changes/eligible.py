"""Who a teacher may hand a session to: every other teacher with an active login
who is not already teaching (or covering) a class at that time."""
from app.extensions import db
from app.models import AuthAccount, Teacher
from app.services.errors import ServiceError

from . import rules
from .serialize import teacher_brief


def eligible_teachers(account, session_id) -> dict:
    session = rules.own_session(account, session_id)
    if rules.has_started(session):
        raise ServiceError(409, "session_started")
    teachers = (
        Teacher.query.join(AuthAccount, db.and_(AuthAccount.actor_type == "teacher",
                                                AuthAccount.actor_id == Teacher.id))
        .filter(AuthAccount.is_active.is_(True), Teacher.id != account.actor_id)
        .order_by(Teacher.first_name, Teacher.last_name, Teacher.id)
        .all()
    )
    busy = rules.busy_teachers([t.id for t in teachers], session)
    return {
        "session_id": session.id,
        "items": [teacher_brief(t) for t in teachers if t.id not in busy],
    }
