"""A promotion makes the notice's SUBJECT_TO set EXACTLY the reviewed rows after the steward's edits.

Ruled 2026-10-20. Live, a notice served 42 parts: 26 from this ingest plus 16 stale edges from an
earlier ingest nobody reviewed. The prune list is computed BEFORE the (immutable) decision record
is built and recorded in it, each entry `not_in_reviewed_set`; the effect deletes only what a
record names (a replay reads the RECORDED list). Only the notice's edges go, never a Component.

Run: uv run --frozen pytest tests/test_promotion_reconciles_the_notice_to_the_reviewed_set.py -q
"""
from __future__ import annotations

import json

import pytest
from iagent_mesh.interfaces import Initiator

from src.iagent import promotion
from src.iagent.promotion_stores import Neo4jIngestGraph

HEX = "ab" * 32
INGEST_ID = "sha256:" + HEX
AUDIENCE = "document_promotion:SUSTAINMENT"
PAYLOAD = {
    "ingest_id": INGEST_ID, "object_ref": f"ingress-user/pdf/{HEX}/pcn-4471.pdf",
    "content_kind": "work-instructions", "pipeline_version": "doc-tools@7f-33",
    "format_fingerprint": "pdf:pcn:v1", "standing": "supervised",
    "extraction_ref": "s3://extractions/pcn-4471/review.json", "notice_id": "PCN-4471",
}
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}
EARLIER = ["sha256:" + "cd" * 32]


class Ledger:
    def __init__(self):
        self.records, self.appends = {}, 0

    def append(self, record, *, acted_by, acted_at):
        self.appends += 1
        rid = record["record_id"]
        if rid in self.records:
            return {"ok": False, "reason": "immutable_conflict", "existing": self.records[rid]}
        self.records[rid] = {"decision": record["outcome"], "acted_by": acted_by,
                             "acted_at": acted_at, "record": record}
        return {"ok": True}

    def only_record(self):
        return next(iter(self.records.values()))["record"]


class Graph:
    """An in-memory notice: `edges` is the set of exact mpns the notice is SUBJECT_TO-linked from;
    None means no notice node."""

    def __init__(self, edges=None, fail_reconcile=False, fail_read=False):
        self.edges = None if edges is None else list(edges)
        self.calls, self.fail_reconcile, self.fail_read = [], fail_reconcile, fail_read

    def node_exists(self, iid):
        return True

    def notice_mpns(self, ingest_id, *, domain):
        self.calls.append(("notice_mpns",))
        if self.fail_read:
            raise RuntimeError("neo4j down")
        return None if self.edges is None else list(self.edges)

    def apply_row_edits(self, ingest_id, row_edits, *, domain, record_id):
        self.calls.append(("apply_row_edits",))
        n = 0
        for e in row_edits:
            if e["op"] == "deleted" and e["mpn"] in (self.edges or []):
                self.edges.remove(e["mpn"])
                n += 1
        return {"deleted": n, "corrected": 0, "added": 0, "not_applied": []}

    def remove_notice_edges(self, ingest_id, mpns, *, domain):
        self.calls.append(("remove_notice_edges", list(mpns)))
        if self.fail_reconcile:
            raise RuntimeError("neo4j down")
        gone = [m for m in mpns if m in (self.edges or [])]
        for m in gone:
            self.edges.remove(m)
        return len(gone)

    def write_fact(self, iid, fact):
        self.calls.append(("write_fact",))

    def attest_origin(self, iid, *, owner_domain, record_id):
        return "written"

    def delete_carrying(self, iid):
        return 0

    def names(self):
        return [c[0] for c in self.calls]


def _act(graph, ledger=None, *, reviewed, row_edits=None, earlier=EARLIER):
    stores = promotion.PromotionStores(ledger=ledger or Ledger(), graph=graph)
    return promotion.act(
        dict(PAYLOAD), decision="promoted", acted_by="bob", audience=AUDIENCE, comment="why",
        can_act=lambda a, c: True, stores=stores, governing=GOVERNING, era="commissioning",
        now_ms=1_000, row_edits=row_edits, reviewed_mpns=reviewed, earlier_ingests=earlier)


