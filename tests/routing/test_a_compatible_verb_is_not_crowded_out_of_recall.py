"""A COMPATIBLE VERB IS NOT CROWDED OUT OF RECALL BY ANOTHER VERB'S ROW COUNT.

MEASURED 2026-09-30 on revision 159, read-only, each fire x3:

- "how do I add a canvas template" (DATA_ENGINEER, DOCS) resolved `mesh:DocPage`, instance
  `docs#runbook-adding-a-canvas-template`. Neo4j named `mesh:explain` (and the stale full-IRI
  spelling) compatible. `/classify_predicate` answered UNKNOWN 0.0 with `classify_called=False`,
  through the conjunctive-read branch, so the LLM never saw the question.
- The Predicate rows a DOCS caller's filter admits: 36. Thirty-five are domain-agnostic
  `mesh:rendersAs` rows (33 distinct inputs), and one is `mesh:explain`.
- The recall limit was 25 ROWS, and the intersection with the compat set ran AFTER it. At limit 25
  the window was 25 rendersAs rows. At 50, explain arrived at rank 2 and the LLM picked it.
- "how do I add an engine" ranks explain FIRST, which is why that row passed. The outcome
  depended on a rival verb's row count and on the question's wording.

The population below mirrors that measurement, and the fake applies the filter and the limit
the way Weaviate does: rows in ranked order, the filter first, then the limit. `.equal` on the
WORD-tokenized `verb_iri` is token CONTAINMENT, as measured live (`equal("explain")` and
`equal("mesh")` both match).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_predicate_hybrid_search import _FakeObject, ontology_main  # noqa: E402,F401

EXPLAIN = "mesh:explain"
STALE_EXPLAIN = "http://invincible-agent/mesh#explain"
DOC_PAGE = "http://invincible-agent/mesh#DocPage"
CANVAS_Q = "how do I add a canvas template"


def _tokens(v) -> set[str]:
    return {t for t in re.split(r"[^0-9a-z]+", str(v).lower()) if t}


def _admits(props: dict, f) -> bool:
    """Interprets the stub harness's filter tuples with Weaviate's semantics."""
    if f is None:
        return True
    tag = f[0]
    if tag == "any_of":
        return any(_admits(props, g) for g in f[1])
    if tag == "all_of":
        return all(_admits(props, g) for g in f[1])
    if tag == "contains_any":
        return bool(set(props.get(f[1]) or []) & set(f[2]))
    if tag == "equal" and f[1] == "domains":  # the stub drops `length=True`; 0 means "empty"
        assert f[2] == 0, f
        return len(props.get("domains") or []) == 0
    if tag == "equal":  # WORD tokenization: the row's tokens CONTAIN the value's
        return _tokens(f[2]) <= _tokens(props.get(f[1]) or "")
    raise AssertionError(f"filter shape this fake does not know: {f!r}")


class _Query:
    def __init__(self, ranked):
        self._ranked = ranked
        self.calls: list[dict] = []

    def _run(self, mode, limit, filters):
        self.calls.append({"mode": mode, "limit": limit, "filters": filters})
        objects = [o for o in self._ranked if _admits(o.properties, filters)][:limit]
        return type("Resp", (), {"objects": objects})()

    def hybrid(self, query, limit, filters, return_metadata, vector=None):
        return self._run("hybrid", limit, filters)

    def bm25(self, query, limit, filters, return_metadata):
        return self._run("bm25", limit, filters)


class _Client:
    def __init__(self, ranked):
        self.query = _Query(ranked)
        coll = type("C", (), {"query": self.query})()
        self.collections = type("Cs", (), {
            "exists": staticmethod(lambda name: True),
            "get": staticmethod(lambda name: coll),
        })()


def _row(verb, input_uri, domains, score):
    return _FakeObject(properties={
        "verb_iri": verb, "verb_local": verb.rsplit(":", 1)[-1],
        "input_uri": input_uri, "output_uri": "", "endpoint_url": "http://x",
        "owner_persona": "", "domains": domains, "cost_class": "fast",
        "requires_human_approval": False, "description": f"{verb} on {input_uri}",
    }, score=score)


def _live_population():
    """Ranked as the vector half ranked the canvas question: two scoped rows the DOCS filter
    must drop, then 35 domain-agnostic rendersAs rows, then the one explain row."""
    rows = [_row("mesh:costLotBreakdown", "cost:Lot", ["PRODUCTION_COST"], 0.99),
            _row("mesh:canvasForCost", "cost:Lot", ["PRODUCTION_COST"], 0.98)]
    rows += [_row("mesh:rendersAs", f"http://invincible-agent/mesh#Archetype{i}", [], 0.7 - i / 1000)
             for i in range(35)]
    rows.append(_row(EXPLAIN, DOC_PAGE, [], 0.3))
    return rows


@pytest.fixture
def client(ontology_main, monkeypatch):
    c = _Client(_live_population())
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", c)
    monkeypatch.setattr(ontology_main, "embed_query", lambda text, *a, **k: [0.0])
    return c


def _verbs(hits):
    return [h["verb_iri"] for h in hits]


# --------------------------------------------------------------------------------------------
# The recall
# --------------------------------------------------------------------------------------------
def test_CONTROL_the_fake_reproduces_the_MEASURED_window(ontology_main, client):
    """Without the compat set, the window at 25 is exactly what rev 159 served: 25 rendersAs
    rows and no explain. Only the compat set differs between this arm and the next."""
    hits = ontology_main._predicate_hybrid_search_sync(CANVAS_Q, ["DOCS"], 25)
    assert _verbs(hits) == ["mesh:rendersAs"] * 25


def test_the_compat_set_is_applied_BEFORE_the_limit(ontology_main, client):
    hits = ontology_main._predicate_hybrid_search_sync(
        CANVAS_Q, ["DOCS"], 25, verb_iris=[STALE_EXPLAIN, EXPLAIN])
    assert EXPLAIN in _verbs(hits), (
        "a verb Neo4j called compatible was crowded out of recall by rows of a verb it did not "
        "call compatible: the compat set is being applied after the limit again"
    )


def test_a_compatible_verb_with_MORE_ROWS_than_the_window_does_not_truncate_its_neighbour(
        ontology_main, client):
    """rendersAs is compatible here too, and holds 35 admitted rows, more than the 25 the caller
    asked for. Filtering alone would leave the same crowding inside the compat set: the limit
    has to be a ceiling once the graph has bounded the set."""
    hits = ontology_main._predicate_hybrid_search_sync(
        CANVAS_Q, ["DOCS"], 25, verb_iris=["mesh:rendersAs", EXPLAIN])
    assert EXPLAIN in _verbs(hits)
    assert _verbs(hits).count("mesh:rendersAs") == 35
    assert client.query.calls[-1]["limit"] == ontology_main._COMPAT_RECALL_CEILING


def test_the_compat_filter_KEEPS_the_domain_scope(ontology_main, client):
    """The compat filter is AND-ed with the caller's domain filter, never substituted for it.
    A compatible verb registered only in a domain the caller lacks stays out."""
    hits = ontology_main._predicate_hybrid_search_sync(
        CANVAS_Q, ["DOCS"], 25, verb_iris=["mesh:canvasForCost", EXPLAIN])
    assert _verbs(hits) == [EXPLAIN]
    f = client.query.calls[-1]["filters"]
    assert f[0] == "all_of" and f[1][0][0] == "any_of", f


def test_an_UNCONSTRAINED_caller_is_unchanged(ontology_main, client):
    """No compat set: the domain filter alone, and the caller's own limit."""
    ontology_main._predicate_hybrid_search_sync(CANVAS_Q, ["DOCS"], 25)
    call = client.query.calls[-1]
    assert call["limit"] == 25
    assert call["filters"][0] == "any_of"
    assert ("contains_any", "domains", ["DOCS"]) in call["filters"][1]


