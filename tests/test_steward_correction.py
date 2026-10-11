"""STEWARD CORRECTION (architect ruling 2026-10-10, rev187 pin).

A steward reviewing an extracted parts list may DELETE a row, ADD one the extractor missed, or CORRECT
a misread MPN -- each with evidence -- or REJECT the whole review as the wrong document. The ruling:

  1. a correction WRITES TO THE GRAPH, stamped obtained_via=steward-corrected (+ who, what the
     extractor read, the evidence pointer);
  2. every accepted decision with edits files ONE extraction_defect task (notice, pin digest, edits);
  3. a narrow REJECT closes the task, writes NOTHING, and leaves the row `review_rejected`;
  4. a retry is driven only by a pin change, never by a person.

Arms (each defended by a named mutation, see the commit body):
  1 reject writes nothing          2 correction writes provenance     3 never re-keys
  4 the defect is filed once       5 validation (gateway 422 AND the workflow bypass)
  6 retry is pin-driven            7 the refusal envelope (appended by the presentation commit)

Run: uv run pytest tests/test_steward_correction.py -v
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent_fleet" / "restate_analyst"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("restate")
httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import dispatch_driver  # noqa: E402  -- the executor's own (flat) module identity
import grouped_review_workflow as grw  # noqa: E402
import main as ra_main  # noqa: E402
import review_composer  # noqa: E402
import steward_correction as sc  # noqa: E402
from workflow_bulk_resolve import PartItem, ReviewBatch  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

FP = "IPCN25300X"
EV = "p3 table 2 row 7"
IRI = "http://internal/components/"
PIN = "doc-tools@61f74dc"


def _iri(mpn):
    return IRI + mpn


def _items():
    """A, B, C are extracted. A is the unedited control; B is corrected; C is deleted."""
    return [PartItem(mpn=m, relevance=1.0, subject=_iri(m), proposed_disposition="dispatchLTB",
                     needs_review=False, proposed_by_ruleset="rules@abc123def456")
            for m in ("A", "B", "C")]


def _state_items():
    return grw.batch_items_to_state(ReviewBatch(approver="svc:review-starter", items=_items()))


EDITS = {
    "corrected": [{"mpn": "B", "corrected_mpn": "B2", "evidence": EV}],
    "deleted": [{"mpn": "C", "reason": "page furniture, not a part"}],
    "added": [{"mpn": "D", "disposition": "dispatchLTB", "reason": "missed by the extractor",
               "evidence": "p4 table 1 row 2"}],
}


# ---------------------------------------------------------------------------
# A Restate-faithful context for the grouped step + recorders for every effect
# ---------------------------------------------------------------------------
class _Promise:
    def __init__(self, value):
        self._v = value

    async def value(self):
        return self._v


class _Ctx:
    def __init__(self, decision, *, key="wf-1", journal=None, state=None):
        self._decision, self._key = decision, key
        self.journal = journal if journal is not None else {}
        self.state = state if state is not None else {}
        self.sends = []

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    async def get(self, k):
        return self.state.get(k)

    async def run(self, name, fn):
        if name in self.journal:
            return self.journal[name]
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        self.journal[name] = r
        return r

    def promise(self, name, type_hint=None):
        return _Promise(self._decision)

    def object_send(self, handler, key, arg, idempotency_key=None):
        self.sends.append({"key": key, "arg": arg})


class Effects:
    def __init__(self):
        self.minted = []          # every _mint_dispatch_task(task) body
        self.writes = []          # every engine-o /write_item_state body
        self.resolved = []        # every subject resolution asked of engine-o


@pytest.fixture
def fx(monkeypatch):
    e = Effects()
    monkeypatch.setattr(dispatch_driver, "_mint_dispatch_task",
                        lambda task: e.minted.append(task) or {"ok": True})
    monkeypatch.setattr(review_composer, "resolve_subject_via_engine_o",
                        lambda mpn, **kw: e.resolved.append(mpn) or _iri(mpn))

    def _post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/write_item_state"), f"unexpected POST {url}"
        e.writes.append(json)
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"ok": True})
    monkeypatch.setattr(dispatch_driver.requests, "post", _post)
    monkeypatch.setattr(dispatch_driver, "outbound_auth_headers", lambda **kw: {}, raising=False)
    return e


def _step():
    return SimpleNamespace(id="s", audience="disposition_review:SUSTAINMENT", title=None,
                           summary=None, requested_by=None,
                           completion=SimpleNamespace(claiming=False))


def _request(**over):
    r = {"approver": "svc:review-starter", "notice_fingerprint": FP, "notice_id": FP,
         "batch_items": _state_items(), "compartment": "SUSTAINMENT", "pipeline_version": PIN}
    r.update(over)
    return r


async def _run_step(decision, fx, *, ctx=None, request=None):
    ctx = ctx or _Ctx(decision)
    out = await ra_main._run_grouped_human_await(
        ctx, "wf-1", _step(), "decision", request or _request(), {}, "")
    # deliver every enqueued dispatch's graph write exactly as the DispatchItem handler would
    for s in ctx.sends:
        gw = (s["arg"] or {}).get("graph_write")
        if gw:
            dispatch_driver._write_disposition_state(gw)
    return out, ctx


def _approve(**extra):
    return {"verdict": "approved", "overrides": {}, "acted_by": "alice@example.com", **extra}


def _defects(fx):
    return [t for t in fx.minted if t.get("kind") == sc.EXTRACTION_DEFECT_KIND]


# ===========================================================================
# ARM 1 -- a narrow reject WRITES NOTHING, carries its code, and the row ends review_rejected
# ===========================================================================
@pytest.mark.asyncio
async def test_reject_writes_nothing_and_keeps_the_record(fx):
    decision = {"verdict": "rejected", "reason_code": "not_a_notice", "comment": "a datasheet",
                "acted_by": "alice@example.com", "overrides": {}}
    out, ctx = await _run_step(decision, fx)
    assert out["status"] == "REJECTED"
    assert ctx.sends == [], "a reject dispatched work"
    assert fx.writes == [], "a reject wrote item state"
    assert _defects(fx) == [], "a reject filed an extraction_defect"
    assert out["decision_record"]["reason_code"] == "not_a_notice"
    assert out["decision_record"]["comment"] == "a datasheet"
    assert out["decision_record"]["acted_by"] == "alice@example.com"


# --- the gateway half: a fake Restate ingress + the act route --------------------------------
class _FakeAsyncClient:
    calls: list = []
    submit_response: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        type(self).calls.append((url, json))
        if url.endswith("/get_batch"):
            return SimpleNamespace(status_code=200, json=lambda: {"items": _state_items()})
        return SimpleNamespace(status_code=200, json=lambda: dict(type(self).submit_response))


_TASK = {"task_id": "grouped:wf-1", "kind": "grouped_review", "workflow_id": "wf-1",
         "audience": "disposition_review:SUSTAINMENT"}


@pytest.fixture
def act(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.submit_response = {"status": "accepted", "accepted": True, "resolved_count": 3,
                                        "notice_fingerprint": FP}
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(ht, "list_tasks_for", lambda actor, status="pending": [dict(_TASK)])
    monkeypatch.setattr(ht, "check_can_act", lambda audience, actor: True)
    monkeypatch.setattr(ht, "mark_task_resolved", lambda *a, **k: 1)
    statuses = []
    monkeypatch.setattr(ist, "update_status",
                        lambda ingest_id, status, **kw: statuses.append((ingest_id, status, kw)))
    user = SimpleNamespace(authz_id="alice@example.com", id="alice@example.com",
                           sub="alice@example.com", email="alice@example.com", persona=None,
                           entitled_domains=[], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        c.statuses = statuses
        yield c
    gateway.app.dependency_overrides.clear()


def _submits():
    return [j for u, j in _FakeAsyncClient.calls if u.endswith("/submit_decision")]


def test_reject_reaches_submit_decision_with_the_code_and_the_row_ends_review_rejected(act):
    _FakeAsyncClient.submit_response = {"status": "accepted", "accepted": True, "rejected": True,
                                        "reason_code": "parts_list_unusable", "resolved_count": 0,
                                        "notice_fingerprint": FP}
    r = act.post("/human_tasks/grouped:wf-1/act",
                 json={"decision": "rejected", "reason_code": "parts_list_unusable", "comment": "garbled"})
    assert r.status_code == 200, r.text
    (sent,) = _submits()
    assert sent["decision"]["verdict"] == "rejected"
    assert sent["decision"]["reason_code"] == "parts_list_unusable"
    assert sent["decision"]["comment"] == "garbled"
    assert sent["decision"]["acted_by"] == "alice@example.com"
    assert r.json()["status"] == "review_rejected"
    assert [(i, s) for i, s, _ in act.statuses] == [(FP, ist.REVIEW_REJECTED)], \
        "the ingest row did not end review_rejected"


def test_reject_without_a_reason_code_is_422_and_reaches_nothing(act):
    r = act.post("/human_tasks/grouped:wf-1/act", json={"decision": "rejected", "comment": "no"})
    assert r.status_code == 422, r.text
    assert _submits() == [] and act.statuses == []


def test_the_workflow_refuses_a_reject_without_a_valid_code():
    batch = ReviewBatch(approver="a", items=_items())
    for raw in ({"verdict": "rejected", "acted_by": "x"},
                {"verdict": "rejected", "reason_code": "because", "acted_by": "x"}):
        assert not grw.evaluate_submission(batch, raw, notice_fingerprint=FP).accepted


# ===========================================================================
# ARM 2 -- a correction WRITES provenance; the unedited row's write is untouched (control)
# ===========================================================================
PROV_KEYS = ("obtained_via", "corrected_by", "extracted_value", "evidence")


def _by_iri(fx):
    return {w["subject_iri"]: w for w in fx.writes}


@pytest.mark.asyncio
async def test_a_corrected_row_and_an_added_row_carry_provenance(fx):
    out, _ = await _run_step(_approve(row_edits=EDITS), fx)
    w = _by_iri(fx)
    b = w[_iri("B")]
    assert b["obtained_via"] == "steward-corrected"
    assert b["corrected_by"] == "alice@example.com"
    assert b["extracted_value"] == "B"
    assert b["evidence"] == EV
    d = w[_iri("D")]
    assert d["obtained_via"] == "steward-corrected" and d["corrected_by"] == "alice@example.com"
    assert "extracted_value" in d and d["extracted_value"] is None, \
        "an ADDED row has no extracted value -- it must be an explicit null"
    assert d["evidence"] == "p4 table 1 row 2"


@pytest.mark.asyncio
async def test_the_unedited_row_keeps_todays_write_exactly(fx):
    await _run_step(_approve(row_edits=EDITS), fx)
    a = _by_iri(fx)[_iri("A")]
    assert not any(k in a for k in PROV_KEYS + ("corrected_value",)), a
    assert set(a) == {"subject_iri", "disposition_state", "disposition_ref", "proposed_by_ruleset"}
    # and a decision with NO edits is byte-for-byte today's path for every row
    fx.writes.clear()
    await _run_step(_approve(), fx, ctx=_Ctx(_approve(), key="wf-2"))
    assert len(fx.writes) == 3
    assert all(set(x) == {"subject_iri", "disposition_state", "disposition_ref", "proposed_by_ruleset"}
               for x in fx.writes)


@pytest.mark.asyncio
async def test_a_deleted_row_gets_no_write_and_is_not_dispatched(fx):
    _, ctx = await _run_step(_approve(row_edits=EDITS), fx)
    assert _iri("C") not in _by_iri(fx)
    assert not any(s["key"].endswith(":C") for s in ctx.sends)


# ===========================================================================
# ARM 3 -- identity NEVER moves: the write targets the EXTRACTED mpn's IRI
# ===========================================================================
@pytest.mark.asyncio
async def test_the_corrected_write_targets_the_extracted_mpns_iri(fx):
    _, ctx = await _run_step(_approve(row_edits=EDITS), fx)
    w = _by_iri(fx)
    assert _iri("B") in w, "the corrected row's write must target the EXTRACTED mpn's subject"
    assert _iri("B2") not in w, "the corrected value must never become a subject (that is a re-key)"
    assert w[_iri("B")]["corrected_value"] == "B2", "the corrected value rides as a PROPERTY"
    assert f"{FP}:B" in {s["key"] for s in ctx.sends}
    assert f"{FP}:B2" not in {s["key"] for s in ctx.sends}


# ===========================================================================
# ARM 4 -- ONE extraction_defect per accepted decision with edits, idempotent, none without edits
# ===========================================================================
def _canon_pin(v):
    return "sha256:" + hashlib.sha256(
        json.dumps({"pipeline_version": v}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.asyncio
async def test_one_defect_task_carries_notice_pin_and_every_edit(fx):
    await _run_step(_approve(row_edits=EDITS), fx)
    (t,) = _defects(fx)
    p = t["payload"]
    assert p["notice"] == FP
    assert p["pin_digest"] == _canon_pin(PIN) and p["pin_fields_missing"] is False
    ops = {(e["op"], e.get("extracted"), e.get("corrected")) for e in p["edits"]}
    assert ops == {("corrected", "B", "B2"), ("added", None, "D"), ("deleted", "C", None)}
    ev = {e["op"]: e for e in p["edits"]}
    assert ev["corrected"]["evidence"] == EV and ev["deleted"]["reason"]
    assert t["audience"] == "dispatch_failure:SUSTAINMENT"


@pytest.mark.asyncio
async def test_a_record_with_no_pin_says_so_and_invents_none(fx):
    await _run_step(_approve(row_edits=EDITS), fx, request=_request(pipeline_version=""))
    (t,) = _defects(fx)
    assert t["payload"]["pin_digest"] is None and t["payload"]["pin_fields_missing"] is True


@pytest.mark.asyncio
async def test_a_repeat_delivery_files_no_second_task(fx):
    ctx1 = _Ctx(_approve(row_edits=EDITS))
    await _run_step(None, fx, ctx=ctx1)
    # (a) a REPLAY of the same invocation (same journal) re-executes nothing
    await _run_step(None, fx, ctx=_Ctx(_approve(row_edits=EDITS), journal=ctx1.journal))
    assert len(_defects(fx)) == 1, "a replay re-filed the defect"
    # (b) a whole REDELIVERY (fresh journal) re-issues the SAME task_key, which the register upserts
    await _run_step(None, fx, ctx=_Ctx(_approve(row_edits=EDITS)))
    assert len({t["task_key"] for t in _defects(fx)}) == 1


@pytest.mark.asyncio
async def test_an_approval_with_no_edits_files_nothing(fx):
    await _run_step(_approve(), fx)
    assert _defects(fx) == []


# ===========================================================================
# ARM 5 -- the validation table: the gateway's 422s, and the workflow when the gateway is bypassed
# ===========================================================================
_OK_DEL = {"mpn": "C", "reason": "furniture"}
_CASES = {
    "reason_code_with_approved": {"decision": "approved", "reason_code": "not_a_notice"},
    "row_edits_with_rejected": {"decision": "rejected", "reason_code": "not_a_notice",
                                "row_edits": {"deleted": [_OK_DEL]}},
    "reject_without_reason_code": {"decision": "rejected"},
    "reason_code_not_in_the_set": {"decision": "rejected", "reason_code": "because"},
    "added_without_evidence": {"decision": "approved", "row_edits": {"added": [
        {"mpn": "D", "disposition": "dispatchLTB", "reason": "r", "evidence": "  "}]}},
    "corrected_without_evidence": {"decision": "approved", "row_edits": {"corrected": [
        {"mpn": "B", "corrected_mpn": "B2", "evidence": ""}]}},
    "deleted_without_reason": {"decision": "approved", "row_edits": {"deleted": [
        {"mpn": "C", "reason": ""}]}},
    "added_without_reason": {"decision": "approved", "row_edits": {"added": [
        {"mpn": "D", "disposition": "dispatchLTB", "reason": " ", "evidence": EV}]}},
    "mpn_twice_across_deleted_and_corrected_ignoring_case": {"decision": "approved", "row_edits": {
        "deleted": [{"mpn": "B", "reason": "r"}],
        "corrected": [{"mpn": "b", "corrected_mpn": "B2", "evidence": EV}]}},
    "corrected_mpn_equals_mpn_ignoring_case": {"decision": "approved", "row_edits": {"corrected": [
        {"mpn": "B", "corrected_mpn": "b", "evidence": EV}]}},
    "added_collides_with_an_extracted_mpn_ignoring_case": {"decision": "approved", "row_edits": {
        "added": [{"mpn": "a", "disposition": "dispatchLTB", "reason": "r", "evidence": EV}]}},
    "corrected_mpn_collides_with_an_extracted_mpn": {"decision": "approved", "row_edits": {
        "corrected": [{"mpn": "B", "corrected_mpn": "A", "evidence": EV}]}},
    "unknown_key_in_row_edits": {"decision": "approved", "row_edits": {"renamed": []}},
    "unknown_key_on_a_row": {"decision": "approved", "row_edits": {"deleted": [
        {"mpn": "C", "reason": "r", "why": "x"}]}},
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_the_gateway_refuses_with_422(act, case):
    r = act.post("/human_tasks/grouped:wf-1/act", json=_CASES[case])
    assert r.status_code == 422, (case, r.status_code, r.text)
    assert _submits() == [], "a 422 case reached the workflow"


def _as_workflow_decision(body):
    d = {"verdict": body["decision"], "overrides": {}, "acted_by": "alice@example.com"}
    d.update({k: v for k, v in body.items() if k != "decision"})
    return d


@pytest.mark.parametrize("case", sorted(_CASES))
def test_evaluate_submission_refuses_the_same_payload_when_the_gateway_is_bypassed(case):
    batch = ReviewBatch(approver="a", items=_items())
    sub = grw.evaluate_submission(batch, _as_workflow_decision(_CASES[case]), notice_fingerprint=FP)
    assert not sub.accepted, f"{case}: the workflow accepted a payload the gateway refuses"
    assert sub.reason


def test_positive_control_a_valid_edit_passes_both_doors(act):
    r = act.post("/human_tasks/grouped:wf-1/act", json={"decision": "approved", "row_edits": EDITS})
    assert r.status_code == 200, r.text
    (sent,) = _submits()
    assert sent["decision"]["row_edits"]["corrected"][0]["corrected_mpn"] == "B2"
    batch = ReviewBatch(approver="a", items=_items())
    sub = grw.evaluate_submission(batch, _approve(row_edits=EDITS), notice_fingerprint=FP)
    assert sub.accepted, sub.reason
    assert {r.mpn for r in sub.resolutions} == {"A", "B", "D"}


def test_an_override_aimed_at_a_new_identity_is_refused_by_the_workflow():
    batch = ReviewBatch(approver="a", items=_items())
    raw = _approve(row_edits=EDITS, overrides={"B2": {"disposition": "archive", "reason": "r"}})
    assert not grw.evaluate_submission(batch, raw, notice_fingerprint=FP).accepted


# ===========================================================================
# ARM 6 -- the retry is driven only by a pin change
# ===========================================================================
_RID = "sha256:" + "d" * 64
_OLD = "sha256:" + "1" * 64


def _caller(authz_id):
    return SimpleNamespace(authz_id=authz_id, id=authz_id, sub=authz_id, email=authz_id,
                           persona=None, entitled_domains=[], is_authenticated=True)


@pytest.fixture
def retry(monkeypatch):
    state = {"row": {"id": _RID, "status": ist.REVIEW, "kind": "pdf", "pin_digest": _OLD},
             "lookups": 0, "filed": 0}

    def _row(ingest_id):
        state["lookups"] += 1
        return state["row"]
    monkeypatch.setattr(ist, "get_status_unscoped", _row)

    async def _file(*a, **k):
        state["filed"] += 1
        return ("document_promotion:" + _RID, "FILED")
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _file)

    def _as(authz_id):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _caller(authz_id)
        return TestClient(gateway.app)
    state["as"] = _as
    yield state
    gateway.app.dependency_overrides.clear()


def test_a_human_caller_is_403_before_any_lookup(retry):
    r = retry["as"]("alice@example.com").post(f"/ingest/{_RID}/retry", json={"pin_digest": "sha256:x"})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "retry_is_pin_driven"
    assert retry["lookups"] == 0 and retry["filed"] == 0


def test_a_service_with_the_recorded_pin_is_409_pin_unchanged(retry):
    r = retry["as"]("svc:pin-driver").post(f"/ingest/{_RID}/retry", json={"pin_digest": _OLD})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "pin_unchanged"
    assert retry["filed"] == 0


def test_a_service_with_a_different_pin_proceeds(retry):
    r = retry["as"]("svc:pin-driver").post(f"/ingest/{_RID}/retry",
                                           json={"pin_digest": "sha256:" + "2" * 64})
    assert r.status_code == 200, r.text
    assert r.json()["task_status"] == "FILED" and retry["filed"] == 1


def test_a_row_with_no_recorded_pin_is_409_no_recorded_pin(retry):
    retry["row"].pop("pin_digest")
    r = retry["as"]("svc:pin-driver").post(f"/ingest/{_RID}/retry",
                                           json={"pin_digest": "sha256:" + "2" * 64})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "no_recorded_pin"
    assert retry["filed"] == 0


def test_a_service_without_a_pin_in_the_body_is_422(retry):
    r = retry["as"]("svc:pin-driver").post(f"/ingest/{_RID}/retry", json={})
    assert r.status_code == 422


# ===========================================================================
# ARM 7 -- the refusal envelope carries hazard_id and gap when the body has them, and only then
# ===========================================================================
@pytest.fixture(scope="module")
def pres():
    import importlib
    from unittest.mock import MagicMock
    mp = pytest.MonkeyPatch()
    for n in ("baml_client", "baml_client.types", "baml_client.type_builder"):
        mp.setitem(sys.modules, n, MagicMock())
    name = "agent_fleet.presentation_agent.main"
    mp.delitem(sys.modules, name, raising=False)
    mod = importlib.import_module(name)
    mp.setitem(sys.modules, name, mod)
    try:
        yield mod
    finally:
        mp.undo()


def test_the_envelope_keeps_hazard_id_and_gap_when_the_body_has_them(pres):
    env = pres._refusal_envelope({"refused": True, "outcome": "source_unavailable", "reason": "r",
                                  "hazard_id": "HAZ-1003", "gap": "no source connected"})
    assert env["hazard_id"] == "HAZ-1003" and env["gap"] == "no source connected"


def test_the_envelope_gets_neither_key_when_the_body_has_neither(pres):
    env = pres._refusal_envelope({"refused": True, "outcome": "source_unavailable", "reason": "r"})
    assert "hazard_id" not in env and "gap" not in env
