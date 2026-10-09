"""Issue a whole class's certificates at once (``POST /admin/cohorts/<id>/certificates``).

The way ``ai-asia-contract`` produced certificates — one run per class — on top of
the per-student rules: each active student is issued (eligibility checked unless
``force``) and gets the PDF from the course template. Students who already hold a
certificate are reported (and given their PDF if it is missing); the rest are
listed with the reason they were skipped.
"""
from __future__ import annotations

from app.models import Certificate, Cohort, Enrollment

from ..errors import ServiceError
from ..params import get_by_id, parse_id
from .generation import generate_if_possible
from .issuing import issue


def _student_ids(value):
    if value is None:
        return None
    ids = [parse_id(v) for v in value] if isinstance(value, list) else [None]
    if not ids or None in ids:
        raise ServiceError(400, "invalid_student_ids")
    return set(ids)


def issue_for_cohort(cohort_id, *, force=False, student_ids=None) -> dict:
    cohort = get_by_id(Cohort, cohort_id)
    if cohort is None:
        raise ServiceError(404, "cohort_not_found")
    wanted = _student_ids(student_ids)
    enrollments = (Enrollment.query.filter_by(cohort_id=cohort.id, status="active")
                   .order_by(Enrollment.id).all())
    issued, existing, skipped = [], [], []
    for enr in enrollments:
        if wanted is not None and enr.student_id not in wanted:
            continue
        cert = Certificate.query.filter_by(student_id=enr.student_id,
                                           course_id=cohort.course_id).first()
        if cert is not None:
            if not cert.is_archived and not cert.file_key:
                generate_if_possible(cert)
            existing.append(cert.to_dict())
            continue
        try:
            issued.append(issue(enr.student_id, cohort.course_id, force=force).to_dict())
        except ServiceError as exc:
            skipped.append({"student_id": enr.student_id, "error": exc.code, **exc.extra})
    return {"cohort_id": cohort.id, "course_id": cohort.course_id,
            "issued": issued, "existing": existing, "skipped": skipped}
