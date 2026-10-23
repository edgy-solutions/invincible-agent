"""Q9 offline: a CLOSED hazard must still RESOLVE, and the verb is what refuses it.

Q9 (docs/measurements/safety-walk-sheet.md): "draft a risk assessment for HAZ-1005", caller bob /
SAFETY_ENGINEER / [SUSTAINMENT]. The verb is mesh:draftRiskAssessment (input safety:Hazard).
Expected: the ENGINE refuses `hazard_closed` and opens no task. HAZ-1005 is `status="closed"` in
agent_fleet/safety_agent/entities.py.

THE ARCHITECT, 10-23: "walk Q9/HAZ-1005 offline against the item-1 branch: closed hazards must
resolve." The sandbox is frozen, so this is doubles plus real code, no cluster and no network.

WHY "MUST RESOLVE" IS THE CLAIM. If the resolution layer quietly dropped closed hazards the walk
would end in "no compatible verbs" and the user would be told nothing about WHY. The refusal
(`hazard_closed`, with the held status and mitigations) is only reachable if the subject grounds
first, so the ground and the refusal are one chain, asserted end to end.

THE RECALL POOLS ARE ASSUMED. No live Q9 pool was ever recorded: the 201 walk output carries no
subject telemetry for this question. So the arms cover EVERY path the admission rule allows to a
non-empty pool, instead of one guess at the live one:
  P1  recall holds safety:Hazard; the model picks it and extracts the identifier (Step 4 fan-out).
  P2  recall lacks it; the verb row for draftRiskAssessment admits it (input-declared pool).
  P3  recall lacks it and no Hazard verb clears the floor; `entity_refs` carry the id (Step 1.6).

REAL: Engine O `resolve()` (via 74's rig), `_resolve_instance`, `_call_resolver`, `_read_class_chains`
(it degrades to "unavailable" with no driver, which the rig sets), the safety provider app and its
`instances.resolve`, the safety `measure` route, and the supervisor's `_classify_route`.
DOUBLED (the rig's, plus two new): `_discover_instance_resolvers` returns one row shaped as the real
function builds it (id_namespaces read from `safety_agent.main.ID_NAMESPACES`, not typed);
`httpx.AsyncClient` forwards each post to the REAL safety app through a TestClient, built without
the lifespan so no registration call is attempted.

Run: uv run --frozen pytest tests/routing/test_q9_a_closed_hazard_grounds_and_its_verb_refuses_it.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 74's rig and measured data, imported not copied.
from tests.routing.test_a_dead_end_pool_grounds_on_the_input_the_question_names import (  # noqa: E402,F401
    HAZARD, Q4_POOL, _renderer, _verb, rig,
)
# The supervisor fixture and the wire shapes, imported from the router seal.
from tests.routing.test_the_router_takes_the_verb_the_input_declared_subject_carries import (  # noqa: E402,F401
    _Ctx, _Resp, _wire_verbs, sup,
)
from agent_fleet.safety_agent import main as safety_main  # noqa: E402
from agent_fleet.safety_agent.entities import HAZARDS  # noqa: E402

Q9 = "draft a risk assessment for HAZ-1005"
HAZ_ID = "HAZ-1005"
REFS = [HAZ_ID]

# P1: the recalled pool holds the Hazard class among dead ends. Of them only HAZARD is served.
P1_POOL = [HAZARD] + Q4_POOL[:3]
# P2: the verb row that admits it; the renderer is the noise the rule must skip.
P2_ROWS = [_verb("draftRiskAssessment", HAZARD, 0.9, "draft a risk acceptance"), _renderer(0.6)]
# P3: no Hazard verb clears the floor (renderers only), so nothing admits a pooled class.
P3_ROWS = [_renderer(0.7), _renderer(0.65)]


class _HttpResp:
    """The httpx.Response surface `_call_resolver` reads."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._p


class _BamlWithIdentifier:
    """The rig's pick (the first class offered) plus the identifier the model extracted."""

    def __init__(self, identifier):
        self.offered = None
        self._identifier = identifier

    async def ClassifyDomainIntent(self, **kw):
        self.offered = list(kw["baml_options"]["tb"].values)
        first, ident = self.offered[0], self._identifier

        class _R:
            resolved_uri = first
            confidence_score = 0.9
            reasoning = ""
            instance_identifier = ident
        return _R()


