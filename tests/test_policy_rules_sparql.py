"""GENERIC policy-rules SPARQL sealed — parse-validation + Turtle-fidelity.

engine-o's `/policy_rules` is a thin typed-triples window: it CONSTRUCTs the rule subgraph and serves
Turtle, interpreting nothing. Two seals at the layer that owns the property:

1. PARSE-VALIDATE — the CONSTRUCT/ASK builders are valid SPARQL (the brace-bug guard, one form out).
2. TURTLE-FIDELITY — the served subgraph round-trips through rdflib to the SAME triples the source TTL
   holds, TERM TYPES INTACT. This is the CONSTRUCT-over-SELECT rationale made into an assertion: a
   boolean rule condition (`whenHasReplacement true`) survives as a boolean Literal, not the string
   "true" (which `bool()` would read as truthy either way — the landmine the SELECT path would arm).
   Proven by loading the CONSTRUCT result through the real loader and diffing against the known-good
   answer (rules@2915ddb229e4) — the seam-diff pattern, at the endpoint's layer.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with rdflib \
        pytest ../../tests/test_policy_rules_sparql.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for p in (str(_REPO / "agent_fleet" / "ontology_service"), str(_REPO / "agent_fleet" / "restate_analyst"), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.ontology_service.policy_rules_sparql import build_graph_probe_ask, build_rules_construct  # noqa: E402
from agent_fleet.restate_analyst.policy_rules_loader import load_disposition_rules  # noqa: E402

_TTL = _REPO / "setup" / "ontologies" / "pcn_disposition_rules.ttl"
_RULE_TYPE = "http://internal/sustainment/pcn#DispositionRule"
_CHANGE_CLASS = "http://internal/sustainment/pcn#changeClass"
_GRAPH_IRI = "http://internal/SUSTAINMENT"


def _construct(domain="SUSTAINMENT"):
    return build_rules_construct(domain, rule_type_iri=_RULE_TYPE, change_class_pred=_CHANGE_CLASS)


# ---------------------------------------------------------------------------
# 1. Parse-validate
# ---------------------------------------------------------------------------
def test_construct_and_ask_are_valid_sparql():
    from rdflib.plugins.sparql import prepareQuery
    prepareQuery(_construct())            # raises on malformed SPARQL
    prepareQuery(build_graph_probe_ask("SUSTAINMENT"))


def test_builders_are_domain_free():
    """The route/builders carry no domain in the QUERY — the vocab is a parameter, the graph a name.
    A different domain name just scopes to a different graph."""
    q = build_rules_construct("MANUFACTURING", rule_type_iri=_RULE_TYPE, change_class_pred=_CHANGE_CLASS)
    assert "http://internal/MANUFACTURING" in q and "http://internal/MANUFACTURING_INSTANCES" in q


# ---------------------------------------------------------------------------
# 2. Turtle-fidelity — CONSTRUCT result round-trips to the known-good loader answer
# ---------------------------------------------------------------------------
def _load_named_dataset():
    import rdflib
    ds = rdflib.Dataset()
    ds.graph(rdflib.URIRef(_GRAPH_IRI)).parse(str(_TTL), format="turtle")
    return ds


def test_construct_preserves_everything_the_loader_needs():
    """Run the CONSTRUCT over the real TTL (in a named graph) and load BOTH the result and the source
    directly — identical (ruleset, category_classes, ruleset_ref). Fidelity = the window loses nothing."""
    import rdflib
    ds = _load_named_dataset()
    result = ds.query(_construct())  # CONSTRUCT -> a result graph
    result_graph = rdflib.Graph()
    for t in result:
        result_graph.add(t)

    direct = rdflib.Graph()
    direct.parse(str(_TTL), format="turtle")

    from_construct = load_disposition_rules(result_graph)
    from_direct = load_disposition_rules(direct)
    assert from_construct == from_direct, "CONSTRUCT result did not round-trip to the source loader answer"
    assert from_construct[2] == "rules@2915ddb229e4", f"ruleset_ref drifted: {from_construct[2]}"


def test_construct_preserves_boolean_term_type():
    """The CONSTRUCT-over-SELECT reason, asserted: a boolean rule condition survives as a boolean
    Literal (not the string 'true'). Through the SELECT path this would be stringified and boolean rule
    matching would silently break."""
    import rdflib
    ds = _load_named_dataset()
    result = ds.query(_construct())
    has_repl = rdflib.URIRef("http://internal/sustainment/pcn#whenHasReplacement")
    bool_objs = [o for (s, p, o) in result if p == has_repl]
    assert bool_objs, "whenHasReplacement not in the constructed subgraph"
    assert all(isinstance(o, rdflib.Literal) and o.datatype and o.datatype.endswith("boolean") for o in bool_objs), \
        "boolean condition lost its type in the CONSTRUCT (would arm the bool('false')==True landmine)"
