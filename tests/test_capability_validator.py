"""Slice 2c: the validator answers the question the normalizer only approximated.

`normalize_chart_data_to_recharts` asked "can I reshape this into {name, value}?" and
treated "no" as unrenderable. That threw away payloads the COMPONENT could draw -- witnessed
at work 2026-08-15, where the data path worked end to end and the presentation layer
discarded the values.

This asks "does this satisfy the component's published contract?", which is the question
that was always being asked. These tests pin the difference, because the difference is the
whole justification for deleting 194 lines.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_capability_validator.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.presentation_agent.capability_validator import (  # noqa: E402
    validate_chart_payload,
)


def _j(rows):
    return json.dumps(rows)


# ── the shapes the OLD normalizer destroyed ──────────────────────────────────────────
def test_MULTI_SERIES_is_renderable_the_normalizer_would_have_flattened_it():
    """Two categorical + one numeric is `kind: "multi"` in the component. The coercion
    flattened it to single-series name/value before it ever arrived."""
    rows = [{"region": "n", "plan": "pro", "n": 1}, {"region": "s", "plan": "pro", "n": 2}]
    assert validate_chart_payload(_j(rows), "BAR") is None


def test_SCATTER_is_renderable_and_the_normalizer_had_no_concept_of_it():
    rows = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
    assert validate_chart_payload(_j(rows), "SCATTER") is None


def test_arbitrary_column_names_are_renderable_because_the_component_INFERS_keys():
    """The stale belief was that the widget hardcodes dataKey name/value. It infers them,
    so a payload naming its columns anything is fine."""
    rows = [{"quarter": "Q1", "revenue": 100.5}]
    assert validate_chart_payload(_j(rows), "LINE") is None


# ── refusals, using the contract's own published vocabulary ──────────────────────────
def test_no_rows():
    assert validate_chart_payload(_j([]), "BAR") == "no rows"
    assert validate_chart_payload(None, "BAR") == "no rows"
    assert validate_chart_payload("", "BAR") == "no rows"


def test_not_an_array():
    assert validate_chart_payload(_j({"a": 1}), "BAR") == "not an array"


def test_json_parse_failure():
    assert validate_chart_payload("{definitely not json", "BAR") == "JSON parse failure"


def test_rows_arent_objects():
    assert validate_chart_payload(_j(["a", "b"]), "BAR") == "rows aren't objects"


def test_no_numeric_column():
    assert validate_chart_payload(_j([{"a": "x", "b": "y"}]), "BAR") == "no numeric column"


def test_no_categorical_column_for_categorical_axis():
    assert validate_chart_payload(_j([{"v": 1}]), "BAR") == "no categorical column"


def test_scatter_needs_two_numeric():
    assert (validate_chart_payload(_j([{"label": "a", "x": 1}]), "SCATTER")
            == "scatter requires 2 numeric columns (x and y)")


# ── agreement with the component, which is what makes the deletion safe ──────────────
def test_a_bool_is_NOT_a_numeric_column():
    """JS `typeof true === "boolean"`, so the component does not count it. A validator that
    disagreed would ACCEPT a payload the component then refuses -- the confident-wrong shape
    at the render boundary."""
    assert validate_chart_payload(_j([{"label": "a", "flag": True}]), "BAR") == "no numeric column"


def test_the_witnessed_regression_does_not_recur():
    """2026-08-15: rows present, normalizer declined, empty-check said 'not empty', no
    fallback fired, and a correct answer was discarded behind 'CHART DATA NOT RENDERABLE'.
    Under the contract this payload is simply renderable."""
    rows = [{"cage": "00000", "count": 3}, {"cage": "00001", "count": 5}]
    assert validate_chart_payload(_j(rows), "BAR") is None


def test_a_registered_contract_can_TIGHTEN_the_requirements():
    """The requirements come from the caller's registered contract when it declares them --
    the point of registering a typed contract at all."""
    strict = {"rowRequirements": {"minRows": 3, "minNumericColumns": 1,
                                  "minCategoricalColumnsForCategoricalAxis": 1,
                                  "categoricalAxisTypes": ["BAR"],
                                  "minNumericColumnsForScatter": 2}}
    rows = [{"label": "a", "v": 1}]
    assert validate_chart_payload(_j(rows), "BAR") is None            # default floor: 1 row
    assert validate_chart_payload(_j(rows), "BAR", strict) == "no rows"  # contract wants 3
