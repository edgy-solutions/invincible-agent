"""One ledger vocabulary, two graphs — and which terms each can reach is its `refusal` clause.

EXTRACTED AT THE SECOND CONSUMER. The cost lot review became the second graph to emit ledger
rows, and this repo has paid twice for the alternative: the card and the routing record each had
a rule for picking the primary subtask, the two agreed in a docstring, and they disagreed in
production. A second copy of a vocabulary is a second vocabulary the moment either is edited.

── THE FINDING THAT SHAPED THIS FILE ───────────────────────────────────────────────────────
**A `refusal: fail` graph can never emit a hole disposition.** Not by omission — by contract: a
refused inner call RAISES, so the graph never returns a row for one. The finance brief declares
`named-hole` and reaches all five terms; the cost review declares `fail` and reaches three.

So a per-graph seal asserting "all five are reachable" would be WRONG for cost, and one
hand-listing three would go stale the day its ratified row changed its clause. `reachable_for`
derives the subset FROM THE CLAUSE, and the seals below read the clause out of the ratified
yaml rather than restating it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from tests.graph_host._engine_deps import needs_langgraph

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_POLICY = _ROOT / "policy" / "graphs"


def _refusal(graph_id: str) -> str:
    return yaml.safe_load((_POLICY / f"{graph_id}.yaml").read_text(encoding="utf-8"))["refusal"]


# -- one vocabulary, not two ----------------------------------------------------------------

@needs_langgraph
def test_BOTH_graphs_use_the_SAME_vocabulary_OBJECT():
    """IDENTITY, NOT EQUALITY. Two tuples with the same contents pass an equality check and are
    still two vocabularies — they agree until someone edits one, which is the exact failure
    this extraction exists to prevent and the one an `==` here would not see."""
    import iagent_mesh as shared
    from agent_fleet.graph_host.graphs import fin_program_brief as fin

    # AGAINST THE SDK's PACKAGE ROOT. This is what the move makes assertable: the host's
    # vocabulary is not an equal copy of the contract, it IS the contract object — and asserting
    # it at the ROOT makes this repo the first local witness to a surface ca's export seal was
    # guarding with none.
    assert fin.ROW_DISPOSITIONS is shared.ROW_DISPOSITIONS
    assert fin.HOLE_DISPOSITIONS is shared.HOLE_DISPOSITIONS
    assert fin.holes_from is shared.holes_from


@needs_langgraph
def test_the_partition_holds_in_the_SHARED_module():
    """Every declared term is a hole or is named as not one — no overlap, no remainder. A new
    term FAILS WHILE UNDECIDED rather than defaulting to not-a-hole and silently shrinking the
    named-hole list."""
    import iagent_mesh as shared

    holes, non = set(shared.HOLE_DISPOSITIONS), set(shared.NON_HOLE_DISPOSITIONS)
    declared = set(shared.ROW_DISPOSITIONS)
    assert not (holes & non), f"classified both ways: {sorted(holes & non)}"
    assert not declared - holes - non, (
        f"{sorted(declared - holes - non)} are declared and classified neither way"
    )
    assert not (holes | non) - declared, (
        f"{sorted((holes | non) - declared)} are classified but not declared"
    )


# -- reachability is the refusal clause ------------------------------------------------------

@needs_langgraph
def test_a_FAIL_graph_can_reach_NO_hole_disposition():
    """Read from the ratified row, not restated. A `fail` graph raises on a refused inner call,
    so it never RETURNS a row for one — asserting a hole term against it would be asserting an
    outcome its own contract forbids."""
    import iagent_mesh as shared

    assert _refusal("cost_lot_costing_review") == "fail", "this seal's subject changed clause"
    reachable = shared.reachable_for(_refusal("cost_lot_costing_review"))
    assert not reachable & set(shared.HOLE_DISPOSITIONS)
    assert reachable == set(shared.NON_HOLE_DISPOSITIONS)


@needs_langgraph
def test_a_NAMED_HOLE_graph_CAN_reach_them():
    """THE CONTROL. Without it, "a fail graph reaches no holes" is satisfied by a rule that
    returns the non-hole set for everyone — which would make the finance brief's named holes
    unassertable while reading as correct."""
    import iagent_mesh as shared

    assert _refusal("fin_program_brief") == "named-hole", "this control changed clause"
    reachable = shared.reachable_for(_refusal("fin_program_brief"))
    assert reachable == set(shared.ROW_DISPOSITIONS)
    assert reachable & set(shared.HOLE_DISPOSITIONS)


# -- the cost review actually emits them -----------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        return None


def _cost_row(monkeypatch, payload) -> dict:
    from agent_fleet.graph_host.graphs import cost_lot_costing_review as c

    monkeypatch.setattr(c.httpx, "post", lambda *a, **k: _Resp(payload))
    node = c._fetch("cost_lot_breakdown", "lot cost breakdown")
    out = node({"lot": 4, "rate_vintage": "2026-Q1",
                "identity": {"authorization": "Bearer t"}})
    assert len(out["rows"]) == 1
    return out["rows"][0]


@needs_langgraph
def test_the_cost_review_emits_a_row_per_source(monkeypatch):
    """Without rows it cannot be the second SOURCE_LEDGER consumer — binding it would advertise
    a shape it does not produce, which is registered-and-not-participating one layer over."""
    assert _cost_row(monkeypatch, {"verdict": "within tolerance", "artifact_id": "c-1",
                                   "rows": [1]})["disposition"] == "finding"
    assert _cost_row(monkeypatch, {"artifact_id": "c-2", "rows": [1]})["disposition"] == \
        "unsummarised"
    assert _cost_row(monkeypatch, {"artifact_id": "c-3", "rows": []})["disposition"] == "empty"


@needs_langgraph
def test_the_cost_review_reaches_ONLY_what_its_clause_allows(monkeypatch):
    """The two halves joined: what the graph EMITS against what its declared clause ALLOWS. A
    graph reaching a term its contract forbids is the more interesting direction, and no
    per-side check can see it."""
    import iagent_mesh as shared

    allowed = shared.reachable_for(_refusal("cost_lot_costing_review"))
    seen = {
        _cost_row(monkeypatch, {"verdict": "v", "rows": [1]})["disposition"],
        _cost_row(monkeypatch, {"rows": [1]})["disposition"],
        _cost_row(monkeypatch, {"rows": []})["disposition"],
    }
    assert seen <= allowed, f"emitted {sorted(seen - allowed)}, which its refusal clause forbids"
    assert seen == allowed, (
        f"declared reachable {sorted(allowed)} but only {sorted(seen)} are produced — an "
        f"unreachable term is a name nobody can emit."
    )


@needs_langgraph
def test_a_REFUSED_inner_call_RAISES_rather_than_producing_a_hole_row(monkeypatch):
    """The mechanism behind the reachability rule, asserted rather than assumed. If this ever
    returned a row instead, `reachable_for` would be describing a contract the graph no longer
    keeps — and the seal above would still pass, because it only checks what IS emitted."""
    import pytest

    from agent_fleet.graph_host.graphs import cost_lot_costing_review as c

    class _R403:
        status_code = 403

        def json(self):
            return {}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(c.httpx, "post", lambda *a, **k: _R403())
    node = c._fetch("cost_lot_breakdown", "lot cost breakdown")
    with pytest.raises(c.RefusedInner):
        node({"lot": 4, "rate_vintage": "2026-Q1", "identity": {"authorization": "Bearer t"}})
