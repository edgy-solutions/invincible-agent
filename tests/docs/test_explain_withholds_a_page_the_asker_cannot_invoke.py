"""Serve-time entitlement at engine-docs: DATA_ENGINEER is refused the cost page, served the MESH one.

Ruled 2026-09-30 (ADR-0037:179, ADR-0025:291): the verified asker's identity -- the on-behalf-of
token, never an envelope field -- must hold `can_invoke` on every verb a page explains, checked
AFTER resolve and BEFORE any body is read. Dark until `ENABLE_AGENTIC_AUTH`.

THE PAGES ARE THE CORPUS'S OWN, read from `setup/ontologies/docs_corpus.ttl` with rdflib -- iri,
title, source and `explains` exactly as primed. Only `body_sha` is replaced, by the sha of the
test body the double store returns, because `explain()` asserts body against sha and the gate
does not read either.

THE GRANTS ARE A FIXTURE, AND SAY SO. The capability namespace holds no mesh verb today (flip
packet, named consequence 3), so there is no live grant to read. DATA_ENGINEER is given the two
canvas verbs and nothing of cost or finance -- the cell the seal names.
"""
from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import agent_fleet.docs_agent.entitlement as ent  # noqa: E402
import agent_fleet.docs_agent.main as m  # noqa: E402
from agent_fleet.docs_agent.reads import PageRow  # noqa: E402

CORPUS = _REPO / "setup" / "ontologies" / "docs_corpus.ttl"
DOCS = "http://invincible-agent/docs#"
MESH = "http://invincible-agent/mesh#"
COST_PAGE = DOCS + "runbook-adding-a-graph"
MESH_PAGE = DOCS + "runbook-adding-a-canvas-template"
BODY = b"# a page\n\nbody text\n"

DATA_ENGINEER = "data.engineer@sandbox.test"
COST_ANALYST = "cost.analyst@sandbox.test"
GRANTS = {
    DATA_ENGINEER: {"mesh:seedCanvas", "mesh:seedPortfolioCanvas"},
    COST_ANALYST: {"mesh:seedCanvas", "mesh:seedPortfolioCanvas",
                   "mesh:costLotCostingReview", "mesh:finProgramBrief"},
}


def _corpus_rows() -> dict:
    import rdflib
    from rdflib.namespace import RDF, RDFS

    g = rdflib.Graph().parse(CORPUS, format="turtle")
    M = rdflib.Namespace(MESH)
    rows = {}
    for page in g.subjects(RDF.type, M.DocPage):
        rows[str(page)] = PageRow(
            iri=str(page),
            title=str(g.value(page, RDFS.label) or ""),
            doc_kind=str(g.value(page, M.doc_kind) or ""),
            audience_hint=str(g.value(page, M.audience_hint) or ""),
            source=str(g.value(page, M.source) or ""),
            body_sha=hashlib.sha256(BODY).hexdigest(),
            explains=tuple(sorted(str(o) for o in g.objects(page, M.explains))),
        )
    return rows


ROWS = _corpus_rows()


class _Caller:
    def __init__(self, authz_id, verified=True):
        self.authz_id, self.verified = authz_id, verified


class _Topaz:
    """Answers from GRANTS and records every request it was sent, whole."""

    def __init__(self, fail=False):
        self.requests, self.fail = [], fail

    def __call__(self, url, json=None, timeout=None, **_kw):
        self.requests.append({"url": url, **json})
        if self.fail:
            raise RuntimeError("directory unreachable")
        ok = (json["object_type"] == "capability" and json["relation"] == "can_invoke"
              and json["subject_type"] == "user"
              and json["object_id"] in GRANTS.get(json["subject_id"], set()))

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"check": ok}

        return _R()


class _Reader:
    def __init__(self, *iris):
        self.iris = iris

    def page_for_subject(self, subject_iri):
        return [ROWS[i] for i in self.iris]


class _Store:
    def __init__(self):
        self.reads = []

    def read(self, locator):
        self.reads.append(locator)
        return BODY


