"""THE AUTONOMOUS STEP KIND — dispatch when clean, escalate the whole notice when not.

`dispatch_fanout` is the autonomous counterpart of `human_await`, and like it, its semantics are
EXECUTOR-OWNED. The YAML declares WHAT (a capability-gated dispatch of this review's batch); the
executor owns HOW: gate, synthesize the empty decision, run the shared pure core, then either fan out
on the sealed exactly-once path or escalate.

THE PROPERTY THIS FILE EXISTS TO PIN: **escalation cannot be omitted, because it is not authored.**
A definition that dispatches without an escalation path is unexpressible — there is no field for it.
That is the seal-inheritance principle earning its second dividend (the first was `human_await`'s
mechanics: server-authored batch, race guard, fan-out, none of them definition content).

WHY IT IS NOT `direct_call` ANY MORE: it never made a generic HTTP call. It POSTed a fixed envelope
to prove the capability gate existed — which it did faithfully for months while the gate denied it.
The false generality is precisely what let `{dispatch_endpoint}` sit unbound: a generic caller is
ALLOWED an arbitrary endpoint, so nothing could tell that this one was nonsense.

Run:  uv run --frozen python -m pytest tests/test_dispatch_fanout_step.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_RA = _ROOT / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.workflow_definition import (  # noqa: E402
    DispatchFanoutStep, WorkflowDefinition, WorkflowDefinitionError, get_workflow_definition,
)

_WF = _ROOT / "policy" / "workflows"


# ===========================================================================
# THE DECLARATION — what a definition may and may not say
# ===========================================================================
def test_the_shipped_autonomous_definition_uses_the_new_kind():
    d = get_workflow_definition("autonomous_review")
    kinds = [(s.kind, s.id) for s in d.steps]
    assert kinds == [("dispatch_fanout", "dispatch_dispositions")], kinds


def test_the_step_declares_NO_endpoint():
    """There is no URL for a definition author to get wrong — the step dispatches the review's OWN
    batch through the sealed fan-out. Removing the field removes the class of bug that hid here."""
    raw = yaml.safe_load((_WF / "autonomous_review.yaml").read_text(encoding="utf-8"))
    step = raw["steps"][0]
    assert "endpoint" not in step, "an endpoint on this kind is the false generality returning"
    assert set(step) <= {"kind", "id", "capability"}, step


def test_the_capability_is_REQUIRED_so_an_UNGATED_autonomous_dispatch_is_UNEXPRESSIBLE():
    """The one thing this kind must never permit. An autonomous dispatch that could be declared
    ungated would let a definition author remove the gate the recorded [403] proved."""
    with pytest.raises(Exception):
        DispatchFanoutStep(kind="dispatch_fanout", id="x")          # no capability
    with pytest.raises(Exception):
        DispatchFanoutStep(kind="dispatch_fanout", id="x", capability="")   # blank


def test_a_definition_CANNOT_declare_an_escalation_path():
    """ESCALATION IS NOT AUTHORED — the seal-inheritance property, asserted as unexpressibility.
    Pydantic models here forbid extra fields only if configured to; what matters is that no field
    EXISTS for it, so every definition gets the executor's escalation and none can opt out."""
    assert "escalation" not in DispatchFanoutStep.model_fields
    assert set(DispatchFanoutStep.model_fields) == {"kind", "id", "capability"}


def test_generic_direct_call_SURVIVES_unchanged():
    """The rename narrowed one step; it did not delete the escape hatch. `direct_call` keeps its
    endpoint and its ADR-0029 promotion path."""
    d = WorkflowDefinition.model_validate({
        "id": "x", "name": "x", "classification": "UNCLASSIFIED",
        "steps": [{"kind": "direct_call", "id": "s", "endpoint": "http://h/p",
                   "capability": "mesh:x"}],
    })
    assert d.steps[0].kind == "direct_call"
    assert d.steps[0].endpoint == "http://h/p"


def test_an_unknown_kind_still_fails_LOUDLY():
    with pytest.raises((WorkflowDefinitionError, Exception)):
        WorkflowDefinition.model_validate({
            "id": "x", "name": "x", "classification": "UNCLASSIFIED",
            "steps": [{"kind": "not_a_kind", "id": "s"}],
        })