@pytest.fixture
def inst(rig, monkeypatch):
    """The instance fan-out: one provider row, and an AsyncClient that calls the REAL safety app."""
    from fastapi.testclient import TestClient

    eo = rig.eo
    # NO `with`: the lifespan registers verbs with the mesh, which is a network call.
    client = TestClient(safety_main.app)
    rig.posts = []
    rig.provider_answer = None  # a canned body replaces the real app's answer when set

    row = {
        "endpoint_url": "http://engine-safety/resolve_instance",
        "provider": "engine_safety_sustainment",
        "timeout_s": None,
        "domains": ["SUSTAINMENT"],
        "id_namespaces": list(safety_main.ID_NAMESPACES),
    }
    monkeypatch.setattr(eo, "_discover_instance_resolvers",
                        lambda refresh=False: eo.MeshResult.answered([dict(row)]))

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **k):
            rig.posts.append((url, json))
            if rig.provider_answer is not None:
                return _HttpResp(200, rig.provider_answer)
            r = client.post("/resolve_instance", json=json)
            return _HttpResp(r.status_code, r.json())

    monkeypatch.setattr(eo.httpx, "AsyncClient", _Client)

    async def run_refs(query, entity_refs=None):
        return await eo.resolve(eo.ResolveRequest(
            query=query, domain="SUSTAINMENT", domains=["SUSTAINMENT"],
            user_email="bob@example.com", entity_refs=list(entity_refs or [])))
    rig.run_refs = run_refs
    rig.client = client
    return rig


@pytest.fixture
def p1(inst, monkeypatch):
    inst.pool, inst.rows = P1_POOL, []
    inst.baml = _BamlWithIdentifier(HAZ_ID)
    monkeypatch.setattr(inst.eo, "b", inst.baml)
    return inst


@pytest.fixture
def p2(inst):
    inst.pool, inst.rows = Q4_POOL, P2_ROWS
    return inst


@pytest.fixture
def p3(inst):
    inst.pool, inst.rows = Q4_POOL, P3_ROWS
    return inst


# 1
def test_the_fixture_holds_a_closed_hazard_to_refuse():
    assert {h.hazard_id: h.status for h in HAZARDS}[HAZ_ID] == "closed"


# 2
@pytest.mark.parametrize("hazard", HAZARDS, ids=lambda h: f"{h.hazard_id}-{h.status}")
def test_the_provider_resolves_every_hazard_by_id_whatever_its_status(hazard):
    got = safety_main.instances_mod.resolve(hazard.hazard_id)
    assert got and got[0]["instance_id"] == hazard.hazard_id
    assert got[0]["class_uri"] == HAZARD


def test_the_provider_grounds_the_q9_sentence_on_the_closed_hazard():
    got = safety_main.instances_mod.resolve(Q9)
    assert got[0]["instance_id"] == HAZ_ID and got[0]["class_uri"] == HAZARD


# 3
@pytest.mark.asyncio
async def test_p1_recall_holds_the_hazard_and_the_models_identifier_grounds_it(p1):
    resp = await p1.run_refs(Q9)
    assert resp.resolved_uri == HAZARD
    assert p1.baml.offered == [HAZARD]
    # .get, not [...]: with Step 4's fan-out off the key is absent, and that must red HERE as
    # an assertion naming the identifier, not as a KeyError that never reached the claim.
    assert resp.provenance.get("instance_identifier") == HAZ_ID, (
        "the model's instance_identifier never reached Step 4's fan-out", resp.provenance)
    assert resp.provenance.get("instance_id") == HAZ_ID
    assert [j["identifier"] for _u, j in p1.posts][0] == HAZ_ID


@pytest.mark.asyncio
async def test_p2_the_verb_row_admits_the_hazard_class_and_the_model_picks_it(p2):
    resp = await p2.run_refs(Q9)
    assert resp.resolved_uri == HAZARD
    assert HAZARD in p2.baml.offered


@pytest.mark.asyncio
async def test_p3_entity_refs_ground_it_when_nothing_else_admits_a_class(p3):
    resp = await p3.run_refs(Q9, REFS)
    assert resp.resolved_uri == HAZARD
    assert p3.baml.offered is None, "the model was asked; the fan-out did not ground this"
    assert resp.provenance["instance_id"] == HAZ_ID
    assert [j["identifier"] for _u, j in p3.posts] == [HAZ_ID]