def _reconciliation(ledger):
    for c in ledger.only_record()["checks"]:
        if c["name"] == "human_review":
            return c["inputs"].get("reconciliation")
    raise AssertionError("no human_review check")


def _deleted(mpn):
    return {"op": "deleted", "mpn": mpn, "reason": "not on the notice"}


# -- the act ------------------------------------------------------------------------------------

def test_stale_edges_are_recorded_as_not_in_reviewed_set_and_removed_and_reviewed_ones_stay():
    g, ledger = Graph(["R1", "R2", "S1", "S2"]), Ledger()
    out = _act(g, ledger, reviewed=["R1", "R2"])
    rec = _reconciliation(ledger)
    assert rec["removed"] == [{"mpn": "S1", "reason": "not_in_reviewed_set"},
                              {"mpn": "S2", "reason": "not_in_reviewed_set"}]
    assert rec["earlier_ingests"] == EARLIER and "candidates_by_notice_id" in rec["attribution"]
    assert ("remove_notice_edges", ["S1", "S2"]) in g.calls
    assert sorted(g.edges) == ["R1", "R2"]
    assert out["reconciled"] == {"removed": 2, "mpns": ["S1", "S2"]}


def test_a_row_edit_deleted_mpn_is_not_listed_in_the_reconciliation():
    g, ledger = Graph(["R1", "R2", "S1"]), Ledger()
    _act(g, ledger, reviewed=["R1", "R2"], row_edits=[_deleted("R2")])
    assert [e["mpn"] for e in _reconciliation(ledger)["removed"]] == ["S1"]
    assert g.edges == ["R1"]


def test_comparison_is_on_strip_and_removal_is_by_the_graphs_exact_value():
    g, ledger = Graph(["X", " S "]), Ledger()
    _act(g, ledger, reviewed=[" X "])
    assert [e["mpn"] for e in _reconciliation(ledger)["removed"]] == [" S "]
    assert ("remove_notice_edges", [" S "]) in g.calls and g.edges == ["X"]


def test_the_reconcile_runs_after_row_edits_and_before_write_fact():
    g = Graph(["R1", "S1"])
    _act(g, reviewed=["R1"], row_edits=[_deleted("R1")])
    assert g.names() == ["notice_mpns", "apply_row_edits", "remove_notice_edges", "write_fact"]


def test_a_failed_reconcile_is_effect_incomplete_503_naming_the_step_and_writes_no_fact():
    g = Graph(["R1", "S1"], fail_reconcile=True)
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(g, reviewed=["R1"])
    assert ei.value.error == "promotion_effect_incomplete" and ei.value.status == 503
    assert "reconcile" in str(ei.value)
    assert "write_fact" not in g.names()


def test_a_notice_present_with_the_reviewed_set_unknown_is_409_and_nothing_is_recorded():
    g, ledger = Graph(["R1"]), Ledger()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(g, ledger, reviewed=None)
    assert ei.value.error == "promotion_reviewed_set_unknown" and ei.value.status == 409
    assert ledger.appends == 0 and g.names() == ["notice_mpns"]


def test_an_unreadable_notice_is_503_store_unavailable_and_nothing_is_recorded():
    g, ledger = Graph(["R1"], fail_read=True), Ledger()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(g, ledger, reviewed=["R1"])
    assert ei.value.error == "promotion_store_unavailable" and ei.value.status == 503
    assert ledger.appends == 0


def test_no_notice_node_means_no_reconcile_and_no_reconciliation_in_the_record():
    g, ledger = Graph(None), Ledger()
    out = _act(g, ledger, reviewed=None)
    assert _reconciliation(ledger) is None
    assert "remove_notice_edges" not in g.names() and "reconciled" not in out


def test_a_clean_notice_still_records_an_empty_reconciliation():
    g, ledger = Graph(["R1"]), Ledger()
    out = _act(g, ledger, reviewed=["R1"], earlier=None)
    rec = _reconciliation(ledger)
    assert rec["removed"] == [] and rec["earlier_ingests"] is None
    assert "unavailable" in rec["attribution"]
    assert out["reconciled"] == {"removed": 0, "mpns": []}
    assert "remove_notice_edges" not in g.names()


