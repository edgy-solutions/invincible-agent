"""Promotion and rejection are verbs on the ONE approval plane (ADR-0041 §5, §6, §8).

What this seals, each against the unfixed shape it replaces:
  * A PROMOTION APPENDS. The ingest node is checked present, the decision record is written,
    then the fact's three predicates {promoted_by, promoted_at, promotion_ref} go onto the node.
    THE BLOCK IS BYTE-IDENTICAL AFTER: the fake graph holds a node as ONE property map, the way
    a triple store holds one subject, so a fact naming any block field would overwrite it.
  * A REJECTION SWEEPS BY KEY after its record: graph, then indexes, then the objects are moved
    (not deleted). The record is never touched.
  * EVERY STORE A VERB NEEDS IS CHECKED FIRST. A missing one is 503 BY NAME, and a promotion
    whose node is absent is 409, both before any record is written.
  * RECORD FIRST, AND FAIL-CLOSED. A ledger that does not say ok refuses the act and no effect
    runs. The partial state that can exist is record-without-effect, which leaves the data
    labelled unvouched.
  * A RETRY FINISHES THE JOB. After a failed effect, acting again with the same decision
    re-applies it with the STORED actor and time; a different decision is refused.
  * can_act ON THE AUDIENCE, FAIL-CLOSED. False, a raise, or an empty identity: all refuse.
  * REFUSED MEANS STILL PENDING. Through the real route, every refusal leaves
    `mark_task_resolved` uncalled, and with today's stores (no graph writer) the act is 503.

Run: uv run --frozen pytest tests/test_a_document_is_promoted_on_the_approval_plane.py -q
"""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from src.iagent import decision_record, human_tasks, ingest_status, promotion, provenance
from src.iagent.decision_record import canonical_json

HEX = "ab" * 32
INGEST_ID = "sha256:" + HEX
PAYLOAD = {
    "ingest_id": INGEST_ID,
    "object_ref": f"ingress-user/pdf/{HEX}/pcn-4471.pdf",
    "content_kind": "work-instructions",
    "pipeline_version": "doc-tools@7f-33",
    "format_fingerprint": "pdf:pcn:v1",
    "standing": "supervised",
    "extraction_ref": "s3://extractions/pcn-4471/review.json",
    "notice_id": "PCN-4471",
}
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}

#: Every field make_provenance can emit, the optional ones included, so the disjointness arm
#: is checked against the block's whole population and not its required subset.
BLOCK = provenance.make_provenance(
    authoritative_source="vendor-x", obtained_via=provenance.USER_DROP,
    as_of=provenance.AS_OF_UNKNOWN, ingested_at="2026-09-30T00:00:00Z",
    ingest_run=f"user-drop:{INGEST_ID}", standing="supervised",
    derived_from="urn:x:parent", ingest_id=INGEST_ID)


class Ledger:
    def __init__(self, log, result=None):
        self.log, self.result, self.rows = log, result, {}

    def append(self, record, *, acted_by, acted_at):
        self.log.append(("record", record))
        if self.result is not None:
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        rid = record["record_id"]
        if rid in self.rows:
            d, by, at = self.rows[rid]
            return {"ok": False, "reason": "immutable_conflict",
                    "existing": {"decision": d, "acted_by": by, "acted_at": at}}
        self.rows[rid] = (record["outcome"], acted_by, acted_at)
        return {"ok": True}


class Graph:
    """A node is ONE property map: the block's fields and any fact's predicates share it."""

    def __init__(self, log, present=True):
        self.log = log
        self.nodes = {INGEST_ID: dict(BLOCK)} if present else {}
        self.fail = None
        self.answer = None      # what node_exists says, when set

    def node_exists(self, iid):
        self.log.append(("exists", iid))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer if self.answer is not None else iid in self.nodes

    def write_fact(self, iid, fact):
        self.log.append(("fact", iid, fact))
        if self.fail == "write":
            raise RuntimeError("graph writer down")
        self.nodes[iid].update(fact)

    def delete_carrying(self, iid):
        self.log.append(("graph-delete", iid))
        if self.fail == "graph":
            raise RuntimeError("graph writer down")
        return 3


