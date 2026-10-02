"""The DOCS subject pool: a DOCS question's subject is a DocPage, and it binds.

THE DISPATCH'S SEAL: "how do I add an engine" and "how do I add a canvas template" bind to their
pages as subjects and reach `mesh:explain`. Both census rows died at SUBJECT BINDING, before any
page lookup: no OntologyClass is labelled engine or canvas template, and `mesh:explain`'s `subject`
declares the universal referent `mesh:Thing`, so `/fill_slots` refused every class the fan-out
found as `wrong_class`.

EVERYTHING HERE RUNS OVER THE REAL CORPUS. `setup/ontologies/docs_corpus.ttl` is loaded into
`http://internal/DOCS`, the graph the prime writes, and the route arms drive engine-o's REAL
`execute_sparql` through a Jena stand-in that executes the query the executor actually posts,
graph wrapper and all. A stub returning rows I wrote would agree with my reading of the corpus.

THE CONTROL IS THE GRAPH PAGE ("Runbook — adding a graph to engine-lg"). Its label says engine
too, so a keyword hit ties it with the engine page; `test_the_rival_is_real` asserts that, so the
engine arm is a discrimination and not a lookup.

Run: uv run --frozen pytest tests/docs/test_the_docs_subject_pool_binds_the_page.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

rdflib = pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

from agent_fleet.ontology_service.doc_pages import (  # noqa: E402
    DOCPAGE_CLASS,
    DOCS_GRAPH,
    DOCS_NS,
    _page_tokens,
    _stem,
    build_all_pages_query,
    match_pages,
    page_for_subject,
    rows_to_pages,
)

_CORPUS = _REPO / "setup" / "ontologies" / "docs_corpus.ttl"

ENGINE_Q = "how do I add an engine"
CANVAS_Q = "how do I add a canvas template"
ENGINE_PAGE = DOCS_NS + "runbook-adding-an-engine"
CANVAS_PAGE = DOCS_NS + "runbook-adding-a-canvas-template"
GRAPH_PAGE = DOCS_NS + "runbook-adding-a-graph"
ROLLING_PAGE = DOCS_NS + "runbook-rolling-a-service"
MESH_THING = "http://invincible-agent/mesh#Thing"


@pytest.fixture(scope="module")
def store():
    assert _CORPUS.exists(), f"the corpus is the subject of this file and is missing: {_CORPUS}"
    ds = rdflib.Dataset()
    ds.get_context(rdflib.URIRef(DOCS_GRAPH)).parse(str(_CORPUS), format="turtle")
    return ds


def _rows(ds, query: str) -> list[dict]:
    return [
        {str(v): str(row[v]) for v in row.labels if row[v] is not None}
        for row in ds.query(query)
    ]


@pytest.fixture(scope="module")
def pages(store):
    return rows_to_pages(_rows(store, build_all_pages_query(graph=DOCS_GRAPH)))


# ── THE MATCHER, over the real pool ──────────────────────────────────────────────────────────

def test_the_pool_is_every_page_in_the_corpus(pages):
    """Nine pages, and the engine, canvas and graph pages among them, or every arm below is vacuous."""
    iris = {p["iri"] for p in pages}
    assert len(iris) == 9, sorted(iris)
    assert {ENGINE_PAGE, CANVAS_PAGE, GRAPH_PAGE} <= iris


def test_the_engine_question_binds_the_engine_page(pages):
    m = match_pages(ENGINE_Q, pages)
    assert m["page"] is not None and m["page"]["iri"] == ENGINE_PAGE, m


def test_the_canvas_question_binds_the_canvas_page(pages):
    m = match_pages(CANVAS_Q, pages)
    assert m["page"] is not None and m["page"]["iri"] == CANVAS_PAGE, m


def test_the_rival_is_real(pages):
    """A SEAL THAT DEFENDS A CHOICE must show its fixture tells the rules apart. The graph page
    carries every token the engine question does, so a keyword rule ties the two; the engine arm
    passes only because the scorer weighs the whole claim. Its runner-up must BE the graph page."""
    q = {_stem("add"), _stem("engine")}
    graph = next(p for p in pages if p["iri"] == GRAPH_PAGE)
    assert q <= _page_tokens(graph), "the control no longer contains the question; find a new rival"
    m = match_pages(ENGINE_Q, pages)
    assert m["candidates"][1]["instance_id"] == GRAPH_PAGE, m["candidates"][:3]
    assert m["runner_up"] > 0.0


def test_the_graph_question_binds_the_graph_page(pages):
    """The control binds too: the engine page's rival is a page a question CAN reach."""
    m = match_pages("how do I add a graph", pages)
    assert m["page"] is not None and m["page"]["iri"] == GRAPH_PAGE, m


