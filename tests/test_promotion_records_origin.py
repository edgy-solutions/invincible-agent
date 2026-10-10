"""A promotion records the document's origin: the steward's attestation, at the `steward` rung.

Ruled: `document_promotion:<D>` is a domain task. When a steward of D promotes a drop, the
promotion records origin = D at the SDK's `steward` rung, with `steward_attestation:<record_id>`
in the evidence. The dropper can never be the attesting steward. A record origin outranks it and
an existing steward origin stays as first attested. A one-shot backfill gives the rows promoted
earlier the same origin, through the SAME writer, and is a no-op the second time.

Run: uv run --frozen pytest tests/test_promotion_records_origin.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from iagent_mesh.interfaces import Initiator, MeshWriteResult
from iagent_mesh.systems_of_record import Origin

from src.iagent import promotion, promotion_stores
from src.iagent.promotion_stores import INGEST_FACT_FAMILY, Neo4jIngestGraph

HEX = "ab" * 32
INGEST_ID = "sha256:" + HEX
AUDIENCE = "document_promotion:SUSTAINMENT"
PAYLOAD = {
    "ingest_id": INGEST_ID,
    "object_ref": f"ingress-user/pdf/{HEX}/pcn-4471.pdf",
    "content_kind": "work-instructions",
    "pipeline_version": "doc-tools@7f-33",
    "format_fingerprint": "pdf:pcn:v1",
    "standing": "supervised",
    "extraction_ref": "s3://extractions/pcn-4471/review.json",
    "notice_id": "PCN-4471",
    "domain": "NOT-THE-AUDIENCE",     # the payload's domain is NOT where D comes from
}
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}
BOB = Initiator(subject="bob", kind="person")


# ── doubles ───────────────────────────────────────────────────────────────────────────────────

class Ledger:
    def __init__(self, result=None):
        self.appends, self.result = [], result

    def append(self, record, *, acted_by, acted_at):
        self.appends.append(record)
        return self.result if self.result is not None else {"ok": True}


class Graph:
    def __init__(self, outcome="written"):
        self.outcome, self.facts, self.attests, self.writes = outcome, [], [], 0

    def node_exists(self, iid):
        return True

    def write_fact(self, iid, fact):
        self.facts.append((iid, fact))
        self.writes += 1

    def attest_origin(self, iid, *, owner_domain, record_id):
        self.attests.append((iid, owner_domain, record_id))
        return self.outcome

    def delete_carrying(self, iid):
        self.writes += 1
        return 0


class Quiet:
    def delete_carrying(self, iid):
        return 0

    def quarantine(self, iid, ref):
        return []


def _stores(ledger=None, graph=None):
    return promotion.PromotionStores(ledger=ledger or Ledger(), graph=graph or Graph(),
                                     indexes=Quiet(), objects=Quiet())


def _act(stores, *, decision="promoted", acted_by="bob", audience=AUDIENCE, payload=None):
    return promotion.act(
        dict(PAYLOAD) if payload is None else payload, decision=decision, acted_by=acted_by,
        audience=audience, comment="why", can_act=lambda a, c: True, stores=stores,
        governing=GOVERNING, era="commissioning", now_ms=1_000)


class State:
    """Neo4j in a dict: the node's property map, read by the rung cypher, written by write_node."""

    def __init__(self, nodes):
        self.nodes = {k: dict(v) for k, v in nodes.items()}
        self.write_node_calls = []


class _Session:
    def __init__(self, state):
        self.s = state

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        node = self.s.nodes.get(params["ingest_id"])
        if cypher == promotion_stores._NODE_EXISTS_CYPHER:
            row = {"n": 1 if node is not None else 0}
        elif cypher == promotion_stores._ORIGIN_RUNG_CYPHER:
            row = None if node is None else {"rung": node.get("origin_resolved_by")}
        else:  # pragma: no cover
            raise AssertionError(cypher)
        return type("R", (), {"single": lambda _self: row})()