class Indexes:
    def __init__(self, log):
        self.log, self.fail = log, False

    def delete_carrying(self, iid):
        self.log.append(("index-delete", iid))
        if self.fail:
            raise RuntimeError("vectors writer down")
        return 5


class Objects:
    def __init__(self, log):
        self.log, self.fail = log, False

    def quarantine(self, iid, ref):
        self.log.append(("quarantine", iid, ref))
        if self.fail:
            raise RuntimeError("minio down")
        return [f"rejected/{iid}/pcn-4471.pdf", f"rejected/{iid}/manifest.json"]


def _stores(log, **over):
    parts = {"ledger": Ledger(log), "graph": Graph(log), "indexes": Indexes(log),
             "objects": Objects(log)}
    parts.update(over)
    return promotion.PromotionStores(**parts)


def _act(stores, *, decision="promoted", can_act=lambda a, c: True, payload=None,
         acted_by="bob", comment="", now_ms=1_000):
    return promotion.act(
        dict(PAYLOAD) if payload is None else payload, decision=decision, acted_by=acted_by,
        audience="aud:sustainment-approvers", comment=comment, can_act=can_act,
        stores=stores, governing=GOVERNING, era="commissioning", now_ms=now_ms)


def _kinds(log):
    return [e[0] for e in log]


# ── THE VERBS ─────────────────────────────────────────────────────────────────────────────────

def test_a_PROMOTION_checks_the_node_writes_the_record_THEN_adds_the_fact():
    log: list = []
    out = _act(_stores(log))
    assert _kinds(log) == ["exists", "record", "fact"]
    record, (_, subject, fact) = log[1][1], log[2]
    assert record["request_key"] == INGEST_ID
    assert record["record_id"] == decision_record.record_id_for(INGEST_ID)
    assert record["outcome"] == "promoted" and record["admitted_by"] == "policy"
    assert record["trust_rung"] == "supervised"
    assert record["checks"][0]["inputs"]["extraction_ref"] == PAYLOAD["extraction_ref"]
    assert record["checks"][0]["inputs"]["reviewed_by"] == "human:bob"
    decision_record.validate_decision_record(record)
    assert subject == INGEST_ID
    assert fact == {"promoted_by": "human:bob", "promoted_at": 1_000,
                    "promotion_ref": record["record_id"]}
    assert out["fact"] == fact and out["record_id"] == record["record_id"]
    assert out["replayed"] is False


def test_the_BLOCK_is_BYTE_IDENTICAL_across_a_promotion():
    log: list = []
    stores = _stores(log)
    before = canonical_json({k: stores.graph.nodes[INGEST_ID][k] for k in BLOCK})
    _act(stores)
    node = stores.graph.nodes[INGEST_ID]
    assert canonical_json({k: node[k] for k in BLOCK}) == before
    assert set(node) == set(BLOCK) | {"promoted_by", "promoted_at", "promotion_ref"}


def test_no_fact_predicate_is_a_ProvenanceBlock_field():
    fact = promotion.promotion_fact(acted_by="bob", record_id="dr-1", promoted_at=1)
    assert set(fact) == {"promoted_by", "promoted_at", "promotion_ref"}
    assert not (set(fact) & set(BLOCK))


def test_a_REJECTION_writes_the_record_THEN_sweeps_graph_indexes_and_MOVES_the_objects():
    log: list = []
    stores = _stores(log)
    out = _act(stores, decision="rejected", comment="superseded revision")
    assert _kinds(log) == ["record", "graph-delete", "index-delete", "quarantine"]
    assert log[0][1]["outcome"] == "rejected"
    assert log[0][1]["checks"][0]["inputs"]["comment"] == "superseded revision"
    assert log[1][1] == log[2][1] == INGEST_ID
    assert log[3][1:] == (INGEST_ID, PAYLOAD["object_ref"])
    assert out["swept"] == {"graph": 3, "indexes": 5, "objects": [
        f"rejected/{INGEST_ID}/pcn-4471.pdf", f"rejected/{INGEST_ID}/manifest.json"]}
    assert "fact" not in out
    # the record stays: the rejection's sweep never reaches the ledger
    assert stores.ledger.rows[decision_record.record_id_for(INGEST_ID)][0] == "rejected"


