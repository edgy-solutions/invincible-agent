"""The census reads `task_requested` from the answer record, not only the stream.

The gateway consumes the engine's `review_request` before the render (gateway.py
`_open_safety_acceptance`; iagent_pure/acceptance_request.py:25-45), so a dispatched task leaves
no block in the SSE events. Its outcome is on `resolved_intent.acceptance_dispatched` /
`acceptance_not_opened`, served by GET /answers/{id}/body.

Run: uv run pytest tests/eval/test_the_census_reads_the_dispatched_acceptance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.walk_census import FAIL, PASS, CensusRow, judge  # noqa: E402

_TASK = {"kind": "risk_assessment_review", "audience": "safety_reviewer"}


def _row(*dispositions):
    return CensusRow(
        id="fixture-row", sheet="fixture", sheet_index=1, question="q", user="bob",
        persona="SAFETY_ENGINEER", domains=("SUSTAINMENT",), frontend_id="fx",
        expect_verb=None, expect_archetype=None, min_rows=0,
        dispositions=tuple(dispositions), expect_task=dict(_TASK),
    )


def _result(*, cards=True, block=None, ri=None, err=None):
    final = {"components": [{"archetype": "KNOWLEDGE_DOCUMENT"}] if cards else []}
    events = [{"event": "route_decision", "data": {
        "action": {"iri": "mesh:draftRiskAssessment"},
        "handled_by": {"endpoint_url": "http://e/measure/draft_risk_assessment"},
        "route_status": "matched", "fallback": False}}]
    if block:
        events.append({"event": "x", "data": {"review_request": block}})
    r = {"events": events, "final": final}
    if ri is not None:
        r["resolved_intent"] = ri
    if err:
        r["resolved_intent_error"] = err
    return r


def _dispatched(**over):
    return {"acceptance_dispatched": [{"workflow": "w", "subject_ref": "s", "path": "p",
                                       **_TASK, **over}]}


def test_a_dispatched_acceptance_on_the_record_is_task_requested():
    state, why = judge(_row("task_requested"), _result(ri=_dispatched()))
    assert (state, why) == (PASS, [])


def test_a_dispatched_acceptance_with_the_wrong_audience_fails_on_audience():
    state, why = judge(_row("task_requested"), _result(ri=_dispatched(audience="nobody")))
    assert state == FAIL and any("audience" in w for w in why)


def test_acceptance_not_opened_fails_and_names_the_exception():
    ri = {"acceptance_not_opened": {"exception": "TopazDown", "where": "dispatch",
                                    "message": "m"}}
    state, why = judge(_row("task_requested", "drawn"), _result(ri=ri))
    assert state == FAIL and any("TopazDown" in w and "dispatch" in w for w in why)


def test_neither_with_cards_is_still_drawn():
    state, why = judge(_row("drawn"), _result(ri={}))
    assert (state, why) == (PASS, [])
    state, why = judge(_row("task_requested"), _result(ri={}))
    assert state == FAIL and any("'drawn'" in w for w in why)


def test_a_review_request_in_the_stream_is_still_task_requested():
    state, why = judge(_row("task_requested"), _result(block=dict(_TASK)))
    assert (state, why) == (PASS, [])


def test_an_unreadable_record_on_a_task_requested_row_fails():
    state, why = judge(_row("task_requested"), _result(err="HTTP 404"))
    assert state == FAIL and any("HTTP 404" in w for w in why)
    # a row that does not accept task_requested is not failed for it
    state, _ = judge(_row("drawn"), _result(err="HTTP 404"))
    assert state == PASS