@pytest.fixture
def engine(monkeypatch):
    def _run(*iris, caller, gate=True, topaz=None, params=None):
        topaz = topaz or _Topaz()
        store = _Store()
        monkeypatch.setattr(ent, "ENABLE_AGENTIC_AUTH", gate)
        monkeypatch.setattr(ent, "TOPAZ_DIRECTORY_URL", "http://topaz.test:9393")
        monkeypatch.setattr(ent.httpx, "post", topaz)
        monkeypatch.setattr(m, "READER", _Reader(*iris))
        monkeypatch.setattr(m, "STORE", store)
        out = m.explain_endpoint(
            m.ExplainRequest(params={"subject": MESH + "seedCanvas", **(params or {})}),
            caller=caller)
        return out, store, topaz
    return _run


def _served(out):
    return [p["page_iri"] for p in out["pages"]]


def _withheld(out):
    return [w["page_iri"] for w in out["withheld"]]


# ── THE FIXTURE DISCRIMINATES ──────────────────────────────────────────────────────────────────

def test_the_two_pages_differ_in_what_the_gate_decides_on():
    """The cost page must oblige a verb DATA_ENGINEER lacks and the MESH page must not, or the
    refusal below could be the gate refusing everything."""
    cost_caps = ent.gated_capabilities(ROWS[COST_PAGE].explains)
    mesh_caps = ent.gated_capabilities(ROWS[MESH_PAGE].explains)
    assert set(cost_caps) - GRANTS[DATA_ENGINEER], cost_caps
    assert mesh_caps and set(mesh_caps) <= GRANTS[DATA_ENGINEER], mesh_caps
    assert any(t.startswith("http://invincible-agent/cost#") for t in ROWS[COST_PAGE].explains), \
        "the 'cost-domain page' is no longer one -- re-pick it from the corpus"


def test_every_corpus_explains_target_is_a_verb_or_a_class():
    """The gate decides verb-vs-class by the local name's case. Derived over the WHOLE corpus:
    an undecided target is asked as a verb (safe) but means the convention has drifted."""
    targets = {t for r in ROWS.values() for t in r.explains}
    kinds = {t: ent.classify_target(t) for t in targets}
    assert not [t for t, k in kinds.items() if k == "undecided"], kinds
    assert {"verb", "class"} <= set(kinds.values()), kinds


# ── THE SEAL ───────────────────────────────────────────────────────────────────────────────────

def test_DATA_ENGINEER_is_refused_the_cost_page_and_served_the_MESH_one(engine):
    out, store, _ = engine(COST_PAGE, MESH_PAGE, caller=_Caller(DATA_ENGINEER))
    assert _served(out) == [MESH_PAGE]
    assert _withheld(out) == [COST_PAGE]
    (w,) = out["withheld"]
    assert w["reason"] == "exists_but_not_in_your_entitlements"
    assert w["title"] == ROWS[COST_PAGE].title
    assert "body" in w and BODY.decode() not in w["body"]
    # THE WITHHELD BODY WAS NEVER READ -- not read and discarded.
    assert store.reads == [ROWS[MESH_PAGE].source]


def test_CONTROL_an_asker_holding_the_cost_verbs_is_served_both(engine):
    """Differs in exactly one thing, the grant. The refusal above is about DATA_ENGINEER."""
    out, store, _ = engine(COST_PAGE, MESH_PAGE, caller=_Caller(COST_ANALYST))
    assert _served(out) == [COST_PAGE, MESH_PAGE]
    assert out["withheld"] == []
    assert len(store.reads) == 2


def test_the_decider_is_asked_the_ruled_question(engine):
    _, _, topaz = engine(MESH_PAGE, caller=_Caller(DATA_ENGINEER))
    assert topaz.requests == [
        {"url": "http://topaz.test:9393/api/v3/directory/check", "object_type": "capability",
         "object_id": cap, "relation": "can_invoke", "subject_type": "user",
         "subject_id": DATA_ENGINEER}
        for cap in ("mesh:seedCanvas", "mesh:seedPortfolioCanvas")
    ]


