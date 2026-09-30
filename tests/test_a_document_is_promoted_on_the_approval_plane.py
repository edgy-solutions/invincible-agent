"""Promotion and rejection are verbs on the ONE approval plane (ADR-0041 §5, §6, §8).

What this seals, each against the unfixed shape it replaces:
  * A PROMOTION APPENDS. The decision record is written, then a promotion fact whose keys are
    exactly {ingest_id, promoted_by, promoted_at, promotion_ref}. Nothing carries or edits a
    provenance block.
  * A REJECTION SWEEPS BY KEY, once, on the ingest_id, after its record.
  * RECORD FIRST, AND FAIL-CLOSED. The writer's soft failure refuses the act, and the store is
    never touched. The partial state that can exist is record-without-fact, which leaves the data
    labelled unvouched.
  * can_act ON THE AUDIENCE, FAIL-CLOSED. False, a raise, or an empty identity: all refuse.
  * REFUSED MEANS STILL PENDING. Through the real route, every refusal leaves
    `mark_task_resolved` uncalled, and with no store configured (today's deployment) the act is
    503.

Run: uv run --frozen pytest tests/test_a_document_is_promoted_on_the_approval_plane.py -q
"""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from src.iagent import decision_record, decision_record_writer, human_tasks, ingest_status, promotion

INGEST_ID = "sha256:" + "ab" * 32
PAYLOAD = {
    "ingest_id": INGEST_ID,
    "object_ref": "ingress-user/bob/pcn-4471.pdf",
    "content_kind": "work-instructions",
    "pipeline_version": "doc-tools@7f-33",
    "format_fingerprint": "pdf:pcn:v1",
    "standing": "supervised",
    "extraction_ref": "s3://extractions/pcn-4471/review.json",
    "notice_id": "PCN-4471",
}
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}


class Recorder:
    """One log for the writer and the store, so ORDER is observable."""

    def __init__(self, write_result=None):
        self.log: list = []
        self.write_result = {"ok": True} if write_result is None else write_result

    def writer(self, rec):
        self.log.append(("record", rec))
        return self.write_result

    def append_promotion(self, fact):
        self.log.append(("fact", fact))

    def sweep(self, ingest_id):
        self.log.append(("sweep", ingest_id))
        return 7


def _act(rec: Recorder, *, decision="promoted", can_act=lambda a, c: True, store="rec",
         payload=None, acted_by="bob", comment=""):
    return promotion.act(
        dict(PAYLOAD) if payload is None else payload, decision=decision, acted_by=acted_by,
        audience="aud:sustainment-approvers", comment=comment, can_act=can_act,
        record_writer=rec.writer, store=rec if store == "rec" else store,
        governing=GOVERNING, era="commissioning", now_ms=1_000)


# ── THE VERBS ─────────────────────────────────────────────────────────────────────────────────

def test_a_PROMOTION_writes_the_record_THEN_appends_a_new_fact():
    rec = Recorder()
    out = _act(rec)
    assert [k for k, _ in rec.log] == ["record", "fact"]
    record, fact = rec.log[0][1], rec.log[1][1]
    assert record["request_key"] == INGEST_ID
    assert record["record_id"] == decision_record.record_id_for(INGEST_ID)
    assert record["outcome"] == "promoted" and record["admitted_by"] == "policy"
    assert record["trust_rung"] == "supervised"
    assert record["checks"][0]["inputs"]["extraction_ref"] == PAYLOAD["extraction_ref"]
    assert record["checks"][0]["inputs"]["reviewed_by"] == "human:bob"
    decision_record.validate_decision_record(record)
    assert fact == {"ingest_id": INGEST_ID, "promoted_by": "human:bob", "promoted_at": 1_000,
                    "promotion_ref": record["record_id"]}
    assert out["fact"] == fact and out["record_id"] == record["record_id"]


