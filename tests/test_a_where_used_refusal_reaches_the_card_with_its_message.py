"""A where-used refusal reaches the card with its plain-language message, not only its code.

The 2026-11-19 rehearsal's as-built beat showed the code `configuration_not_available` on the card
because the presentation projector dropped the producer's `message`. The seal drives the REAL
where-used producer and hands its body to the REAL presentation projectors (baml_client stubbed
for the import only, and restored).

Run: uv run pytest tests/test_a_where_used_refusal_reaches_the_card_with_its_message.py -q
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import Response

from tests.test_where_used_rolls_up_through_every_level import ALICE, ask, ident

_STUBS = ("baml_client", "baml_client.types", "baml_client.type_builder")
_MAIN = "agent_fleet.presentation_agent.main"
_CODE = "configuration_not_available"


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


def _body(configuration: str = "as_built") -> dict:
    """The real producer's refusal; the precondition is read, not assumed."""
    body = ask(ident("P"), ALICE, configuration)
    assert body.get("refused") is True or body.get("status") == "refused", body
    assert body["reason"] == _CODE, body
    assert isinstance(body.get("message"), str) and body["message"].strip(), body
    return body


def test_arm_a_the_planning_projector_carries_the_message(m):
    body = _body()
    comp = m._project_planning_archetype(
        "CONTRIBUTION_RANKING",
        [{"persona": "P", "expert_response": {"summary": "s", **body}}], "P", None)
    assert comp is not None
    assert comp["refusal"]["message"] == body["message"], comp
    assert comp["refusal"]["reason"] == _CODE


async def _render_doc(m, monkeypatch, body):
    monkeypatch.setattr(
        m, "_select_presentation",
        lambda *a, **k: ({"archetype": "KNOWLEDGE_DOCUMENT"}, {"presentation_source": "t"}),
    )
    raw = [{"persona": "P", "expert_response": body}]
    out = await m.render_ui(
        m.RenderRequest(raw_data=raw, output_uri="mesh:X", user_persona="P"), Response())
    comps = out["components"]
    assert len(comps) == 1 and comps[0]["archetype"] == "KNOWLEDGE_DOCUMENT", comps
    return comps[0]


@pytest.mark.asyncio
async def test_arm_b_the_document_path_carries_the_message(m, monkeypatch):
    body = _body()
    card = await _render_doc(m, monkeypatch, body)
    assert card[m.REFUSAL_FIELD]["message"] == body["message"], card[m.REFUSAL_FIELD]


@pytest.mark.parametrize("configuration", ["as_built", "as_maintained"])
def test_arm_c_every_emitted_refusal_message_is_one_line(configuration):
    assert "\n" not in _body(configuration)["message"]


def test_control_a_refusal_with_no_message_projects_no_message_key(m):
    body = {k: v for k, v in _body().items() if k != "message"}
    env = m._refusal_envelope(body)
    assert "message" not in env, env
    comp = m._project_planning_archetype(
        "CONTRIBUTION_RANKING",
        [{"persona": "P", "expert_response": {"summary": "s", **body}}], "P", None)
    assert "message" not in comp["refusal"], comp
