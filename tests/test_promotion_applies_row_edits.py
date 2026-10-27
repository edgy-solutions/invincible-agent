"""A PROMOTED decision APPLIES the steward's row edits to the graph, not only records them.

Ruled: a delete removes that part's SUBJECT_TO edge for this ingest (the graph is true on its own,
not filtered at read); a correction rewrites the value with obtained_via=steward-corrected. Only
the notice's edge is touched -- Component nodes are shared across notices and are never deleted.

Run: uv run --frozen pytest tests/test_promotion_applies_row_edits.py -q
"""
from __future__ import annotations

import pytest
from iagent_mesh.interfaces import Initiator

from src.iagent import promotion, provenance
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
DELETED = [{"op": "deleted", "mpn": "M-1", "reason": "not on the notice"},
           {"op": "deleted", "mpn": "M-2", "reason": "not on the notice"}]
CORRECTED = {"op": "corrected", "mpn": "M-3", "obtained_via": "steward-corrected",
             "corrected_by": "bob", "extracted_value": "M-3", "corrected_value": "M-3A",
             "evidence": "page 2"}
ADDED = {"op": "added", "mpn": "M-9", "disposition": "affected", "reason": "missed",
         "obtained_via": "steward-corrected", "corrected_by": "bob", "extracted_value": None,
         "corrected_value": "M-9", "evidence": "page 3"}
HEADER = {"op": "header_corrected", "field": "pcn_number", "reason": "typo"}


class Ledger:
    def __init__(self):
        self.records = {}

    def append(self, record, *, acted_by, acted_at):
        rid = record["record_id"]
        if rid in self.records:
            return {"ok": False, "reason": "immutable_conflict", "existing": self.records[rid]}
        self.records[rid] = {"decision": record["outcome"], "acted_by": acted_by,
                             "acted_at": acted_at, "record": record}
        return {"ok": True}


class Outbox:
    """Records the correction records a promotion leaves for 7f (build 201)."""

    def __init__(self):
        self.emitted = []

    def emit(self, record):
        self.emitted.append(record)
        return f"corrections/{record['ingest_id'][7:]}/{record['record_id']}.json"


class Graph:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def node_exists(self, iid):
        return True

    def apply_row_edits(self, ingest_id, row_edits, *, domain, record_id):
        self.calls.append(("apply_row_edits", ingest_id, list(row_edits), domain, record_id))
        if self.fail:
            raise RuntimeError("neo4j down")
        return {"deleted": 2, "corrected": 0, "added": 0, "not_applied": []}

    def notice_mpns(self, ingest_id, *, domain):
        return None

    def write_fact(self, iid, fact):
        self.calls.append(("write_fact", iid))

    def attest_origin(self, iid, *, owner_domain, record_id):
        return "written"

    def delete_carrying(self, iid):
        return 0


def _act(graph, ledger=None, row_edits=None):
    stores = promotion.PromotionStores(ledger=ledger or Ledger(), graph=graph, corrections=Outbox())
    return promotion.act(
        dict(PAYLOAD), decision="promoted", acted_by="bob", audience=AUDIENCE, comment="why",
        can_act=lambda a, c: True, stores=stores, governing=GOVERNING, era="commissioning",
        now_ms=1_000, row_edits=row_edits)


# -- the act ------------------------------------------------------------------------------------

def test_a_PROMOTED_act_applies_row_edits_BEFORE_it_writes_the_fact():
    g = Graph()
    out = _act(g, row_edits=DELETED)
    names = [c[0] for c in g.calls]
    assert names == ["apply_row_edits", "write_fact"], names
    assert g.calls[0][1] == INGEST_ID and g.calls[0][2] == DELETED and g.calls[0][3] == "SUSTAINMENT"
    assert out["row_edits_applied"]["deleted"] == 2


def test_a_failed_application_is_the_effect_incomplete_503_and_no_fact_is_written():
    g = Graph(fail=True)
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(g, row_edits=DELETED)
    assert ei.value.error == "promotion_effect_incomplete" and ei.value.status == 503
    assert "row_edits" in str(ei.value)
    assert [c[0] for c in g.calls] == ["apply_row_edits"]       # write_fact never reached


def test_a_PROMOTED_act_with_no_row_edits_never_calls_apply_row_edits():
    for edits in (None, []):
        g = Graph()
        out = _act(g, row_edits=edits)
        assert [c[0] for c in g.calls] == ["write_fact"]
        assert "row_edits_applied" not in out


def test_a_REPLAY_with_the_recorded_edits_applies_them_again():
    ledger = Ledger()
    _act(Graph(), ledger=ledger, row_edits=DELETED)
    g = Graph()
    out = _act(g, ledger=ledger, row_edits=DELETED)
    assert out["replayed"] is True
    assert [c[0] for c in g.calls] == ["apply_row_edits", "write_fact"]


# -- the store ----------------------------------------------------------------------------------

class Rec:
    def __init__(self, notice=1, deleted=1):
        self.statements, self.notice, self.deleted = [], notice, deleted

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self.statements.append((cypher, params))
        n = self.deleted if ("DELETE" in cypher or "MERGE" in cypher) else self.notice
        return type("R", (), {"single": lambda _s: {"n": n}})()


def _store(rec):
    return Neo4jIngestGraph(driver=rec, initiator=Initiator(subject="bob", kind="person"),
                            writer_factory=lambda **kw: object())


