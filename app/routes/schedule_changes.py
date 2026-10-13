"""Teacher-to-teacher schedule-change (class handover) requests, and a teacher's
dated sessions including the ones they cover. Teacher tokens only — the sender
is always the authenticated teacher, never an id from the body.
Contract: docs/schedule_change_api_v1.md.
"""
from flask import Blueprint, g, jsonify, request

from app.auth import actor_required
from app.services import schedule_changes as svc

from ._shared import body

bp = Blueprint("schedule_changes", __name__)
teacher_only = actor_required("teacher")


@bp.get("/teacher/sessions")
@teacher_only
def my_sessions():
    return jsonify(svc.my_sessions(g.current_user, request.args.get("from"),
                                   request.args.get("to")))


@bp.get("/teacher/sessions/<int:session_id>/eligible-teachers")
@teacher_only
def eligible_teachers(session_id):
    return jsonify(svc.eligible_teachers(g.current_user, session_id))


@bp.post("/teacher/schedule-change-requests")
@teacher_only
def create_request():
    payload, created = svc.create(g.current_user, body())
    return jsonify(payload), 201 if created else 200


@bp.get("/teacher/schedule-change-requests")
@teacher_only
def list_requests():
    args = request.args
    return jsonify(svc.list_requests(
        g.current_user, direction=args.get("direction"), status=args.get("status"),
        limit=args.get("limit"), before_id=args.get("before_id"),
    ))


@bp.get("/teacher/schedule-change-requests/<int:request_id>")
@teacher_only
def get_request(request_id):
    return jsonify(svc.get(g.current_user, request_id))


@bp.post("/teacher/schedule-change-requests/<int:request_id>/accept")
@teacher_only
def accept_request(request_id):
    return jsonify(svc.accept(g.current_user, request_id))


@bp.post("/teacher/schedule-change-requests/<int:request_id>/reject")
@teacher_only
def reject_request(request_id):
    return jsonify(svc.reject(g.current_user, request_id, body()))


@bp.post("/teacher/schedule-change-requests/<int:request_id>/cancel")
@teacher_only
def cancel_request(request_id):
    return jsonify(svc.cancel(g.current_user, request_id))
