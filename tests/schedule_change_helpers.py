"""Shared fixtures and helpers for the schedule-change (class handover) tests."""
from datetime import date, datetime

import pytest

from app.models import Classroom, ClassSession

DAY = date(2026, 10, 6)  # a Tuesday, after the frozen clock (2026-10-01 09:00)
URL = "/teacher/schedule-change-requests"


def add_session(db, cohort, day=DAY, start="09:00", end="11:00"):
    session = ClassSession(cohort_id=cohort.id, session_date=day, start_time=start,
                           end_time=end)
    db.session.add(session)
    db.session.commit()
    return session


def send(client, headers, session_id, recipient_id, **fields):
    data = {"session_id": session_id, "recipient_teacher_id": recipient_id, **fields}
    return client.post(URL, headers=headers, json=data)


def act(client, headers, request_id, action, **json):
    return client.post(f"{URL}/{request_id}/{action}", headers=headers, json=json or None)


@pytest.fixture
def clock(monkeypatch):
    """``clock(datetime(...))`` freezes the session clock at that Ulaanbaatar time."""
    from app.timeutil import LOCAL_TZ

    def _set(local_dt):
        from datetime import timezone

        utc = local_dt.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        monkeypatch.setattr("app.services.attendance.clock.now", lambda: utc)

    _set(datetime(2026, 10, 1, 9, 0))
    return _set


@pytest.fixture
def handover(db, clock, make_teacher, make_course, make_cohort):
    """Teacher A teaches a cohort with one upcoming session; B and C are colleagues."""
    a, a_headers = make_teacher(first_name="Anar", last_name="Bat")
    b, b_headers = make_teacher(first_name="Bold")
    c, c_headers = make_teacher(first_name="Chimeg")
    room = Classroom(name="Room 204", center_name="AI Academy")
    db.session.add(room)
    db.session.commit()
    course = make_course(title_mn="Corporate Leaders")
    cohort = make_cohort(course=course, teacher_id=a.actor_id, classroom_id=room.id,
                         name="CL-2026-10")
    return {
        "a": a, "a_h": a_headers, "b": b, "b_h": b_headers, "c": c, "c_h": c_headers,
        "course": course, "cohort": cohort, "session": add_session(db, cohort),
        "clock": clock,
    }
