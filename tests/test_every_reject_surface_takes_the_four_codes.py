"""Every reject surface takes the promotion's four codes (architect ruling 2026-10-19: "the
four-code ruling applies to every reject surface. Lane 1 widens the server now").

What this seals:
  * THE GROUPED REVIEW'S CODES ARE THE PROMOTION'S, IN ORDER -- the BFF's tuple, the act model's
    Literal and the workflow's REASON_CODES each equal `PROMOTION_REJECT_CODES`. Cortex's parity seal
    compares its list to the first two in order, so a reorder is a break too.
  * A PRE-RULING NAME IS A TRANSITION ALIAS, NEVER A CODE. The model maps each to its successor, so
    nothing past the boundary sees it; the workflow itself refuses one.
  * AN UNKNOWN CODE IS STILL REFUSED.

Run: uv run --frozen pytest tests/test_every_reject_surface_takes_the_four_codes.py -q
"""
from __future__ import annotations

import typing

import pytest

pytest.importorskip("fastapi")
from pydantic import ValidationError  # noqa: E402

from src.iagent import gateway, promotion  # noqa: E402

FOUR = ("not_a_notice", "unreadable", "parts_unusable", "duplicate")


def _literal_codes():
    ann = gateway.HumanTaskActRequest.model_fields["reason_code"].annotation
    (lit,) = [a for a in typing.get_args(ann) if a is not type(None)]
    return typing.get_args(lit)


def test_the_promotion_codes_are_the_four_this_file_checks_against():
    assert promotion.PROMOTION_REJECT_CODES == FOUR


def test_the_bff_tuple_is_the_promotion_codes_in_order():
    assert gateway._GROUPED_REJECT_CODES == promotion.PROMOTION_REJECT_CODES


def test_the_act_models_literal_is_the_promotion_codes_in_order():
    assert _literal_codes() == promotion.PROMOTION_REJECT_CODES


def test_the_workflows_codes_are_the_promotion_codes_in_order():
    from agent_fleet.restate_analyst import steward_correction
    assert steward_correction.REASON_CODES == promotion.PROMOTION_REJECT_CODES


@pytest.mark.parametrize("code", FOUR)
def test_each_of_the_four_is_taken_as_itself(code):
    assert gateway.HumanTaskActRequest(decision="rejected", reason_code=code).reason_code == code


@pytest.mark.parametrize("legacy", ["parts_list_unusable", "superseded_or_duplicate"])
def test_a_pre_ruling_name_is_refused_since_the_aliases_were_dropped(legacy):
    with pytest.raises(ValidationError):
        gateway.HumanTaskActRequest(decision="rejected", reason_code=legacy)


def test_no_alias_map_survives():
    assert not hasattr(gateway, "_LEGACY_GROUPED_REJECT_CODES")


@pytest.mark.parametrize("bad", ["wrong_value", "superseded", "", "PARTS_UNUSABLE"])
def test_an_unknown_code_is_refused(bad):
    with pytest.raises(ValidationError):
        gateway.HumanTaskActRequest(decision="rejected", reason_code=bad)


@pytest.mark.parametrize("code,accepted", [("parts_list_unusable", False),
                                           ("superseded_or_duplicate", False),
                                           ("unreadable", True), ("duplicate", True)])
def test_the_workflow_takes_the_four_and_refuses_an_old_name(code, accepted):
    pytest.importorskip("restate")
    from agent_fleet.restate_analyst import grouped_review_workflow as grw
    batch = grw.ReviewBatch(approver="alice", items=[])
    out = grw.evaluate_submission(batch, {"verdict": "rejected", "reason_code": code},
                                  notice_fingerprint="fp")
    assert out.accepted is accepted
    if accepted:
        assert out.rejected and out.reason_code == code
