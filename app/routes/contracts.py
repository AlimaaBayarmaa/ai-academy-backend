"""Student e-contracts (docs/e_contract_api_v1.md).

- student : ``/me/contracts`` — list, detail, preview (PDF), sign, download
- staff   : ``/admin/contracts`` (``cohort:manage``) — list, detail, download, reset
"""
from flask import Blueprint, Response, g, jsonify, request

from app.auth import actor_required, require_permission
from app.services.contracts import staff, student

from ._shared import body

bp = Blueprint("contracts", __name__)


# ------------------------------------------------------------------- student
@bp.get("/me/contracts")
@actor_required("student")
def my_contracts():
    return jsonify(student.list_contracts(g.current_user.actor_id))


@bp.get("/me/contracts/<contract_id>")
@actor_required("student")
def my_contract(contract_id):
    return jsonify(student.detail(g.current_user.actor_id, contract_id))


@bp.post("/me/contracts/<contract_id>/preview")
@actor_required("student")
def preview_my_contract(contract_id):
    pdf = student.preview(g.current_user.actor_id, contract_id, body())
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=preview.pdf"})


@bp.post("/me/contracts/<contract_id>/sign")
@actor_required("student")
def sign_my_contract(contract_id):
    return jsonify(student.sign(g.current_user.actor_id, contract_id, body()))


@bp.get("/me/contracts/<contract_id>/download")
@actor_required("student")
def download_my_contract(contract_id):
    return jsonify(student.download(g.current_user.actor_id, contract_id))


# ------------------------------------------------------------------- staff
@bp.get("/admin/contracts")
@require_permission("cohort:manage")
def list_contracts():
    args = request.args
    return jsonify(contracts=staff.list_contracts(
        course_id=args.get("course_id"), cohort_id=args.get("cohort_id"),
        student_id=args.get("student_id"), status=args.get("status"),
        limit=args.get("limit")))


@bp.get("/admin/contracts/<contract_id>")
@require_permission("cohort:manage")
def get_contract(contract_id):
    return jsonify(staff.get_contract(contract_id).to_staff_dict())


@bp.get("/admin/contracts/<contract_id>/download")
@require_permission("cohort:manage")
def download_contract(contract_id):
    return jsonify(staff.download(contract_id))


@bp.post("/admin/contracts/<contract_id>/reset")
@require_permission("cohort:manage")
def reset_contract(contract_id):
    return jsonify(staff.reset(contract_id).to_staff_dict())