# 4
@pytest.mark.asyncio
async def test_c1_p3_without_entity_refs_abstains(p3):
    resp = await p3.run_refs(Q9)
    assert resp.resolved_uri == "UNKNOWN"
    assert resp.provenance["abstention_reason"] == "no_compatible_verbs"
    assert p3.posts == []


@pytest.mark.asyncio
async def test_c2_p3_with_a_provider_that_knows_nothing_does_not_ground(p3):
    p3.provider_answer = {"candidates": []}
    resp = await p3.run_refs(Q9, REFS)
    assert resp.resolved_uri != HAZARD
    assert p3.posts, "the provider was never asked, so the control proves nothing"


@pytest.mark.asyncio
async def test_c3_p3_with_closed_hazards_hidden_from_the_provider_does_not_ground(p3, monkeypatch):
    # The module object the app ACTUALLY uses (flat vs package import duality in instances.py).
    open_only = tuple(h for h in HAZARDS if h.status != "closed")
    assert len(open_only) < len(HAZARDS)
    monkeypatch.setattr(safety_main.instances_mod, "HAZARDS", open_only)
    resp = await p3.run_refs(Q9, REFS)
    assert resp.resolved_uri != HAZARD
    assert p3.posts, "the provider was never asked, so the control proves nothing"


# 5
def _route(rig, sup, monkeypatch, query, entity_refs):
    """Real resolve() (with entity_refs) -> real _classify_route. Returns (subject, telemetry)."""
    box = {}

    def _post(url, *a, **k):
        suffix = url.rsplit("/", 1)[-1]
        if suffix == "resolve":
            assert k["json"].get("entity_refs") == list(entity_refs), "the supervisor dropped entity_refs"
            box["resp"] = asyncio.run(rig.run_refs(query, k["json"].get("entity_refs")))
            return _Resp(box["resp"].model_dump())
        if suffix == "find_compatible_verbs":
            box["subject"] = k["json"]["subject_uri"]
            return _Resp({"verbs": _wire_verbs(box["subject"])})
        if suffix == "classify_predicate":
            return _Resp({"resolved_verb_iri": "UNKNOWN", "confidence_score": 0.0,
                          "classify_called": True, "candidate_verb_iris": []})
        return _Resp({})
    monkeypatch.setattr(sup.requests, "post", _post)
    _s, _p, tele = sup._classify_route(
        _Ctx(), query, ["SUSTAINMENT"], routing_domain="SUSTAINMENT",
        entity_refs=list(entity_refs), user_email="bob@example.com")
    return box.get("subject"), tele


def _verbs_in(tele):
    return {str(v).rsplit(":", 1)[-1].rsplit("#", 1)[-1] for v in tele.get("compatible_verb_iris") or []}


def test_the_supervisor_join_p3_subject_is_the_hazard_and_the_verb_is_in_the_pool(p3, sup, monkeypatch):
    subject, tele = _route(p3, sup, monkeypatch, Q9, REFS)
    assert subject == HAZARD
    assert "draftRiskAssessment" in _verbs_in(tele), tele["compatible_verb_iris"]


def test_the_supervisor_join_p1_subject_is_the_hazard_and_the_verb_is_in_the_pool(p1, sup, monkeypatch):
    subject, tele = _route(p1, sup, monkeypatch, Q9, REFS)
    assert subject == HAZARD
    assert "draftRiskAssessment" in _verbs_in(tele), tele["compatible_verb_iris"]


# 6
@pytest.mark.asyncio
async def test_the_verb_refuses_the_identifier_the_walk_produced(p3):
    resp = await p3.run_refs(Q9, REFS)
    hazard_id = resp.provenance["instance_id"]  # what the walk produced, not retyped
    r = p3.client.post("/measure/draft_risk_assessment",
                       json={"query": "", "params": {"hazard_id": hazard_id}})
    assert r.status_code == 200, r.text[:200]
    out = r.json()
    assert out["refused"] is True
    assert out["outcome"] == "hazard_closed"
    assert "review_request" not in out