# ── EVERY STORE IS CHECKED BEFORE ANYTHING IS WRITTEN ─────────────────────────────────────────

@pytest.mark.parametrize("decision,absent", [
    (d, n) for d in promotion.VERBS for n in promotion.REQUIRES[d]])
def test_a_MISSING_store_is_503_BY_NAME_before_any_record(decision, absent):
    log: list = []
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(log, **{absent: None}), decision=decision, comment="why")
    assert (ei.value.status, ei.value.error) == (503, "promotion_store_unconfigured")
    assert repr(absent) in str(ei.value)
    assert log == []


@pytest.mark.parametrize("decision", promotion.VERBS)
def test_NO_stores_at_all_is_503_before_any_record(decision):
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(None, decision=decision, comment="why")
    assert ei.value.status == 503


def test_a_PROMOTION_needs_no_index_and_no_object_store():
    log: list = []
    out = _act(_stores(log, indexes=None, objects=None))
    assert out["decision"] == "promoted" and _kinds(log) == ["exists", "record", "fact"]


def test_every_store_field_is_required_by_SOME_verb():
    fields = {f.name for f in dataclasses.fields(promotion.PromotionStores)}
    assert fields == set().union(*promotion.REQUIRES.values())


@pytest.mark.parametrize("answer,status,error", [
    (False, 409, "ingest_node_absent"),
    ("yes", 409, "ingest_node_absent"),                     # truthy is not True
    (RuntimeError("graph down"), 503, "promotion_store_unavailable"),
])
def test_a_PROMOTION_whose_node_is_absent_or_unknown_is_refused_before_any_record(
        answer, status, error):
    log: list = []
    stores = _stores(log)
    stores.graph.answer = answer
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(stores)
    assert (ei.value.status, ei.value.error) == (status, error)
    assert _kinds(log) == ["exists"]


def test_a_REJECTION_does_not_need_the_node():
    log: list = []
    out = _act(_stores(log, graph=Graph(log, present=False)), decision="rejected",
               comment="junk")
    assert out["decision"] == "rejected" and "exists" not in _kinds(log)


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
    log: list = []
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(log), can_act=can_act, acted_by=acted_by)
    assert ei.value.status == 403 and log == []


#: Derived from the CONSUMER, not from PAYLOAD_FIELDS: a field dropped from that list must
#: still be required, because the record is built from the subject's fields.
_SUBJECT_FIELDS = tuple(f.name for f in dataclasses.fields(promotion.PromotionSubject)
                        if f.name != "notice_id")


def test_the_required_payload_IS_the_record_subject():
    assert promotion.PAYLOAD_FIELDS == _SUBJECT_FIELDS


@pytest.mark.parametrize("field", _SUBJECT_FIELDS)
def test_a_payload_missing_a_record_field_is_refused(field):
    log: list = []
    payload = dict(PAYLOAD)
    payload[field] = "  "
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(log), payload=payload)
    assert ei.value.status == 422 and log == []


@pytest.mark.parametrize("spelling", [
    HEX,                                    # bare hex
    "sha256:" + HEX.upper(),                # upper case
    "sha256:" + HEX[:-2],                   # short
])
def test_a_misspelled_ingest_id_is_refused_because_its_sweep_would_delete_nothing(spelling):
    log: list = []
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(log), payload={**PAYLOAD, "ingest_id": spelling})
    assert ei.value.status == 422 and log == []


@pytest.mark.parametrize("ref", [
    f"ingress-user/pdf/{'cd' * 32}/pcn-4471.pdf",     # ANOTHER document's directory
    f"sustainment/pdf/{HEX}/pcn-4471.pdf",            # not the seam's root
    f"ingress-user/{HEX}/pcn-4471.pdf",               # no kind
    f"ingress-user/pdf/{HEX}/sub/pcn-4471.pdf",       # deeper than the seam writes
    f"ingress-user/pdf/{HEX}/",                       # no name
    "ingress-user/bob/pcn-4471.pdf",
])
def test_an_object_ref_that_is_not_THIS_documents_seam_key_is_refused(ref):
    """A rejection moves the object_ref's directory whole, so it must be the document's own."""
    log: list = []
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(log), decision="rejected", comment="x", payload={**PAYLOAD, "object_ref": ref})
    assert ei.value.status == 422 and "object_ref" in str(ei.value) and log == []


