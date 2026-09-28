"""The OntologyClass scan must span MESH whenever the caller scoped at all.

WHAT THIS IS ABOUT, AND WHY IT IS A SECOND FILE. `test_the_cold_start_fallback_spans_mesh_and_
the_callers_domains.py` holds the same rule for the SPARQL cold-start fallback. This one holds it
for the Weaviate class scan — the path taken when the index has rows, i.e. the path production
takes first and the fallback exists to rescue. They share a rule and not a surface: one builds
graph URIs in SPARQL text, the other builds a Weaviate property filter, and a seal over one says
nothing about the other. That is exactly how the defect below survived the fallback's seal.

WHAT IT COST, measured 2026-09-27 (roll #5, revision 153). `docs-what-is-an-archetype` routed,
drew, and produced **0 rows under `sections`** — an EMPTY document, not a missing verb, which is
the harder finding to read because the card arrives looking answered. `_weaviate_hybrid_search_
sync` filtered `domain == "DOCS"`, the archetype and system classes every domain's verbs name as
their `input_uri` are declared only in `mesh_system.ttl` and so carry `domain == "MESH"`, and so
the scan returned nothing for every DOCS caller. `/resolve` then took the cold-start fallback
**every time** — and the fallback is what makes the verb resolvable, not what fills a document.
So the walk answered, and answered via the fallback permanently.

THE REQUEST IS THE SUBJECT, not the projection. A recording double asserts the WRITER and never
the store, so these arms read the `filters` object handed to `.hybrid()`/`.bm25()` and compare it
against the filter the rule should have built — property name, operator and domain set together.
An arm that only counted returned rows would be scripted by the double and would pass with any
filter at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_predicate_hybrid_search import (  # noqa: E402,F401
    _FakeClient, _FakeObject, ontology_main,
)
from agent_fleet.ontology_service import main as ontology_main_module  # noqa: E402

def _want_filter(ontology_main, domains):
    """The filter production SHOULD have built, built through the module under test's own `wvc`.

    NOT through an independently imported `weaviate.classes`. The `ontology_main` fixture stubs
    that module, so the production call records the stub's shape — a plain
    `('contains_any', 'domain', [...])` tuple — while a separately imported real library yields a
    `_FilterValue`. Comparing those two reds with the right VALUES in both halves of the diff,
    which is a red that accuses the production code of a defect the test invented.

    Deriving the expectation from the subject's own imports keeps the assertion covering the
    property name and the operator, not just the domain set, under either library.
    """
    return ontology_main.wvc.query.Filter.by_property("domain").contains_any(domains)


def _a_class_row():
    """One OntologyClass row, so the scan has something to return and the arms measure the
    FILTER rather than the empty-result path."""
    # `uri`, not `iri` — the scan does `obj.properties["uri"]` unguarded, so a fixture spelling it
    # `iri` raises KeyError, which this engine converts to a 503 SUBSTRATE FAILURE. The arm then
    # reds for a reason that has nothing to do with the filter it was written to measure.
    return _FakeObject(
        {
            "uri": "http://invincible-agent/mesh#DocPage",
            "label": "DocPage",
            "definition": "A reviewed page of prose.",
            "domain": "MESH",
        },
        score=0.71,
    )


def _filters_of(client):
    """The filter object the production call actually passed, read off the double."""
    coll = client.collections.get("OntologyClass")
    assert coll.query.last_call is not None, (
        "the scan never reached the collection — this arm measured nothing. Check the "
        "`exists()` and `_WEAVIATE_CLIENT` guards before trusting a filter assertion."
    )
    return coll.query.last_call["filters"]


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The rule, at the function that owns it
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_scope_function_APPENDS_MESH_for_a_single_domain_caller(ontology_main):
    """The rule at its own site, and it is the REAL function — not a mirror of it.

    `cold_start_fallback_domains`' docstring records what a mirror cost: with the widening
    inlined in the handler and mirrored in the test, disabling the MESH append left the seal
    GREEN (mutant B, measured 2026-09-26). `class_scan_scope_domains` exists for the same reason.
    """
    assert ontology_main.class_scan_scope_domains(["DOCS"], None) == ["DOCS", "MESH"]
    assert ontology_main.class_scan_scope_domains(None, "DOCS") == ["DOCS", "MESH"]
    assert ontology_main.class_scan_scope_domains(["docs"], None) == ["DOCS", "MESH"]


def test_a_caller_ALREADY_naming_MESH_does_not_get_it_twice(ontology_main):
    """A duplicate would widen nothing and break no behaviour, which is why it needs saying
    once: `contains_any(["MESH", "MESH"])` is a filter nobody would read twice, and the day a
    reader counts the domains to decide whether the append fired, the duplicate answers wrong."""
    got = ontology_main.class_scan_scope_domains(["MESH", "DOCS"], None)
    assert got.count("MESH") == 1, got
    assert set(got) == {"MESH", "DOCS"}, got


def test_AN_UNSCOPED_CALLER_STAYS_UNSCOPED(ontology_main):
    """⛔ THE ARM THAT STOPS THE FIX BECOMING A REGRESSION, and the reason the rule could not
    simply be `cold_start_fallback_domains(domains, domain)` passed straight through.

    That function returns `["MESH"]` for an unscoped caller — correct for the SPARQL fallback,
    where a graph scope is mandatory. Here an empty scope means `filters = None`, i.e. read the
    WHOLE index; handing it `["MESH"]` would NARROW a whole-index read to MESH alone. A caller
    who scoped to nothing is asking for everything, and MESH is already inside everything.
    """
    assert ontology_main.class_scan_scope_domains(None, None) == []
    assert ontology_main.class_scan_scope_domains([], None) == []
    assert ontology_main.class_scan_scope_domains([""], None) == [], (
        "a list of empty strings is an unscoped caller too — it must not become ['MESH']"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The rule where it reaches Weaviate — the REQUEST, not the rows
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_a_DOCS_caller_scans_DOCS_AND_MESH_on_the_wire(ontology_main, monkeypatch):
    """The whole point: a primed MESH class is REACHABLE for a DOCS caller.

    Compared against a filter built the same way production builds it, so the assertion covers
    the property name and the operator and not only the domain set. `contains_any` over two
    domains, never `equal` over one — an `equal("DOCS")` that happened to be spelled with MESH
    in a comment would pass a set-only check.
    """
    client = _FakeClient([_a_class_row()])
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", client)

    rows = ontology_main._weaviate_hybrid_search_sync("what is an archetype", domains=["DOCS"])

    want = _want_filter(ontology_main, ["DOCS", "MESH"])
    assert _filters_of(client) == want, (
        f"the DOCS caller's scan filtered on {_filters_of(client)!r}, not {want!r}. A filter "
        f"that cannot span MESH cannot return mesh:DocPage — mesh:explain's registered subject "
        f"— however completely DOCS is indexed."
    )
    assert rows, "the scripted MESH row did not come back; the arm measured the wrong path"


def test_AN_UNSCOPED_CALLER_SENDS_NO_FILTER_AT_ALL(ontology_main, monkeypatch):
    """THE CONTROL, and it differs from its subject in EXACTLY ONE THING: whether the caller
    scoped. Same double, same collection, same query text, same gate — only `domains` changes.

    It must be a control on the FILTER and not on the row count, because the double returns the
    scripted row either way: a row-count control would pass with the filter narrowed to MESH,
    which is the precise regression `test_AN_UNSCOPED_CALLER_STAYS_UNSCOPED` refuses upstream.
    """
    client = _FakeClient([_a_class_row()])
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", client)

    ontology_main._weaviate_hybrid_search_sync("what is an archetype")

    assert _filters_of(client) is None, (
        f"an unscoped caller was given the filter {_filters_of(client)!r}. Empty in, empty out: "
        f"anything else means a whole-index read has been silently narrowed."
    )


def test_THE_MESH_APPEND_IS_NOT_THE_PREDICATE_SEARCHS_RULE(ontology_main):
    """WHY THE CLASS HAS ONE MEMBER, recorded so the next reader does not have to re-derive it.

    A defence belongs to the class, not the instance that bit you — so: the other Weaviate
    hybrid/bm25 site in this engine, `_predicate_hybrid_search_sync`, is NOT missing this fix.
    It searches the **Predicate** collection, not OntologyClass, and its filter already carries
    an escape arm for platform rows (`Filter.by_property("domains", length=True).equal(0)` —
    domain-agnostic predicates). Appending MESH there would widen nothing and would claim a
    `domains == ["MESH"]` predicate exists, which none does.

    This arm asserts that escape arm is still present, because the exemption above is only true
    while it is. Remove it and the predicate search acquires exactly this defect, silently.
    """
    import inspect
    src = inspect.getsource(ontology_main._predicate_hybrid_search_sync)
    assert 'length=True' in src and '.equal(0)' in src, (
        "the predicate search's domain-agnostic escape arm is gone. The exemption recorded in "
        "this arm's docstring depended on it, so that search now needs the MESH append or an "
        "equivalent arm — decide which, and correct the docstring either way."
    )
