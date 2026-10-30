"""The supervisor's approval IS the release: a maintenance case closes with no signal sent.

RULED 2026-10-28 (architect): "the supervisor's approval is the release. There is no alice step."
`maint_release`'s `action` emit declares `disposes: released`, so the run's outcome is `released`
without a `tier_ack`, the runner writes the ActionRecord and the seeded_by stamp at that outcome,
and `maint_release_chaining` closes the case.

Arms (each walks a fresh case through the real definitions and chaining tables, NO signal sent):
  a1  evacuate_for_depot -> supervisor approves -> maint_release -> closed; the record is written
      once, its approval_chain names the supervisor, and the seeded_by stamp ran.
  a2  replace_after_resupply (no supervisor) -> maint_release -> closed; record written once.
  a3  REPLAY: a suspended instance replays its JOURNALLED definition
      (`ctx.run("definition", _load)` in `workflow_runner._run_instance`), so an instance begun
      before this change still waits for `tier_ack`; its `released` must still close. Asserted at
      the CHAINING level (the harness runs registered definitions, not an inline one): the old
      text validates against the model, ends in a signal whose `accepts` carries `released`, and
      `chain("maint_release", released)` -> `closed` under the new table.
  a4  the released transition's `by` is the chain's last approver (the supervisor, or with none,
      the maintainer who chose), never "system": the emit acts on the approval that reached it.

Run: uv run pytest tests/routing/test_the_supervisor_approval_is_the_release.py -v
"""
from __future__ import annotations

import pytest

from agent_fleet.restate_analyst import case_routing as R
from agent_fleet.restate_analyst import workflow_definition as wd
from tests.test_a_case_runs_from_trigger_to_terminal import wr  # noqa: F401
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- autouse fixtures
    DECIDE, REVIEW, _declared_walk_double, _path, _real_policy, registered)
from tests.test_the_runner_writes_the_action_record_at_released import (  # noqa: F401
    DELEGATE, _drive, _kinds, posts)

#: origin/master cf060216's maint_release.yaml, verbatim: the definition a suspended instance
#: journalled before the supervisor's approval became the release.
_OLD_MAINT_RELEASE = '''# SAMPLE — OVERLAY layer (ADR-0036). Invented in this repo; a deployment replaces the values.
#
# RELEASE: emit the ActionRecord the bridge contract names, then wait for the owning tier to
# acknowledge it. The case closes on the tier's ack.
#
# THE APPROVAL CHAIN IS THE EXECUTOR'S, NEVER THE TEMPLATE'S: `{case.approval_chain}` is what the
# executor wrote from the identities `approve` verified. A template that spelled an approver would
# be a forgery the case record could not tell apart.
#
# `provenance` names the case's definition (its trigger) and the emitter (THIS definition, the
# one that released), and this instance. The proposal is the chosen option's own record.
id: maint_release
name: "Maintenance fault -- release"

classification: null

participants:
  - role: owning_tier

domain_stages: [released, closed]

steps:
  - kind: emit
    id: action
    stage: released
    channel: maintenance_action
    template:
      action_id: "{case.instance_id}"
      event_id: "{trigger.event_id}"
      asset_id: "{trigger.asset_id}"
      owning_tier: "{trigger.owning_tier}"
      label: "{trigger.label}"
      work_order:
        option: "{outputs.maint_fault_propose.decide.chosen.verb}"
        readiness: "{outputs.maint_fault_propose.decide.chosen.readiness}"
        task: "{outputs.maint_fault_propose.decide.chosen.task}"
        task_refs: "{outputs.maint_fault_propose.decide.chosen.task_refs}"
        parts: "{outputs.maint_fault_propose.decide.chosen.parts}"
        outcome: approved
      approval_chain: "{case.approval_chain}"
      provenance:
        # RULED 2026-10-02: provenance names the CASE DEFINITION and the EMITTER, both. A case is
        # declared by its trigger (selection, key, episode), so the case definition is the
        # trigger's name. The three workflow_* fields are the week-1 contract's spelling and
        # name the emitter; emitted_by says so in a field of its own.
        case_definition: "{case.trigger}"
        case_id: "{case.case_id}"
        emitted_by: "{definition.id}"
        workflow_definition_id: "{definition.id}"
        workflow_definition_version: "{definition.version}"
        workflow_instance_id: "{case.instance_id}"
        manual_nodes_consulted:
          - "{outputs.maint_fault_propose.walk.citations.fault_isolation.dmc}"
          - "{outputs.maint_fault_propose.walk.citations.remove_install.dmc}"
          - "{outputs.maint_fault_propose.walk.citations.ipd.dmc}"
          - "{outputs.maint_fault_propose.walk.citations.planning_interval.dmc}"

  # A SYSTEM'S ANSWER, not a human's: no task row. Resolved through the same authority gate.
  - kind: signal_await
    id: tier_ack
    signal: tier_ack
    audience: "maint_tier_ack:{trigger.owning_tier}"
    accepts: [released, tier_refused]
    # A REFUSAL GOES BACK TO A MAINTAINER, so it must say why; the reason rides the hop.
    reason_required: [tier_refused]
'''


