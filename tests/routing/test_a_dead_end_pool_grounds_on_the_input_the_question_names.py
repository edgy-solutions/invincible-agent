"""A dead-end class pool grounds on the class the question's verb takes as input.

THE DEFECT (live walk on 201, caller bob / SAFETY_ENGINEER / [SUSTAINMENT]). Safety Q4 "what failed
on this part" and Q3 "risk of deferring this work order": `/resolve` recalled 10 classes for each
and NONE is served, so the productive-option gate stood down and recorded every candidate
`retained / no_verb_in_scope_but_pool_would_empty`. The LLM picked a dead end (safety#FailureRecord,
safety#RiskAssessment) and the router fell to the generalist. The verbs the questions name are
declared on classes that were never recalled: whatFailedOnThisPart on safety#SafetyCriticalItem and
pcn#Component, assessDeferralRisk on the MaintenanceWorkOrderRecord class.

THE RULING (architect, 2026-10-20): "the resolver prefers input-declared classes; seal with saf's two
phrasings." Built to fire ONLY when the served set is non-empty and no recalled class is served.
SUPERSEDED IN PART 2026-10-20: when the input-declared pool is empty too, the pool is now EMPTY (tests/routing/test_a_class_enters_the_pool_only_as_a_verbs_input.py).

THE LIVE NUMBERS (predicate_hybrid_search, SUSTAINMENT, as bob): Q4 whatFailedOnThisPart 0.923/0.910,
failureTrendForThisPlatformByMonth 0.834 (input Platform), rendersAs 0.523; Q3 assessDeferralRisk
0.893, rendersAs 0.618, draftRiskAssessment 0.519 (input Hazard); off-topic control rendersAs 0.763,
0.710, 0.700, traceLineage 0.692. The floor is 0.80, a sample of one negative.

Drives the REAL `eo.resolve`.
Run: uv run --frozen pytest tests/routing/test_a_dead_end_pool_grounds_on_the_input_the_question_names.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.ontology_service.input_declared import input_declared_classes  # noqa: E402

SAFETY = "http://internal/sustainment/safety#"
PCN = "http://internal/sustainment/pcn#"
PRODUCT = "http://internal/sustainment/product#"
S3KL = "http://www.lksoft.com/s3kl#"
MESH = "http://invincible-agent/mesh#"
MRO = "https://spec.industrialontologies.org/ontology/construct/"

SCI = SAFETY + "SafetyCriticalItem"
COMPONENT = PCN + "Component"
PLATFORM = SAFETY + "Platform"
HAZARD = SAFETY + "Hazard"
WORK_ORDER = MRO + "MaintenanceWorkOrderRecord"
FAILURE_RECORD = SAFETY + "FailureRecord"

Q4 = "what failed on this part"
Q3 = "risk of deferring this work order"
NAPOLEON = "what color was Napoleon's horse"

Q4_POOL = [
    FAILURE_RECORD, S3KL + "FailureMode", PRODUCT + "Part", S3KL + "LSAFailureMode",
    S3KL + "LSACandidateFailureModeAndEffectAnalysisActivity", S3KL + "FunctionalFailure",
    S3KL + "PartAsDesigned", S3KL + "FailureModeLocalizationAbilityRating",
    S3KL + "HardwarePartRepairabilityStrategy", S3KL + "FailureModeDetection",
]
Q3_POOL = [
    S3KL + "TaskRequirementDecision_Deferred", S3KL + "TaskRevisionStatus_inWork",
    S3KL + "BreakdownRevisionStatus_inWork", SAFETY + "RiskAssessment",
    SAFETY + "AcceptanceAuthority", PRODUCT + "ApprovedSourceRelationship",
    S3KL + "BreakdownElementRevisionStatus_inWork", S3KL + "TaskRevisionWarningCautionNote",
    MESH + "ResolvableReferent", FAILURE_RECORD,
]

# What is actually served (include_referents=False): the verbs' inputs, none of the recalled pool.
SERVED = frozenset({SCI, COMPONENT, PLATFORM, HAZARD, WORK_ORDER})
# A declared referent outside the recalled pools (measured: the gate stood down, so no pooled class was served).
SERVED_WITH_REFERENT = SERVED | {MESH + "SomeOtherReferent"}


def _verb(verb, input_uri, score, desc="a verb"):
    return {"verb_iri": MESH + verb, "input_uri": input_uri, "output_uri": "", "endpoint": "http://e/x",
            "score": score, "description": desc}


def _renderer(score):
    return {"verb_iri": MESH + "rendersAs", "input_uri": SAFETY + "Rendered", "output_uri": "",
            "endpoint": "", "score": score, "description": ""}


Q4_ROWS = [
    _verb("whatFailedOnThisPart", SCI, 0.923, "failures for one part"),
    _verb("whatFailedOnThisPart", COMPONENT, 0.910, "failures for one part"),
    _verb("failureTrendForThisPlatformByMonth", PLATFORM, 0.834),
    _renderer(0.523),
]
Q3_ROWS = [
    _verb("assessDeferralRisk", WORK_ORDER, 0.893, "cost of deferring"),
    _renderer(0.618),
    _verb("draftRiskAssessment", HAZARD, 0.519),
]
NAPOLEON_ROWS = [_renderer(0.763), _renderer(0.710), _renderer(0.700),
                 _verb("traceLineage", SAFETY + "Thing", 0.692)]


class _Tb:
    def __init__(self):
        self.values = {}
        tb = self

        class _OC:
            @staticmethod
            def add_value(uri):
                class _V:
                    @staticmethod
                    def description(d):
                        tb.values[uri] = d
                        return _V
                return _V
        self.OntologyClass = _OC


class _Baml:
    def __init__(self):
        self.offered = None

    async def ClassifyDomainIntent(self, **kw):
        self.offered = list(kw["baml_options"]["tb"].values)
        first = self.offered[0]

        class _R:
            resolved_uri = first
            confidence_score = 0.9
            reasoning = ""
            instance_identifier = None
        return _R()


@pytest.fixture
def rig(monkeypatch):
    from agent_fleet.ontology_service import main as eo

    class R:
        pass

    r = R()
    r.eo = eo
    r.baml = _Baml()
    r.served_calls = []
    r.verb_calls = []
    r.pool = Q4_POOL
    r.rows = Q4_ROWS
    r.verb_exc = None
    r.served_for = lambda include_referents: SERVED_WITH_REFERENT if include_referents else SERVED

    async def _docs(request):
        return None

    async def _pool(**kw):
        return [{"uri": u, "label": u.rsplit("#", 1)[-1], "description": "d", "score": None}
                for u in r.pool], "hybrid"

    async def _served(domains, include_referents=False):
        r.served_calls.append(include_referents)
        return r.served_for(include_referents)

    async def _verbs(query, domains, limit=10, user_email="", verb_iris=None):
        r.verb_calls.append(query)
        if r.verb_exc is not None:
            raise r.verb_exc
        return r.rows

    monkeypatch.setattr(eo, "_resolve_docs_subject", _docs)
    monkeypatch.setattr(eo, "class_pool_with_mode", _pool)
    monkeypatch.setattr(eo, "_served_class_uris", _served)
    monkeypatch.setattr(eo, "predicate_hybrid_search", _verbs)
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", False)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: True)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", None)
    monkeypatch.setattr(eo, "TypeBuilder", _Tb)
    monkeypatch.setattr(eo, "b", r.baml)

    async def run(query):
        return await eo.resolve(eo.ResolveRequest(
            query=query, domain="SUSTAINMENT", domains=["SUSTAINMENT"], user_email="bob@example.com"))
    r.run = run
    return r


def _removed(resp):
    return {e["uri"]: (e["disposal"], e["reason"]) for e in resp.excluded}


REMOVED = {("removed", "no_verb_in_scope")}


# 1
@pytest.mark.asyncio
async def test_q4_phrasing_offers_the_two_declared_inputs_and_not_platform(rig):
    resp = await rig.run(Q4)
    assert set(rig.baml.offered) == {SCI, COMPONENT}
    assert PLATFORM not in rig.baml.offered
    assert not any("Rendered" in u for u in rig.baml.offered)
    assert _removed(resp) == {u: ("removed", "input_declared_preferred") for u in Q4_POOL}
    assert len(resp.excluded) == 10


# 2
@pytest.mark.asyncio
async def test_the_fixture_rejects_re_ranking_the_recalled_pool(rig):
    await rig.run(Q4)
    assert set(rig.baml.offered) & set(Q4_POOL) == set()


# 3
@pytest.mark.asyncio
async def test_q3_phrasing_offers_the_work_order_record(rig):
    rig.pool, rig.rows = Q3_POOL, Q3_ROWS
    await rig.run(Q3)
    assert set(rig.baml.offered) == {WORK_ORDER}


# 4
@pytest.mark.asyncio
async def test_control_a_served_recalled_class_means_no_verb_search(rig):
    rig.pool = [COMPONENT, FAILURE_RECORD]
    resp = await rig.run("tell me about this component")
    assert rig.verb_calls == []
    assert set(rig.baml.offered) == {COMPONENT}
    assert _removed(resp) == {FAILURE_RECORD: ("removed", "no_verb_in_scope")}
    assert "input_declared" not in resp.provenance


# 5
@pytest.mark.asyncio
async def test_control_off_topic_the_floor_holds_and_the_pool_empties(rig):
    rig.rows = NAPOLEON_ROWS
    resp = await rig.run(NAPOLEON)
    assert rig.baml.offered is None
    assert set(_removed(resp).values()) == REMOVED
    assert resp.provenance["input_declared"]["reason"] == "no_verb_above_floor"


# 6
@pytest.mark.asyncio
async def test_a_renderer_on_top_is_not_offered_and_the_next_real_verb_is(rig):
    rig.rows = [_renderer(0.95)] + Q3_ROWS
    rig.pool = Q3_POOL
    await rig.run(Q3)
    assert set(rig.baml.offered) == {WORK_ORDER}


# 7
@pytest.mark.asyncio
async def test_visibility_gate_holds_for_an_injected_class(rig, monkeypatch):
    eo = rig.eo
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: uri != COMPONENT)
    await rig.run(Q4)
    assert set(rig.baml.offered) == {SCI}


@pytest.mark.asyncio
async def test_visibility_denying_both_inputs_empties_the_pool(rig, monkeypatch):
    eo = rig.eo
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: uri not in (SCI, COMPONENT))
    resp = await rig.run(Q4)
    assert rig.baml.offered is None
    assert set(_removed(resp).values()) == REMOVED


# 8
@pytest.mark.asyncio
async def test_served_is_asked_without_referents_and_an_unserved_input_is_not_offered(rig):
    rig.served_for = lambda include_referents: (
        SERVED_WITH_REFERENT if include_referents else frozenset({SCI, PLATFORM}))
    # the gate's own question (with referents) must still find no recalled class served
    await rig.run(Q4)
    assert False in rig.served_calls and True in rig.served_calls
    assert set(rig.baml.offered) == {SCI}


# 9
@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [HTTPException(status_code=503, detail="down"), RuntimeError("boom")])
async def test_verb_recall_failure_does_not_admit_the_dead_ends(rig, exc):
    rig.verb_exc = exc
    resp = await rig.run(Q4)
    assert rig.baml.offered is None
    assert set(_removed(resp).values()) == REMOVED
    assert resp.provenance["input_declared"]["reason"] == "verb_recall_failed"


# 10
def _pure(rows, floor=0.80, served=SERVED, visible=lambda u: True):
    return input_declared_classes(rows, served=served, visible=visible, floor=floor)


def test_pure_floor_boundary():
    kept, _ = _pure([_verb("v", SCI, 0.80)])
    assert [c["uri"] for c in kept] == [SCI]
    dropped, trace = _pure([_verb("v", SCI, 0.799)])
    assert dropped == [] and trace["reason"] == "no_verb_above_floor"


def test_pure_dedups_keeping_first():
    kept, _ = _pure([_verb("v", SCI, 0.9), _verb("v", SCI, 0.85)])
    assert [(c["uri"], c["score"]) for c in kept] == [(SCI, 0.9)]


def test_pure_top_verb_only():
    kept, _ = _pure(Q4_ROWS)
    assert {c["uri"] for c in kept} == {SCI, COMPONENT}


def test_pure_drops_none_scores_and_endpointless_rows():
    kept, trace = _pure([_verb("v", SCI, None), _renderer(0.99)])
    assert kept == [] and trace["reason"] == "no_verb_above_floor"


# 11
@pytest.mark.asyncio
async def test_injected_classes_carry_label_description_and_the_trace(rig):
    resp = await rig.run(Q4)
    assert all(c["label"] and c["description"] for c in resp.candidates)
    assert {c["label"] for c in resp.candidates} == {"SafetyCriticalItem", "Component"}
    assert resp.provenance["input_declared"]["reason"] == "declared_input"