# --------------------------------------------------------------------------------------------
# The endpoint: the question reaches the LLM, and only exact compat verbs are offered
# --------------------------------------------------------------------------------------------
class _Enum:
    """Records the dynamic enum the endpoint builds for the LLM."""

    def __init__(self):
        self.values: dict[str, str] = {}
        values = self.values

        class _V:
            def __init__(self, iri):
                self.iri = iri

            def description(self, text):
                values[self.iri] = text
                return self

        class _P:
            def add_value(self, iri):
                values[iri] = ""
                return _V(iri)

        self.Predicate = _P()


class _BAML:
    def __init__(self, pick):
        self.pick = pick
        self.offered: list[list[str]] = []

    async def ClassifyPredicate(self, **kw):
        self.offered.append(list(kw["baml_options"]["tb"].values))
        return type("R", (), {"resolved_verb_iri": self.pick, "confidence_score": 0.9,
                              "reasoning": "stub"})()


@pytest.fixture
def endpoint(ontology_main, client, monkeypatch):
    baml = _BAML(EXPLAIN)
    monkeypatch.setattr(ontology_main, "b", baml)
    monkeypatch.setattr(ontology_main, "TypeBuilder", _Enum)

    async def _chain(subject_uri, max_hops=5):
        return ontology_main.MeshResult.answered([{"uri": DOC_PAGE, "label": "Doc Page", "hops": 0}])
    monkeypatch.setattr(ontology_main, "_get_subject_ancestor_chain", _chain)
    return baml


