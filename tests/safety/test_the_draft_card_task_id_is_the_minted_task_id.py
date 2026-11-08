"""The draft card's `review_request.task_id` is the id the task row is minted under.

The architect's ruling (2026-11-07): the LONG form `<case>~<n>:<step>` is the contract; the short
form `risk-acceptance-<hazard>` is a defect. An `/act` sent from the card finds its task by this id,
so a card that carries any other string addresses nothing.

THE EXPECTED STRING IS DERIVED, NOT TYPED. Its parts are read from the code that defines each:
  * the case key   `iagent_pure.acceptance_request.acceptance_workflow_id` (hazard, level slug);
  * the instance   `restate_analyst.workflow_runner._child_key(case, 1)` (a child is `{case}~{n}`);
  * the task id    `main.py` mints `f"{workflow_id}:{step.id}"`; the step is the definition's own
                   `human_await` step, read from `policy/workflows/safety_acceptance_direct.yaml`.

MEASURED (the real builder `measures.draft_risk_assessment`, driven): it returns the short form
(`risk-acceptance-<hazard>`). STRICT XFAIL until Engine S builds the long form; the builder is
Engine S's own code, so the fix is the lane's to take once ruled (reported, not fixed here).
Positive control: the same assertion passes when the builder is patched to the long form.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ._engine_extra import requires_rdflib
from iagent_pure import acceptance_request as ar

_DEF = Path(__file__).resolve().parents[2] / "policy" / "workflows" / "safety_acceptance_direct.yaml"
_HAZARD = "HAZ-1003"


def _the_awaited_step_id() -> str:
    steps = [s for s in yaml.safe_load(_DEF.read_text(encoding="utf-8"))["steps"]
             if s.get("kind") == "human_await"]
    assert len(steps) == 1, "the definition no longer has exactly one human_await step"
    return steps[0]["id"]


def _expected_task_id(card) -> str:
    from agent_fleet.restate_analyst import workflow_runner
    slug = card["payload"]["risk_level_slug"]
    case = ar.acceptance_workflow_id(_HAZARD, slug)
    return f"{workflow_runner._child_key(case, 1)}:{_the_awaited_step_id()}"


def _card():
    from agent_fleet.safety_agent import measures
    out = measures.draft_risk_assessment(hazard_id=_HAZARD)
    assert "review_request" in out, f"the fixture hazard drafted no card: {str(out)[:120]}"
    return out["review_request"]


@requires_rdflib
@pytest.mark.xfail(strict=True, reason=(
    "the builder (measures.py, Engine S) emits the short form risk-acceptance-<hazard>; the ruled "
    "contract is the long form <case>~<n>:<step>. Reported to the coordinator for a ruling on who "
    "fixes it; not fixed in this PR."))
def test_the_draft_card_task_id_is_the_long_form_the_task_is_minted_under():
    card = _card()
    assert card["task_id"] == _expected_task_id(card)


@requires_rdflib
def test_control_the_expected_string_is_the_long_form_and_the_assertion_can_pass(monkeypatch):
    """The derivation yields `<case>~1:<step>` and the equality passes for a card that carries it."""
    card = _card()
    want = _expected_task_id(card)
    assert want.startswith(card["case_id"] + "~1:") and want.endswith(":" + _the_awaited_step_id())
    assert want != card["task_id"], "the builder and the derivation now agree: drop the xfail"
    assert {**card, "task_id": want}["task_id"] == want
