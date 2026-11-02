"""I3: the minted case key is stamped on `review_request` where the engine response is read.

Engine S's image cannot import `iagent_pure`, so the owner stamps `case_id` before the render.
"""
from __future__ import annotations

import logging
from pathlib import Path

from iagent_pure import acceptance_request as ar


def _block(case_id="risk-acceptance-HAZ-1-short"):
    return {"kind": "risk_acceptance_medium", "subject_ref": "HAZ-1", "case_id": case_id,
            "task_id": "risk-acceptance-HAZ-1",
            "payload": {"hazard_id": "HAZ-1", "risk_level": "Medium",
                        "risk_level_slug": "medium"}}


def test_a_wrong_engine_case_id_comes_out_as_the_minted_key(caplog):
    rr = _block()
    with caplog.at_level(logging.WARNING):
        out = ar.with_minted_ids(rr)
    assert out["case_id"] == ar.acceptance_workflow_id("HAZ-1", "medium")
    assert out["case_id"] == ar.acceptance_trigger(rr, authz_id="a@b.c")["acceptance_id"]
    assert rr["case_id"] == "risk-acceptance-HAZ-1-short"  # a copy
    assert out["task_id"] == "risk-acceptance-HAZ-1"  # not invented, not touched
    assert "risk-acceptance-HAZ-1-short" in caplog.text and out["case_id"] in caplog.text


def test_missing_inputs_leave_the_block_unchanged():
    rr = {"kind": "k", "case_id": "x", "payload": {"hazard_id": "HAZ-1"}}
    assert ar.with_minted_ids(rr) == rr
    assert ar.with_minted_ids({}) == {}


def test_the_supervisor_read_point_stamps_the_response_it_renders():
    from iagent.defs import dynamic_supervisor as ds
    events = []

    class Ctx:
        def log_event(self, e):
            events.append(e)

    resp = {"review_request": _block()}
    assert ds._log_subtask_review_request_asset(Ctx(), engine_response=resp, sub_query="q")
    want = ar.acceptance_workflow_id("HAZ-1", "medium")
    assert resp["review_request"]["case_id"] == want
    assert want in events[0].metadata["review_request_json"].value


def test_the_gateway_direct_read_point_stamps_before_the_open():
    src = (Path(__file__).resolve().parents[2] / "src/iagent/gateway.py").read_text("utf-8")
    i = src.index("_rr = acceptance_request.review_request_of(_expert)")
    tail = src[i:i + 900]
    assert tail.index("with_minted_ids(_rr)") < tail.index('_expert["review_request"] = _rr') \
        < tail.index("_open_safety_acceptance(")