def _records(posts):
    return [j for u, j, _h in posts if u.endswith("/action-record")]


@pytest.mark.asyncio
async def test_a1_a_supervisor_approval_releases_and_closes_with_no_signal(registered, posts):
    out, c = await _drive([(DECIDE, "evacuate_for_depot"), (REVIEW, "approved", "s@x")],
                          seeded_by=DELEGATE)
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    assert out["transitions"][-1]["from"] == "maint_release", out["transitions"][-1]
    assert (out["transitions"][-1]["outcome"], out["transitions"][-1]["to"]) == (
        "released", "closed"), out["transitions"][-1]
    assert _path(out)[-2:] == [("maint_supervisor_review", "approved", "maint_release"),
                               ("maint_release", "released", "closed")], _path(out)
    [rec] = _records(posts)
    emitted = [e["record"] for k, ctx in sorted(c.ctxs.items())
               for e in ctx.state.get("outbox:maintenance_action") or []]
    assert emitted == [rec["record"]], (emitted, rec)
    assert "supervisor" in [e["role"] for e in rec["record"]["approval_chain"]], rec["record"]
    assert [e["approver_sub"] for e in rec["record"]["approval_chain"]][-1] == "s@x", rec["record"]
    assert _kinds(posts) == ["action-record", "seeded-by"], _kinds(posts)


@pytest.mark.asyncio
async def test_a2_a_choice_that_needs_no_supervisor_releases_and_closes_with_no_signal(
        registered, posts):
    out, c = await _drive([(DECIDE, "replace_after_resupply")], seeded_by=DELEGATE)
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    assert _path(out) == [("triaged", "selected", "maint_fault_propose"),
                          ("maint_fault_propose", "replace_after_resupply", "maint_release"),
                          ("maint_release", "released", "closed")], _path(out)
    [rec] = _records(posts)
    assert [e["role"] for e in rec["record"]["approval_chain"]] == ["maintainer"], rec["record"]
    assert _kinds(posts) == ["action-record", "seeded-by"], _kinds(posts)


@pytest.mark.asyncio
async def test_a4_the_release_is_by_the_supervisor_who_approved_it_not_system(registered, posts):
    """The case panel's `released` act reads the transition's `by`: it names the approver."""
    out, _ = await _drive([(DECIDE, "evacuate_for_depot"), (REVIEW, "approved", "s@x")],
                          seeded_by=DELEGATE)
    assert out["transitions"][-1]["by"] == "s@x", out["transitions"][-1]


@pytest.mark.asyncio
async def test_a4_with_no_supervisor_the_release_is_by_the_maintainer_who_chose(registered, posts):
    out, _ = await _drive([(DECIDE, "replace_after_resupply")], seeded_by=DELEGATE)
    [hop] = [t for t in out["transitions"] if t["from"] == "maint_fault_propose"]
    assert out["transitions"][-1]["by"] == hop["by"] != "system", out["transitions"]


def test_a3_the_real_definition_waits_for_nothing_and_disposes_released():
    steps = wd.get_workflow_definition("maint_release").steps
    assert [s.kind for s in steps] == ["emit"], [s.kind for s in steps]
    assert steps[0].disposes == "released", steps[0]


def test_a3_a_suspended_old_instance_that_receives_tier_ack_released_still_closes(tmp_path):
    p = tmp_path / "maint_release.yaml"
    p.write_text(_OLD_MAINT_RELEASE, encoding="utf-8")
    old = wd.load_workflow_definition(p)                    # the old text still validates
    waits = [s for s in old.steps if s.kind == "signal_await"]
    assert [s.signal for s in waits] == ["tier_ack"] and "released" in waits[0].accepts, old.steps
    # An old instance's outcome is the signal's status, `released`; the new table closes on it,
    # whether or not the runner also hands it the measured `outcome_repeated`.
    for facts in ({"outcome": "released"},
                  {"outcome": "released", "outcome_repeated": False}):
        got = R.chain("maint_release", facts)
        assert (got["then"], got["terminal"]) == ("closed", True), got