def _apply(rec, edits, domain="SUSTAINMENT"):
    return _store(rec).apply_row_edits(INGEST_ID, edits, domain=domain, record_id="rec-1")


def test_the_DELETE_statement_scopes_the_notice_and_deletes_only_the_edge():
    rec = Rec()
    out = _apply(rec, DELETED)
    deletes = [(c, p) for c, p in rec.statements if "DELETE" in c]
    assert len(deletes) == 2 and out["deleted"] == 2
    for cypher, params in deletes:
        assert "provenance_ingest_id = $ingest_id" in cypher
        assert "DELETE r" in cypher and "DETACH" not in cypher and "DELETE c" not in cypher
        assert "DELETE n" not in cypher
        assert params["ingest_id"] == INGEST_ID
    assert [p["mpn"] for _, p in deletes] == ["M-1", "M-2"]


def test_a_CORRECTED_edit_rewrites_the_edge_as_steward_corrected():
    rec = Rec()
    out = _apply(rec, [CORRECTED])
    assert out["corrected"] == 1
    writes = [(c, p) for c, p in rec.statements if "MERGE" in c]
    assert len(writes) == 1
    cypher, params = writes[0]
    assert params["obtained_via"] == "steward-corrected"
    assert params["extracted_value"] == "M-3" and params["corrected_by"] == "bob"
    assert params["mpn"] == "M-3A" and params["record_id"] == "rec-1"
    assert "r.extracted_value" in cypher and "r.corrected_by" in cypher
    deletes = [p for c, p in rec.statements if "DELETE r" in c]
    assert deletes and deletes[0]["mpn"] == "M-3"


def test_an_ADDED_edit_writes_the_edge_and_deletes_nothing():
    rec = Rec()
    out = _apply(rec, [ADDED])
    assert out["added"] == 1
    assert not [c for c, _ in rec.statements if "DELETE" in c]
    params = [p for c, p in rec.statements if "MERGE" in c][0]
    assert params["mpn"] == "M-9" and params["disposition"] == "affected"


def test_a_HEADER_edit_is_not_applied_and_issues_no_statement():
    rec = Rec()
    out = _apply(rec, [HEADER])
    assert out["not_applied"] == ["pcn_number"]
    assert rec.statements == []


@pytest.mark.parametrize("bad", ["sustainment", "A B", "X) DETACH DELETE (c", "", "1ABC"])
def test_a_bad_domain_raises_before_any_statement(bad):
    rec = Rec()
    with pytest.raises(ValueError):
        _apply(rec, DELETED, domain=bad)
    assert rec.statements == []


def test_no_matching_notice_raises_rather_than_succeeding_silently():
    rec = Rec(notice=0)
    with pytest.raises(RuntimeError):
        _apply(rec, DELETED)
    assert not [c for c, _ in rec.statements if "DELETE" in c]


def test_zero_matched_edges_is_a_converged_no_op():
    assert _apply(Rec(deleted=0), DELETED)["deleted"] == 0


# ── THE EDGE CARRIES THE EDIT'S OWN RUNG (architect 2026-10-23, item 2) ─────────────────────────
# The write used to stamp the literal "steward-corrected" on every edge it wrote, so a hand-entered
# part (steward-entered) would have landed indistinguishable from a corrected one. Every case
# below uses a rung OTHER than steward-corrected, or the old literal would pass it.

def _writes(rec):
    return [p for c, p in rec.statements if "MERGE" in c]


def test_an_ADDED_edit_lands_as_its_own_rung_not_as_steward_corrected():
    rung = provenance.USER_DROP
    assert rung in provenance.OBTAINED_VIA and rung != provenance.STEWARD_CORRECTED
    rec = Rec()
    _apply(rec, [{**ADDED, "obtained_via": rung}])
    assert [p["obtained_via"] for p in _writes(rec)] == [rung]


@pytest.mark.parametrize("rung", provenance.OBTAINED_VIA)
@pytest.mark.parametrize("edit", [ADDED, CORRECTED], ids=["added", "corrected"])
def test_every_rung_on_the_ladder_is_written_as_itself(edit, rung):
    rec = Rec()
    _apply(rec, [{**edit, "obtained_via": rung}])
    assert [p["obtained_via"] for p in _writes(rec)] == [rung]


@pytest.mark.parametrize("bad", [None, "", "Steward-Corrected", "steward_corrected", "hand"])
@pytest.mark.parametrize("edit", [ADDED, CORRECTED], ids=["added", "corrected"])
def test_a_written_edit_off_the_ladder_is_refused_before_any_statement(edit, bad):
    rec = Rec()
    with pytest.raises(ValueError, match="obtained_via"):
        _apply(rec, DELETED + [{**edit, "obtained_via": bad}])
    assert rec.statements == []          # not even the deletes ahead of it in the batch


def test_a_written_edit_with_no_obtained_via_key_is_refused():
    rec = Rec()
    edit = {k: v for k, v in ADDED.items() if k != "obtained_via"}
    with pytest.raises(ValueError, match="obtained_via"):
        _apply(rec, [edit])
    assert rec.statements == []


def test_a_DELETED_edit_needs_no_rung():
    assert all("obtained_via" not in e for e in DELETED)       # the control's premise
    assert _apply(Rec(), DELETED)["deleted"] == 2
