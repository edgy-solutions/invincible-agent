"""THE JOIN, NOT THE HALVES: Engine O's Q7(a) answer reaches the supervisor's verb pool.

The architect's Q7(a) ruling: the resolver prefers classes some verb declares as INPUT over
classes that are only outputs. Lane 74's seal
(`test_a_dead_end_pool_grounds_on_the_input_the_question_names.py`) drives the REAL Engine O
`resolve()` and asserts what it OFFERS. Nothing asserted the join: that `_classify_route`,
handed that answer, builds a verb pool holding the question's verb. This file does.

Chain under test, all real except the three network doubles: real `resolve()` (74's rig:
recalled pools, verb rows and the BAML pick are doubles) -> `requests.post("/resolve")` double
returns that body -> real `_resolve_subject` -> real `_find_compatible_verbs` whose
`/find_compatible_verbs` double answers from the REAL `safety_agent.VERBS` declarations
(exact `input_uri` match; no subClassOf chain in the double) -> real arity gate -> telemetry.

The control (arm d) runs the same real resolve() with the input-declared step disabled, which
is the pre-Q7a answer 201 measured: dead-end pool, resolved FailureRecord / RiskAssessment.
Without it the arms above could pass on a fixture that never distinguished the behaviours.

Run: uv run pytest tests/routing/test_the_router_takes_the_verb_the_input_declared_subject_carries.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 74's rig fixture and measured data (201's pools, 198's verb rows), imported not copied.
from tests.routing.test_a_dead_end_pool_grounds_on_the_input_the_question_names import (  # noqa: E402,F401
    COMPONENT, FAILURE_RECORD, Q3, Q3_POOL, Q3_ROWS, Q4, Q4_POOL, Q4_ROWS, SAFETY, SCI,
    WORK_ORDER, rig,
)
from agent_fleet.safety_agent.main import VERBS  # noqa: E402  (the real declarations)

RISK_ASSESSMENT = SAFETY + "RiskAssessment"
_SUP_PATH = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"


@pytest.fixture(scope="session")
def sup():
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if f and Path(f).resolve() == _SUP_PATH.resolve():
            yield mod
            return
    spec = importlib.util.spec_from_file_location("dynamic_supervisor_q7_router_test", str(_SUP_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Ctx:
    log = _Log()


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _wire_verbs(subject):
    """What /find_compatible_verbs returns: the real safety declarations whose input_uri is the subject."""
    return [
        {"verb_iri": v["verb"], "input_uri": v["input_uri"], "output_uri": v["output_uri"],
         "endpoint_url": "http://engine-safety/x", "owner_persona": "X", "domains": ["SUSTAINMENT"],
         "cost_class": "cheap", "arity": "any", "slots": "[]"}
        for v in VERBS if v["input_uri"] == subject
    ]


def _route(rig, sup, monkeypatch, query, pick):
    """Real resolve() -> real _classify_route. Returns (resolve_response, telemetry)."""
    orig = rig.baml.ClassifyDomainIntent

    async def _pick(**kw):
        r = await orig(**kw)
        if pick is not None:
            # the double may only pick what the resolver OFFERED, or the pick is not a pick
            assert pick in rig.baml.offered, ("pick not offered", pick, rig.baml.offered)
            r.resolved_uri = pick
        return r
    rig.baml.ClassifyDomainIntent = _pick
    box = {}

    def _post(url, *a, **k):
        suffix = url.rsplit("/", 1)[-1]
        if suffix == "resolve":
            box["resp"] = asyncio.run(rig.run(query))
            return _Resp(box["resp"].model_dump())
        if suffix == "find_compatible_verbs":
            box["subject"] = k["json"]["subject_uri"]
            return _Resp({"verbs": _wire_verbs(box["subject"])})
        if suffix == "classify_predicate":
            return _Resp({"resolved_verb_iri": "UNKNOWN", "confidence_score": 0.0,
                          "classify_called": True, "candidate_verb_iris": []})
        return _Resp({})
    monkeypatch.setattr(sup.requests, "post", _post)
    _status, _pred, tele = sup._classify_route(
        _Ctx(), query, ["SUSTAINMENT"], routing_domain="SUSTAINMENT", user_email="bob@example.com")
    # None when the supervisor never searched verbs (an UNKNOWN subject is never searched).
    return box["resp"], box.get("subject"), tele


def _pool(tele):
    return {str(v).rsplit(":", 1)[-1].rsplit("#", 1)[-1] for v in tele.get("compatible_verb_iris") or []}


def test_the_wire_double_is_the_real_declarations_and_agrees_with_74s_rows():
    # The doubled rows 74 recalls must name inputs the real verbs declare, or the join is fiction.
    declared = {(v["verb"].split(":")[-1], v["input_uri"]) for v in VERBS}
    for row in Q4_ROWS[:2] + Q3_ROWS[:1]:
        assert (row["verb_iri"].rsplit("#", 1)[-1], row["input_uri"]) in declared


# a
@pytest.mark.parametrize("pick", [SCI, COMPONENT])
def test_q4_either_llm_pick_leaves_whatFailedOnThisPart_in_the_pool(rig, sup, monkeypatch, pick):
    resp, subject, tele = _route(rig, sup, monkeypatch, Q4, pick)
    assert subject == pick and subject in {SCI, COMPONENT}
    assert "whatFailedOnThisPart" in _pool(tele), (subject, tele["compatible_verb_iris"])


# b
def test_q3_pool_holds_assessDeferralRisk(rig, sup, monkeypatch):
    rig.pool, rig.rows = Q3_POOL, Q3_ROWS
    resp, subject, tele = _route(rig, sup, monkeypatch, Q3, None)
    assert subject == WORK_ORDER
    assert "assessDeferralRisk" in _pool(tele), (subject, tele["compatible_verb_iris"])


# c
@pytest.mark.parametrize("q", [Q4, Q3])
def test_the_dead_ends_ride_the_route_telemetry_as_input_declared_preferred(rig, sup, monkeypatch, q):
    dead = Q4_POOL if q == Q4 else Q3_POOL
    if q == Q3:
        rig.pool, rig.rows = Q3_POOL, Q3_ROWS
    resp, subject, tele = _route(rig, sup, monkeypatch, q, None)
    got = {e["uri"] for e in tele["eligibility_excluded"] if e.get("reason") == "input_declared_preferred"}
    assert got == set(dead)


# d
@pytest.mark.parametrize("q,pool,rows,pick,verb", [
    (Q4, Q4_POOL, Q4_ROWS, FAILURE_RECORD, "whatFailedOnThisPart"),
    (Q3, Q3_POOL, Q3_ROWS, RISK_ASSESSMENT, "assessDeferralRisk"),
])
def test_control_the_pre_q7a_answer_leaves_the_verb_out_of_the_pool(rig, sup, monkeypatch, q, pool, rows, pick, verb):
    async def _off(request, domains):
        return [], {"reason": "disabled_by_control"}
    monkeypatch.setattr(rig.eo, "_input_declared_pool", _off)
    rig.pool, rig.rows = pool, rows
    resp, subject, tele = _route(rig, sup, monkeypatch, q, pick)
    # SINCE THE ADMISSION RULE (2026-10-20) the dead ends are no longer offered: with Q7(a) off
    # the pool EMPTIES, so the model is never asked and Engine O abstains. 201 measured the
    # dead-end `pick`; the verb is out of the pool either way, which is what this control is for.
    assert rig.baml.offered is None
    assert resp.resolved_uri == "UNKNOWN"
    assert resp.provenance["abstention_reason"] == "no_compatible_verbs"
    assert subject is None, "an UNKNOWN subject was searched for verbs"
    assert tele["fallback_reason"] == "no_compatible_verbs"
    assert verb not in _pool(tele)
    assert not any(e.get("reason") == "input_declared_preferred" for e in tele["eligibility_excluded"])
