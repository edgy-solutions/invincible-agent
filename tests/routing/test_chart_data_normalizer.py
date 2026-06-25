"""Pin the chart_data normalizer against the five input shapes it
must coerce to the ChartWidget contract.

Pure unit, no cluster. Pins logic that was smoke-tested manually
during the 2026-06-25 chart-empty arc but never committed as a
test — exactly the "smoke-tested-but-not-pinned, silently breaks
on next edit" gap. The normalizer is the deterministic conformance
step that makes the §1 principle work: BAML's LLM produces extracted
data, this function makes it match ChartWidget.tsx's hardcoded
``dataKey="name"``/``dataKey="value"``.

When this test fires, either the normalizer or the widget's
required keys have changed. The fix is at one of those two places,
not both — they're the two ends of the same contract. (And until
[[ui-contract-assumed-not-published]] is closed, that contract is
backend-assumed not UI-published; this test is the placeholder
enforcement until the publish path lands.)
"""
from __future__ import annotations

import json

import pytest

from agent_fleet.presentation_agent.chart_normalizer import (
    normalize_chart_data_to_recharts as _normalize_chart_data_to_recharts,
)


# ---------------------------------------------------------------------------
# Shape 1: dict-of-counts/measures — the form Engine DA's smolagent
# returns most often. E.g. ``{'US-East': 3, 'US-West': 2, ...}``.
# ---------------------------------------------------------------------------


def test_dict_of_counts_python_repr_string():
    """The exact production failure mode from c4b3ff7a — DA's
    smolagent serialized a Python dict using ``str()`` so single
    quotes leak in. The normalizer should still coerce."""
    raw = "{'US-East': 3, 'US-West': 2, 'EU-North': 2, 'APAC': 2, 'EU-South': 1}"
    out = _normalize_chart_data_to_recharts(raw)
    assert out is not None
    rows = json.loads(out)
    assert rows == [
        {"name": "US-East", "value": 3},
        {"name": "US-West", "value": 2},
        {"name": "EU-North", "value": 2},
        {"name": "APAC", "value": 2},
        {"name": "EU-South", "value": 1},
    ]


def test_dict_of_counts_native_dict():
    out = _normalize_chart_data_to_recharts({"A": 10, "B": 20})
    assert json.loads(out) == [
        {"name": "A", "value": 10},
        {"name": "B", "value": 20},
    ]


def test_dict_of_counts_json_string():
    out = _normalize_chart_data_to_recharts('{"A": 10, "B": 20}')
    assert json.loads(out) == [
        {"name": "A", "value": 10},
        {"name": "B", "value": 20},
    ]


# ---------------------------------------------------------------------------
# Shape 2: list of records with named fields. E.g.
# ``[{"region": "US-East", "count": 3}, ...]`` — first non-numeric
# field becomes the category, first numeric field becomes the measure.
# ---------------------------------------------------------------------------


def test_list_of_records_with_mismatched_keys():
    """The exact widget-empty bug class — BAML extracted records with
    semantically correct names (``region``/``count``) that
    ChartWidget.tsx couldn't render because it's hardcoded to look
    for ``name``/``value``. The normalizer rescues this shape by
    deterministic field-role detection."""
    rows = [
        {"region": "US-East", "count": 3},
        {"region": "US-West", "count": 2},
    ]
    out = _normalize_chart_data_to_recharts(rows)
    assert out is not None
    assert json.loads(out) == [
        {"name": "US-East", "value": 3},
        {"name": "US-West", "value": 2},
    ]


def test_list_of_records_json_stringified():
    out = _normalize_chart_data_to_recharts(
        '[{"region": "US-East", "count": 3}, {"region": "US-West", "count": 2}]'
    )
    assert json.loads(out) == [
        {"name": "US-East", "value": 3},
        {"name": "US-West", "value": 2},
    ]


# ---------------------------------------------------------------------------
# Shape 3: already-normalized — passthrough. This is what the BAML
# prompt is *supposed* to produce on its best behavior; the
# normalizer must not break the happy path.
# ---------------------------------------------------------------------------


def test_already_normalized_passthrough():
    rows = [{"name": "A", "value": 10}, {"name": "B", "value": 20}]
    out = _normalize_chart_data_to_recharts(rows)
    assert json.loads(out) == rows


def test_already_normalized_stringifies_non_string_names():
    """Names should be coerced to str so the widget's xAxis label
    rendering never sees a number-as-axis-tick (Recharts handles it,
    but downstream display code assumes strings)."""
    rows = [{"name": 2024, "value": 10}, {"name": 2025, "value": 20}]
    out = _normalize_chart_data_to_recharts(rows)
    assert json.loads(out) == [{"name": "2024", "value": 10}, {"name": "2025", "value": 20}]


# ---------------------------------------------------------------------------
# Safe-degradation cases — the normalizer MUST return None on inputs
# that don't look like chart data, so the caller falls back to the
# BAML output verbatim rather than producing a wrong-shape array.
# This is the "never over-coerce" contract from the d34641b/73a012c
# arc.
# ---------------------------------------------------------------------------


def test_returns_none_on_non_chart_string():
    assert _normalize_chart_data_to_recharts("hello world") is None


def test_returns_none_on_empty_list():
    assert _normalize_chart_data_to_recharts([]) is None


def test_returns_none_on_dict_with_no_numeric_values():
    """If no value is numeric there's no measure to plot — bail
    rather than fabricate."""
    assert _normalize_chart_data_to_recharts({"a": "x", "b": "y"}) is None


def test_returns_none_on_list_without_numeric_field():
    """Same reason — list of records but no numeric field means we
    can't infer a measure deterministically."""
    rows = [{"region": "US-East", "label": "foo"}, {"region": "US-West", "label": "bar"}]
    assert _normalize_chart_data_to_recharts(rows) is None


def test_returns_none_on_malformed_string():
    """Looks vaguely like a dict but isn't valid JSON or Python repr —
    bail rather than guess."""
    assert _normalize_chart_data_to_recharts("{not a real payload") is None


def test_returns_none_on_none_input():
    """None means upstream had nothing to render."""
    assert _normalize_chart_data_to_recharts(None) is None


# ---------------------------------------------------------------------------
# Boolean-vs-number guard — Python's ``bool`` is a subclass of ``int``,
# so a naive ``isinstance(v, numbers.Number)`` check treats True/False
# as 1/0. The normalizer must NOT treat booleans as the measure (or
# the category, since they look numeric on the dict-of-counts path).
# ---------------------------------------------------------------------------


def test_booleans_excluded_from_measure_inference():
    """A dict-of-bools is not a chart payload."""
    assert _normalize_chart_data_to_recharts({"on": True, "off": False}) is None


def test_booleans_excluded_in_list_of_records_inference():
    """For list-of-records, a boolean field should NOT be picked as
    the numeric measure — it's a category-like value."""
    rows = [{"category": "A", "active": True, "count": 5}]
    out = _normalize_chart_data_to_recharts(rows)
    assert out is not None
    parsed = json.loads(out)
    assert parsed[0]["value"] == 5
