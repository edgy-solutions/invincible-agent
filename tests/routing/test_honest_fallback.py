"""honest_text_from_response, relocated from chart_normalizer (slice 2c).

These cases MOVED rather than being deleted, because the function moved rather than being
deleted: it was never chart normalization -- it extracts the agent's already-written honest
TEXT so an unrenderable chart falls back to a KNOWLEDGE_DOCUMENT instead of an empty widget
reading as a malfunction. Correct code in the wrong file.

The COERCION tests that shared its old file went with the coercion. They pinned
`normalize_chart_data_to_recharts`, which reshaped payloads into {name, value} for a widget
behaviour that no longer exists -- keeping them would have required keeping the code they
described.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/routing/test_honest_fallback.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.presentation_agent.honest_fallback import (  # noqa: E402
    honest_text_from_response as _honest_text_from_response,
)


@pytest.mark.parametrize("resp,expected", [
    ({"summary": "hello"}, "hello"),
    ({"summary_text": "hi"}, "hi"),
    # The exact Engine DA shape from the 'sales by region' incident:
    ({"status": "success",
      "data": "The dataset 'mesh_demo_customers' does not contain a 'sales' column."},
     "The dataset 'mesh_demo_customers' does not contain a 'sales' column."),
    ({"summary": "", "data": "fallback text"}, "fallback text"),  # empty summary -> data
    ({"data": {"rows": 1}}, ""),   # data not a string -> nothing to render
    ({"data": "   "}, ""),          # whitespace-only -> nothing
    ({}, ""),
    (None, ""),
])
def test_honest_text_from_response(resp, expected):
    assert _honest_text_from_response(resp) == expected


def test_a_list_of_scalars_IS_an_answer():
    """2026-08-15: DA returned data as a list of CAGE codes -- identifiers, not measures, so
    no chart is drawable -- the fallback found no string, returned "", and a CORRECT ANSWER
    was discarded behind 'CHART DATA NOT RENDERABLE'."""
    assert _honest_text_from_response({"data": ["00000", "00001"]}) == "00000, 00001"


def test_joining_scalars_is_FORMATTING_not_synthesis():
    """Every value verbatim and in order; nothing summarised, computed or dropped."""
    assert _honest_text_from_response({"data": [1, 2, 3]}) == "1, 2, 3"


def test_a_list_of_dicts_is_left_alone():
    """Chart-shaped data is not text. Papering it over as prose would hide a real
    renderability gap behind a sentence."""
    assert _honest_text_from_response({"data": [{"a": 1}]}) == ""
