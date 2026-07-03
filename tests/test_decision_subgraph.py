"""Decision-subgraph base layer — the two-layer diff map's foundation.

The decision-path MAP overlays the captured decision on a BOUNDED live
read of the graph neighborhood and renders their divergence honestly. This
file pins the honesty-critical parts of the base-layer read:

  1. _parse_decision_subgraph — folds flat Neo4j rows into
     {live_nodes, live_edges, context_nodes}, bounded to 1 hop, with
     context = neighbors OUTSIDE the captured set (drawn dim). The diff
     (matched vs ghosted) is the frontend's job; this only reports what
     the live graph faithfully holds.
  2. The COULDN'T-CHECK contract: on a live-read failure the endpoint
     returns available=False (NOT a fabricated base layer), so the map
     labels itself "captured-only, cannot verify" instead of presenting
     historical structure as current. "Diffed, nothing changed" and
     "couldn't diff" are different facts — the three-state rule.

Hermetic: the parser is pure; the couldn't-check path is exercised with a
driver stub that raises. No live Neo4j.

Run:  PYTHONPATH=src pytest tests/test_decision_subgraph.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.gateway import (  # noqa: E402
    _parse_decision_subgraph,
    _parse_ancestor_chain,
)


def _row(uri, labels=None, rel_type=None, neighbor_uri=None, outgoing=None):
    return {
        "uri": uri,
        "labels": labels or ["OntologyClass"],
        "rel_type": rel_type,
        "neighbor_uri": neighbor_uri,
        "outgoing": outgoing,
    }


# ---------------------------------------------------------------------------
# The pure parser
# ---------------------------------------------------------------------------
def test_live_nodes_are_the_captured_uris_that_exist():
    """Only captured nodes the live read returned appear in live_nodes.
    (A captured URI absent from the rows is NOT here — the frontend will
    render it ghosted as diverged.)"""
    captured = {"idp#Dashboard", "idp#Dataset", "idp#Gone"}
    rows = [
        _row("idp#Dashboard"),
        _row("idp#Dataset"),
        # idp#Gone produced NO row — it no longer exists in the live graph.
    ]
    out = _parse_decision_subgraph(rows, captured)
    live = {n["uri"] for n in out["live_nodes"]}
    assert live == {"idp#Dashboard", "idp#Dataset"}
    assert "idp#Gone" not in live, (
        "a captured node absent from the live read must NOT appear as live "
        "— that absence is the divergence the map renders as a ghost"
    )


def test_edges_oriented_by_direction():
    """Edge orientation follows the graph direction so the drawn arrow is
    truthful: outgoing → (uri, neighbor); incoming → (neighbor, uri)."""
    captured = {"idp#Dashboard", "idp#Dataset"}
    rows = [
        _row("idp#Dashboard", rel_type="SUBCLASS_OF",
             neighbor_uri="idp#Dataset", outgoing=True),
    ]
    out = _parse_decision_subgraph(rows, captured)
    assert out["live_edges"] == [
        {"source": "idp#Dashboard", "target": "idp#Dataset", "type": "SUBCLASS_OF"}
    ]


def test_context_nodes_are_neighbors_outside_the_captured_set():
    """A 1-hop neighbor NOT in the captured decision is dim context —
    present now, not part of the decision. Bounded: it's context, not a
    new expansion frontier."""
    captured = {"idp#Dataset"}
    rows = [
        _row("idp#Dataset", rel_type="lookupOwnership",
             neighbor_uri="mesh#OwnershipFact", outgoing=True),
        _row("idp#Dataset", rel_type="SUBCLASS_OF",
             neighbor_uri="idp#Resource", outgoing=True),
    ]
    out = _parse_decision_subgraph(rows, captured)
    ctx = {c["uri"] for c in out["context_nodes"]}
    assert ctx == {"mesh#OwnershipFact", "idp#Resource"}, (
        "neighbors outside the captured set are context (dim), never "
        "silently promoted into the decision"
    )


def test_edges_deduped():
    """The same edge surfacing on multiple rows (both endpoints captured)
    collapses to one drawn edge."""
    captured = {"a", "b"}
    rows = [
        _row("a", rel_type="R", neighbor_uri="b", outgoing=True),
        _row("b", rel_type="R", neighbor_uri="a", outgoing=False),  # same edge, other endpoint
    ]
    out = _parse_decision_subgraph(rows, captured)
    assert out["live_edges"] == [{"source": "a", "target": "b", "type": "R"}]


def test_node_with_no_relationships_still_present():
    """OPTIONAL MATCH yields a null-rel row for an isolated node; it must
    still count as a live node (it exists), just with no edges."""
    out = _parse_decision_subgraph([_row("idp#Lonely")], {"idp#Lonely"})
    assert [n["uri"] for n in out["live_nodes"]] == ["idp#Lonely"]
    assert out["live_edges"] == []
    assert out["context_nodes"] == []


# ---------------------------------------------------------------------------
# The COULDN'T-CHECK contract (three-state honesty). Exercised by stubbing
# the module's neo4j driver to raise, and asserting available=False rather
# than a fabricated base layer.
# ---------------------------------------------------------------------------
def test_couldnt_check_on_live_read_failure(monkeypatch):
    import asyncio
    import iagent.gateway as gw

    class _BoomSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, *a, **k): raise RuntimeError("neo4j unreachable")

    class _BoomDriver:
        def session(self): return _BoomSession()

    monkeypatch.setattr(gw, "neo4j_driver", _BoomDriver())

    async def _fake_user():
        return None

    req = gw.DecisionSubgraphRequest(class_uris=["idp#Dashboard"])
    resp = asyncio.run(gw.decision_subgraph(req, current_user=None))

    assert resp.available is False, (
        "a failed live read is COULDN'T-CHECK — never a fabricated base "
        "layer presented as current"
    )
    assert resp.live_nodes == [] and resp.context_nodes == []
    assert "failed" in resp.reason.lower()


# ---------------------------------------------------------------------------
# The ancestor-chain walk (the map's structural prerequisite). The
# projection caps the captured decision at ONE ancestor + a "+N hops"
# count; the map needs every intermediate subClassOf class as a REAL node.
# ---------------------------------------------------------------------------
def test_ancestor_chain_full_walk_intermediate_hops_are_real_nodes():
    """A deep walk Dashboard → Dataset → Resource → Thing: every
    intermediate class must be a real chain node, not collapsed to a
    badge. The ordered spine is subject-first."""
    path_rows = [{
        "nodes": [
            {"uri": "idp#Dashboard", "labels": ["OntologyClass"]},
            {"uri": "idp#Dataset", "labels": ["OntologyClass"]},
            {"uri": "idp#Resource", "labels": ["OntologyClass"]},
            {"uri": "idp#Thing", "labels": ["OntologyClass"]},
        ],
        "edges": [
            {"source": "idp#Dashboard", "target": "idp#Dataset"},
            {"source": "idp#Dataset", "target": "idp#Resource"},
            {"source": "idp#Resource", "target": "idp#Thing"},
        ],
    }]
    out = _parse_ancestor_chain(path_rows)
    chain_uris = {n["uri"] for n in out["chain_nodes"]}
    assert chain_uris == {"idp#Dashboard", "idp#Dataset", "idp#Resource", "idp#Thing"}, (
        "every intermediate subClassOf class must be a REAL node — the "
        "map's structure is the intermediate hops, not a +N badge"
    )
    assert out["ordered_chain"] == [
        "idp#Dashboard", "idp#Dataset", "idp#Resource", "idp#Thing",
    ], "spine is ordered subject-first for the vertical render"
    assert all(e["type"] == "subClassOf" for e in out["chain_edges"])
    assert len(out["chain_edges"]) == 3


def test_ancestor_chain_longest_path_is_the_spine():
    """A branching hierarchy (two parents at some level) → all nodes
    union'd, and the LONGEST path is the canonical ordered spine."""
    path_rows = [
        {"nodes": [{"uri": "A"}, {"uri": "B"}], "edges": [{"source": "A", "target": "B"}]},
        {"nodes": [{"uri": "A"}, {"uri": "C"}, {"uri": "D"}],
         "edges": [{"source": "A", "target": "C"}, {"source": "C", "target": "D"}]},
    ]
    out = _parse_ancestor_chain(path_rows)
    assert {n["uri"] for n in out["chain_nodes"]} == {"A", "B", "C", "D"}
    assert out["ordered_chain"] == ["A", "C", "D"]  # the longer path


def test_ancestor_chain_empty_when_no_paths():
    out = _parse_ancestor_chain([])
    assert out["chain_nodes"] == []
    assert out["ordered_chain"] == []


def test_empty_captured_is_available_but_empty(monkeypatch):
    """No captured class nodes → the read trivially succeeds with an empty
    neighborhood (available=True), distinct from couldn't-check."""
    import asyncio
    import iagent.gateway as gw
    req = gw.DecisionSubgraphRequest(class_uris=[])
    resp = asyncio.run(gw.decision_subgraph(req, current_user=None))
    assert resp.available is True
    assert resp.live_nodes == []