def test_the_stemmer_maps_the_question_and_the_title_to_one_form():
    """"add" (spoken) and "adding" (every title) must meet, or every page loses its verb."""
    assert _stem("add") == _stem("adding")
    assert _stem("template") == _stem("templates")
    assert _stem("canvas") == _stem("canvases")


@pytest.mark.parametrize(
    "question, why",
    [
        ("how do I add something", "six adding-* pages alike: a near-tie is an ask, not a pick"),
        ("runbook", "every page is a runbook"),
        ("what is the status of HAZ-1003", "covers nothing any page says"),
        # THE COVERAGE FLOOR'S OWN CASE. The line above scores zero everywhere and is refused
        # before any gate runs; this one scores on exactly one page (no runner-up, so the margin
        # passes) and is refused only because one docs word is a small part of the question.
        ("the canvas on hazard HAZ-1003 for aircraft tail 12", "one docs word in a non-docs question"),
    ],
)
def test_a_question_no_page_wins_binds_nothing(pages, question, why):
    m = match_pages(question, pages)
    assert m["page"] is None, f"{question!r} bound {m['page'] and m['page']['iri']}: {why}"


def test_a_refused_near_tie_still_carries_its_menu(pages):
    m = match_pages("how do I add something", pages)
    assert m["page"] is None and len(m["candidates"]) >= 2
    assert all(c["class_uri"] == DOCPAGE_CLASS for c in m["candidates"])


# ── page_for_subject: a page is its own subject ─────────────────────────────────────────────

def _pfs(store, subject):
    return page_for_subject(subject, run=lambda q: _rows(store, q), graph=DOCS_GRAPH)


@pytest.mark.parametrize("page", [ENGINE_PAGE, CANVAS_PAGE, GRAPH_PAGE, ROLLING_PAGE])
def test_a_bound_page_iri_returns_that_page(store, page):
    got = _pfs(store, page)
    assert [p["iri"] for p in got] == [page]


def test_a_page_that_explains_nothing_is_still_served_by_its_iri(store, pages):
    """THE CASE THAT MADE `explains` OPTIONAL. The rolling page declares no `explains:`, so the
    old query, which required one, could never return it whatever the subject said."""
    rolling = next(p for p in pages if p["iri"] == ROLLING_PAGE)
    assert rolling["explains"] == (), "the control grew an explains: target; pick a page without one"
    got = _pfs(store, ROLLING_PAGE)
    assert [p["iri"] for p in got] == [ROLLING_PAGE] and got[0]["title"]


def test_the_page_arm_keeps_the_pages_full_claim(store):
    got = _pfs(store, ENGINE_PAGE)
    assert "http://invincible-agent/mesh#resolveInstance" in got[0]["explains"]


def test_a_local_name_does_not_select_a_page(store):
    """The page arm matches the FULL IRI only. A bare name equal to a page's local name is not
    that page, or any subject that happened to share a slug would be served its body."""
    assert _pfs(store, "runbook-adding-an-engine") == []


# ── engine-o, through the real executor ─────────────────────────────────────────────────────

def _eo():
    from agent_fleet.ontology_service import main as eo
    return eo


class _CorpusJena:
    """A Jena that runs the query engine-o POSTS against the corpus in its real named graph."""

    def __init__(self, ds, posted):
        self._ds, self._posted = ds, posted

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, headers=None):
        q = data["query"]
        self._posted.append(q)
        bindings = [{k: {"value": v} for k, v in row.items()} for row in _rows(self._ds, q)]
        return type("R", (), {
            "status_code": 200,
            "json": lambda self: {"results": {"bindings": bindings}},
        })()


@pytest.fixture
def eo(store, monkeypatch):
    mod = _eo()
    posted: list[str] = []
    monkeypatch.setattr(mod, "_JENA_ENDPOINT", "http://fuseki/ds/query", raising=False)
    monkeypatch.setattr(mod, "_jena_client", lambda: _CorpusJena(store, posted), raising=False)
    monkeypatch.setattr(mod, "_can_view_class", lambda email, iri: True)

    async def _answerable(uri, domains):
        return False

    monkeypatch.setattr(mod, "_preempted_subject_is_unanswerable", _answerable)

    async def _no_recall(**kw):
        raise AssertionError("class recall ran for a question the DOCS pool should have bound")

    async def _no_fanout(*a, **kw):
        raise AssertionError("the instance fan-out ran for a slot the DOCS pool should have bound")

    monkeypatch.setattr(mod, "weaviate_hybrid_search", _no_recall)
    monkeypatch.setattr(mod, "_resolve_instance", _no_fanout)
    mod._test_posted = posted
    return mod


def _resolve(eo, query, domains):
    return asyncio.run(eo.resolve(eo.ResolveRequest(query=query, domains=domains, user_email="u@x")))


