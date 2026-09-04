"""EVERY OPTION IN THE GROUNDING POOL MUST BE ONE THE ROUTER CAN SERVE.

THE DEFECT, measured across three engines in one week. A class nothing serves still grounds:
`/resolve` returns it at high confidence, `/find_compatible_verbs` returns nothing, and the
supervisor falls to the generalist — which answers from the catalog wearing the CALLER's
persona. That answer is indistinguishable from a real one until a human reads the card.

    cost#CostCategory         0.96, zero verbs   -> generalist, answered as DATA_ENGINEER
    idp#Job, idp#Pipeline     reachable in the DATA_ENGINEERING pool, zero verbs in any scope
    fin#EarnedValueTechnique  zero verbs, and it WON a draw for "show me SPI over time"

THAT LAST ONE IS WHY THIS IS STRUCTURAL RATHER THAN TIDY. The SPI row was recorded as winner
instability — it flipped between PerformanceMeasurementBaseline and EarnedValueTechnique
across draws on one substrate. One of those winners routes; the other cannot be answered at
all. So half its draws were a different KIND of event, and a run scored on class names cannot
see the difference **because both produce a class name**. "The sampler is unstable" and "the
pool has dead ends" were the same incident, filed twice, by two lanes, with the causal link in
neither document.

DOMAIN-RELATIVE BY CONSTRUCTION, which is the half a global check gets wrong. idp:Dashboard
carries nine verbs under DATA_ENGINEERING and none under PORTFOLIO_PLANNING — the domain
filter working, not a gap. A global count reports 4 unserved idp: classes; the assertion that
holds is UNSERVED IN EVERY SCOPE, which is 2.

THE ESCAPE IS DECLARED, NEVER INFERRED: `rdfs:subClassOf mesh:ResolvableReferent` marks a
subject a speaker names and a provider resolves with no verb of its own — a drill-down
target. A subClassOf marker rather than an annotation because doc-tools syncs subClassOf
edges to Neo4j and carries nothing else, and a declaration the enforcement point cannot see
is not a declaration.

Run: uv run --frozen pytest tests/routing/test_productive_option_gate.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MAIN = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_TTL = _REPO / "setup" / "ontologies" / "mesh_system.ttl"

_SRC = _MAIN.read_text(encoding="utf-8")


# ── the filter's decision, as pure set logic ────────────────────────────────
#
# Mirrors the wired branch exactly. Kept as a local function rather than importing main.py,
# which pulls BAML, Weaviate and Neo4j at module scope — the seal must not be able to fail
# for an environment reason, which is the discipline the response-shape seal already uses.

def _gate(candidates: list, served: frozenset) -> list:
    if not candidates or not served:
        return candidates
    productive = [c for c in candidates if c in served]
    if not productive:
        return candidates
    return productive


A, B, DEAD = "idp#Portfolio", "idp#Site", "cost#CostCategory"


def test_an_unserved_class_is_dropped():
    """THE REGRESSION. cost#CostCategory grounded at 0.96 and could not be answered."""
    assert _gate([A, DEAD, B], frozenset({A, B})) == [A, B]


def test_a_served_class_survives():
    assert _gate([A, B], frozenset({A, B})) == [A, B]


# ── the two degradations, and they are the dangerous half ───────────────────

def test_an_EMPTY_served_set_does_NOT_filter():
    """DEGRADE OPEN. An empty served-set means the lookup failed or the graph is cold.
    Applying it would empty the pool and take routing down for every caller — turning a
    Neo4j hiccup into a total outage, which is far worse than the dead end this removes."""
    assert _gate([A, DEAD, B], frozenset()) == [A, DEAD, B]


def test_a_filter_that_would_empty_the_pool_is_REFUSED():
    """The signature of a served-set computed against the wrong domains. Answering from a
    dead end beats answering nothing while the cause is found — and an empty pool would
    present as UNKNOWN, which reads as 'we do not understand you' rather than as a fault."""
    assert _gate([A, B], frozenset({"cost#Something"})) == [A, B]


def test_the_gate_is_a_noop_on_an_empty_pool():
    assert _gate([], frozenset({A})) == []


# ── the wiring, asserted structurally ───────────────────────────────────────

def _resolve_fn() -> ast.FunctionDef:
    tree = ast.parse(_SRC)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "resolve"),
              None)
    assert fn is not None, "resolve() not found — was it renamed?"
    return fn


def test_the_gate_is_wired_into_resolve():
    """Checked on the AST, not by grepping the file: this module carries a long comment
    explaining the gate, and a substring search would pass on the prose that describes the
    code rather than on the code."""
    called = {n.func.id for n in ast.walk(_resolve_fn())
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_served_class_uris" in called, (
        "resolve() does not call _served_class_uris — the gate is declared and unwired, "
        "which is the shape of every registration defect this repo has filed."
    )


def test_the_gate_runs_BEFORE_the_instance_fanout():
    """Order matters. The fan-out at Step 1.6 fires only when class recall is EMPTY, so a
    gate running after it could empty the pool without the fan-out ever getting its chance —
    turning a filtered-out dead end into an UNKNOWN rather than into a resolved instance."""
    gate = _SRC.index("_served_class_uris(request.domains")
    fanout = _SRC.index("if not candidates and request.entity_refs:")
    assert gate < fanout, "the productive-option gate must run before the instance fan-out"


def test_the_domains_passed_are_the_CALLERS():
    """`domains` (plural) is the caller's real scope; `domain` is a legacy field defaulting
    to MAINTENANCE. Passing the wrong one computes the served set against a domain the
    caller never asked for — the scoping trap that has already invalidated one published
    measurement in this repo."""
    m = re.search(r"_served_class_uris\(\s*request\.domains[^)]*\)", _SRC)
    assert m, "the gate must be given request.domains, not request.domain alone"


# ── the declared escape ─────────────────────────────────────────────────────

def test_the_referent_marker_is_declared_and_reachable_from_neo4j():
    """A subClassOf marker, because doc-tools syncs subClassOf edges to Neo4j and carries
    nothing else about a class. An annotation property would live in Fuseki and never reach
    the store the filter queries."""
    ttl = _TTL.read_text(encoding="utf-8")
    assert "mesh:ResolvableReferent a owl:Class" in ttl
    assert "_RESOLVABLE_REFERENT_ROOT" in _SRC
    assert "mesh#ResolvableReferent" in _SRC


def test_the_cypher_walks_ancestors_like_find_compatible_verbs_does():
    """A filter with a shorter reach than the consumer it feeds would drop classes that DO
    route — served through an ancestor rather than directly. The walk must match."""
    assert "subClassOf*0..5" in _SRC, "the served-class walk must mirror the compat walk"


def test_the_cypher_treats_domainless_verbs_as_agnostic():
    """Matching /find_compatible_verbs: a verb declaring no domains is domain-agnostic and
    serves every caller. Treating an empty list as 'serves nobody' would drop every class
    whose only verb is infrastructure."""
    assert "coalesce(r.domains, []) = []" in _SRC
