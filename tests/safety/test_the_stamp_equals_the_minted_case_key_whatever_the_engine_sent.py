"""I3: at BOTH read points the card's `case_id` is `acceptance_workflow_id(hazard, slug)`, whether the
engine sent no `case_id`, a wrong one, or the right one. The stamp overwrites; it never defers."""
from __future__ import annotations

from pathlib import Path

import pytest

from iagent_pure import acceptance_request as ar

WANT = ar.acceptance_workflow_id("HAZ-1", "medium")
SENT = {"none": None, "wrong": "risk-acceptance-HAZ-1-short", "right": WANT}


def _block(case_id):
    rr = {"kind": "risk_acceptance_medium", "subject_ref": "HAZ-1",
          "payload": {"hazard_id": "HAZ-1", "risk_level": "Medium", "risk_level_slug": "medium"}}
    if case_id is not None:
        rr["case_id"] = case_id
    return rr


@pytest.mark.parametrize("sent", SENT)
def test_the_supervisor_read_point_stamps_the_minted_key(sent):
    from iagent.defs import dynamic_supervisor as ds

    class Ctx:
        def log_event(self, e):
            pass

    resp = {"review_request": _block(SENT[sent])}
    assert ds._log_subtask_review_request_asset(Ctx(), engine_response=resp, sub_query="q")
    assert resp["review_request"]["case_id"] == WANT


@pytest.mark.parametrize("sent", SENT)
def test_the_gateway_read_point_stamps_the_minted_key(sent):
    """The gateway's direct path calls `with_minted_ids` on the block and writes it back to the
    response it renders; the call is checked for presence and order in the source, the value here."""
    src = (Path(__file__).resolve().parents[2] / "src/iagent/gateway.py").read_text("utf-8")
    i = src.index("_rr = acceptance_request.review_request_of(_expert)")
    tail = src[i:i + 900]
    assert tail.index("_rr = acceptance_request.with_minted_ids(_rr)") < tail.index(
        '_expert["review_request"] = _rr')
    expert = {"review_request": _block(SENT[sent])}
    rr = ar.with_minted_ids(ar.review_request_of(expert))
    assert rr["case_id"] == WANT