def test_the_seams_own_key_is_accepted_and_names_its_directory():
    assert promotion.object_prefix_for(INGEST_ID, PAYLOAD["object_ref"]) == \
        f"ingress-user/pdf/{HEX}/"


def test_the_ingest_id_is_the_bytes_sha256_in_the_accepted_spelling():
    data = b"%PDF-1.7 pcn"
    iid = promotion.ingest_id_for(data)
    assert iid == "sha256:" + hashlib.sha256(data).hexdigest()
    assert promotion.INGEST_ID_RE.match(iid)


@pytest.mark.parametrize("result,status,error", [
    ({"ok": False, "reason": "unreachable"}, 503, "decision_record_not_written"),
    ({"ok": False, "reason": "conflict_unreadable"}, 503, "decision_record_not_written"),
    (None, 503, "decision_record_not_written"),
    ({"ok": "true"}, 503, "decision_record_not_written"),
    (RuntimeError("pg down"), 503, "decision_record_not_written"),
    ({"ok": False, "reason": "immutable_conflict"}, 409, "promotion_already_decided"),
    ({"ok": False, "reason": "immutable_conflict",
      "existing": {"decision": "rejected", "acted_by": "al", "acted_at": 5}},
     409, "promotion_already_decided"),
    ({"ok": False, "reason": "immutable_conflict",
      "existing": {"decision": "promoted", "acted_by": "", "acted_at": 5}},
     409, "promotion_already_decided"),
    ({"ok": False, "reason": "immutable_conflict",
      "existing": {"decision": "promoted", "acted_by": "al", "acted_at": "5"}},
     409, "promotion_already_decided"),
])
def test_a_record_that_was_not_written_REFUSES_the_act_and_no_effect_runs(
        result, status, error):
    log: list = []
    stores = _stores(log)
    if result is None:     # a ledger that answers nothing
        stores.ledger.append = lambda record, **kw: log.append(("record", record))
    else:
        stores.ledger.result = result
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(stores)
    assert (ei.value.status, ei.value.error) == (status, error)
    assert _kinds(log) == ["exists", "record"]


def test_an_undeclared_verb_is_refused():
    log: list = []
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(log), decision="approved")
    assert ei.value.status == 422 and log == []


# ── A RETRY FINISHES THE JOB ──────────────────────────────────────────────────────────────────

def test_a_failed_FACT_is_503_the_record_stands_and_a_retry_writes_it_AS_THE_ORIGINAL_ACT():
    log: list = []
    stores = _stores(log)
    stores.graph.fail = "write"
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(stores)
    assert (ei.value.status, ei.value.error) == (503, "promotion_effect_incomplete")
    assert len(stores.ledger.rows) == 1

    stores.graph.fail = None
    out = _act(stores, acted_by="carol", now_ms=2_000)
    assert out["replayed"] is True
    assert out["fact"] == {"promoted_by": "human:bob", "promoted_at": 1_000,
                           "promotion_ref": decision_record.record_id_for(INGEST_ID)}
    assert stores.graph.nodes[INGEST_ID]["promoted_by"] == "human:bob"
    assert len(stores.ledger.rows) == 1


@pytest.mark.parametrize("step", ["graph", "indexes", "objects"])
def test_a_failed_SWEEP_step_is_503_BY_NAME_and_a_retry_completes_it(step):
    log: list = []
    stores = _stores(log)
    if step == "graph":
        stores.graph.fail = "graph"
    else:
        getattr(stores, step).fail = True
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(stores, decision="rejected", comment="junk")
    assert (ei.value.status, ei.value.error) == (503, "promotion_effect_incomplete")
    assert f"the {step} step" in str(ei.value)

    stores.graph.fail = None
    stores.indexes.fail = stores.objects.fail = False
    log.clear()
    out = _act(stores, decision="rejected", comment="junk", acted_by="carol")
    assert out["replayed"] is True
    assert _kinds(log) == ["record", "graph-delete", "index-delete", "quarantine"]


