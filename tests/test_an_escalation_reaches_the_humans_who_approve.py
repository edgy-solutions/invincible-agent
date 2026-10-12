"""An unanswered maintenance approval escalates to the humans who approve it (ruling 2026-10-12).

`maint_fault_escalate` parks its await on `maint_escalation:{trigger.owning_tier}`. Before this
ruling no tier granted that audience, so a timed-out approval opened a task nobody could claim.
The ruling names its holders: the SAME group that holds `maint_fault_approval` at that tier.

The arms are derived from the grant file, never restated: every tier at which an approval is
granted is a tier at which an escalation can fire, and each must name exactly the approval's groups.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GRANTS = ROOT / "policy" / "task_grants.yaml"
ESCALATE = ROOT / "policy" / "overlays" / "openddil-lab" / "workflows" / "maint_fault_escalate.yaml"


def _audiences() -> dict:
    return yaml.safe_load(GRANTS.read_text(encoding="utf-8"))["audiences"]


def _tiers(family: str, audiences: dict) -> set[str]:
    return {k.split(":", 1)[1] for k in audiences if k.startswith(family + ":")}


def test_the_escalation_audience_is_the_owning_tier_family() -> None:
    # The grant keys below only mean something if the workflow still parks on this family.
    steps = yaml.safe_load(ESCALATE.read_text(encoding="utf-8"))["steps"]
    awaits = [s["audience"] for s in steps if s.get("kind") == "human_await"]
    assert awaits == ["maint_escalation:{trigger.owning_tier}"], awaits


def test_every_approval_tier_has_an_escalation_grant() -> None:
    audiences = _audiences()
    approval = _tiers("maint_fault_approval", audiences)
    assert approval, "no maint_fault_approval tier is granted, so this seal has no population"
    missing = sorted(approval - _tiers("maint_escalation", audiences))
    assert not missing, f"an approval at these tiers escalates to nobody: {missing}"


def test_the_escalation_goes_to_the_same_groups_that_approve() -> None:
    audiences = _audiences()
    for tier in sorted(_tiers("maint_fault_approval", audiences)):
        approve = audiences[f"maint_fault_approval:{tier}"]
        escalate = audiences.get(f"maint_escalation:{tier}") or {}
        assert sorted(escalate.get("grant_to_groups") or []) == sorted(
            approve.get("grant_to_groups") or []
        ), f"{tier}: escalation groups differ from the approvers'"
        # Through the group only, like every maint_* cell -- never a person named directly.
        assert not escalate.get("grant_to"), f"{tier}: escalation names a principal directly"


def test_no_escalation_tier_exists_without_an_approval() -> None:
    # An escalation at a tier nobody approves at would be a grant with no case that reaches it.
    audiences = _audiences()
    orphan = sorted(_tiers("maint_escalation", audiences) - _tiers("maint_fault_approval", audiences))
    assert not orphan, orphan