def test_the_fact_carries_NO_provenance_and_the_block_is_never_handed_to_the_store():
    """ADR-0041 §5: the block is frozen at write. A fact with a provenance-shaped key is the
    shape a store would merge over the block, so the fact's key set is exact."""
    rec = Recorder()
    _act(rec)
    fact = rec.log[1][1]
    assert set(fact) == {"ingest_id", "promoted_by", "promoted_at", "promotion_ref"}
    assert not ({"standing", "obtained_via", "provenance"} & set(fact))


def test_a_REJECTION_writes_the_record_THEN_sweeps_by_ingest_id_once():
    rec = Recorder()
    out = _act(rec, decision="rejected", comment="superseded revision")
    assert [k for k, _ in rec.log] == ["record", "sweep"]
    assert rec.log[0][1]["outcome"] == "rejected"
    assert rec.log[0][1]["checks"][0]["inputs"]["comment"] == "superseded revision"
    assert rec.log[1][1] == INGEST_ID
    assert out["swept"] == 7 and "fact" not in out


# ── FAIL-CLOSED ───────────────────────────────────────────────────────────────────────────────

def _boom(a, c):
    raise RuntimeError("topaz down")


@pytest.mark.parametrize("can_act,acted_by", [
    (lambda a, c: False, "bob"),
    (_boom, "bob"),
    (lambda a, c: "yes", "bob"),     # truthy is not True
    (lambda a, c: True, ""),
])
def test_can_act_is_FAIL_CLOSED_and_nothing_is_written(can_act, acted_by):
    rec = Recorder()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(rec, can_act=can_act, acted_by=acted_by)
    assert ei.value.status == 403 and rec.log == []


#: Derived from the CONSUMER, not from PAYLOAD_FIELDS: a field dropped from that list must
#: still be required, because the record is built from the subject's fields.
_SUBJECT_FIELDS = tuple(f.name for f in dataclasses.fields(promotion.PromotionSubject)
                        if f.name != "notice_id")


def test_the_required_payload_IS_the_record_subject():
    assert promotion.PAYLOAD_FIELDS == _SUBJECT_FIELDS


@pytest.mark.parametrize("field", _SUBJECT_FIELDS)
def test_a_payload_missing_a_record_field_is_refused(field):
    rec = Recorder()
    bad = dict(PAYLOAD)
    bad.pop(field)
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(rec, payload=bad)
    assert ei.value.status == 422 and field in str(ei.value) and rec.log == []


@pytest.mark.parametrize("spelling", [
    "ab" * 32,                       # no prefix
    "sha256:" + "AB" * 32,           # upper case
    "sha256:" + "ab" * 31 + "a",     # 63 hex
    "sha1:" + "ab" * 20,
])
def test_a_misspelled_ingest_id_is_refused_because_its_sweep_would_delete_nothing(spelling):
    rec = Recorder()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(rec, payload={**PAYLOAD, "ingest_id": spelling}, decision="rejected")
    assert ei.value.status == 422 and rec.log == []


def test_the_ingest_id_is_the_bytes_sha256_in_the_accepted_spelling():
    data = b"%PDF-1.7 pcn"
    iid = promotion.ingest_id_for(data)
    assert iid == "sha256:" + hashlib.sha256(data).hexdigest()
    assert promotion.INGEST_ID_RE.match(iid)


def test_NO_STORE_refuses_503_before_any_record_is_written():
    rec = Recorder()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(rec, store=None)
    assert ei.value.status == 503 and rec.log == []


@pytest.mark.parametrize("result,status,error", [
    ({"ok": False, "reason": "unreachable"}, 503, "decision_record_not_written"),
    ({"ok": False, "reason": "http_403"}, 503, "decision_record_not_written"),
    (None, 503, "decision_record_not_written"),
    ({"ok": "true"}, 503, "decision_record_not_written"),
    ({"ok": False, "reason": "immutable_conflict"}, 409, "promotion_already_decided"),
])
def test_a_record_that_was_not_written_REFUSES_the_act_and_the_store_is_untouched(
        result, status, error):
    rec = Recorder()
    rec.write_result = result
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(rec, decision="rejected")
    assert (ei.value.status, ei.value.error) == (status, error)
    assert [k for k, _ in rec.log] == ["record"]