def test_every_page_withheld_is_UNENTITLED_not_an_abstain(engine):
    out, store, _ = engine(COST_PAGE, caller=_Caller(DATA_ENGINEER))
    assert out.get("refused") is True and out.get("outcome") == "unentitled"
    assert "abstained" not in out
    assert out["pages"] == [] and out["page_count"] == 0
    assert _withheld(out) == [COST_PAGE]
    assert store.reads == []


# ── FAIL CLOSED ────────────────────────────────────────────────────────────────────────────────

def test_an_UNVERIFIED_caller_naming_DATA_ENGINEER_holds_nothing(engine):
    out, store, topaz = engine(MESH_PAGE, caller=_Caller(DATA_ENGINEER, verified=False))
    assert out.get("outcome") == "unentitled" and _withheld(out) == [MESH_PAGE]
    assert store.reads == []
    assert topaz.requests == [], "an empty identity is denied before the directory is asked"


def test_on_behalf_of_in_the_envelope_changes_no_decision(engine):
    """Ruling 2026-09-26 §4: `on_behalf_of` is provenance, never a gate input. Naming a fully
    granted principal in the request must not widen what DATA_ENGINEER is served."""
    base, _, _ = engine(COST_PAGE, MESH_PAGE, caller=_Caller(DATA_ENGINEER))
    named, _, _ = engine(COST_PAGE, MESH_PAGE, caller=_Caller(DATA_ENGINEER),
                         params={"on_behalf_of": COST_ANALYST})
    assert _served(named) == _served(base) == [MESH_PAGE]


def test_a_directory_error_is_a_deny(engine):
    out, store, topaz = engine(MESH_PAGE, caller=_Caller(DATA_ENGINEER), topaz=_Topaz(fail=True))
    assert topaz.requests, "the directory was never asked -- this arm tested nothing"
    assert out.get("outcome") == "unentitled" and store.reads == []


def test_a_page_explaining_no_verb_is_served_under_the_gate(engine, monkeypatch):
    """Nothing to ask: its class targets were the resolve-time check's to decide."""
    classes_only = dataclasses.replace(ROWS[COST_PAGE],
                                       explains=tuple(t for t in ROWS[COST_PAGE].explains
                                                      if ent.classify_target(t) == "class"))
    assert classes_only.explains
    ROWS["classes-only"] = classes_only
    try:
        out, _, topaz = engine("classes-only", caller=_Caller(DATA_ENGINEER))
    finally:
        del ROWS["classes-only"]
    assert _served(out) == [COST_PAGE] and topaz.requests == []


# ── DARK ───────────────────────────────────────────────────────────────────────────────────────

def test_DARK_the_gate_is_not_consulted_and_the_shape_is_unchanged(engine):
    def _never(*_a, **_kw):
        raise AssertionError("Topaz was asked while ENABLE_AGENTIC_AUTH is off")

    out, store, _ = engine(COST_PAGE, MESH_PAGE, caller=_Caller(DATA_ENGINEER), gate=False,
                           topaz=_never)
    assert set(out) == {"archetype", "subject", "pages", "page_count"}
    assert _served(out) == [COST_PAGE, MESH_PAGE] and len(store.reads) == 2


def test_the_route_takes_the_caller_from_the_transport_dependency():
    """WIRING: the gate is only as good as where `caller` comes from. It must be the SDK's
    verified transport identity, not a body field."""
    import inspect

    from fastapi.params import Depends as _DependsParam

    default = inspect.signature(m.explain_endpoint).parameters["caller"].default
    assert isinstance(default, _DependsParam)
    assert "transport_auth" in getattr(default.dependency, "__qualname__", "") or \
        "transport_auth" in getattr(default.dependency, "__module__", ""), default.dependency


def test_an_UNDECIDED_target_is_ASKED_not_waved_through():
    """The corpus arm above holds no undecided target, so it cannot see this branch. A target of
    no recognised shape must be gated like a verb: waving it through as a class would serve the
    page with nothing asked."""
    for odd in ("mesh:9lives", "mesh:", "http://invincible-agent/mesh#_x"):
        assert ent.classify_target(odd) == "undecided", odd
    assert ent.gated_capabilities(("mesh:9lives",)) == ["mesh:9lives"]
