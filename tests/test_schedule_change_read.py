"""Schedule-change requests: sent/received lists, detail, expiry, privacy."""
from datetime import datetime

import schedule_change_helpers
from schedule_change_helpers import URL, send

handover = schedule_change_helpers.handover
clock = schedule_change_helpers.clock


def _send(client, h, who="b"):
    return send(client, h["a_h"], h["session"].id, h[who].actor_id).get_json()


def test_sender_and_recipient_lists(client, handover):
    h = handover
    req = _send(client, h)
    sent = client.get(URL + "?direction=sent", headers=h["a_h"]).get_json()
    received = client.get(URL + "?direction=received&status=pending",
                          headers=h["b_h"]).get_json()
    assert [r["id"] for r in sent["items"]] == [req["id"]]
    assert [r["id"] for r in received["items"]] == [req["id"]]
    assert client.get(URL + "?direction=received", headers=h["a_h"]).get_json()["items"] == []
    assert client.get(URL + "?direction=sent", headers=h["b_h"]).get_json()["items"] == []
    assert client.get(URL + "?direction=received&status=accepted",
                      headers=h["b_h"]).get_json()["items"] == []


def test_list_validation(client, handover):
    h = handover
    for query, code in (("", "invalid_direction"), ("?direction=all", "invalid_direction"),
                        ("?direction=sent&status=done", "invalid_status"),
                        ("?direction=sent&before_id=x", "invalid_before_id"),
                        ("?direction=sent&limit=x", "invalid_limit")):
        resp = client.get(URL + query, headers=h["a_h"])
        assert (resp.status_code, resp.get_json()["error"]) == (400, code), query


def test_paging_with_before_id(client, db, handover, make_cohort):
    h = handover
    other = schedule_change_helpers.add_session(db, h["cohort"], start="14:00", end="15:00")
    first = _send(client, h)
    second = send(client, h["a_h"], other.id, h["b"].actor_id).get_json()
    page = client.get(URL + "?direction=sent&limit=1", headers=h["a_h"]).get_json()
    assert [r["id"] for r in page["items"]] == [second["id"]]
    rest = client.get(URL + f"?direction=sent&before_id={second['id']}",
                      headers=h["a_h"]).get_json()
    assert [r["id"] for r in rest["items"]] == [first["id"]]


def test_detail_for_parties_only(client, handover):
    h = handover
    req = _send(client, h)
    for headers in (h["a_h"], h["b_h"]):
        resp = client.get(f"{URL}/{req['id']}", headers=headers)
        assert resp.status_code == 200 and resp.get_json()["status"] == "pending"
    resp = client.get(f"{URL}/{req['id']}", headers=h["c_h"])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "request_not_found"
    assert client.get(f"{URL}/999999", headers=h["a_h"]).status_code == 404


def test_pending_request_expires_once_the_session_starts(client, handover):
    h = handover
    req = _send(client, h)
    h["clock"](datetime(2026, 10, 6, 9, 0))
    data = client.get(f"{URL}/{req['id']}", headers=h["b_h"]).get_json()
    assert data["status"] == "expired" and data["resolved_at"] is not None
    pending = client.get(URL + "?direction=received&status=pending", headers=h["b_h"])
    assert pending.get_json()["items"] == []


def test_deleting_the_session_removes_its_requests(client, handover):
    h = handover
    req = _send(client, h)
    assert client.delete(f"/teacher/sessions/{h['session'].id}",
                         headers=h["a_h"]).status_code == 200
    assert client.get(f"{URL}/{req['id']}", headers=h["b_h"]).status_code == 404
