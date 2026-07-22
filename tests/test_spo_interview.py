"""Pin the SPO interview's PURE core (ADR-0029 Slice 2) — the enforceable machinery,
no network, no LLM. Proves the three strengthenings over the old BPMN interview:
server-side pick validation, verb-from-eligibility, and termination-on-validity.

Run:  PYTHONPATH=agent_fleet/restate_analyst pytest tests/test_spo_interview.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RA = Path(__file__).resolve().parent.parent / "agent_fleet" / "restate_analyst"
if str(_RA) not in sys.path:
    sys.path.insert(0, str(_RA))

from spo_interview import (  # noqa: E402
    InterviewState, PickRefused, _parse_classes, _parse_verbs,
    emit_definition_yaml, try_finalize, validate_pick,
)
from workflow_definition import load_workflow_definition  # noqa: E402

_AGENTTASK = "http://invincible-agent/mesh#AgentTask"

_VERBS_RESP = {"verbs": [
    {"verb_iri": "mesh:analyzeWithCodeAgent", "verb_local": "analyzeWithCodeAgent",
     "output_uri": "http://invincible-agent/mesh#AgentResponse",
     "endpoint_url": "http://iagent-engine-a:8081/analyze",
     "owner_persona": "DATA_STEWARD", "domains": ["MAINTENANCE", "MANUFACTURING"]},
]}
_CLASSES_RESP = {"classes": [
    {"uri": _AGENTTASK, "label": "Agent Task"},
    {"uri": "http://invincible-agent/mesh#Dataset", "label": "Dataset"},
]}


# --- parsing -----------------------------------------------------------------

def test_parse_classes_keeps_uri_and_label():
    out = _parse_classes(_CLASSES_RESP)
    assert {c["uri"] for c in out} == {_AGENTTASK, "http://invincible-agent/mesh#Dataset"}


def test_parse_verbs_carries_advisory_permission():
    """The verb set is the predicate the old interview never asked; each verb carries an
    ADVISORY permission requirement (Decision A — never a gate at authoring)."""
    out = _parse_verbs(_VERBS_RESP)
    assert len(out) == 1
    v = out[0]
    assert v["verb_iri"] == "mesh:analyzeWithCodeAgent"
    assert v["output_uri"] == "http://invincible-agent/mesh#AgentResponse"  # -> expected_output
    assert v["requires_advisory"]["owner_persona"] == "DATA_STEWARD"
    assert "MAINTENANCE" in v["requires_advisory"]["domains"]


def test_parse_verbs_empty_safe():
    assert _parse_verbs({}) == [] and _parse_verbs({"verbs": []}) == []


# --- server-side select-from-authorized-set enforcement ----------------------

def test_validate_pick_accepts_exact_match():
    assert validate_pick(_AGENTTASK, _parse_classes(_CLASSES_RESP)) == _AGENTTASK


def test_validate_pick_refuses_out_of_set():
    """The old exact-match was PROMPT-ONLY; here a hallucinated pick is REFUSED server-side."""
    with pytest.raises(PickRefused):
        validate_pick("http://invincible-agent/mesh#NotAThing", _parse_classes(_CLASSES_RESP))


def test_validate_pick_refuses_ineligible_verb_inexpressible_by_construction():
    """The un-doomable-by-construction property in test form: a verb NOT in the eligible
    set (from /find_compatible_verbs) cannot be selected — it was never offered."""
    verbs = _parse_verbs(_VERBS_RESP)
    assert validate_pick("mesh:analyzeWithCodeAgent", verbs, key="verb_iri") == "mesh:analyzeWithCodeAgent"
    with pytest.raises(PickRefused):
        validate_pick("mesh:publishArtifact", verbs, key="verb_iri")  # not eligible for AgentTask


def test_validate_pick_suggests_closest():
    verbs = _parse_verbs(_VERBS_RESP)
    with pytest.raises(PickRefused) as ei:
        validate_pick("analyzeWithCodeAgent", verbs, key="verb_iri")  # local, not the full IRI
    assert "Closest" in str(ei.value)


# --- termination = the definition VALIDATES (Decision B) ---------------------

def _promotion_state():
    return InterviewState(
        id="promote_answer_artifact", name="Promote an AnswerArtifact",
        classification="DATA_ENGINEERING",
        steps=[
            {"kind": "human_await", "id": "approve_promotion",
             "audience": "promotion:DATA_ENGINEERING", "subject_ref": "{artifact_urn}"},
            {"kind": "direct_call", "id": "publish_artifact",
             "endpoint": "{publish_endpoint}", "capability": "mesh:publishArtifact"},
        ],
    )


def test_terminates_when_definition_validates():
    wf, gaps = try_finalize(_promotion_state())
    assert gaps == []
    assert wf is not None and wf.id == "promote_answer_artifact" and len(wf.steps) == 2


def test_incomplete_no_steps_does_not_terminate():
    wf, gaps = try_finalize(InterviewState(id="x", name="y", steps=[]))
    assert wf is None
    assert any("steps" in g for g in gaps)


def test_incomplete_spo_step_missing_verb_reports_the_gap():
    """A partial spo_operation (subject chosen, verb pending) does NOT validate; the gap
    names the missing verb — which is exactly the next question to ask."""
    state = InterviewState(id="x", name="y", steps=[
        {"kind": "spo_operation", "id": "s1", "subject": _AGENTTASK},  # no verb
    ])
    wf, gaps = try_finalize(state)
    assert wf is None
    assert any("verb" in g.lower() for g in gaps)


def test_direct_call_missing_capability_does_not_terminate():
    """Q3: a capability-less direct_call is INEXPRESSIBLE — the schema refuses it, so the
    interview cannot finalize a definition with an ungated step."""
    state = InterviewState(id="x", name="y", steps=[
        {"kind": "direct_call", "id": "d1", "endpoint": "http://x"},  # no capability
    ])
    wf, gaps = try_finalize(state)
    assert wf is None
    assert any("capability" in g.lower() for g in gaps)


# --- emit: interview authors, human asserts (Decision C) ---------------------

def test_emit_yaml_round_trips_through_the_loader(tmp_path):
    """The emitted file is a valid policy/workflows/<id>.yaml — it LOADS back into an
    equal definition, so the human commits a real, executable artifact."""
    wf, _ = try_finalize(_promotion_state())
    assert wf is not None
    text = emit_definition_yaml(wf)
    assert text.startswith("#")  # carries the human-asserts header
    p = tmp_path / "promote_answer_artifact.yaml"
    p.write_text(text, encoding="utf-8")
    loaded = load_workflow_definition(p)
    assert loaded.id == wf.id
    assert loaded.name == wf.name
    assert [s.id for s in loaded.steps] == [s.id for s in wf.steps]
    assert [s.kind for s in loaded.steps] == ["human_await", "direct_call"]