# ===========================================================================
# THE EXECUTOR BRANCH — asserted on the source, scoped to the branch
# ===========================================================================
def _branch_source() -> str:
    """The branch's EXECUTABLE body — imports stripped.

    The first version of this helper included the lazy import block, so the ordering test below
    compared the position of `resolve_batch` in an IMPORT LIST against `check_can_invoke` in
    another, and went red while the code was correct. A positional assertion is only about
    execution order if the text it measures is execution.
    """
    src = (_RA / "main.py").read_text(encoding="utf-8")
    start = src.index('elif step.kind == "dispatch_fanout":')
    end = src.index('results.append({', src.index('"status": "SUCCESS"', start))
    body = src[start:end]
    return body[body.index("_fp = request.get("):]


def test_the_gate_runs_BEFORE_the_batch_is_resolved():
    """Order is the claim: a caller who may not dispatch must be refused before any disposition is
    computed, not after. Asserted positionally because that is where the property lives."""
    b = _branch_source()
    assert b.index("check_can_invoke") < b.index("resolve_batch"), (
        "the capability gate must precede resolution — otherwise an unauthorized caller's notice "
        "still gets resolved and only the send is refused")


def test_the_refusal_catch_is_TYPED():
    """`except BatchRefusal`, never `except ValueError` — or escalation becomes an error sink and a
    genuine bug is silently converted into human workload."""
    b = _branch_source()
    assert "except BatchRefusal" in b
    assert "except ValueError" not in b, (
        "a bare ValueError catch here files phantom reviews for defects, each looking exactly like "
        "policy working")


def test_the_escalation_uses_a_DERIVED_key():
    b = _branch_source()
    assert "escalation_request_key(" in b, (
        "re-sending the identical trigger under the identical key collides with the very run that "
        "refused it — the escalation is swallowed and the notice dropped")
    assert '"admitted_by": "escalation"' in b, (
        "the escalated review must say policy REFUSED, not report the rung that admitted it")


def test_the_dispatch_reuses_the_SEALED_fan_out_and_names_POLICY_as_actor():
    b = _branch_source()
    assert "fan_out_dispatch(" in b, "one dispatcher, two triggers — do not mint a second"
    assert "acted_by=f\"policy:" in b, (
        "a service must never be recorded as the approver — the 2026-08-05 field split exists for "
        "exactly this")


def test_the_escalation_branch_dispatches_NOTHING():
    """Zero-compensation, asserted structurally: the escalation path must `continue` before reaching
    the fan-out, so a refused notice has no partial effects to unwind."""
    b = _branch_source()
    esc = b.index("ESCALATED")
    assert "continue" in b[esc:esc + 400], "the escalation branch must not fall through to dispatch"
    assert b.index("continue", esc) < b.index("fan_out_dispatch("), (
        "escalation falls through into the fan-out — a refused notice would dispatch")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

# ===========================================================================
# THE ENVELOPE READER — a renamed step must never report failure over landed effects
# ===========================================================================
def test_the_workflow_accepts_the_dispatch_kind_it_actually_RUNS():
    """WITNESSED LIVE 2026-08-09, and the worst reporting direction available.

    The step was renamed `direct_call` -> `dispatch_fanout`; this reader was not updated with it. So
    the FIRST successful autonomous dispatch — two per-item DispatchItem invocations, both
    `completed success` on the sealed keys — was followed by:

        [500] autonomous_review definition produced no direct_call result

    The effects had landed and the record denied them. "Approved but the effects never landed" has a
    whole triage path in this codebase; this is its INVERSE, and it would send an operator to
    re-drive work that already succeeded.

    Asserted on the reader itself so the step kind and its consumer cannot drift apart again.
    """
    src = (_RA / "autonomous_review_workflow.py").read_text(encoding="utf-8")
    reader = src[src.index("dispatched = next("):src.index("if dispatched is None:")]
    assert '"dispatch_fanout"' in reader, (
        "the workflow does not recognise the kind its own definition declares — a successful "
        "dispatch will be reported as a failure")
    assert '"direct_call"' in reader, "generic direct_call must stay accepted for its own callers"


def test_ESCALATION_is_reported_as_an_OUTCOME_not_a_failure():
    """A refused notice reached a human ON PURPOSE. Reporting that as failure would make every
    escalation look like a broken pipeline, and `admitted_by` must say `escalation` rather than
    repeat the rung — the record would otherwise claim policy acted where policy declined."""
    src = (_RA / "autonomous_review_workflow.py").read_text(encoding="utf-8")
    tail = src[src.index("_escalated = dispatched.get("):]
    assert '"status": "ESCALATED" if _escalated else "RESOLVED"' in tail
    assert '"admitted_by": "escalation" if _escalated else "policy"' in tail
