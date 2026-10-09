"""Student certificates, staff issuing and public verification (contract §2.9).

- student : ``/me/certificates``, ``/me/courses/<slug>/certificate``,
            ``/me/certificates/<n>/download``
- staff   : ``/admin/certificates`` (+ ``/generate``), ``/admin/cohorts/<id>/certificates``
            (``cohort:manage``; super_admin via wildcard)
- public  : ``/certificates/verify/<n>?code=`` — no Authorization header; HTML for browsers
"""
from flask import Blueprint, Response, g, jsonify, request

from app.auth import actor_required, require_permission
from app.services import access
from app.services import certificates as cert_svc
from app.services.errors import ServiceError

from ._shared import body

bp = Blueprint("certificates", __name__)


# ------------------------------------------------------------------- student
@bp.get("/me/courses/<course_slug>/certificate")
@actor_required("student")
def my_course_certificate(course_slug):
    student_id = g.current_user.actor_id
    course = access.course_by_slug(course_slug)
    enrollment = access.enrollment_for_course(student_id, course.id)
    return jsonify(cert_svc.certificate_status(student_id, course, enrollment))


@bp.get("/me/certificates")
@actor_required("student")
def my_certificates():
    return jsonify(cert_svc.my_certificates(g.current_user.actor_id))


@bp.get("/me/certificates/<cert_number>/download")
@actor_required("student")
def download_my_certificate(cert_number):
    return jsonify(cert_svc.student_download(g.current_user.actor_id, cert_number))


# ------------------------------------------------------------------- staff
@bp.get("/admin/certificates")
@require_permission("cohort:manage")
def list_certificates():
    args = request.args
    return jsonify(certificates=cert_svc.list_certificates(
        course_id=args.get("course_id"), student_id=args.get("student_id"),
        limit=args.get("limit")))


@bp.post("/admin/certificates")
@require_permission("cohort:manage")
def issue_certificate():
    data = body()
    cert = cert_svc.issue(data.get("student_id"), data.get("course_id"),
                          force=data.get("force") is True)
    return jsonify(cert.to_dict()), 201


@bp.post("/admin/certificates/<cert_id>/generate")
@require_permission("cohort:manage")
def generate_certificate_file(cert_id):
    return jsonify(cert_svc.generate(cert_svc.get_certificate(cert_id)).to_dict())


@bp.post("/admin/cohorts/<cohort_id>/certificates")
@require_permission("cohort:manage")
def issue_cohort_certificates(cohort_id):
    data = body()
    return jsonify(cert_svc.issue_for_cohort(
        cohort_id, force=data.get("force") is True, student_ids=data.get("student_ids")))


@bp.put("/admin/certificates/<cert_id>/file")
@require_permission("cohort:manage")
def upload_certificate_file(cert_id):
    cert = cert_svc.get_certificate(cert_id)
    cert_svc.upload_file(cert, request.files.get("file"), content_length=request.content_length)
    return jsonify(cert.to_dict())


@bp.delete("/admin/certificates/<cert_id>")
@require_permission("cohort:manage")
def archive_certificate(cert_id):
    cert = cert_svc.archive(cert_svc.get_certificate(cert_id))
    return jsonify(cert.to_dict())


# ------------------------------------------------------------------- public
@bp.get("/certificates/verify/<cert_number>")
def verify_certificate(cert_number):
    """JSON for API clients; an HTML page for a phone that scanned the QR."""
    wants_html = request.accept_mimetypes.best == "text/html"
    try:
        data = cert_svc.verify(cert_number, request.args.get("code"))
    except ServiceError:
        if not wants_html:
            raise
        return Response(cert_svc.verify_page(None), status=404, mimetype="text/html")
    if wants_html:
        return Response(cert_svc.verify_page(data), mimetype="text/html")
    return jsonify(data)
