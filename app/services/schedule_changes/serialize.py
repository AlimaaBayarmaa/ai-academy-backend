"""Wire shapes. Teachers appear by id and name only — no phone or e-mail —
and nothing about the cohort's students is ever included."""
from app.extensions import db
from app.models import Classroom, Cohort, Course, CourseTopic
from app.timeutil import iso

ASSIGNMENT_COVERING = "covering"
ASSIGNMENT_REGULAR = "regular"


def teacher_brief(teacher):
    if teacher is None:
        return None
    return {
        "id": teacher.id,
        "name": f"{teacher.first_name} {teacher.last_name or ''}".strip(),
        "photo_url": None,  # teachers have no photo yet; the field is reserved
    }


def session_brief(session) -> dict:
    cohort = db.session.get(Cohort, session.cohort_id)
    course = db.session.get(Course, cohort.course_id) if cohort else None
    topic = db.session.get(CourseTopic, session.topic_id) if session.topic_id else None
    room = db.session.get(Classroom, cohort.classroom_id) if cohort and cohort.classroom_id \
        else None
    return {
        "id": session.id,
        "cohort_id": session.cohort_id,
        "cohort_name": cohort.name if cohort else None,
        "title": course.title_mn if course else (cohort.name if cohort else None),
        "topic_id": session.topic_id,
        "topic": topic.name_mn if topic else None,
        "date": iso(session.session_date),
        "start_time": session.start_time,
        "end_time": session.end_time,
        "room": room.name if room else None,
    }


def request_dict(req) -> dict:
    accepted = req.status == "accepted"
    return {
        "id": req.id,
        "session_id": req.class_session_id,
        "session": session_brief(req.session),
        "sender": teacher_brief(req.sender),
        "recipient": teacher_brief(req.recipient),
        "status": req.status,
        "message": req.message,
        "reason": req.reason,
        "created_at": iso(req.created_at),
        "updated_at": iso(req.updated_at),
        "resolved_at": iso(req.resolved_at),
        "resolved_by_teacher_id": req.resolved_by_teacher_id,
        "session_assignment": {
            "session_id": req.class_session_id,
            "teacher_id": req.recipient_teacher_id,
            "assignment_type": ASSIGNMENT_COVERING,
        } if accepted else None,
    }
