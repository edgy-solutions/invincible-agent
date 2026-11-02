"""Spec 208: the two outcomes of a `document_empty_confirm`, through both doors (the task act and
`POST /ingest/{id}/empty`), which share the one writer `_decide_empty`; plus `no_parts` as a terminal
stage that the stage route, the retry route and the retries listing all leave alone.

Run: uv run --frozen pytest tests/test_an_empty_notice_is_confirmed_or_sent_back_by_a_steward.py -v
"""
from __future__ import annotations

import pytest

from src.iagent import gateway
from tests._empty_confirm_world import (
    DROPPER, ID, OUTSIDER, STEWARD, SVC, as_user, client, install, stage_review)

TASK = f"document_empty_confirm:{ID}:a1"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    gateway.app.dependency_overrides.clear()


def _open(monkeypatch, *, second_zero=False):
    w = install(monkeypatch)
    if second_zero:
        w.row.update(attempt=2, force_text_fallback=True)
    as_user(SVC)
    assert stage_review().status_code == 200
    return w


def _door_empty(who, body):
    as_user(who)
    return client().post(f"/ingest/{ID}/empty", json=body)


def _door_act(who, body, task=TASK):
    as_user(who)
    return client().post(f"/human_tasks/{task}/act", json=body)


@pytest.mark.parametrize("door", ["empty_dropper", "empty_steward_via_act", "act"])
def test_confirmed_no_parts_ends_the_row_no_parts_and_closes_the_task(monkeypatch, door):
    w = _open(monkeypatch)
    if door == "empty_dropper":
        r = _door_empty(DROPPER, {"decision": "confirmed_no_parts"})
        who = DROPPER
    else:
        r = _door_act(STEWARD, {"decision": "confirmed_no_parts"})
        who = STEWARD
    assert r.status_code == 200, r.text
    assert w.row["status"] == "no_parts"
    assert w.writes[-1][0] == "no_parts" and w.writes[-1][1]["detail"] == f"no parts (confirmed by {who})"
    assert w.tasks[TASK]["open"] is False and w.tasks[TASK]["decision"] == "confirmed_no_parts"
    assert w.tasks[TASK]["by"] == who
    assert [s for s, _ in w.writes if s == "failed"] == []


def test_a_caller_who_is_neither_the_dropper_nor_a_steward_gets_the_gates_refusal(monkeypatch):
    w = _open(monkeypatch)
    r = _door_empty(OUTSIDER, {"decision": "confirmed_no_parts"})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled"
    assert w.row["status"] == "review" and w.tasks[TASK]["open"] is True


def test_an_outsider_cannot_act_on_the_task_either(monkeypatch):
    w = _open(monkeypatch)
    r = _door_act(OUTSIDER, {"decision": "confirmed_no_parts"})
    assert r.status_code in (403, 404), r.text
    assert w.row["status"] == "review" and w.tasks[TASK]["open"] is True


def test_has_parts_without_a_page_is_refused_and_writes_nothing(monkeypatch):
    w = _open(monkeypatch)
    for r in (_door_empty(DROPPER, {"decision": "has_parts"}),
              _door_act(STEWARD, {"decision": "has_parts"})):
        assert r.status_code == 422, r.text
    r = _door_act(STEWARD, {"decision": "has_parts", "page": 0})
    assert r.status_code == 422, r.text
    assert w.row["status"] == "review" and w.row["attempt"] == 1 and w.tasks[TASK]["open"] is True
    assert list(w.tasks) == [TASK]


def test_confirmed_no_parts_with_a_page_is_refused(monkeypatch):
    w = _open(monkeypatch)
    for r in (_door_empty(DROPPER, {"decision": "confirmed_no_parts", "page": 3}),
              _door_act(STEWARD, {"decision": "confirmed_no_parts", "page": 3})):
        assert r.status_code == 422, r.text
    assert w.row["status"] == "review" and w.tasks[TASK]["open"] is True


def test_a_page_on_another_kind_of_task_is_refused(monkeypatch):
    w = _open(monkeypatch)
    w.register_task(kind="document_promotion", task_id="P-1", audience="document_promotion:SUSTAINMENT",
                    payload={}, title="t", summary="s", requested_by=SVC, subject_ref=ID)
    r = _door_act(STEWARD, {"decision": "has_parts", "page": 3}, task="P-1")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "page_not_for_kind"


