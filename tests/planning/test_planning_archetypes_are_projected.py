"""THE PLANNING ARCHETYPES ARE PROJECTED, NOT GENERATED — and the card is the same twice.

Engine P returns typed rows against a declared output_uri, and every cortex-ui
contract for these five archetypes explicitly FORBIDS interpretation: "NOT
re-derive risk_flag", "NOT infer grouping from the ids", "NOT treat '(none)' as
missing data". A model in that path has nothing to decide and one thing to get
wrong.

WHY THIS GUARD EXISTS, measured 2026-08-24: the DesignUI fallback rendered
plan_schedule's 14 rows as "CHART DATA NOT RENDERABLE — no numeric column" on
one request and drew them cleanly on the next. Same measure, same rows, opposite
outcomes, because the chart shape was GUESSED per request.

    A beat that worked in rehearsal can fail in the room, with no change anywhere.

That is a nondeterministic component on the demo's critical path, in a project
that pre-registers every other number. These arms delete it.

Run: uv run --frozen --with pytest pytest tests/planning/test_planning_archetypes_are_projected.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent" / "main.py"


def _fns():
    """Load ONLY the projection helpers, without importing the whole agent.

    main.py pulls fastapi, baml and the mesh client at import time. A guard that
    skips whenever its dependencies are absent is a guard that never runs in CI.
    """
    src = _SRC.read_text(encoding="utf-8")
    ns: dict = {
        "json": json, "Dict": dict, "Any": object, "Optional": object,
        "logger": types.SimpleNamespace(warning=lambda *a, **k: None),
    }
    import re as _re
    for marker in ("def _extract_agent_response(", "_PLANNING_ARCHETYPES: Dict[str, tuple] = {",
                   "def _project_planning_archetype("):
        start = src.index(marker)
        # End at the next TOP-LEVEL definition OF ANY KIND. Searching for a bare
        # newline-def walked straight past `async def _render_archetype_hardened`
        # and swallowed half the module, which surfaced as a SyntaxError in the
        # loader rather than a failure in the thing under test.
        tail = src[start + len(marker):]
        m = _re.search("[\n](?:async def |def |class |@)", tail)
        end = start + len(marker) + (m.start() if m else len(tail))
        exec(compile(src[start:end], str(_SRC), "exec"), ns)  # noqa: S102
    return ns


def _envelope(rows, **extra):
    return [{"persona": "PORTFOLIO_LEAD",
             "expert_response": {"summary": "s", "structured_data": rows, **extra}}]


TIMELINE_ROW = {
    "group_kind": "initiative", "group_id": "I1", "group_name": "ERP",
    "group_weight": None, "initiative_id": "I1", "initiative_name": "ERP",
    "phase_id": "P", "phase_name": "Build", "phase_sequence": 1,
    "project_id": "P5", "project_name": "Wave 1 Cutover",
    "planned_start": "2026-10-01", "planned_end": "2026-12-31",
    "actual_start": None, "actual_end": None, "risk_flag": None,
}


def test_every_planning_archetype_projects_without_a_model():
    """The arm returns a component for all five, with no BAML client in scope."""
    ns = _fns()
    for arch, key in [("INTERVAL_TIMELINE", "rows"), ("PERIOD_SERIES", "rows"),
                      ("THRESHOLD_GRID", "rows"), ("MATRIX_GRID", "rows"),
                      ("DELTA_SET", "effects")]:
        got = ns["_project_planning_archetype"](arch, _envelope([{"a": 1}]), "PORTFOLIO_LEAD", None)
        assert got is not None, f"{arch} did not project"
        assert got["archetype"] == arch
        assert json.loads(got[key]) == [{"a": 1}], f"{arch} did not carry rows verbatim"


def test_rows_are_VERBATIM_including_the_capability_fan_out():
    """THE ROW KEY IS (group_id, project_id).

    Under the capability pivot ONE PROJECT PRODUCES MULTIPLE ROWS — one per
    contribution. A renderer that dedupes on project_id would silently drop real
    contributions, which the contract calls out by name. Projection must not
    collapse them.
    """
    ns = _fns()
    fan = [dict(TIMELINE_ROW, group_kind="capability", group_id="C1", group_weight=0.6),
           dict(TIMELINE_ROW, group_kind="capability", group_id="C2", group_weight=0.4)]
    got = ns["_project_planning_archetype"]("INTERVAL_TIMELINE", _envelope(fan), "X", None)
    out = json.loads(got["rows"])
    assert len(out) == 2, "the capability fan-out was collapsed — project_id is not unique"
    assert [r["group_id"] for r in out] == ["C1", "C2"]
    assert out == fan, "rows were not verbatim"


def test_group_kind_is_LIFTED_never_inferred():
    """`group_kind` says what the top level MEANS. The contract forbids guessing
    it from whether an id looks like an initiative — that is how a capability
    pivot silently renders as an initiative one."""
    ns = _fns()
    got = ns["_project_planning_archetype"](
        "INTERVAL_TIMELINE", _envelope([dict(TIMELINE_ROW, group_kind="capability")]), "X", None)
    assert got["group_kind"] == "capability"


def test_absent_optional_fields_are_OMITTED_not_defaulted():
    """Nothing is invented. A field the producer did not write must not appear
    with a made-up value — inventing `scope_label` would put framing on a card
    that no verb asserted."""
    ns = _fns()
    got = ns["_project_planning_archetype"]("PERIOD_SERIES", _envelope([{"period": "FY26-Q3"}]), "X", None)
    assert "scope_label" not in got and "value_unit" not in got


@pytest.mark.parametrize("rows", [[], None, "not-a-list"], ids=["empty", "missing", "wrong-type"])
def test_a_rowless_payload_DEGRADES_rather_than_drawing_an_empty_card(rows):
    """An empty planning card is a REFUSAL, not an answer — the IntervalTimeline
    contract states it: "a plan with nothing in it is a broken scope filter".
    Returning a component here would render a confident blank."""
    ns = _fns()
    assert ns["_project_planning_archetype"]("INTERVAL_TIMELINE", _envelope(rows), "X", None) is None


def test_projection_is_DETERMINISTIC_across_repeated_calls():
    """The whole point. The same payload must produce byte-identical output —
    this is the property the DesignUI fallback did not have."""
    ns = _fns()
    env = _envelope([TIMELINE_ROW])
    outs = {json.dumps(ns["_project_planning_archetype"]("INTERVAL_TIMELINE", env, "X", None),
                       sort_keys=True) for _ in range(8)}
    assert len(outs) == 1, "projection varied across identical inputs"


def test_a_non_planning_archetype_is_NOT_claimed():
    """The arm must not intercept archetypes it does not own, or CHART_WIDGET
    loses its existing key-conformance pass."""
    ns = _fns()
    assert ns["_project_planning_archetype"]("CHART_WIDGET", _envelope([{"a": 1}]), "X", None) is None