class _Driver:
    def __init__(self, state):
        self.s = state

    def session(self):
        return _Session(self.s)


class _Writer:
    def __init__(self, state, result=None):
        self.s, self.result = state, MeshWriteResult.written() if result is None else result

    def write_node(self, initiator, *, label, id, payload):
        self.s.write_node_calls.append((initiator, label, id, dict(payload)))
        if self.result.outcome == "written":
            self.s.nodes[id].update(payload)       # MERGE ... SET n += props
        return self.result


def _home(nodes, result=None):
    state = State(nodes)
    graph = Neo4jIngestGraph(driver=_Driver(state), initiator=BOB,
                             writer_factory=lambda **kw: _Writer(state, result))
    return graph, state


# ── 1. the promotion writes origin and the rung ───────────────────────────────────────────────

def test_a_PROMOTION_attests_the_AUDIENCES_domain_not_the_payloads():
    graph = Graph()
    out = _act(_stores(graph=graph))
    assert graph.attests == [(INGEST_ID, "SUSTAINMENT", out["record_id"])]
    assert out["origin"] == "written"


def test_the_store_writes_exactly_the_three_origin_properties_and_the_SDK_accepts_them():
    graph, state = _home({INGEST_ID: {}})
    assert graph.attest_origin(INGEST_ID, owner_domain="SUSTAINMENT", record_id="dr-1") == "written"
    ((who, label, nid, payload),) = state.write_node_calls
    assert who is BOB and label == INGEST_FACT_FAMILY["node_label"] and nid == INGEST_ID
    assert payload == {"origin_owner_domain": "SUSTAINMENT", "origin_resolved_by": "steward",
                       "origin_evidence": "steward_attestation:dr-1"}
    Origin(owner_domain=payload["origin_owner_domain"], resolved_by="steward",
           evidence=(payload["origin_evidence"],))


# ── 2. the keep rule ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rung,outcome,writes", [
    ("record", "kept_record", 0), ("steward", "kept_steward", 0),
    ("unresolved", "written", 1), (None, "written", 1)])
def test_a_record_or_steward_origin_is_KEPT_and_nothing_else_is_overwritten(rung, outcome, writes):
    node = {} if rung is None else {"origin_resolved_by": rung}
    graph, state = _home({INGEST_ID: node})
    assert graph.attest_origin(INGEST_ID, owner_domain="D", record_id="dr-1") == outcome
    assert len(state.write_node_calls) == writes


def test_a_write_that_did_not_apply_raises():
    graph, _ = _home({INGEST_ID: {}}, MeshWriteResult.refused("nope"))
    with pytest.raises(RuntimeError, match="origin attestation"):
        graph.attest_origin(INGEST_ID, owner_domain="D", record_id="dr-1")


# ── 3. a rejection attests nothing ────────────────────────────────────────────────────────────

def test_a_REJECTION_writes_no_origin():
    graph = Graph()
    out = _act(_stores(graph=graph), decision="rejected")
    assert graph.attests == [] and "origin" not in out


# ── 4. the dropper cannot attest ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dropped_by", [
    {"authz_id": "bob"}, {"authz_id": "alice", "on_behalf_of": "bob"}])
def test_the_DROPPER_cannot_promote_403_before_the_ledger_and_the_graph(dropped_by):
    ledger, graph = Ledger(), Graph()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(ledger, graph), payload={**PAYLOAD, "dropped_by": dropped_by})
    assert ei.value.error == "dropper_cannot_attest_origin" and ei.value.status == 403
    assert ledger.appends == [] and graph.writes == 0 and graph.attests == []


def test_the_dropper_REJECTING_is_not_refused_by_this_rule():
    out = _act(_stores(), decision="rejected",
               payload={**PAYLOAD, "dropped_by": {"authz_id": "bob"}})
    assert out["decision"] == "rejected"