def test_a_retry_with_the_OTHER_decision_is_refused_and_runs_no_effect():
    log: list = []
    stores = _stores(log)
    _act(stores, decision="rejected", comment="junk")
    log.clear()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(stores, decision="promoted")
    assert (ei.value.status, ei.value.error) == (409, "promotion_already_decided")
    assert "'rejected'" in str(ei.value)
    assert "fact" not in _kinds(log)


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
    log: list = []
    calls: dict = {"resolved": [], "can_act": [], "log": log}
    task = {"task_id": "t-1", "kind": promotion.KIND, "audience": "aud:sustainment-approvers",
            "payload": dict(PAYLOAD)}
    monkeypatch.setattr(human_tasks, "list_tasks_for", lambda caller, status="pending": [task])

    def can_act(audience, caller):
        calls["can_act"].append((audience, caller))
        return calls.get("allow", True)

    monkeypatch.setattr(human_tasks, "check_can_act", can_act)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: calls["resolved"].append((tid, kw)) or 1)
    user = type("U", (), {"authz_id": "bob", "sub": "bob", "email": "bob@x",
                          "persona": "SUSTAINMENT_ENGINEER", "entitled_domains": ["SUSTAINMENT"],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c, calls, monkeypatch
    gateway.app.dependency_overrides.clear()


def _wired(route, **over):
    c, calls, mp = route
    stores = _stores(calls["log"], **over)
    calls["stores_for"] = []
    mp.setattr(gateway, "_promotion_stores",
               lambda acted_by: calls["stores_for"].append(acted_by) or stores)
    return c, calls, mp, stores


def _post(c, decision, comment=""):
    return c.post("/human_tasks/t-1/act", json={"decision": decision, "comment": comment})


def test_TODAYS_stores_build_the_graph_AS_THE_ACTOR_and_the_declared_indexes():
    """The real `_promotion_stores`: the graph and the indexes are no longer None. The graph is
    built per act with the acting PERSON as its initiator -- never a service, never shared."""
    from src.iagent import promotion_stores

    stores = gateway._promotion_stores("bob")
    assert isinstance(stores.graph, promotion_stores.Neo4jIngestGraph)
    assert stores.graph._initiator.subject == "bob"
    assert stores.graph._initiator.kind == "person"
    assert isinstance(stores.indexes, promotion_stores.DeclaredIngestIndexes)
    carol = gateway._promotion_stores("carol").graph
    assert carol is not stores.graph and carol._initiator.subject == "carol"


@pytest.mark.parametrize("decision", promotion.VERBS)
def test_ROUTE_with_TODAYS_stores_and_NO_LEDGER_is_503_naming_ONLY_the_ledger_and_STAYS_PENDING(
        route, decision):
    """With the graph wired, the only store the real `_promotion_stores` can leave unbuilt
    without configuration is the ledger; the refusal names it and nothing else."""
    from src.iagent import promotion_stores

    c, calls, mp = route
    mp.setattr(promotion_stores, "_PG_DSN", "")
    r = _post(c, decision, comment="why")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "promotion_store_unconfigured"
    message = r.json()["detail"]["message"]
    # the message also lists what the verb NEEDS; the refusal is the unconfigured bracket
    assert "and ['ledger'] is not configured" in message, message
    assert calls["resolved"] == [] and calls["log"] == []


def test_ROUTE_builds_the_stores_for_the_CALLER_who_acts(route):
    """The stores are built for `authz_id` -- the identity `can_act` was asked about -- so the
    user here carries a DIFFERENT `sub`, or the two could not be told apart."""
    c, calls, _, _ = _wired(route)
    user = gateway.app.dependency_overrides[gateway.get_current_user]()
    split = type("U", (), {**{k: v for k, v in vars(type(user)).items() if not k.startswith("__")},
                           "sub": "kc-0b7e"})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: split
    assert _post(c, "promoted").status_code == 200
    assert calls["stores_for"] == ["bob"]


def test_ROUTE_promotes_then_resolves_the_projection(route):
    c, calls, _, _ = _wired(route)
    r = _post(c, "promoted")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "promoted" and body["ingest_id"] == INGEST_ID
    assert body["fact"]["promoted_by"] == "human:bob"
    record = next(e[1] for e in calls["log"] if e[0] == "record")
    assert record["governing"]["ruleset_ref"].startswith("task_kind:document_promotion@")
    assert _kinds(calls["log"]) == ["exists", "record", "fact"]
    assert calls["resolved"] == [("t-1", {"caller_id": "bob", "decision": "promoted",
                                          "comment": ""})]
    # the effect re-asked can_act itself, beyond the route's own check
    assert len(calls["can_act"]) == 2


def test_ROUTE_a_record_write_failure_leaves_the_task_PENDING(route):
    c, calls, _, stores = _wired(route)
    stores.ledger.result = {"ok": False, "reason": "unreachable"}
    r = _post(c, "rejected", comment="superseded")
    assert r.status_code == 503, r.text
    assert _kinds(calls["log"]) == ["record"] and calls["resolved"] == []


def test_ROUTE_an_effect_failure_leaves_the_task_PENDING(route):
    c, calls, _, stores = _wired(route)
    stores.objects.fail = True
    r = _post(c, "rejected", comment="superseded")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "promotion_effect_incomplete"
    assert calls["resolved"] == []


def test_ROUTE_an_absent_node_is_409_and_the_task_STAYS_PENDING(route):
    c, calls, _, _ = _wired(route, graph=Graph(route[1]["log"], present=False))
    r = _post(c, "promoted")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "ingest_node_absent"
    assert calls["resolved"] == [] and "record" not in _kinds(calls["log"])


# ── AFTER mark_task_resolved: the ingest_status_projection is updated, best-effort ───────────

def test_ROUTE_promotion_updates_the_ingest_status_projection(route):
    c, calls, mp, _ = _wired(route)
    updates: list = []
    mp.setattr(ingest_status, "update_status",
              lambda ingest_id, stage, *, detail=None: updates.append((ingest_id, stage, detail)))
    r = _post(c, "promoted")
    assert r.status_code == 200, r.text
    record_id = decision_record.record_id_for(INGEST_ID)
    assert len(updates) == 1
    got_id, got_stage, got_detail = updates[0]
    assert got_id == INGEST_ID and got_stage == "promoted"
    assert got_detail.startswith("record "), got_detail
    assert record_id in got_detail


def test_ROUTE_rejection_updates_the_ingest_status_projection_with_the_comment(route):
    c, calls, mp, _ = _wired(route)
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
    reason, this goes red instead of a row silently stranding at review."""
    c, calls, mp, _ = _wired(route)
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
    c, calls, mp, _ = _wired(route)

    def _boom(ingest_id, stage, *, detail=None):
        raise RuntimeError("projector db down")

    mp.setattr(ingest_status, "update_status", _boom)
    r = _post(c, "promoted")
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "promoted"
    assert calls["resolved"] != [], "mark_task_resolved must still have run"


def test_ROUTE_can_act_no_is_403_before_any_write(route):
    c, calls, _, _ = _wired(route)
    calls["allow"] = False
    r = _post(c, "promoted")
    assert r.status_code == 403
    assert calls["log"] == [] and calls["resolved"] == []


@pytest.mark.parametrize("decision,comment", [("approved", ""), ("rejected", "")])
def test_ROUTE_the_declaration_refuses_before_the_effect(route, decision, comment):
    """`approved` is not this species' verb, and `rejected` needs a reason. Both are refused by
    the declaration, before anything is written."""
    c, calls, _, _ = _wired(route)
    r = _post(c, decision, comment)
    assert r.status_code == 422, r.text
    # `allowed` is the DECLARATION's refusal; the effect's own 422 carries no such key, so
    # this cannot pass on the effect's refusal standing in for a missing declaration.
    assert "allowed" in r.json()["detail"], r.text
    assert calls["log"] == [] and calls["resolved"] == []
