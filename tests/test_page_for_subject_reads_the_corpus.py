"""`page_for_subject` against THE REAL CORPUS, not a fixture of one.

`setup/ontologies/docs_corpus.ttl` is the artifact the prime loads into `internal/DOCS`, and rdflib
can hold it, so these run the actual query against the actual triples. **A fixture built from my
own reading of the corpus would agree with my reading** — the shape this lane has been finding all
week — and the corpus is right there.

WHAT THE SEVENTH ASSERTION IS FOR, and it is the one worth reading: `mesh:seedCanvas` is one of the
FOUR targets f3 measured as RELATIONSHIP TYPES in Neo4j. A Neo4j probe asking only the class
question reports it absent with total confidence. This reader finds it, because a triple match does
not care what shape the target takes in a different store — which is why there is no both-shapes
branch here and why that absence is asserted rather than assumed.

Run: uv run --frozen pytest tests/test_page_for_subject_reads_the_corpus.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

rdflib = pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

from agent_fleet.ontology_service.doc_pages import (  # noqa: E402
    DOCS_GRAPH,
    build_page_for_subject_query,
    order_pages,
    page_for_subject,
    rows_to_pages,
)

_CORPUS = _REPO / "setup" / "ontologies" / "docs_corpus.ttl"


@pytest.fixture(scope="module")
def run():
    """An executor over the real corpus, in the named graph the prime loads it into."""
    assert _CORPUS.exists(), f"the corpus is the subject of this file and is missing: {_CORPUS}"
    store = rdflib.Dataset()
    store.get_context(rdflib.URIRef(DOCS_GRAPH)).parse(str(_CORPUS), format="turtle")

    def _run(query: str):
        return [
            {str(v): str(row[v]) for v in row.labels if row[v] is not None}
            for row in store.query(query)
        ]

    return _run


def test_a_relationship_typed_target_is_FOUND(run):
    """THE ASSERTION THAT REPLACES A BOTH-SHAPES BRANCH.

    `mesh:seedCanvas` is one of the four targets f3 measured as a RELATIONSHIP TYPE in Neo4j — the
    half a class-only probe reports absent as a clean finding. Here it resolves, because this read
    matches triples. If this ever fails, the store assumption in the module docstring is wrong and
    the operation has moved.
    """
    pages = page_for_subject("mesh:seedCanvas", run=run)
    assert pages, "a relationship-typed explains target returned nothing"
    assert any("canvas" in p["iri"].lower() for p in pages)


def test_all_seven_fields_come_back(run):
    page = page_for_subject("mesh:seedCanvas", run=run)[0]
    for field in ("iri", "title", "doc_kind", "audience_hint", "source", "body_sha", "explains"):
        assert field in page, f"{field} missing from the row"
    assert page["body_sha"] and page["body_sha"] in page["source"], (
        "source is keyed by body_sha in this corpus; if that stops being true the renderer's "
        "sha assertion is reading a path that cannot confirm it"
    )


def test_explains_carries_the_PAGE_S_FULL_CLAIM_not_the_matched_target(run):
    """The second `mesh:explains` pattern earns its place here or it is a duplicate."""
    page = page_for_subject("mesh:seedCanvas", run=run)[0]
    assert len(page["explains"]) >= 2, page["explains"]
    assert any("seedCanvas" in e for e in page["explains"])


def test_the_subject_may_arrive_as_a_CURIE_an_IRI_or_a_BARE_NAME(run):
    """`subject` is the RAW SLOT VALUE — the verb is polymorphic, so the slot declares no referent.
    All three spellings name the same target and must find the same page."""
    got = [
        {p["iri"] for p in page_for_subject(s, run=run)}
        for s in ("mesh:seedCanvas", "http://invincible-agent/mesh#seedCanvas", "seedCanvas")
    ]
    assert got[0] == got[1] == got[2] and got[0], got


def test_an_unresolvable_subject_is_EMPTY_and_does_not_raise(run):
    """A gap in the writing, not a failure of the question — and the corpus's normal state.
    engine-docs turns this into an abstain naming the subject; a raise would be a 500."""
    assert page_for_subject("mesh:nothingExplainsThisYet", run=run) == []
    assert page_for_subject("", run=run) == []


def test_an_EMPTY_CORPUS_is_also_empty_and_not_an_error():
    """THE CONTROL that keeps the arm above from being satisfied by a query that never matches."""
    empty = rdflib.Dataset()
    assert page_for_subject("mesh:seedCanvas", run=lambda q: list(empty.query(q))) == []


# ── ordering: ruled, and unwitnessed ────────────────────────────────────────────────────────


_PAGES = [
    {"iri": "docs:a", "audience_hint": "ARCHITECT"},
    {"iri": "docs:b", "audience_hint": "DATA_ENGINEER"},
    {"iri": "docs:c", "audience_hint": "ARCHITECT"},
]


def test_without_an_audience_the_order_is_a_STABLE_IDENTITY():
    """Neither ruled key exists yet: no audience reaches the operation, and the corpus carries no
    timestamp. **Ordering by something arbitrary would manufacture a winner** — the defect f3
    removed when they replaced `rows[0]` with rendering every surviving row."""
    assert [p["iri"] for p in order_pages(_PAGES)] == ["docs:a", "docs:b", "docs:c"]


def test_with_an_audience_the_MATCHES_COME_FIRST_and_ties_keep_their_order():
    out = [p["iri"] for p in order_pages(_PAGES, audience="data_engineer")]
    assert out[0] == "docs:b", out
    assert out[1:] == ["docs:a", "docs:c"], "a stable sort keeps the tie's order rather than picking"


def test_the_corpus_carries_NO_TIMESTAMP_which_is_why_recency_is_unwitnessed():
    """THE MISSING INPUT, ASSERTED RATHER THAN DESCRIBED. When 5f stamps
    `mesh:source_committed_at`, this goes red — at the failure line, naming what to implement —
    instead of the ordering rule quietly staying half-applied for another month."""
    text = _CORPUS.read_text(encoding="utf-8")
    assert "source_committed_at" not in text, (
        "the corpus now carries a commit timestamp — order_pages can implement the ruled second "
        "key (most recent body) and this assertion should be replaced by one that exercises it"
    )


def test_rows_to_pages_groups_the_cross_product():
    rows = [
        {"iri": "docs:a", "title": "A", "ex": "mesh:x"},
        {"iri": "docs:a", "title": "A", "ex": "mesh:y"},
        {"iri": "docs:b", "title": "B", "ex": "mesh:x"},
    ]
    pages = {p["iri"]: p for p in rows_to_pages(rows)}
    assert pages["docs:a"]["explains"] == ("mesh:x", "mesh:y")
    assert pages["docs:b"]["explains"] == ("mesh:x",)


def test_the_query_parses_for_every_slot_shape():
    """The brace-bug lesson: a SPARQL template is parse-validated before it meets Fuseki."""
    from rdflib.plugins.sparql import prepareQuery

    for subject in ("mesh:seedCanvas", "http://x/y#z", "bare", 'quote"inside'):
        prepareQuery(build_page_for_subject_query(subject))
