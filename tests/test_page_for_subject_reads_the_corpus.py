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
    pages = page_for_subject("mesh:seedCanvas", run=run, graph=DOCS_GRAPH)
    assert pages, "a relationship-typed explains target returned nothing"
    assert any("canvas" in p["iri"].lower() for p in pages)


def test_all_seven_fields_come_back(run):
    page = page_for_subject("mesh:seedCanvas", run=run, graph=DOCS_GRAPH)[0]
    for field in ("iri", "title", "doc_kind", "audience_hint", "source", "body_sha", "explains"):
        assert field in page, f"{field} missing from the row"
    assert page["body_sha"] and page["body_sha"] in page["source"], (
        "source is keyed by body_sha in this corpus; if that stops being true the renderer's "
        "sha assertion is reading a path that cannot confirm it"
    )


def test_explains_carries_the_PAGE_S_FULL_CLAIM_not_the_matched_target(run):
    """The second `mesh:explains` pattern earns its place here or it is a duplicate."""
    page = page_for_subject("mesh:seedCanvas", run=run, graph=DOCS_GRAPH)[0]
    assert len(page["explains"]) >= 2, page["explains"]
    assert any("seedCanvas" in e for e in page["explains"])


def test_the_subject_may_arrive_as_a_CURIE_an_IRI_or_a_BARE_NAME(run):
    """`subject` is the RAW SLOT VALUE — the verb is polymorphic, so the slot declares no referent.
    All three spellings name the same target and must find the same page."""
    got = [
        {p["iri"] for p in page_for_subject(s, run=run, graph=DOCS_GRAPH)}
        for s in ("mesh:seedCanvas", "http://invincible-agent/mesh#seedCanvas", "seedCanvas")
    ]
    assert got[0] == got[1] == got[2] and got[0], got


def test_an_unresolvable_subject_is_EMPTY_and_does_not_raise(run):
    """A gap in the writing, not a failure of the question — and the corpus's normal state.
    engine-docs turns this into an abstain naming the subject; a raise would be a 500."""
    assert page_for_subject("mesh:nothingExplainsThisYet", run=run, graph=DOCS_GRAPH) == []
    assert page_for_subject("", run=run, graph=DOCS_GRAPH) == []


def test_an_EMPTY_CORPUS_is_also_empty_and_not_an_error():
    """THE CONTROL that keeps the arm above from being satisfied by a query that never matches."""
    empty = rdflib.Dataset()
    assert page_for_subject("mesh:seedCanvas", run=lambda q: list(empty.query(q)), graph=DOCS_GRAPH) == []


# ── ordering: ruled, and unwitnessed ────────────────────────────────────────────────────────


_PAGES = [
    {"iri": "docs:a", "audience_hint": "ARCHITECT"},
    {"iri": "docs:b", "audience_hint": "DATA_ENGINEER"},
    {"iri": "docs:c", "audience_hint": "ARCHITECT"},
]


def test_RECENCY_orders_most_recent_first():
    """THE SECOND KEY, LIVE SINCE 5f's `98aef67`. This arm replaced one that asserted the stamp's
    ABSENCE — the tripwire fired exactly as designed and named what to implement."""
    pages = [
        {"iri": "docs:old", "source_committed_at": "2026-09-12T22:04:37-05:00"},
        {"iri": "docs:new", "source_committed_at": "2026-09-15T08:32:52-05:00"},
        {"iri": "docs:mid", "source_committed_at": "2026-09-12T22:50:06-05:00"},
    ]
    assert [p["iri"] for p in order_pages(pages)] == ["docs:new", "docs:mid", "docs:old"]


def test_an_UNSTAMPED_page_sorts_LAST_and_is_not_dated_here():
    """5f's generator REFUSES an uncommitted page rather than substituting mtime or `now`, because
    a fabricated timestamp would then order the corpus. A page without one comes from a corpus
    generated before the stamp existed — it ties, it is not invented a date."""
    pages = [
        {"iri": "docs:none"},
        {"iri": "docs:stamped", "source_committed_at": "2026-09-12T22:04:37-05:00"},
    ]
    assert [p["iri"] for p in order_pages(pages)] == ["docs:stamped", "docs:none"]


