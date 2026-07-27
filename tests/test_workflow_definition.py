"""Unit tests for the SPO-native WorkflowDefinition schema + loader (ADR-0029
Slice 1 foundation). Pure — no runner, no deploy, no seal. Verifies the git
YAML parses, the step kinds validate, and the RULING-Q3 gate holds (a
direct_call with no capability is a schema error — a permanently-ungated step
kind cannot be expressed).

Run:
    uv run --with pydantic --with pyyaml python tests/test_workflow_definition.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MOD = _REPO / "agent_fleet" / "restate_analyst" / "workflow_definition.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("workflow_definition", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


wd = _load_module()


def test_promotion_definition_loads() -> None:
    path = _REPO / "policy" / "workflows" / "promote_answer_artifact.yaml"
    d = wd.load_workflow_definition(path)
    assert d.id == "promote_answer_artifact"
    assert d.classification == "DATA_ENGINEERING"
    kinds = [s.kind for s in d.steps]
    assert kinds == ["human_await", "direct_call"], kinds
    # human_await carries the sealed HITL audience
    aw = d.steps[0]
    assert aw.audience == "promotion:DATA_ENGINEERING"
    # direct_call is GATED — capability present + non-empty (RULING Q3)
    pub = d.steps[1]
    assert pub.capability == "mesh:publishArtifact"


def test_grouped_review_definition_loads() -> None:
    """M3.1 artifact: the grouped disposition-review expressed as a WorkflowDefinition
    (human_await grouped task -> gated direct_call dispatch). Executor + the spo_operation
    extraction steps are deferred (ADR-0029 prereqs); this asserts the DATA parses + validates
    against the sealed Slice-1 model, and that the audience was de-pcn'd (M2) to a generic,
    compartment-bound disposition-review key."""
    path = _REPO / "policy" / "workflows" / "grouped_review.yaml"
    d = wd.load_workflow_definition(path)
    assert d.id == "grouped_review"
    kinds = [s.kind for s in d.steps]
    assert kinds == ["human_await", "direct_call"], kinds
    aw = d.steps[0]
    assert aw.audience.startswith("disposition_review:"), aw.audience   # generic, not pcn_disposition
    assert aw.subject_ref == "{notice_ref}"
    disp = d.steps[1]                                                    # dispatch is GATED (Q3)
    assert disp.capability == "mesh:dispatchDispositions"


def test_load_all_keys_by_id() -> None:
    workflows = wd.load_all_workflows(_REPO / "policy" / "workflows")
    assert "promote_answer_artifact" in workflows
    assert "grouped_review" in workflows


def test_direct_call_without_capability_is_rejected() -> None:
    """The Q3 gate at the schema layer: a direct_call must declare a capability
    (Topaz can_invoke). No capability -> validation error, so the model can NOT
    express a permanently-ungated step."""
    bad = {
        "id": "x",
        "name": "x",
        "steps": [{"kind": "direct_call", "id": "s1", "endpoint": "http://x"}],
    }
    try:
        wd.WorkflowDefinition.model_validate(bad)
    except Exception:  # pydantic ValidationError
        return
    raise AssertionError("direct_call with no capability should have been rejected")


def test_unknown_step_kind_is_rejected() -> None:
    bad = {"id": "x", "name": "x", "steps": [{"kind": "nope", "id": "s1"}]}
    try:
        wd.WorkflowDefinition.model_validate(bad)
    except Exception:
        return
    raise AssertionError("unknown step kind should have been rejected")


def test_empty_steps_is_rejected() -> None:
    try:
        wd.WorkflowDefinition.model_validate({"id": "x", "name": "x", "steps": []})
    except Exception:
        return
    raise AssertionError("empty steps should have been rejected")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