@pytest.mark.parametrize("question, page", [(ENGINE_Q, ENGINE_PAGE), (CANVAS_Q, CANVAS_PAGE)])
def test_resolve_binds_a_DOCS_question_to_its_page(eo, question, page):
    r = _resolve(eo, question, ["DOCS"])
    assert r.resolved_uri == DOCPAGE_CLASS, r
    assert r.provenance["instance_id"] == page
    assert r.provenance["instance_resolved"] is True
    assert r.provenance["instance_class_uri"] == DOCPAGE_CLASS
    assert r.provenance["preemption_path"] == "docs_subject_pool"


def test_the_executor_scoped_the_pool_read_to_DOCS(eo):
    """The pool read went through the executor's graph wrapper, not around it."""
    _resolve(eo, ENGINE_Q, ["DOCS"])
    assert eo._test_posted, "nothing was posted: the pool was not read through the executor"
    assert all("<http://internal/DOCS>" in q and "GRAPH ?__mesh_g" in q for q in eo._test_posted)


def test_a_caller_outside_DOCS_never_reads_the_pool(eo):
    r = asyncio.run(eo._resolve_docs_subject(
        eo.ResolveRequest(query=ENGINE_Q, domains=["MAINTENANCE"], user_email="u@x")))
    assert r is None and eo._test_posted == []


def test_a_caller_who_cannot_see_DocPage_falls_through(eo, monkeypatch):
    monkeypatch.setattr(eo, "_can_view_class", lambda email, iri: iri != DOCPAGE_CLASS)
    r = asyncio.run(eo._resolve_docs_subject(
        eo.ResolveRequest(query=ENGINE_Q, domains=["DOCS"], user_email="u@x")))
    assert r is None


def test_a_DocPage_no_verb_serves_falls_through(eo, monkeypatch):
    async def _unanswerable(uri, domains):
        return uri == DOCPAGE_CLASS

    monkeypatch.setattr(eo, "_preempted_subject_is_unanswerable", _unanswerable)
    r = asyncio.run(eo._resolve_docs_subject(
        eo.ResolveRequest(query=ENGINE_Q, domains=["DOCS"], user_email="u@x")))
    assert r is None