def test_AUDIENCE_outranks_recency_because_the_rule_says_audience_FIRST():
    """The keys are ordered, not blended. An older page for the right audience beats a newer one
    for the wrong audience — that is what "audience match first, then most recent body" means."""
    pages = [
        {"iri": "docs:new-wrong", "audience_hint": "ARCHITECT",
         "source_committed_at": "2026-09-15T08:32:52-05:00"},
        {"iri": "docs:old-right", "audience_hint": "DATA_ENGINEER",
         "source_committed_at": "2026-09-12T22:04:37-05:00"},
    ]
    out = [p["iri"] for p in order_pages(pages, audience="data_engineer")]
    assert out == ["docs:old-right", "docs:new-wrong"], out


def test_EQUAL_ON_BOTH_KEYS_STAYS_A_TIE():
    """THE CONTROL AGAINST MANUFACTURING A WINNER. Anything level after both keys is rendered as a
    list by the consumer; ordering by insertion, IRI or sha here would reintroduce the `rows[0]`
    defect `8a424d6` removed."""
    pages = [
        {"iri": "docs:b", "audience_hint": "A", "source_committed_at": "2026-09-12T22:04:37-05:00"},
        {"iri": "docs:a", "audience_hint": "A", "source_committed_at": "2026-09-12T22:04:37-05:00"},
    ]
    assert [p["iri"] for p in order_pages(pages)] == ["docs:b", "docs:a"]


def test_the_QUERY_SELECTS_the_stamp_whether_or_not_this_corpus_carries_it():
    """THE ARM THAT REPLACED THE ABSENCE PIN, and it holds in both worlds.

    The stamp is live on `lane/5f` and has not reached master, so THIS tree's corpus has none —
    which would make an assertion about corpus content green for the wrong reason. What must be
    true regardless is that the query ASKS for it, optionally, so the day the corpus merges the
    ordering works without another change here.
    """
    q = build_page_for_subject_query("mesh:seedCanvas")
    assert "mesh:source_committed_at ?committed" in q
    assert "OPTIONAL" in q, "the stamp must be optional or a corpus without it returns nothing"


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


def test_the_builder_EMITS_NO_GRAPH_CLAUSE_BY_DEFAULT():
    """THE FLEET PATH IS THE EXECUTOR PATH, and the default has to suit it rather than this file.

    `execute_sparql` wraps every query in its own `VALUES ?__mesh_g ... GRAPH ?__mesh_g { ... }`
    by brace surgery on the text. A builder emitting its own GRAPH clause hands that wrapper a
    nested scope it never expected — and the route would have been the ONLY caller taking that
    path, so a test written against this file's explicit-graph usage would have stayed green over
    it. That is the instrument and the subject diverging, so it is asserted directly.
    """
    assert "GRAPH <" not in build_page_for_subject_query("mesh:seedCanvas")
    assert "GRAPH <" in build_page_for_subject_query("mesh:seedCanvas", graph=DOCS_GRAPH)


def test_both_forms_parse():
    from rdflib.plugins.sparql import prepareQuery

    prepareQuery(build_page_for_subject_query("mesh:seedCanvas"))
    prepareQuery(build_page_for_subject_query("mesh:seedCanvas", graph=DOCS_GRAPH))


def test_NO_SUBJECT_YET_RESOLVES_TO_TWO_PAGES_so_ordering_has_no_live_case(run):
    """THE ORDERING RULE IS IMPLEMENTED AND UNEXERCISED BY REAL DATA, and that is worth an arm
    rather than a sentence.

    Measured against the corpus: 14 distinct `mesh:explains` targets, **none on more than one
    page**. So every real call returns zero or one page, `order_pages` never chooses, and both
    ruled keys — audience and recency — are exercised only by the unit fixtures above.

    **This reds the day a second page explains an existing target**, which is the day the ordering
    stops being theoretical and starts deciding what a person reads first. That is when someone
    should look at it on purpose, rather than discovering it decided something.
    """
    targets: dict[str, set] = {}
    text = _CORPUS.read_text(encoding="utf-8")
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("docs:") and " a mesh:DocPage" in stripped:
            current = stripped.split()[0]
        elif current and "mesh:explains" in stripped:
            for tok in stripped.replace("mesh:explains", "").replace(";", "").replace(".", "").split(","):
                tok = tok.strip()
                if tok:
                    targets.setdefault(tok, set()).add(current)
        elif current and stripped.endswith(".") and "mesh:explains" not in stripped:
            pass
    shared = {t: pages for t, pages in targets.items() if len(pages) > 1}
    assert not shared, (
        f"a target now explains more than one page: {shared}. `order_pages` is now DECIDING what "
        f"a reader sees first — audience match, then most recent commit, ties rendered as a list. "
        f"Check it against the real pair rather than the unit fixtures, and replace this arm with "
        f"one that asserts the chosen order."
    )