def _request(ontology_main, compatible):
    return ontology_main.ClassifyPredicateRequest(
        query=CANVAS_Q, subject_uri=DOC_PAGE, subject_reasoning="", entitled_domains=["DOCS"],
        domain="DOCS", compatible_verb_iris=compatible)


@pytest.mark.asyncio
async def test_the_CANVAS_question_REACHES_the_LLM_and_is_offered_explain(ontology_main, endpoint):
    resp = await ontology_main.classify_predicate(_request(ontology_main, [EXPLAIN, STALE_EXPLAIN]))
    assert endpoint.offered, f"the LLM was never called: {resp.reasoning}"
    assert sorted(endpoint.offered[0]) == sorted([EXPLAIN, "UNKNOWN"])
    assert resp.resolved_verb_iri == EXPLAIN


@pytest.mark.asyncio
async def test_a_TOKEN_MATCH_the_filter_over_admits_is_NOT_offered(ontology_main, client, endpoint):
    """`equal("mesh:explain")` also admits a row spelled with extra tokens around the same
    words. The exact intersection after the query is what keeps it out of the enum."""
    legacy = "urn:mesh:explain:legacy"
    client.query._ranked.insert(0, _row(legacy, DOC_PAGE, [], 0.95))
    await ontology_main.classify_predicate(_request(ontology_main, [EXPLAIN]))
    assert endpoint.offered and legacy not in endpoint.offered[0]
    admitted = [o.properties["verb_iri"] for o in client.query._ranked
                if _admits(o.properties, client.query.calls[-1]["filters"])]
    assert legacy in admitted, (
        "the fake no longer over-admits, so this arm no longer tests the exact intersection"
    )


@pytest.mark.asyncio
async def test_an_EMPTY_intersection_now_means_ABSENCE_and_says_so(ontology_main, client, endpoint):
    client.query._ranked[:] = [o for o in client.query._ranked
                               if o.properties["verb_iri"] != EXPLAIN]
    resp = await ontology_main.classify_predicate(_request(ontology_main, [EXPLAIN]))
    assert resp.resolved_verb_iri == "UNKNOWN" and not endpoint.offered
    assert "absence, not ranking" in resp.reasoning