def test_an_undeclared_verb_is_refused():
    rec = Recorder()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(rec, decision="approved")
    assert ei.value.status == 422 and rec.log == []


# ── THE JOIN: THE DECLARATION AND THE CODE NAME THE SAME VERBS ────────────────────────────────

@pytest.fixture
def fresh_declarations(monkeypatch):
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)


def test_the_species_is_DECLARED_with_exactly_the_verbs_the_effect_implements(
        fresh_declarations):
    assert tuple(human_tasks.verbs_for_kind(promotion.KIND)) == promotion.VERBS
    assert "rejected" in human_tasks.reason_required_for(promotion.KIND)
    assert "promoted" not in human_tasks.reason_required_for(promotion.KIND)


# ── THROUGH THE REAL ROUTE: REFUSED MEANS STILL PENDING ───────────────────────────────────────

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402


@pytest.fixture
def route(monkeypatch, fresh_declarations):
    calls: dict = {"resolved": [], "records": [], "can_act": []}
    task = {"task_id": "t-1", "kind": promotion.KIND, "audience": "aud:sustainment-approvers",
            "payload": dict(PAYLOAD)}
    monkeypatch.setattr(human_tasks, "list_tasks_for", lambda caller, status="pending": [task])

    def can_act(audience, caller):
        calls["can_act"].append((audience, caller))
        return calls.get("allow", True)

    monkeypatch.setattr(human_tasks, "check_can_act", can_act)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: calls["resolved"].append((tid, kw)) or 1)

    def writer(rec):
        calls["records"].append(rec)
        return calls.get("write", {"ok": True})

    monkeypatch.setattr(decision_record_writer, "graph_writer", writer)
    user = type("U", (), {"authz_id": "bob", "sub": "bob", "email": "bob@x",
                          "persona": "SUSTAINMENT_ENGINEER", "entitled_domains": ["SUSTAINMENT"],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c, calls, monkeypatch
    gateway.app.dependency_overrides.clear()


def _post(c, decision, comment=""):
    return c.post("/human_tasks/t-1/act", json={"decision": decision, "comment": comment})


def test_ROUTE_with_no_store_configured_is_503_and_the_task_STAYS_PENDING(route):
    c, calls, _ = route
    r = _post(c, "promoted")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "promotion_store_unconfigured"
    assert calls["resolved"] == [] and calls["records"] == []


def test_ROUTE_promotes_then_resolves_the_projection(route):
    c, calls, mp = route
    store = Recorder()
    mp.setattr(gateway, "_promotion_store", lambda: store)
    r = _post(c, "promoted")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "promoted" and body["ingest_id"] == INGEST_ID
    assert body["fact"]["promoted_by"] == "human:bob"
    assert calls["records"][0]["governing"]["ruleset_ref"].startswith("task_kind:document_promotion@")
    assert [k for k, _ in store.log] == ["fact"]
    assert calls["resolved"] == [("t-1", {"caller_id": "bob", "decision": "promoted",
                                          "comment": ""})]
    # the effect re-asked can_act itself, beyond the route's own check
    assert len(calls["can_act"]) == 2


def test_ROUTE_a_record_write_failure_leaves_the_task_PENDING(route):
    c, calls, mp = route
    store = Recorder()
    mp.setattr(gateway, "_promotion_store", lambda: store)
    calls["write"] = {"ok": False, "reason": "unreachable"}
    r = _post(c, "rejected", comment="superseded")
    assert r.status_code == 503, r.text
    assert store.log == [] and calls["resolved"] == []


# ── AFTER mark_task_resolved: the ingest_status_projection is updated, best-effort ───────────

def test_ROUTE_promotion_updates_the_ingest_status_projection(route):
    c, calls, mp = route
    mp.setattr(gateway, "_promotion_store", lambda: Recorder())
    updates: list = []
    mp.setattr(ingest_status, "update_status",
              lambda ingest_id, stage, *, detail=None: updates.append((ingest_id, stage, detail)))
    r = _post(c, "promoted")
    assert r.status_code == 200, r.text
    record_id = calls["records"][0]["record_id"]
    assert len(updates) == 1
    got_id, got_stage, got_detail = updates[0]
    assert got_id == INGEST_ID and got_stage == "promoted"
    assert got_detail.startswith("record "), got_detail
    assert record_id in got_detail


def test_ROUTE_rejection_updates_the_ingest_status_projection_with_the_comment(route):
    c, calls, mp = route
    mp.setattr(gateway, "_promotion_store", lambda: Recorder())
    updates: list = []
    mp.setattr(ingest_status, "update_status",
              lambda ingest_id, stage, *, detail=None: updates.append((ingest_id, stage, detail)))
    r = _post(c, "rejected", comment="superseded revision")
    assert r.status_code == 200, r.text
    assert updates == [(INGEST_ID, "rejected", "superseded revision")]


@pytest.mark.parametrize("comment", ["", "   "])
def test_ROUTE_a_rejection_WITHOUT_a_reason_is_refused_before_the_projection(route, comment):
    """update_status refuses `rejected` without a detail, and the act branch passes the comment
    as that detail. What makes that safe is the kind declaration refusing a bare rejection
    first (422), so the projection is never asked. If the declaration ever stops requiring a
    reason, this goes red instead of a row silently stranding at awaiting_disposition."""
    c, calls, mp = route
    mp.setattr(gateway, "_promotion_store", lambda: Recorder())
    updates: list = []
    mp.setattr(ingest_status, "update_status",
              lambda ingest_id, stage, *, detail=None: updates.append((ingest_id, stage, detail)))
    r = _post(c, "rejected", comment=comment)
    assert r.status_code == 422, r.text
    assert "REQUIRES a reason" in r.text
    assert updates == [] and calls["resolved"] == []


def test_ROUTE_a_failed_projection_update_is_LOGGED_and_the_request_still_succeeds(route):
    """The decision record is the grant (ADR-0041 §5); the projection is a read model. A
    failure updating it must not fail a request whose decision already stands."""
    c, calls, mp = route
    mp.setattr(gateway, "_promotion_store", lambda: Recorder())

    def _boom(ingest_id, stage, *, detail=None):
        raise RuntimeError("projector db down")

    mp.setattr(ingest_status, "update_status", _boom)
    r = _post(c, "promoted")
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "promoted"
    assert calls["resolved"] != [], "mark_task_resolved must still have run"


def test_ROUTE_can_act_no_is_403_before_any_write(route):
    c, calls, mp = route
    mp.setattr(gateway, "_promotion_store", lambda: Recorder())
    calls["allow"] = False
    r = _post(c, "promoted")
    assert r.status_code == 403
    assert calls["records"] == [] and calls["resolved"] == []


@pytest.mark.parametrize("decision,comment", [("approved", ""), ("rejected", "")])
def test_ROUTE_the_declaration_refuses_before_the_effect(route, decision, comment):
    """`approved` is not this species' verb, and `rejected` needs a reason. Both are refused by
    the declaration, before anything is written."""
    c, calls, mp = route
    mp.setattr(gateway, "_promotion_store", lambda: Recorder())
    r = _post(c, decision, comment)
    assert r.status_code == 422, r.text
    # `allowed` is the DECLARATION's refusal; the effect's own 422 carries no such key, so
    # this cannot pass on the effect's refusal standing in for a missing declaration.
    assert "allowed" in r.json()["detail"], r.text
    assert calls["records"] == [] and calls["resolved"] == []
