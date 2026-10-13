"""Schedule-change requests: eligible teachers, sending, reading, notifications."""
import schedule_change_helpers
from schedule_change_helpers import URL, act, add_session, send

from app.models import AuthAccount, Notification, ScheduleChangeRequest

handover = schedule_change_helpers.handover
clock = schedule_change_helpers.clock


def _id(account):
    return account.actor_id


# ----------------------------------------------------------------- eligible teachers
def test_eligible_lists_other_active_teachers(client, handover):
    h = handover
    resp = client.get(f"/teacher/sessions/{h['session'].id}/eligible-teachers", headers=h["a_h"])
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert [t["name"] for t in items] == ["Bold", "Chimeg"]
    assert items[0] == {"id": _id(h["b"]), "name": "Bold", "photo_url": None}


def test_eligible_skips_inactive_and_busy_teachers(client, db, handover, make_cohort):
    h = handover
    db.session.get(AuthAccount, h["c"].id).is_active = False
    db.session.commit()
    busy = make_cohort(teacher_id=_id(h["b"]))
    add_session(db, busy, start="10:00", end="12:00")  # overlaps 09:00-11:00
    resp = client.get(f"/teacher/sessions/{h['session'].id}/eligible-teachers", headers=h["a_h"])
    assert resp.get_json()["items"] == []


def test_back_to_back_session_is_not_a_clash(client, db, handover, make_cohort):
    h = handover
    add_session(db, make_cohort(teacher_id=_id(h["b"])), start="11:00", end="12:00")
    resp = client.get(f"/teacher/sessions/{h['session'].id}/eligible-teachers", headers=h["a_h"])
    assert _id(h["b"]) in [t["id"] for t in resp.get_json()["items"]]


def test_eligible_for_someone_elses_session_is_404(client, handover):
    h = handover
    resp = client.get(f"/teacher/sessions/{h['session'].id}/eligible-teachers", headers=h["b_h"])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "session_not_found"


def test_staff_and_students_are_forbidden(client, handover, admin_headers, make_student):
    _, s_headers = make_student()
    for headers in (admin_headers, s_headers):
        assert client.get(URL + "?direction=sent", headers=headers).status_code == 403
    assert client.get(URL + "?direction=sent").status_code == 401


# ----------------------------------------------------------------- sending
def test_send_creates_pending_request_and_notifies(client, db, handover):
    h = handover
    resp = send(client, h["a_h"], h["session"].id, _id(h["b"]), message="Өвчтэй байна")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "pending"
    assert data["sender"]["name"] == "Anar Bat"
    assert data["recipient"]["id"] == _id(h["b"])
    assert data["message"] == "Өвчтэй байна"
    assert data["session"] == {
        "id": h["session"].id, "cohort_id": h["cohort"].id, "cohort_name": "CL-2026-10",
        "title": "Corporate Leaders", "topic_id": None, "topic": None,
        "date": "2026-10-06", "start_time": "09:00", "end_time": "11:00", "room": "Room 204",
    }
    assert data["resolved_at"] is None and data["session_assignment"] is None
    note = Notification.query.filter_by(account_id=h["b"].id).one()
    assert note.kind == "schedule_change_request"
    assert note.data == {"request_id": data["id"], "session_id": h["session"].id}
    assert Notification.query.filter_by(account_id=h["a"].id).count() == 0


def test_retry_returns_the_same_request(client, handover):
    h = handover
    first = send(client, h["a_h"], h["session"].id, _id(h["b"]))
    again = send(client, h["a_h"], h["session"].id, _id(h["b"]))
    assert again.status_code == 200
    assert again.get_json()["id"] == first.get_json()["id"]
    assert ScheduleChangeRequest.query.count() == 1
    assert Notification.query.count() == 1


def test_second_recipient_while_pending_is_409(client, handover):
    h = handover
    first = send(client, h["a_h"], h["session"].id, _id(h["b"])).get_json()
    resp = send(client, h["a_h"], h["session"].id, _id(h["c"]))
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "request_pending", "request_id": first["id"]}


def test_after_rejection_another_teacher_can_be_asked(client, handover):
    h = handover
    first = send(client, h["a_h"], h["session"].id, _id(h["b"])).get_json()
    act(client, h["b_h"], first["id"], "reject")
    assert send(client, h["a_h"], h["session"].id, _id(h["c"])).status_code == 201


def test_covered_session_cannot_be_requested_again(client, handover):
    h = handover
    first = send(client, h["a_h"], h["session"].id, _id(h["b"])).get_json()
    act(client, h["b_h"], first["id"], "accept")
    resp = send(client, h["a_h"], h["session"].id, _id(h["c"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "session_already_covered"


def test_send_validation(client, handover):
    h = handover
    sid, b = h["session"].id, _id(h["b"])
    cases = [
        ({"recipient_teacher_id": b}, 400, "session_id_required"),
        ({"session_id": sid}, 400, "recipient_required"),
        ({"session_id": sid, "recipient_teacher_id": _id(h["a"])}, 400, "cannot_request_self"),
        ({"session_id": sid, "recipient_teacher_id": 999999}, 404, "recipient_not_found"),
        ({"session_id": sid, "recipient_teacher_id": "x"}, 404, "recipient_not_found"),
        ({"session_id": 999999, "recipient_teacher_id": b}, 404, "session_not_found"),
        ({"session_id": sid, "recipient_teacher_id": b, "message": 5}, 400, "invalid_message"),
        ({"session_id": sid, "recipient_teacher_id": b, "message": "x" * 501},
         400, "message_too_long"),
    ]
    for payload, status, code in cases:
        resp = client.post(URL, headers=h["a_h"], json=payload)
        assert (resp.status_code, resp.get_json()["error"]) == (status, code), payload


def test_only_the_cohort_teacher_may_send(client, handover):
    h = handover
    resp = send(client, h["b_h"], h["session"].id, _id(h["c"]))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "session_not_found"


def test_busy_recipient_is_409(client, db, handover, make_cohort):
    h = handover
    add_session(db, make_cohort(teacher_id=_id(h["b"])), start="08:30", end="09:30")
    resp = send(client, h["a_h"], h["session"].id, _id(h["b"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "recipient_busy"


def test_started_session_cannot_be_requested(client, handover):
    from datetime import datetime

    h = handover
    h["clock"](datetime(2026, 10, 6, 9, 0))
    resp = send(client, h["a_h"], h["session"].id, _id(h["b"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "session_started"