def test_an_unreadable_pool_falls_through_and_does_not_raise(eo, monkeypatch):
    class _Down(_CorpusJena):
        async def post(self, *a, **k):
            raise ConnectionError("connect timeout")

    monkeypatch.setattr(eo, "_jena_client", lambda: _Down(None, []))
    monkeypatch.setattr(eo, "_get_local_graph", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    r = asyncio.run(eo._resolve_docs_subject(
        eo.ResolveRequest(query=ENGINE_Q, domains=["DOCS"], user_email="u@x")))
    assert r is None


def _explain_decls():
    from agent_fleet.docs_agent.slots import slots_for
    decls = slots_for("explain")
    subject = next(d for d in decls if d.get("name") == "subject")
    assert subject.get("referent") == MESH_THING, "the fixture assumes the universal referent"
    return decls


def _fill(eo, monkeypatch, query, slots_json, acting, subject_uri=""):
    class _Filled:
        slots_json = ""
        confidence = 0.9
        reasoning = "stub"

    filled = _Filled()
    filled.slots_json = slots_json

    async def _fake(**kw):
        return filled

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(query=query, verb_iri="mesh:explain",
                              declarations=json.dumps(_explain_decls()), acting_domains=acting,
                              subject_uri=subject_uri)
    return asyncio.run(eo.fill_slots(req))


@pytest.mark.parametrize(
    "question, spoken, page",
    [(ENGINE_Q, "an engine", ENGINE_PAGE), (CANVAS_Q, "canvas template", CANVAS_PAGE)],
)
def test_fill_slots_binds_the_spoken_subject_to_its_page(eo, monkeypatch, question, spoken, page):
    r = _fill(eo, monkeypatch, question, json.dumps({"subject": spoken}), ["DOCS"])
    assert r.slots == {"subject": page}, (r.slots, r.refused)
    assert r.resolution["subject"]["instance_id"] == page
    assert r.resolution["subject"]["bound_from"] == "spoken"


@pytest.mark.parametrize("question, page", [(ENGINE_Q, ENGINE_PAGE), (CANVAS_Q, CANVAS_PAGE)])
def test_fill_slots_binds_an_unspoken_subject_from_the_question(eo, monkeypatch, question, page):
    r = _fill(eo, monkeypatch, question, "{}", ["DOCS"])
    assert r.slots == {"subject": page}, (r.slots, r.refused)
    assert r.resolution["subject"]["bound_from"] == "question"
    # THE SPEAKER SAID NOTHING, AND THE RECORD SAYS SO. A slot bound from the question must not
    # re-enter the spoken loop, where the page IRI it now holds would be scored as if spoken.
    assert r.resolution["subject"]["spoken"] == ""


def test_a_vague_spoken_subject_falls_back_to_the_question(eo, monkeypatch):
    r = _fill(eo, monkeypatch, ENGINE_Q, json.dumps({"subject": "it"}), ["DOCS"])
    assert r.slots == {"subject": ENGINE_PAGE}
    assert r.resolution["subject"]["bound_from"] == "question"


def test_outside_DOCS_the_fan_out_still_decides(eo, monkeypatch):
    """The pool ADDS a binding under DOCS and changes nothing elsewhere: the old path runs."""
    called = []

    async def _fanout(identifier, query, asked_domains=None):
        called.append(identifier)
        return None, {"instance_match": "empty"}

    monkeypatch.setattr(eo, "_resolve_instance", _fanout)
    r = _fill(eo, monkeypatch, ENGINE_Q, json.dumps({"subject": "an engine"}), ["MAINTENANCE"])
    assert called == ["an engine"]
    assert "subject" not in r.slots
    assert eo._test_posted == []


# ── THE ROUTE'S OWN CLASS: MESH ends up at the pool too, when /resolve chose mesh:DocPage ──────
#
# MEASURED 2026-09-30: cortex hides DOCS from the picker, so the UI sends domains=['MESH']. The
# old gate (`_acts_in_docs`) never sees DOCS on that call, however confidently /resolve routed
# the question to mesh:DocPage — the subject pool never ran, the fan-out found nothing called
# "engine", and the supervisor abstained. `_docs_pool_applies` adds the route's own class as a
# second door into the pool; the CONTROL below shows the door stays shut for every other class.

_NON_DOCPAGE_CLASS = "http://invincible-agent/mesh#Dataset"


def test_the_screenshot_question_binds_its_page_under_MESH_when_the_route_chose_DocPage(eo, monkeypatch):
    r = _fill(eo, monkeypatch, ENGINE_Q, json.dumps({"subject": "engine"}), ["MESH"],
              subject_uri=DOCPAGE_CLASS)
    assert r.slots == {"subject": ENGINE_PAGE}, (r.slots, r.refused)


def test_the_screenshot_question_binds_an_unspoken_subject_under_MESH_when_the_route_chose_DocPage(eo, monkeypatch):
    r = _fill(eo, monkeypatch, ENGINE_Q, "{}", ["MESH"], subject_uri=DOCPAGE_CLASS)
    assert r.slots == {"subject": ENGINE_PAGE}, (r.slots, r.refused)


def test_a_route_to_any_other_class_under_MESH_still_leaves_the_pool_shut(eo, monkeypatch):
    """CONTROL: differs from the two arms above in exactly one thing, `subject_uri`. A route to
    a class that is not mesh:DocPage must not open the pool — the old, unscoped fan-out decides,
    same as `test_outside_DOCS_the_fan_out_still_decides`."""
    called = []

    async def _fanout(identifier, query, asked_domains=None):
        called.append(identifier)
        return None, {"instance_match": "empty"}

    monkeypatch.setattr(eo, "_resolve_instance", _fanout)
    r = _fill(eo, monkeypatch, ENGINE_Q, json.dumps({"subject": "engine"}), ["MESH"],
              subject_uri=_NON_DOCPAGE_CLASS)
    assert called == ["engine"]
    assert "subject" not in r.slots
    assert eo._test_posted == []


# ── THE JOIN: the bound subject reaches mesh:explain and its page ────────────────────────────

@pytest.mark.parametrize("question, page", [(ENGINE_Q, ENGINE_PAGE), (CANVAS_Q, CANVAS_PAGE)])
def test_the_bound_subject_reaches_explain_and_its_page(eo, monkeypatch, question, page):
    """/resolve's class IS `mesh:explain`'s registered input (LEG 1), and /fill_slots' value is
    what `/page_for_subject` serves: the three declarations agree, read from where they live."""
    from agent_fleet.docs_agent.main import VERBS

    explain = next(v for v in VERBS if v["verb"] == "mesh:explain")
    r = _resolve(eo, question, ["DOCS"])
    assert r.resolved_uri == explain["input_uri"]

    subject = _fill(eo, monkeypatch, question, "{}", ["DOCS"]).slots["subject"]
    served = asyncio.run(eo.page_for_subject_route(eo.PageForSubjectRequest(subject=subject)))
    assert [p["iri"] for p in served["pages"]] == [page]


def test_a_subject_containing_graph_is_still_scoped(eo):
    """THE EXECUTOR CHECKED A SUBSTRING. `"GRAPH" not in query.upper()` meant the graph page's
    own IRI (`…adding-a-graph`) disabled the scope and the read hit the empty default graph."""
    served = asyncio.run(eo.page_for_subject_route(eo.PageForSubjectRequest(subject=GRAPH_PAGE)))
    assert [p["iri"] for p in served["pages"]] == [GRAPH_PAGE]
    assert "GRAPH ?__mesh_g" in eo._test_posted[-1]