def test_a_REPLAY_applies_the_RECORDED_list_not_a_recomputed_one():
    ledger = Ledger()
    _act(Graph(["R1", "S1"]), ledger, reviewed=["R1"])
    g = Graph(["R1", "OTHER"])          # the graph now would give a different plan
    out = _act(g, ledger, reviewed=["R1"])
    assert out["replayed"] is True
    assert ("remove_notice_edges", ["S1"]) in g.calls
    assert g.edges == ["R1", "OTHER"]


def test_a_REPLAY_of_a_record_with_no_reconciliation_prunes_nothing():
    ledger = Ledger()
    _act(Graph(None), ledger, reviewed=None)             # recorded with no reconciliation
    g = Graph(["R1", "S1"])
    out = _act(g, ledger, reviewed=["R1"])
    assert out["replayed"] is True
    assert "remove_notice_edges" not in g.names() and g.edges == ["R1", "S1"]


def test_the_TYC_shape_26_reviewed_16_stale_10_deleted_leaves_16():
    reviewed = [f"P{i:02d}" for i in range(1, 27)]
    stale = [f"S{i:02d}" for i in range(1, 17)]
    deleted = reviewed[:10]
    g, ledger = Graph(reviewed + stale), Ledger()
    out = _act(g, ledger, reviewed=reviewed, row_edits=[_deleted(m) for m in deleted])
    assert [e["mpn"] for e in _reconciliation(ledger)["removed"]] == stale
    assert out["row_edits_applied"]["deleted"] == 10
    assert out["reconciled"]["removed"] == 16
    assert sorted(g.edges) == reviewed[10:] and len(g.edges) == 16
    assert json.dumps(ledger.only_record())      # the record stays serialisable


# -- the store ----------------------------------------------------------------------------------

class Rec:
    def __init__(self, mpn_row=None, n=1):
        self.statements, self.mpn_row, self.n = [], mpn_row, n

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self.statements.append((cypher, params))
        row = self.mpn_row if "collect(c.mpn)" in cypher else {"n": self.n}
        return type("R", (), {"single": lambda _s: row})()


def _store(rec):
    return Neo4jIngestGraph(driver=rec, initiator=Initiator(subject="bob", kind="person"),
                            writer_factory=lambda **kw: object())


def test_remove_notice_edges_scopes_by_ingest_id_and_deletes_only_the_relationship():
    rec = Rec(n=2)
    assert _store(rec).remove_notice_edges(INGEST_ID, ["A", "B"], domain="SUSTAINMENT") == 2
    (cypher, params), = rec.statements
    assert "n.provenance_ingest_id = $ingest_id" in cypher
    assert "DELETE r" in cypher and "DETACH" not in cypher
    assert "DELETE c" not in cypher and "DELETE n" not in cypher
    assert params == {"mpns": ["A", "B"], "ingest_id": INGEST_ID}


def test_remove_notice_edges_with_no_mpns_runs_nothing_and_a_bad_domain_raises_first():
    rec = Rec()
    assert _store(rec).remove_notice_edges(INGEST_ID, [], domain="SUSTAINMENT") == 0
    with pytest.raises(ValueError):
        _store(rec).remove_notice_edges(INGEST_ID, ["A"], domain="x) DETACH DELETE (c")
    with pytest.raises(ValueError):
        _store(rec).notice_mpns(INGEST_ID, domain="sustainment")
    assert rec.statements == []


def test_notice_mpns_is_a_read_answering_none_for_no_notice_and_the_exact_values_otherwise():
    assert _store(Rec({"notices": 0, "mpns": []})).notice_mpns(INGEST_ID, domain="SUSTAINMENT") is None
    assert _store(Rec({"notices": 1, "mpns": []})).notice_mpns(INGEST_ID, domain="SUSTAINMENT") == []
    rec = Rec({"notices": 1, "mpns": [" X", "Y"]})
    assert _store(rec).notice_mpns(INGEST_ID, domain="SUSTAINMENT") == [" X", "Y"]
    cypher, params = rec.statements[0]
    assert "DELETE" not in cypher and "MERGE" not in cypher and "SET " not in cypher
    assert "provenance_ingest_id = $ingest_id" in cypher and params == {"ingest_id": INGEST_ID}
