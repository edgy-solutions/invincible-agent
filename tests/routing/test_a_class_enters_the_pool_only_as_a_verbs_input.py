"""A class enters the candidate pool only as a verb's declared input.

THE RULING (architect, 2026-10-20): "a class enters the candidate pool only if some verb declares it
as input." When the served set is non-empty, the pool is recalled-and-served; failing that, the
input-declared pool (Q7(a)); failing that, the pool is EMPTY. An empty served set (lookup failed,
graph cold) still degrades open.

THE FIRST MEASUREMENT. On revision 201, for caller bob / SAFETY_ENGINEER / [SUSTAINMENT], safety Q4
"what failed on this part" and Q3 "risk of deferring this work order" each recalled 10 classes and
none was served. The gate stood down (`retained / no_verb_in_scope_but_pool_would_empty`), the model
picked a dead end (safety#FailureRecord, safety#RiskAssessment), and the router fell to the
generalist anyway.

THE SECOND MEASUREMENT. On the work cluster, 2026-09-08, the same stand-down ("would have emptied
the pool (10 candidate(s), 0 served)") let the model answer IOF `SellingBusinessProcess` at 0.62: a
real class, a plausible confidence, the wrong ontology.

So a retained dead end costs a `ClassifyDomainIntent` call (measured p100 52.6 s on revision 199) and
then reaches the generalist or a wrong answer. An empty pool reaches the generalist directly, with a
reason.

Drives the REAL `eo.resolve`. `_Baml.offered` stays None when the model is never called: that is the
evidence no call was made.
Run: uv run --frozen pytest tests/routing/test_a_class_enters_the_pool_only_as_a_verbs_input.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# THE RIG BELOW IS COPIED FROM tests/routing/test_a_dead_end_pool_grounds_on_the_input_the_question_names.py
# (URI constants, pools, rows, _verb, _renderer, _Tb, _Baml, the rig fixture, _removed), trimmed to what
# these arms need, with `run` extended to accept entity_refs.
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
NAPOLEON = "what color was Napoleon's horse"

Q4_POOL = [
    FAILURE_RECORD, S3KL + "FailureMode", PRODUCT + "Part", S3KL + "LSAFailureMode",
    S3KL + "LSACandidateFailureModeAndEffectAnalysisActivity", S3KL + "FunctionalFailure",
    S3KL + "PartAsDesigned", S3KL + "FailureModeLocalizationAbilityRating",
    S3KL + "HardwarePartRepairabilityStrategy", S3KL + "FailureModeDetection",
]

SERVED = frozenset({SCI, COMPONENT, PLATFORM, HAZARD, WORK_ORDER})
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
    r.pool = Q4_POOL
    r.rows = NAPOLEON_ROWS
    r.verb_exc = None
    r.served_for = lambda include_referents: SERVED_WITH_REFERENT if include_referents else SERVED

    async def _docs(request):
        return None

    async def _pool(**kw):
        return [{"uri": u, "label": u.rsplit("#", 1)[-1], "description": "d", "score": None}
                for u in r.pool], "hybrid"

    async def _served(domains, include_referents=False):
        return r.served_for(include_referents)

    async def _verbs(query, domains, limit=10, user_email="", verb_iris=None):
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

    async def run(query, entity_refs=None):
        kw = {"entity_refs": entity_refs} if entity_refs else {}
        return await eo.resolve(eo.ResolveRequest(
            query=query, domain="SUSTAINMENT", domains=["SUSTAINMENT"], user_email="bob@example.com", **kw))
    r.run = run
    return r


def _removed(resp):
    return {e["uri"]: (e["disposal"], e["reason"]) for e in resp.excluded}


def _assert_pool_emptied(rig, resp):
    assert rig.baml.offered is None
    assert resp.resolved_uri == "UNKNOWN"
    assert resp.provenance["abstention_reason"] == "no_compatible_verbs"
    assert resp.provenance["admission"] == {
        "rule": "verb_declared_input", "recalled": len(Q4_POOL), "admitted": 0}
    assert {(e["disposal"], e["reason"]) for e in resp.excluded} == {("removed", "no_verb_in_scope")}
    assert {e["uri"] for e in resp.excluded} == set(Q4_POOL)
    assert resp.candidates == []


# 1
@pytest.mark.asyncio
async def test_no_admissible_class_empties_the_pool_and_the_model_is_never_asked(rig):
    resp = await rig.run(NAPOLEON)
    _assert_pool_emptied(rig, resp)


# 2
@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [HTTPException(status_code=503, detail="down"), RuntimeError("boom")])
async def test_a_failed_verb_search_does_not_admit_the_recalled_dead_ends(rig, exc):
    rig.verb_exc = exc
    resp = await rig.run(Q4)
    _assert_pool_emptied(rig, resp)
    assert resp.provenance["input_declared"]["reason"] == "verb_recall_failed"


# 3
@pytest.mark.asyncio
async def test_visibility_denying_both_declared_inputs_empties_the_pool(rig, monkeypatch):
    # Monkeypatching copied from arm 7b of the Q7(a) file.
    eo = rig.eo
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: uri not in (SCI, COMPONENT))
    resp = await rig.run(Q4)
    _assert_pool_emptied(rig, resp)


# 4
@pytest.mark.asyncio
async def test_CONTROL_an_empty_served_set_still_degrades_open(rig):
    rig.served_for = lambda include_referents: frozenset()
    resp = await rig.run(NAPOLEON)
    assert set(rig.baml.offered) == set(Q4_POOL)
    assert not any(e.get("gate") == "productive_option" for e in resp.excluded)
    assert "abstention_reason" not in (resp.provenance or {})


# 5
@pytest.mark.asyncio
async def test_CONTROL_a_served_recalled_class_is_offered_alone(rig):
    rig.pool = [COMPONENT, FAILURE_RECORD]
    await rig.run("tell me about this component")
    assert set(rig.baml.offered) == {COMPONENT}


# 6
@pytest.mark.asyncio
async def test_CONTROL_the_input_declared_pool_still_rescues_q4(rig):
    rig.rows = Q4_ROWS
    await rig.run(Q4)
    assert set(rig.baml.offered) == {SCI, COMPONENT}


# 7
@pytest.mark.asyncio
async def test_the_reason_names_what_was_found_not_an_empty_recall(rig):
    resp = await rig.run(NAPOLEON)
    assert "No ontology classes found" not in resp.reasoning
    assert Q4_POOL[0].rsplit("#", 1)[-1] in resp.reasoning


def test_unadmitted_pool_msg_one_versus_many_and_at_most_three_names():
    from agent_fleet.ontology_service import main as eo

    def c(n):
        return {"uri": f"http://x#Name{n}", "label": ""}

    one = eo._unadmitted_pool_msg([c(1)])
    assert "Name1" in one and "questions about it." in one and "any of them" not in one
    four = eo._unadmitted_pool_msg([c(1), c(2), c(3), c(4)])
    assert "questions about any of them." in four
    assert "Name1, Name2, Name3" in four and "Name4" not in four
    labelled = eo._unadmitted_pool_msg([{"uri": "http://x#Raw", "label": "Pretty"}])
    assert "Pretty" in labelled and "Raw" not in labelled


# 8
@pytest.mark.asyncio
async def test_an_emptied_pool_still_asks_the_phone_book_and_says_recall_was_not_empty(rig, monkeypatch):
    eo = rig.eo
    seen = []

    async def _resolve_instance(identifier, **kw):
        seen.append(identifier)
        return SCI, {}

    async def _not_unanswerable(resolved_uri, domains):
        return False

    monkeypatch.setattr(eo, "_resolve_instance", _resolve_instance)
    monkeypatch.setattr(eo, "_preempted_subject_is_unanswerable", _not_unanswerable)
    resp = await rig.run(NAPOLEON, entity_refs=["part 123"])
    assert seen == ["part 123"]
    assert resp.provenance["preemption_path"] == "class_recall_unanswerable_fallback"


# 9
def _supervisor_reasons():
    src = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "_ENGINE_O_ABSTENTION_REASONS" in targets:
            return {n.value for n in ast.walk(node.value)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return set()


@pytest.mark.asyncio
async def test_the_abstention_reason_is_one_the_supervisor_explains(rig):
    reasons = _supervisor_reasons()
    assert reasons, "_ENGINE_O_ABSTENTION_REASONS not found"
    resp = await rig.run(NAPOLEON)
    assert resp.provenance["abstention_reason"] in reasons


# 10
@pytest.mark.asyncio
async def test_CONTROL_a_truly_empty_recall_keeps_its_message(rig, monkeypatch):
    # An empty pool first triggers the cold-start SPARQL fallback; stub it empty too, so both
    # attempts fail and the recall is truly empty.
    async def _no_rows(*a, **kw):
        return []

    monkeypatch.setattr(rig.eo, "execute_sparql", _no_rows)
    rig.pool = []
    resp = await rig.run(NAPOLEON)
    assert "No ontology classes found" in resp.reasoning
    assert "abstention_reason" not in (resp.provenance or {})
