"""A refusal is a body with a refusal envelope, not zero rows.

THE DEFECT (traced in cortex-ui PR #1): an engine (saf) answers
`200 {refused: true, outcome: "source_unavailable", reason, connector, fn}` with no `slot` and no
`available`. The refusal->ELICITATION arm only takes refusals carrying both, so this one fell
through; selection picked a planning archetype from the declared output_uri;
`_project_planning_archetype` returned None on "no rows"; the card degraded to the legacy
DesignUI render, where "could not read" is not guaranteed to survive. No rows-less component
reached cortex.

RULING (architect): "a refusal is a body with a refusal envelope, not zero rows; let a
`refused` outcome through to cortex."

These arms call the REAL `render_ui` / `_project_planning_archetype` (baml_client is stubbed
for the import only, and restored).

Run: uv run pytest tests/planning/test_a_refusal_is_a_body_with_an_envelope_not_zero_rows.py -v
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import Response

_STUBS = ("baml_client", "baml_client.types", "baml_client.type_builder")
_MAIN = "agent_fleet.presentation_agent.main"

SAF_REFUSAL = {
    "refused": True, "outcome": "source_unavailable",
    "reason": "the connector could not read the source",
    "connector": "saf-sql", "fn": "incident_rate",
}


@pytest.fixture(scope="module")
def m():
    mp = pytest.MonkeyPatch()
    for n in _STUBS:
        mp.setitem(sys.modules, n, MagicMock())
    mp.delitem(sys.modules, _MAIN, raising=False)
    mod = importlib.import_module(_MAIN)
    mp.setitem(sys.modules, _MAIN, mod)
    try:
        yield mod
    finally:
        mp.undo()


def _wrap(body):
    return [{"persona": "P", "expert_response": {"summary": "s", **body}}]


def _project(m, body, archetype="CONTRIBUTION_RANKING"):
    return m._project_planning_archetype(archetype, _wrap(body), "P", None)


async def _render(m, monkeypatch, body, archetype="CONTRIBUTION_RANKING"):
    monkeypatch.setattr(
        m, "_select_presentation",
        lambda *a, **k: ({"archetype": archetype}, {"presentation_source": "t"}),
    )
    resp = Response()
    out = await m.render_ui(
        m.RenderRequest(raw_data=_wrap(body), output_uri="mesh:X", user_persona="P"), resp,
    )
    return out, resp


def test_a_refused_saf_body_projects_an_empty_array_and_its_envelope(m):
    comp = _project(m, dict(SAF_REFUSAL))
    assert comp is not None
    assert comp["rows"] == [] and isinstance(comp["rows"], list)
    assert comp[m.REFUSAL_FIELD] == {
        "refused": True, "outcome": "source_unavailable",
        "reason": "the connector could not read the source",
        "connector": "saf-sql", "fn": "incident_rate",
    }


def test_the_envelope_key_set_is_one_constant_and_the_field_is_named_refusal(m):
    assert m.REFUSAL_FIELD == "refusal"
    comp = _project(m, dict(SAF_REFUSAL))
    assert set(comp["refusal"]) == set(m.REFUSAL_ENVELOPE_REQUIRED) | set(m.REFUSAL_ENVELOPE_OPTIONAL)


def test_connector_and_fn_travel_only_when_the_producer_supplied_them(m):
    bare = _project(m, {"refused": True, "outcome": "source_unavailable", "reason": "r"})
    assert set(bare["refusal"]) == set(m.REFUSAL_ENVELOPE_REQUIRED)
    assert "connector" not in bare["refusal"] and "fn" not in bare["refusal"]
    only_fn = _project(m, {"refused": True, "outcome": "o", "reason": None, "fn": "f"})
    assert only_fn["refusal"]["fn"] == "f" and "connector" not in only_fn["refusal"]
    assert only_fn["refusal"]["reason"] is None


@pytest.mark.parametrize("archetype", ["CONTRIBUTION_RANKING", "MULTI_SERIES", "STEP_LADDER"])
def test_every_projected_archetype_keeps_its_own_payload_key_as_an_empty_array(m, archetype):
    key = m._PROJECTED_ARCHETYPES[archetype][0]
    comp = _project(m, dict(SAF_REFUSAL), archetype)
    assert comp[key] == [] and isinstance(comp[key], list)
    assert comp["refusal"]["outcome"] == "source_unavailable"


def test_a_non_refused_empty_body_is_still_no_card(m):
    assert _project(m, {"structured_data": []}) is None
    assert _project(m, {}) is None
    assert _project(m, {"refused": False, "structured_data": []}) is None


@pytest.mark.parametrize("fake", ["true", 1, "yes", {"x": 1}])
def test_only_the_boolean_true_is_a_refusal(m, fake):
    assert _project(m, {**SAF_REFUSAL, "refused": fake}) is None


def test_a_refusal_that_carries_rows_projects_them_without_an_envelope(m):
    comp = _project(m, {**SAF_REFUSAL, "structured_data": [{"a": 1}]})
    assert comp["rows"] == [{"a": 1}] and "refusal" not in comp


@pytest.mark.asyncio
async def test_render_ui_lets_the_refusal_through_with_its_own_path_header(m, monkeypatch):
    out, resp = await _render(m, monkeypatch, dict(SAF_REFUSAL))
    comp = out["components"][0]
    assert comp["rows"] == [] and comp["refusal"]["outcome"] == "source_unavailable"
    assert resp.headers["X-Presentation-Path"] == "refusal-envelope"


@pytest.mark.asyncio
async def test_a_refusal_with_slot_and_options_is_still_an_elicitation(m, monkeypatch):
    body = {**SAF_REFUSAL, "outcome": "not_in_model", "slot": "vintage",
            "available": ["2021-01-01", "2021-02-01"]}
    out, resp = await _render(m, monkeypatch, body)
    assert resp.headers["X-Presentation-Path"] == "refusal-with-menu"
    assert out["components"][0]["archetype"] == "ELICITATION"
    assert "refusal" not in out["components"][0]


@pytest.mark.asyncio
async def test_declared_non_answer_statuses_are_unchanged(m, monkeypatch):
    out, resp = await _render(m, monkeypatch, {"status": "ungrounded", "reason": "no source"})
    assert resp.headers["X-Presentation-Path"] == m.PRESENTATION_PATH_DECLARED_UNGROUNDED


def test_the_disposition_vocabulary_is_unchanged_and_only_unentitled_draws_a_hole(m):
    assert m._DISPOSITIONS == frozenset({"unentitled", "unavailable", "empty", "unsummarised"})
    assert m._HOLE_DISPOSITIONS == frozenset({"unentitled"})
    assert "source_unavailable" not in m._DISPOSITIONS
