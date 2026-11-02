"""A document_promotion reject names one of four codes (architect ruling 2026-10-17, "Reject
codes, final": not_a_notice, unreadable, parts_unusable, duplicate).

The wire carries the code AS the comment (`<code>` or `<code>: <note>`) and the stored detail is
that comment verbatim. A wrong value, a wrong part or missing rows is a CORRECTION (promote with
row_edits), so those three are refused. `row_edits` is read by the grouped_review branch and, behind
IAGENT_PROMOTION_ROW_EDITS (default off), the document_promotion branch; sent anywhere it is not
read it would be dropped, so it is refused by name.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import human_tasks, ingest_status, promotion  # noqa: E402
from src.iagent import gateway  # noqa: E402

INGEST_ID = "sha256:" + "ab" * 32
FOUR = ("not_a_notice", "unreadable", "parts_unusable", "duplicate")
EDITS = {"deleted": [{"mpn": "A-1", "reason": "not a part"}]}


def test_the_ruled_codes_are_exactly_four():
    """The ruling's seal: widening or narrowing the set is a new ruling."""
    assert promotion.PROMOTION_REJECT_CODES == FOUR


class _FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        if url.endswith("/get_batch"):
            return SimpleNamespace(status_code=200, json=lambda: {"items": [{"mpn": "A-1"}]})
        return SimpleNamespace(status_code=200, json=lambda: {
            "status": "accepted", "accepted": True, "resolved_count": 1})


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    w = SimpleNamespace(acts=[], resolved=[], statuses=[], kind=promotion.KIND)

    def list_tasks(caller, status="pending"):
        t = {"task_id": "t-1", "kind": w.kind, "audience": "document_promotion:SUSTAINMENT",
             "payload": {"ingest_id": INGEST_ID}}
        if w.kind == "grouped_review":
            t.update(workflow_id="wf-1", audience="disposition_review:SUSTAINMENT")
        return [t]

    def act(payload, **kw):
        w.acts.append(kw)
        return {"ingest_id": INGEST_ID, "record_id": "dr-1"}

    monkeypatch.setattr(human_tasks, "list_tasks_for", list_tasks)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda a, c: True)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: w.resolved.append((tid, kw)) or 1)
    monkeypatch.setattr(promotion, "act", act)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: object())
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(ingest_status, "get_row", lambda _id: None)   # the act reads the row first (203b)
    monkeypatch.setattr(ingest_status, "update_status",
                        lambda iid, stage, *, detail=None: w.statuses.append((iid, stage, detail)))
    user = SimpleNamespace(authz_id="bob", sub="bob", email="bob@x", persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        w.client = c
        yield w
    gateway.app.dependency_overrides.clear()


def _reject(w, comment):
    return w.client.post("/human_tasks/t-1/act", json={"decision": "rejected", "comment": comment})


@pytest.mark.ingest_v1_unconformant(
    reason="the world fake of promotion.decide returns only {ingest_id, record_id}; production also returns decision and replayed")
@pytest.mark.parametrize("code", FOUR)
def test_each_of_the_four_is_accepted_bare(world, code):
    r = _reject(world, code)
    assert r.status_code == 200, r.text
    assert r.json()["reject_code"] == code
    assert len(world.acts) == 1 and world.resolved != []


@pytest.mark.ingest_v1_unconformant(
    reason="the world fake of promotion.decide returns only {ingest_id, record_id}; production also returns decision and replayed")
@pytest.mark.parametrize("comment", ["unreadable", "unreadable: the scan is blank"])
def test_unreadable_with_or_without_a_note_is_accepted_and_stored_verbatim(world, comment):
    r = _reject(world, comment)
    assert r.status_code == 200, r.text
    assert r.json()["reject_code"] == "unreadable"
    assert world.acts[0]["comment"] == comment
    assert world.statuses == [(INGEST_ID, "rejected", comment)]


@pytest.mark.parametrize("code", ["wrong_value", "wrong_part", "missing_rows"])
def test_a_correction_is_refused_as_a_reject_and_nothing_runs(world, code):
    r = _reject(world, f"{code}: the mpn is off by one")
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "reject_code_unknown" and d["codes"] == list(FOUR)
    assert d["task_id"] == "t-1" and "row_edits" in d["message"]
    assert world.acts == [] and world.resolved == [] and world.statuses == []


@pytest.mark.parametrize("comment", ["Unreadable", "garbage", "garbage: unreadable"])
def test_the_compare_is_case_sensitive_and_unknown_is_refused(world, comment):
    r = _reject(world, comment)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "reject_code_unknown"
    assert world.acts == [] and world.resolved == []


def test_a_blank_reason_keeps_its_own_refusal(world):
    r = _reject(world, "  ")
    assert r.status_code == 422 and "REQUIRES a reason" in r.text


def test_row_edits_on_a_document_promotion_is_refused_before_any_write(world, monkeypatch):
    """Flag OFF (unset): the refusal is by name, with enabled False, and nothing runs."""
    monkeypatch.delenv("IAGENT_PROMOTION_ROW_EDITS", raising=False)
    r = world.client.post("/human_tasks/t-1/act", json={"decision": "promoted", "row_edits": EDITS})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "row_edits_not_for_kind" and d["kind"] == promotion.KIND
    assert d["enabled"] is False
    assert world.acts == [] and world.resolved == []


def test_row_edits_with_the_grouped_verb_on_a_promotion_is_also_refused(world, monkeypatch):
    monkeypatch.delenv("IAGENT_PROMOTION_ROW_EDITS", raising=False)
    r = world.client.post("/human_tasks/t-1/act", json={"decision": "approved", "row_edits": EDITS})
    assert r.status_code == 422, r.text
    assert world.acts == [] and world.resolved == []


def test_control_row_edits_on_a_grouped_review_approval_is_still_accepted(world):
    world.kind = "grouped_review"
    r = world.client.post("/human_tasks/t-1/act", json={"decision": "approved", "row_edits": EDITS})
    assert r.status_code == 200, r.text
    assert world.resolved != []