@pytest.mark.parametrize("dropped_by", [None, {}, {"authz_id": None, "on_behalf_of": ""}])
def test_a_payload_with_no_dropper_excludes_nobody(dropped_by):
    payload = dict(PAYLOAD) if dropped_by is None else {**PAYLOAD, "dropped_by": dropped_by}
    assert _act(_stores(), payload=payload)["origin"] == "written"


# ── 5. an audience without a domain ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("audience", ["aud:sustainment-approvers", "document_promotion:",
                                      "document_promotion:  ", "document_promotion"])
def test_an_audience_with_no_domain_is_422_before_any_write(audience):
    ledger, graph = Ledger(), Graph()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(ledger, graph), audience=audience)
    assert ei.value.error == "promotion_audience_has_no_domain" and ei.value.status == 422
    assert ledger.appends == [] and graph.writes == 0 and graph.attests == []


# ── 6. a replay attests again, and the store keeps ────────────────────────────────────────────

def test_a_REPLAY_runs_the_attestation_again_and_the_store_keeps_the_first():
    graph, state = _home({INGEST_ID: {"origin_resolved_by": "steward"}})
    graph.write_fact = lambda iid, fact: None            # the fact is not under test here
    ledger = Ledger({"ok": False, "reason": "immutable_conflict",
                     "existing": {"decision": "promoted", "acted_by": "bob", "acted_at": 5}})
    out = _act(_stores(ledger, graph))
    assert out["replayed"] is True and out["origin"] == "kept_steward"
    assert state.write_node_calls == []


def test_a_failed_attestation_is_the_effect_incomplete_refusal():
    class Down(Graph):
        def attest_origin(self, *a, **k):
            raise RuntimeError("down")

    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(graph=Down()))
    assert ei.value.error == "promotion_effect_incomplete" and "origin step" in str(ei.value)


# ── 7. the backfill ───────────────────────────────────────────────────────────────────────────

def _backfill_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_promotion_origin.py"
    spec = importlib.util.spec_from_file_location("backfill_promotion_origin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rec(n, audience="document_promotion:SUSTAINMENT"):
    inputs = {} if audience is None else {"audience": audience}
    return {"record_id": f"dr-{n}", "ingest_id": f"sha256:{n:064x}",
            "record": {"checks": [{"inputs": inputs}]}}


def _four():
    records = [_rec(1), _rec(2), _rec(3, audience="aud:something"), _rec(4)]
    nodes = {records[0]["ingest_id"]: {},
             records[1]["ingest_id"]: {"origin_resolved_by": "record"},
             records[2]["ingest_id"]: {}}                    # record 4's node is absent
    return records, nodes


def test_the_BACKFILL_writes_once_then_is_a_NO_OP():
    mod = _backfill_module()
    records, nodes = _four()
    graph, state = _home(nodes)
    first = mod.backfill(records, graph, apply=True)
    assert {k: first[k] for k in ("written", "kept_record", "kept_steward",
                                  "skipped_unparseable", "node_absent")} == {
        "written": 1, "kept_record": 1, "kept_steward": 0, "skipped_unparseable": 1,
        "node_absent": 1}
    assert first["skipped_ingest_ids"] == [records[2]["ingest_id"]]
    assert len(state.write_node_calls) == 1
    assert state.nodes[records[0]["ingest_id"]]["origin_evidence"] == "steward_attestation:dr-1"
    assert state.nodes[records[0]["ingest_id"]]["origin_owner_domain"] == "SUSTAINMENT"
    assert records[3]["ingest_id"] not in state.nodes          # an absent node is never created
    state.write_node_calls.clear()
    second = mod.backfill(records, graph, apply=True)
    assert second["written"] == 0 and second["kept_steward"] == 1 and second["kept_record"] == 1
    assert state.write_node_calls == []


def test_the_backfill_DRY_RUN_reports_and_writes_nothing():
    mod = _backfill_module()
    records, nodes = _four()
    graph, state = _home(nodes)
    out = mod.backfill(records, graph)
    assert out["written"] == 1 and out["applied"] is False
    assert state.write_node_calls == []
