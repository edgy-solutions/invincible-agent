"""SATISFIED, REFUSED, NOT_EVALUATED — the migration policy stops impersonating evaluation.

ADR-0043 §6. `_satisfies` answered a two-valued question and returned "satisfied"
for every archetype without a typed contract, so "I checked and it passed" and
"I never looked" were indistinguishable to the selector.

WITNESSED IN PRODUCTION 2026-08-24. mesh:FundingGapSet had no registered
binding, output_uri matched nothing, selection widened to the whole menu, every
non-CHART archetype passed unconditionally, and KNOWLEDGE_DOCUMENT won by
fallthrough. The card read "No content available." — the document renderer being
honest about a payload it never had a contract for. Provenance said
`presentation_source: registered`, which was true and useless; three separate
broken cards carried that same green field that day.

THE RULE THIS PINS:
    declared   (output_uri matched) -> may render unevaluated; the caller's menu
                                       named this archetype for this output type
    undeclared (reached by widening) -> must NOT win on a check that never ran

Run: uv run --frozen --with pytest pytest tests/planning/test_satisfies_third_state.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent"))

cr = pytest.importorskip("capability_registry")

DOC = {"archetype": "KNOWLEDGE_DOCUMENT", "subject_uri": "http://invincible-agent/mesh#CatalogListing"}
CHART = {"archetype": "CHART_WIDGET", "subject_uri": "http://invincible-agent/mesh#DatasetAnalysisReport"}


def test_an_archetype_with_no_typed_contract_is_NOT_EVALUATED_not_satisfied():
    """THE ARM THAT WAS RED. Previously this returned "satisfied", which is a
    claim the code was in no position to make."""
    verdict, reason = cr._evaluate(DOC, {"chart_data": None})
    assert verdict == cr.NOT_EVALUATED
    assert "no typed contract" in (reason or "")


def test_a_typed_contract_still_evaluates_to_SATISFIED_or_REFUSED():
    """The third state must not swallow real evaluation — CHART_WIDGET has a
    validator and must still reach a verdict."""
    ok, _ = cr._evaluate(CHART, {"chart_data": '[{"name":"a","value":1}]', "chart_type": "BAR"})
    bad, reason = cr._evaluate(CHART, {"chart_data": None, "chart_type": None})
    assert ok == cr.SATISFIED
    assert bad == cr.REFUSED and reason


def test_NOT_EVALUATED_is_not_a_failure_it_is_an_absence_of_evidence():
    """Most archetypes legitimately have no server-side validator. The planning
    five are validated by their cortex-ui contracts, not here. The point is that
    the selector KNOWS the difference, not that unevaluated means broken."""
    assert cr._evaluate(DOC, {"chart_data": None})[0] != cr.REFUSED


def test_the_two_valued_view_still_reads_NOT_EVALUATED_as_passing():
    """`_satisfies` keeps historical behaviour for callers that only need
    pass/fail — which is exactly why anything making a SELECTION decision must
    call `_evaluate` instead."""
    assert cr._satisfies(DOC, {"chart_data": None}) is None


def test_ACCEPTANCE_an_undeclared_archetype_can_no_longer_win_by_fallthrough(monkeypatch):
    """THE FundingGapSet SHAPE, MADE IMPOSSIBLE.

    A menu that has no capability for the answer's output_uri must not quietly
    render it as a KNOWLEDGE_DOCUMENT. Widening is allowed to look; it is not
    allowed to select on the strength of a check that never ran.
    """
    menu = {"frontend_id": "cortex-ui-desktop", "frontend_version": "1",
            "capabilities": [DOC]}
    monkeypatch.setattr(cr, "menu_for", lambda fid: menu)
    cap, prov = cr.select_presentation(
        "cortex-ui-desktop",
        "http://invincible-agent/mesh#FundingGapSet",   # nothing on the menu binds this
        {"chart_data": None, "chart_type": None},
    )
    assert cap is None, "an undeclared archetype won by fallthrough — the defect is back"
    assert prov["presentation_source"] == "unrenderable"
    assert any(r.get("verdict") == cr.NOT_EVALUATED for r in prov.get("refusals") or []), \
        "the refusal must SAY it was never evaluated, not invent a shape reason"


def test_a_DECLARED_binding_still_renders_without_a_server_side_validator(monkeypatch):
    """The other direction, and it is the one that keeps tonight's six planning
    arms working: their archetypes have no validator here, but the menu NAMES
    them for their output_uri, and that declaration is authority."""
    timeline = {"archetype": "INTERVAL_TIMELINE",
                "subject_uri": "http://invincible-agent/mesh#IntervalSchedule"}
    menu = {"frontend_id": "cortex-ui-desktop", "frontend_version": "1",
            "capabilities": [timeline, DOC]}
    monkeypatch.setattr(cr, "menu_for", lambda fid: menu)
    cap, prov = cr.select_presentation(
        "cortex-ui-desktop", "http://invincible-agent/mesh#IntervalSchedule",
        {"chart_data": None, "chart_type": None},
    )
    assert cap is not None and cap["archetype"] == "INTERVAL_TIMELINE"
    assert prov["presentation_source"] == "registered"
