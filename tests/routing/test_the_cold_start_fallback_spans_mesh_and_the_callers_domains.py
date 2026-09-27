"""THE COLD-START FALLBACK MUST SPAN MESH AND THE CALLER'S DOMAINS, NOT `MAINTENANCE`.

THE DEFECT. `/resolve`'s cold-start fallback (taken when Weaviate is empty for the caller's
domain) used to call `execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=request.domain)` —
the SINGULAR `domain`, while the supervisor sends `request.domains` (plural). A DOCS-scoped
caller therefore silently answered from `MAINTENANCE` (`execute_sparql`'s own default) instead
of DOCS. Separately, the archetype/system classes every domain's verbs declare as their
`input_uri` (`mesh:DocPage`, the registered subject of `mesh:explain`, among them) live in the
MESH system graph, not in any single domain's graph — so a domain-scoped read structurally
cannot offer them as candidates, however completely that domain's own ontology is indexed.

THE FIX has two independently-testable halves:
  1. `execute_sparql` (agent_fleet/ontology_service/main.py) gained a `domains: list[str] |
     None` keyword that, when non-empty, supersedes `domain` and unions EVERY listed domain's
     two graphs (vocabulary + `_INSTANCES`) into the query's `VALUES ?__mesh_g { ... }` scope.
  2. `/resolve`'s cold-start fallback now builds `_fallback_domains` from
     `request.domains` (falling back to `[request.domain]` when unset) and appends `"MESH"`
     when it is not already present, before calling `execute_sparql(..., domains=_fallback_domains)`.

THIS FILE'S TESTS ARE ALL UNIT-LEVEL (no cluster): they drive `execute_sparql` through the
same stub Jena transport `test_execute_sparql_refuses_instead_of_zeroing.py` uses, capturing
the exact query text POSTed to Jena — which IS the wrapped query, brace-wrap and all.

`_fallback_domains_like_resolve` below mirrors the two-line domain-widening snippet that
lives INLINE in `resolve()` (it is not an importable helper, so there is nothing to import
directly) — see agent_fleet/ontology_service/main.py's `/resolve` handler, the block
immediately after "Step 1.5: COLD START FALLBACK". If that inline logic is ever extracted
into a standalone function, this mirror should be replaced with an import of it.

Run: uv run --frozen pytest tests/routing/test_the_cold_start_fallback_spans_mesh_and_the_callers_domains.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_predicate_hybrid_search import ontology_main  # noqa: E402,F401  (the module fixture)
from agent_fleet.ontology_service import main as ontology_main_module  # noqa: E402

rdflib = pytest.importorskip("rdflib")
from rdflib.plugins.sparql import prepareQuery  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _fallback_domains_like_resolve(domains=None, domain=None):
    """THE REAL FUNCTION `/resolve` CALLS — deliberately not a reimplementation of it.

    This was a mirror of three inline lines in the `/resolve` handler, and the mirror cost the
    MESH half of this file its coverage: with it in place, disabling the MESH append in
    production left `test_the_fallback_query_RUN_yields_DocPage_and_NO_response_shape` green
    (mutant B, measured 2026-09-26). The widening now lives in
    `agent_fleet.ontology_service.main.cold_start_fallback_domains`, and this thin wrapper
    exists only so the arms below read the same way. Do NOT reintroduce a local copy.
    """
    return ontology_main_module.cold_start_fallback_domains(domains, domain)


class _CapturingClient:
    """A Jena stand-in that records the exact query text POSTed to it, then answers empty —
    a real empty result, not an outage, so `execute_sparql` returns cleanly and this file
    measures the QUERY TEXT rather than the refusal path `test_execute_sparql_refuses_
    instead_of_zeroing.py` already covers."""

    def __init__(self, sink: dict):
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, headers=None):
        self._sink["query"] = data["query"]
        return type("R", (), {
            "status_code": 200,
            "json": lambda self: {"results": {"bindings": []}},
        })()


@pytest.fixture
def captured_query(ontology_main, monkeypatch):
    """Wires `_jena_client` to `_CapturingClient` and returns the sink dict that will hold
    the wrapped query text after `execute_sparql` runs."""
    sink: dict = {}
    monkeypatch.setattr(ontology_main, "_JENA_ENDPOINT", "http://fuseki/ds/query", raising=False)
    monkeypatch.setattr(ontology_main, "_jena_client", lambda: _CapturingClient(sink), raising=False)
    return sink


def test_the_fallback_scope_includes_MESH_even_for_a_single_domain_caller(ontology_main, captured_query):
    """A caller entitled to DOCS alone (request.domains == ["DOCS"]) must still see the MESH
    graphs in the cold-start fallback's scope — that is the whole point of 1d's MESH append,
    and this is what makes `mesh:DocPage` (mesh:explain's registered subject) reachable for a
    DOCS-only caller. `_fallback_domains_like_resolve` reproduces the domain list `/resolve`
    would compute for such a caller; `execute_sparql` is what actually builds the graph
    scope from it."""
    fallback_domains = _fallback_domains_like_resolve(domains=["DOCS"])
    assert fallback_domains == ["DOCS", "MESH"]  # sanity: the mirror behaves as documented

    _run(ontology_main.execute_sparql("SELECT ?s WHERE { ?s ?p ?o }", domains=fallback_domains))

    query = captured_query["query"]
    for graph in (
        "<http://internal/DOCS>",
        "<http://internal/DOCS_INSTANCES>",
        "<http://internal/MESH>",
        "<http://internal/MESH_INSTANCES>",
    ):
        assert graph in query, f"{graph} missing from the wrapped query:\n{query}"


def test_a_single_domain_caller_is_UNCHANGED_when_domains_is_absent(ontology_main, captured_query):
    """THE CONTROL. The pre-existing `domain=` call shape (no `domains` kwarg at all) must
    emit EXACTLY the two graphs it always emitted — no MESH, no widening, byte-identical to
    the behaviour before `domains` existed. If this ever starts including MESH too, the
    `domains is None` branch has stopped being a true no-op and every OTHER caller of
    `execute_sparql` (there are several beyond `/resolve`) is now silently scoped wider than
    it asked for."""
    _run(ontology_main.execute_sparql("SELECT ?s WHERE { ?s ?p ?o }", domain="MAINTENANCE"))

    query = captured_query["query"]
    assert "<http://internal/MAINTENANCE>" in query
    assert "<http://internal/MAINTENANCE_INSTANCES>" in query
    assert "<http://internal/MESH>" not in query
    assert query.count("<http://internal/") == 2, (
        f"expected exactly the two MAINTENANCE graphs, found more:\n{query}"
    )


def test_the_wrapped_fallback_query_is_well_formed_SPARQL(ontology_main, captured_query):
    """THE ARM THAT CATCHES THE BRACE-WRAP HAZARD. `execute_sparql` wraps the query by
    string-replacing the first `WHERE {` and appending `} }` at the last `}` — a purely
    textual operation with no awareness of the `FILTER NOT EXISTS { ... }` block 1b added
    inside `_SPARQL_MAINTENANCE_CLASSES`. If that addition ever shifted the last `}` to the
    wrong place, the wrap would produce syntactically broken SPARQL that no earlier arm here
    would notice (they assert on substrings, not on parseability). This arm drives the REAL
    `_SPARQL_MAINTENANCE_CLASSES` constant — not a toy query — through the real wrap and
    parses the result with rdflib's `prepareQuery`."""
    fallback_domains = _fallback_domains_like_resolve(domains=["DOCS"])
    _run(ontology_main.execute_sparql(
        ontology_main._SPARQL_MAINTENANCE_CLASSES, domains=fallback_domains
    ))

    query = captured_query["query"]
    prepareQuery(query)  # raises on malformed SPARQL; the assertion IS that this doesn't raise


# ---------------------------------------------------------------------------
# THE BEHAVIOURAL HALF. Every arm above asserts on the query's TEXT — that MESH is in
# scope, that the wrap parses. None of them runs the query, so none of them can tell a
# working exclusion from a `FILTER NOT EXISTS` that matches nothing. `tests/routing/
# test_response_shapes_are_not_groundable.py`'s new arm has the same limit: it asserts
# the roots and the FILTER appear in the constant. A declaration seal over a filter is
# the shape that let THIS defect ship — the file named for response shapes was green
# while a response shape was the resolved subject — so the arms below execute the real
# wrapped query against a real rdflib Dataset whose named graphs are the ones
# `execute_sparql` scopes to, and assert on the ROWS.
# ---------------------------------------------------------------------------

_MESH = "http://invincible-agent/mesh#"
_DOCS = "http://invincible-agent/docs#"
_PROV = "http://www.w3.org/ns/prov#"


def _dataset_like_the_deployed_graphs():
    """DOCS and MESH as the TTLs actually land them, and nothing else.

    Measured against `setup/ontologies/` on 2026-09-26: `docs_extension.ttl` declares exactly
    one `owl:Class` and it IS `rdfs:subClassOf mesh:Response`; `mesh:DocPage` is declared only
    in `mesh_system.ttl` and subclasses `prov:Entity`. `mesh:KnowledgeDocument` stands in for
    the ARCHETYPE root, so both roots are exercised rather than only the one the defect used.
    """
    from rdflib import RDF, Dataset, Literal, URIRef
    from rdflib.namespace import OWL, RDFS

    ds = Dataset()
    docs = ds.graph(URIRef("http://internal/DOCS"))
    docs.add((URIRef(_DOCS + "DocExplanation"), RDF.type, OWL.Class))
    docs.add((URIRef(_DOCS + "DocExplanation"), RDFS.label, Literal("Doc Explanation")))
    docs.add((URIRef(_DOCS + "DocExplanation"), RDFS.subClassOf, URIRef(_MESH + "Response")))

    mesh = ds.graph(URIRef("http://internal/MESH"))
    mesh.add((URIRef(_MESH + "DocPage"), RDF.type, OWL.Class))
    mesh.add((URIRef(_MESH + "DocPage"), RDFS.label, Literal("Doc Page")))
    mesh.add((URIRef(_MESH + "DocPage"), RDFS.subClassOf, URIRef(_PROV + "Entity")))
    mesh.add((URIRef(_MESH + "KnowledgeDocument"), RDF.type, OWL.Class))
    mesh.add((URIRef(_MESH + "KnowledgeDocument"), RDFS.label, Literal("Knowledge Document")))
    mesh.add((URIRef(_MESH + "KnowledgeDocument"), RDFS.subClassOf, URIRef(_MESH + "Archetype")))
    return ds


def test_the_fallback_query_RUN_yields_DocPage_and_NO_response_shape(ontology_main, captured_query):
    """THE SEAL AS DISPATCHED: "how do I add an engine" as a DOCS caller must be able to reach
    `mesh:DocPage`, and a response shape must never appear in the candidate list.

    This is the arm the rest of this file cannot be a substitute for. It takes the query text
    the shipping wrap produces for a DOCS caller and EXECUTES it, so a `FILTER NOT EXISTS` that
    silently matched nothing would red here and nowhere else.

    Both roots are exercised: `DocExplanation` (under `mesh:Response`, the class the live
    resolver actually offered at 0.99) and `KnowledgeDocument` (under `mesh:Archetype`, the
    second root, which the defect never touched and which a one-root fix would leak).
    """
    _run(ontology_main.execute_sparql(
        ontology_main._SPARQL_MAINTENANCE_CLASSES,
        domains=_fallback_domains_like_resolve(domains=["DOCS"]),
    ))
    rows = {str(r[0]) for r in _dataset_like_the_deployed_graphs().query(captured_query["query"])}

    assert _MESH + "DocPage" in rows, (
        "mesh:DocPage is mesh:explain's registered input_uri and the ONLY answerable subject a "
        f"DOCS caller has. Without it the docs walk dead-ends. Rows: {sorted(rows)}"
    )
    assert _DOCS + "DocExplanation" not in rows, (
        "docs:DocExplanation is rdfs:subClassOf mesh:Response — it is mesh:explain's OUTPUT and "
        f"carries no verb. Offering it is the NO_COMPATIBLE_VERBS defect. Rows: {sorted(rows)}"
    )
    assert _MESH + "KnowledgeDocument" not in rows, (
        "mesh:KnowledgeDocument is rdfs:subClassOf mesh:Archetype — the SECOND root. A fix that "
        f"excluded only mesh:Response would pass every other arm and leak this. Rows: {sorted(rows)}"
    )


def test_the_exclusion_is_SINGLE_GRAPH_transitive_and_that_is_recorded(ontology_main, captured_query):
    """A MEASURED LIMITATION, PINNED SO IT CANNOT BECOME A SILENT HOLE.

    The `FILTER NOT EXISTS` sits INSIDE the wrap's `GRAPH ?__mesh_g { ... }`, and `GRAPH ?g`
    binds one graph for its whole pattern — so `rdfs:subClassOf+` cannot walk a chain whose
    links live in DIFFERENT named graphs, however many domains are in scope.

    THIS IS NOT A LIVE HOLE TODAY, and that is a measurement rather than an assumption: all 82
    response shapes in `setup/ontologies/` declare `rdfs:subClassOf mesh:Response|Archetype`
    DIRECTLY, in their own domain's file, so every one of them is a one-hop match inside a
    single graph (checked 2026-09-26 across mesh_system, cost_, finance_, safety_ and docs_
    extensions). doc-tools computes its exclusion over a MERGED graph and so has no such limit.

    This arm asserts the limitation still behaves as described. It is deliberately written to
    pass WHILE THE LEAK EXISTS: if someone later makes the exclusion graph-spanning (a
    `FILTER NOT EXISTS { GRAPH ?any { ... } }`, or an exclusion computed before scoping), this
    arm reds and should be DELETED along with the caveat in the docstring above — a red here is
    good news. What it forbids is the third state: an ontology gaining a cross-graph shape
    chain while everyone still believes the filter covers it.
    """
    from rdflib import RDF, Dataset, Literal, URIRef
    from rdflib.namespace import OWL, RDFS

    ds = Dataset()
    near = ds.graph(URIRef("http://internal/DOCS"))
    near.add((URIRef(_DOCS + "Orphan"), RDF.type, OWL.Class))
    near.add((URIRef(_DOCS + "Orphan"), RDFS.label, Literal("Orphan")))
    near.add((URIRef(_DOCS + "Orphan"), RDFS.subClassOf, URIRef(_DOCS + "Mid")))
    far = ds.graph(URIRef("http://internal/MESH"))
    far.add((URIRef(_DOCS + "Mid"), RDFS.subClassOf, URIRef(_MESH + "Response")))

    _run(ontology_main.execute_sparql(
        ontology_main._SPARQL_MAINTENANCE_CLASSES,
        domains=_fallback_domains_like_resolve(domains=["DOCS"]),
    ))
    rows = {str(r[0]) for r in ds.query(captured_query["query"])}

    assert _DOCS + "Orphan" in rows, (
        "The cross-graph leak this arm documents has been CLOSED — the exclusion now spans "
        "named graphs. That is an improvement: delete this arm and the single-graph caveat in "
        "its docstring, and drop the matching note from the 2026-09-26 measurement."
    )
