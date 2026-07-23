"""SPO interview — the ENFORCEMENT FUNNEL sealed deterministically (ADR-0029 Slice 2).

The BAML shell is stochastic and cluster-gated; the *enforcement* is not. This drives the
pure pick-application funnel (``apply_pick`` + the granular helpers) with a SCRIPTED sequence
of picks — no LLM — and proves the properties the design promises:

  * select-from-authorized-set is ENFORCED server-side (out-of-set subject / verb / audience
    is hard-refused, not merely discouraged in a prompt);
  * termination is the definition VALIDATING (not an LLM flag) — gaps until required fields
    are present, then a valid ``WorkflowDefinition``;
  * the interview can author the Slice-1 promotion definition (``promote_answer_artifact.yaml``)
    AND an ``spo_operation`` that exercises the novel verb question;
  * the emitted YAML round-trips through ``load_workflow_definition`` (what a human commits).

Run:  cd agent_fleet/restate_analyst && uv run --frozen pytest ../../tests/test_spo_interview_orchestration.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst import spo_interview as si  # noqa: E402
from agent_fleet.restate_analyst.workflow_definition import (  # noqa: E402
    load_workflow_definition,
)

# --- Fixture authorized sets (what Engine O would return; here fixed so the funnel is
#     tested without a cluster). The verb set is what /find_compatible_verbs returns for
#     the AgentTask subject — proven live in the design doc's §7 probe. ---------------
SUBJECTS = [{"uri": "http://invincible-agent/mesh#AgentTask", "label": "Agent Task"}]
VERBS_FOR_AGENTTASK = [
    {
        "verb_iri": "mesh:analyzeWithCodeAgent",
        "verb_local": "analyzeWithCodeAgent",
        "output_uri": "http://invincible-agent/mesh#AgentResponse",
        "endpoint_url": "http://iagent-engine-a:8080/analyze",
        "requires_advisory": {"domains": ["DATA_ENGINEERING"], "owner_persona": "DATA_STEWARD"},
    }
]
AUDIENCES = [{"audience": "promotion:DATA_ENGINEERING"}]
CAPABILITIES = [{"capability": "mesh:publishArtifact"}]


# ---------------------------------------------------------------------------
# 1. Out-of-set picks are HARD-REFUSED (the enforcement, not the prompt)
# ---------------------------------------------------------------------------

def test_out_of_set_subject_refused():
    st = si.InterviewState()
    with pytest.raises(si.PickRefused):
        si.apply_pick(
            st,
            {"action": "AddSpoStep", "subject_uri": "http://evil/mesh#NotAThing",
             "verb_iri": "mesh:analyzeWithCodeAgent"},
            authorized_subjects=SUBJECTS, authorized_verbs=VERBS_FOR_AGENTTASK,
            authorized_audiences=AUDIENCES,
        )
    assert st.steps == []  # nothing leaked into the definition


def test_out_of_set_verb_refused():
    st = si.InterviewState()
    with pytest.raises(si.PickRefused):
        si.apply_pick(
            st,
            {"action": "AddSpoStep", "subject_uri": "http://invincible-agent/mesh#AgentTask",
             "verb_iri": "mesh:deleteEverything"},
            authorized_subjects=SUBJECTS, authorized_verbs=VERBS_FOR_AGENTTASK,
            authorized_audiences=AUDIENCES,
        )
    assert st.steps == []


def test_out_of_set_audience_refused():
    st = si.InterviewState()
    with pytest.raises(si.PickRefused):
        si.apply_pick(
            st,
            {"action": "AddHumanAwait", "audience": "promotion:AVIATION"},  # not granted
            authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES,
        )
    assert st.steps == []


def test_ungated_direct_call_inexpressible():
    """RULING Q3: a direct_call with no capability cannot be applied (never ungated)."""
    st = si.InterviewState()
    with pytest.raises(ValueError):
        si.apply_pick(
            st,
            {"action": "AddDirectCall", "endpoint": "http://x/publish", "capability": ""},
            authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES,
        )
    assert st.steps == []


# ---------------------------------------------------------------------------
# 2. The verb question — expected_output derived from the verb's FIXED type (ADR-0030)
# ---------------------------------------------------------------------------

def test_spo_step_derives_fixed_output_type():
    st = si.InterviewState()
    step = si.apply_pick(
        st,
        {"action": "AddSpoStep", "subject_uri": "http://invincible-agent/mesh#AgentTask",
         "verb_iri": "mesh:analyzeWithCodeAgent"},
        authorized_subjects=SUBJECTS, authorized_verbs=VERBS_FOR_AGENTTASK,
        authorized_audiences=AUDIENCES,
    )
    assert step["kind"] == "spo_operation"
    assert step["subject"] == "http://invincible-agent/mesh#AgentTask"
    assert step["verb"] == "mesh:analyzeWithCodeAgent"
    # NOT invented by the model — pulled from the verb's registered output_uri.
    assert step["expected_output"] == "http://invincible-agent/mesh#AgentResponse"


# ---------------------------------------------------------------------------
# 3. Termination = the definition VALIDATES (gaps until required fields present)
# ---------------------------------------------------------------------------

def test_termination_is_validity_not_a_flag():
    st = si.InterviewState()
    # id/name set, but no steps yet -> NOT done (steps has min_length=1).
    si.apply_pick(st, {"action": "SetMetadata", "workflow_id": "wf1", "workflow_name": "WF One"},
                  authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES)
    wf, gaps = si.try_finalize(st)
    assert wf is None and gaps, "empty-steps definition must not validate"

    # add one valid step -> now it validates (server-side, no LLM 'ready' flag).
    si.apply_pick(st, {"action": "AddHumanAwait", "audience": "promotion:DATA_ENGINEERING"},
                  authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES)
    wf, gaps = si.try_finalize(st)
    assert wf is not None and gaps == []


# ---------------------------------------------------------------------------
# 4. THE SEAL: author the promotion definition + an spo_operation, end to end
# ---------------------------------------------------------------------------

def _author_promotion_plus_spo() -> si.InterviewState:
    """Scripted interview — the exact pick sequence a driven conversation would produce."""
    st = si.InterviewState()
    si.apply_pick(st, {
        "action": "SetMetadata", "workflow_id": "promote_answer_artifact",
        "workflow_name": "Promote an AnswerArtifact (DATA_ENGINEERING) before publish",
        "classification": "DATA_ENGINEERING",
    }, authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES)
    # An spo_operation step — exercises the NOVEL verb question (subject -> verb).
    si.apply_pick(st, {
        "action": "AddSpoStep", "subject_uri": "http://invincible-agent/mesh#AgentTask",
        "verb_iri": "mesh:analyzeWithCodeAgent", "step_id": "analyze",
    }, authorized_subjects=SUBJECTS, authorized_verbs=VERBS_FOR_AGENTTASK, authorized_audiences=AUDIENCES)
    # The sealed HITL human-await.
    si.apply_pick(st, {
        "action": "AddHumanAwait", "audience": "promotion:DATA_ENGINEERING",
        "step_id": "approve_promotion", "step_title": "Approve promotion",
        "step_summary": "Promote this answer artifact to the published catalog",
    }, authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES)
    # The transitional gated publish.
    si.apply_pick(st, {
        "action": "AddDirectCall", "endpoint": "{publish_endpoint}",
        "capability": "mesh:publishArtifact", "step_id": "publish_artifact",
    }, authorized_subjects=SUBJECTS, authorized_verbs=[], authorized_audiences=AUDIENCES,
       authorized_capabilities=CAPABILITIES)
    return st


def test_seal_authors_a_valid_definition():
    st = _author_promotion_plus_spo()
    wf, gaps = si.try_finalize(st)
    assert wf is not None, f"definition did not validate: {gaps}"
    kinds = [s.kind for s in wf.steps]
    assert kinds == ["spo_operation", "human_await", "direct_call"]
    # The human_await + direct_call match the Slice-1 promotion mechanics.
    approve = next(s for s in wf.steps if s.kind == "human_await")
    publish = next(s for s in wf.steps if s.kind == "direct_call")
    assert approve.audience == "promotion:DATA_ENGINEERING"
    assert publish.capability == "mesh:publishArtifact"


def test_seal_emitted_yaml_round_trips(tmp_path):
    st = _author_promotion_plus_spo()
    wf, _ = si.try_finalize(st)
    yaml_text = si.emit_definition_yaml(wf)
    assert yaml_text.lstrip().startswith("#")  # the human-commit header
    f = tmp_path / "authored.yaml"
    f.write_text(yaml_text, encoding="utf-8")
    reloaded = load_workflow_definition(f)  # the exact loader the runner uses
    assert reloaded.id == "promote_answer_artifact"
    assert [s.kind for s in reloaded.steps] == ["spo_operation", "human_await", "direct_call"]


def test_seal_matches_committed_promotion_mechanics():
    """The interview-authored definition carries the SAME human_await audience + gated
    publish capability as the committed Slice-1 promotion YAML (the workflow known to work)."""
    committed = load_workflow_definition(_REPO / "policy" / "workflows" / "promote_answer_artifact.yaml")
    authored, _ = si.try_finalize(_author_promotion_plus_spo())
    c_await = next(s for s in committed.steps if s.kind == "human_await")
    a_await = next(s for s in authored.steps if s.kind == "human_await")
    assert a_await.audience == c_await.audience
    c_call = next(s for s in committed.steps if s.kind == "direct_call")
    a_call = next(s for s in authored.steps if s.kind == "direct_call")
    assert a_call.capability == c_call.capability


# ---------------------------------------------------------------------------
# 5. Decision D — the operation-subject menu is the capability graph
# ---------------------------------------------------------------------------

def test_operation_subject_parser_and_enforcement():
    """/operable_subjects response parses to the {uri,label} funnel shape, and the
    same select-from-authorized-set enforcement applies (Decision D — the operation
    menu is verb-bearing subjects, sourced from the capability graph)."""
    payload = {"subjects": [
        {"uri": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
         "label": "Technical Manual"},
        {"uri": "", "label": "junk-dropped"},
    ], "count": 1, "domain": "MAINTENANCE"}
    subs = si._parse_operation_subjects(payload)
    assert subs == [{"uri": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
                     "label": "Technical Manual"}]
    tm = subs[0]["uri"]
    assert si.validate_pick(tm, subs, key="uri") == tm
    with pytest.raises(si.PickRefused):
        si.validate_pick("http://not/offered", subs, key="uri")
