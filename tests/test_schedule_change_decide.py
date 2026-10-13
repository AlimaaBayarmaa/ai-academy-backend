"""Schedule-change requests: accept, reject, cancel, and the schedules after."""
from datetime import datetime

import schedule_change_helpers
from schedule_change_helpers import URL, act, add_session, send

from app.models import Notification, ScheduleChangeRequest

handover = schedule_change_helpers.handover
clock = schedule_change_helpers.clock


def _send(client, h, who="b"):
    return send(client, h["a_h"], h["session"].id, h[who].actor_id).get_json()


def test_accept_records_the_covering_assignment(client, handover):
    h = handover
    req = _send(client, h)
    resp = act(client, h["b_h"], req["id"], "accept")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "accepted" and data["resolved_at"]
    assert data["resolved_by_teacher_id"] == h["b"].actor_id
    assert data["session_assignment"] == {
        "session_id": h["session"].id, "teacher_id": h["b"].actor_id,
        "assignment_type": "covering"}
    note = Notification.query.filter_by(account_id=h["a"].id).one()
    assert note.kind == "schedule_change_response"
    assert note.data == {"request_id": req["id"], "session_id": h["session"].id,
                         "status": "accepted"}


def test_accept_is_idempotent_and_final(client, handover):
    h = handover
    req = _send(client, h)
    act(client, h["b_h"], req["id"], "accept")
    again = act(client, h["b_h"], req["id"], "accept")
    assert again.status_code == 200 and again.get_json()["status"] == "accepted"
    assert Notification.query.filter_by(account_id=h["a"].id).count() == 1
    for action, headers in (("reject", h["b_h"]), ("cancel", h["a_h"])):
        resp = act(client, headers, req["id"], action)
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "request_already_resolved",
                                   "current_status": "accepted"}


def test_only_the_recipient_decides(client, handover):
    h = handover
    req = _send(client, h)
    for action in ("accept", "reject"):
        resp = act(client, h["a_h"], req["id"], action)
        assert (resp.status_code, resp.get_json()["error"]) == (403, "not_recipient")
        resp = act(client, h["c_h"], req["id"], action)
        assert (resp.status_code, resp.get_json()["error"]) == (404, "request_not_found")
    resp = act(client, h["b_h"], req["id"], "cancel")
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_sender")
    assert act(client, h["b_h"], 999999, "accept").status_code == 404
    assert ScheduleChangeRequest.query.one().status == "pending"


def test_reject_keeps_schedules_unchanged(client, handover):
    h = handover
    req = _send(client, h)
    resp = act(client, h["b_h"], req["id"], "reject", reason="Завгүй")
    data = resp.get_json()
    assert resp.status_code == 200
    assert (data["status"], data["reason"], data["session_assignment"]) == (
        "rejected", "Завгүй", None)
    sent = client.get(URL + "?direction=sent", headers=h["a_h"]).get_json()["items"]
    assert sent[0]["status"] == "rejected"
    assert client.get("/teacher/sessions", headers=h["b_h"]).get_json()["items"] == []
    assert act(client, h["b_h"], req["id"], "reject").status_code == 200
    assert act(client, h["b_h"], req["id"], "accept").status_code == 409
    bad = act(client, h["b_h"], req["id"], "reject", reason=["x"])
    assert bad.get_json()["error"] == "invalid_reason"


def test_sender_cancels_pending(client, handover):
    h = handover
    req = _send(client, h)
    resp = act(client, h["a_h"], req["id"], "cancel")
    assert resp.status_code == 200 and resp.get_json()["status"] == "cancelled"
    assert act(client, h["b_h"], req["id"], "accept").get_json() == {
        "error": "request_already_resolved", "current_status": "cancelled"}
    assert send(client, h["a_h"], h["session"].id, h["c"].actor_id).status_code == 201


def test_accept_after_start_expires_the_request(client, handover):
    h = handover
    req = _send(client, h)
    h["clock"](datetime(2026, 10, 6, 9, 30))
    resp = act(client, h["b_h"], req["id"], "accept")
    assert (resp.status_code, resp.get_json()["error"]) == (409, "session_started")
    assert client.get(f"{URL}/{req['id']}", headers=h["a_h"]).get_json()["status"] == "expired"


def test_accept_blocked_by_a_clash_made_after_sending(client, db, handover, make_cohort):
    h = handover
    req = _send(client, h)
    clash = add_session(db, make_cohort(teacher_id=h["b"].actor_id), start="10:30",
                        end="12:00")
    resp = act(client, h["b_h"], req["id"], "accept")
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "schedule_conflict", "session_ids": [clash.id]}
    assert ScheduleChangeRequest.query.one().status == "pending"


def test_accepted_cover_makes_the_recipient_busy(client, db, handover, make_cohort):
    h = handover
    act(client, h["b_h"], _send(client, h)["id"], "accept")
    other = make_cohort(teacher_id=h["c"].actor_id)
    same_time = add_session(db, other)
    eligible = client.get(f"/teacher/sessions/{same_time.id}/eligible-teachers",
                          headers=h["c_h"]).get_json()["items"]
    assert h["b"].actor_id not in [t["id"] for t in eligible]


# ----------------------------------------------------------------- schedules
def test_covering_session_on_recipient_schedule(client, handover):
    h = handover
    act(client, h["b_h"], _send(client, h)["id"], "accept")
    mine = client.get("/teacher/sessions?from=2026-10-01&to=2026-10-31",
                      headers=h["b_h"]).get_json()
    assert mine["from"] == "2026-10-01"
    [entry] = mine["items"]
    assert entry["id"] == h["session"].id and entry["assignment_type"] == "covering"
    assert entry["original_teacher"]["name"] == "Anar Bat"
    outside = client.get("/teacher/sessions?from=2026-11-01&to=2026-11-30", headers=h["b_h"])
    assert outside.get_json()["items"] == []
    legacy = client.get(f"/teachers/{h['b'].actor_id}/schedule", headers=h["b_h"]).get_json()
    assert legacy["cohorts"] == []
    assert [s["id"] for s in legacy["covering_sessions"]] == [h["session"].id]


def test_original_teacher_schedule_is_unchanged(client, handover):
    h = handover
    act(client, h["b_h"], _send(client, h)["id"], "accept")
    [entry] = client.get("/teacher/sessions", headers=h["a_h"]).get_json()["items"]
    assert entry["assignment_type"] == "regular"
    assert entry["covered_by"]["id"] == h["b"].actor_id
    legacy = client.get(f"/teachers/{h['a'].actor_id}/schedule", headers=h["a_h"]).get_json()
    assert [c["id"] for c in legacy["cohorts"]] == [h["cohort"].id]
    assert legacy["covering_sessions"] == []
    c_view = client.get("/teacher/sessions", headers=h["c_h"]).get_json()["items"]
    assert c_view == []
    assert client.get("/teacher/sessions?from=x", headers=h["a_h"]).status_code == 400