@pytest.mark.parametrize("door", ["empty", "act"])
def test_has_parts_with_a_page_files_the_defect_forces_the_fallback_and_relaunches(monkeypatch, door):
    w = _open(monkeypatch)
    body = {"decision": "has_parts", "page": 3}
    r = _door_empty(DROPPER, body) if door == "empty" else _door_act(STEWARD, body)
    assert r.status_code == 200, r.text
    actor = DROPPER if door == "empty" else STEWARD
    defect = w.tasks[f"extraction-defect:{ID}:empty-a1"]["kw"]
    assert defect["kind"] == "extraction_defect" and defect["audience"] == "dispatch_failure:SUSTAINMENT"
    assert defect["payload"]["page"] == 3 and defect["payload"]["ingest_id"] == ID
    assert defect["payload"]["reason"] == ("the steward says the document has parts; "
                                           "the extraction found none")
    assert defect["payload"]["decided_by"] == actor and defect["payload"]["account"]["why"] == "no_table"
    assert w.row["status"] == "received" and w.row["attempt"] == 2 and w.row["force_text_fallback"] is True
    assert w.tasks[TASK]["open"] is False and w.tasks[TASK]["decision"] == "has_parts"
    as_user(SVC)
    items = client().get("/ingest/retries").json()["retries"]
    assert [(i["ingest_id"], i["attempt"], i["force_text_fallback"]) for i in items] == [(ID, 2, True)]


def test_a_second_zero_after_the_forced_fallback_refuses_has_parts_and_still_confirms(monkeypatch):
    w = _open(monkeypatch, second_zero=True)
    t2 = f"document_empty_confirm:{ID}:a2"
    assert w.tasks[t2]["kw"]["payload"]["add_missed_part"] is True
    for r in (_door_empty(DROPPER, {"decision": "has_parts", "page": 2}),
              _door_act(STEWARD, {"decision": "has_parts", "page": 2}, task=t2)):
        assert r.status_code == 409 and r.json()["detail"]["error"] == "add_missed_part_not_built"
        assert "not built yet" in r.json()["detail"]["message"]
    assert w.row["status"] == "review" and w.row["attempt"] == 2 and w.tasks[t2]["open"] is True
    assert not any(k.startswith("extraction-defect") for k in w.tasks)
    r = _door_empty(DROPPER, {"decision": "confirmed_no_parts"})
    assert r.status_code == 200 and w.row["status"] == "no_parts" and w.tasks[t2]["open"] is False


def test_a_task_from_a_superseded_attempt_cannot_decide_the_row(monkeypatch):
    w = _open(monkeypatch)
    w.row.update(status="review", attempt=2)         # the row moved on; the a1 task is stale
    r = _door_act(STEWARD, {"decision": "confirmed_no_parts"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "no_open_empty_task"
    assert w.row["status"] == "review" and w.tasks[TASK]["open"] is True


def test_deciding_a_row_that_is_not_at_review_is_refused(monkeypatch):
    w = _open(monkeypatch)
    w.row["status"] = "received"
    r = _door_empty(DROPPER, {"decision": "confirmed_no_parts"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "no_open_empty_task"


def test_an_unknown_decision_is_refused_by_the_empty_door(monkeypatch):
    _open(monkeypatch)
    assert _door_empty(DROPPER, {"decision": "approved"}).status_code == 422


def test_a_double_has_parts_relaunches_once(monkeypatch):
    w = _open(monkeypatch)
    assert _door_empty(DROPPER, {"decision": "has_parts", "page": 3}).status_code == 200
    r = _door_empty(DROPPER, {"decision": "has_parts", "page": 3})
    assert r.status_code == 409 and w.row["attempt"] == 2


# no_parts is terminal ------------------------------------------------------------------------


def _no_parts(monkeypatch):
    w = _open(monkeypatch)
    assert _door_empty(DROPPER, {"decision": "confirmed_no_parts"}).status_code == 200
    return w


def test_the_stage_route_refuses_to_move_a_no_parts_row(monkeypatch):
    w = _no_parts(monkeypatch)
    as_user(SVC)
    n = len(w.writes)
    r = client().post(f"/ingest/{ID}/stage", json={"stage": "extracting"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "backwards_move"
    assert len(w.writes) == n and w.row["status"] == "no_parts"


def test_the_retry_route_refuses_a_no_parts_row(monkeypatch):
    w = _no_parts(monkeypatch)
    as_user(SVC)
    w.row["pin_digest"] = "sha256:" + "b" * 64   # a recorded, DIFFERENT pin: only the stage stops it
    r = client().post(f"/ingest/{ID}/retry", json={"pin_digest": "sha256:" + "a" * 64})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "terminal", r.text
    assert w.row["status"] == "no_parts"


def test_the_retries_listing_never_returns_a_no_parts_row(monkeypatch):
    w = _no_parts(monkeypatch)
    w.row["attempt"] = 3                      # even a high attempt: it is not at `received`
    as_user(SVC)
    assert client().get("/ingest/retries").json() == {"retries": []}
