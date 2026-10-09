"""``GET /me/certificates`` — one card per course the student is in (spec §4.7).

Replaces the app's several calls per course: every course the student has an
active enrollment in, plus any course they hold a certificate for, each with the
same ``status`` / ``requirements`` / ``certificate`` body as
``/me/courses/<slug>/certificate``. A certificate is per **course**, so a student
in two cohorts of one course gets one card (the newest cohort).
"""
from __future__ import annotations

from app.models import Certificate, Cohort, Course, Enrollment
from app.timeutil import iso

from .eligibility import certificate_status


def _course(course) -> dict:
    return {"id": course.id, "slug": course.slug, "level": course.level,
            "title": {"mn": course.title_mn, "en": course.title_en}}


def _cohort(cohort) -> dict | None:
    if cohort is None:
        return None
    return {"id": cohort.id, "name": cohort.name, "start_date": iso(cohort.start_date),
            "end_date": iso(cohort.end_date)}


def my_certificates(student_id: int) -> dict:
    rows = (Enrollment.query.join(Cohort, Enrollment.cohort_id == Cohort.id)
            .filter(Enrollment.student_id == student_id, Enrollment.status == "active")
            .order_by(Cohort.start_date.desc().nullslast(), Enrollment.id.desc()).all())
    newest = {}
    for enr in rows:
        newest.setdefault(enr.cohort.course_id, enr)
    held = Certificate.query.filter_by(student_id=student_id, is_archived=False).all()
    course_ids = list(newest) + [c.course_id for c in held if c.course_id not in newest]
    courses = {c.id: c for c in Course.query.filter(Course.id.in_(course_ids))} \
        if course_ids else {}
    items = []
    held_ids = {c.course_id for c in held}
    for course_id in course_ids:
        course, enr = courses.get(course_id), newest.get(course_id)
        if course is None or not (course.is_public or course_id in held_ids):
            continue
        item = {"course": _course(course), "cohort": _cohort(enr.cohort if enr else None)}
        item.update(certificate_status(student_id, course, enr))
        items.append(item)
    return {"certificates": items}
