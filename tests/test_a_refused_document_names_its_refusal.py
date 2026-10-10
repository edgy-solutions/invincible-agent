"""A refused document verb names its refusal on the card.

THE DEFECT: the KNOWLEDGE_DOCUMENT path (`_render_document_deterministic`) rendered before any
refusal check, so safety's refused RiskAssessmentDraft reached cortex as a plain document and the
walk census scored it `drawn`. The card now carries `_refusal_envelope(body)` under REFUSAL_FIELD.

Drives the real `render_ui` (baml_client stubbed for the import only, and restored).

Run: uv run pytest tests/test_a_refused_document_names_its_refusal.py -v
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import Response

_STUBS = ("baml_client", "baml_client.types", "baml_client.type_builder")
_MAIN = "agent_fleet.presentation_agent.main"

_REFUSED = {"refused": True, "outcome": "hazard_closed", "reason": "HAZ-1005 is closed",
            "hazard_id": "HAZ-1005"}


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


async def _render(m, monkeypatch, body):
    monkeypatch.setattr(
        m, "_select_presentation",
        lambda *a, **k: ({"archetype": "KNOWLEDGE_DOCUMENT"}, {"presentation_source": "t"}),
    )
    raw = [{"persona": "P", "expert_response": body}]
    out = await m.render_ui(
        m.RenderRequest(raw_data=raw, output_uri="safety:RiskAssessmentDraft", user_persona="P"),
        Response(),
    )
    comps = out["components"]
    assert len(comps) == 1 and comps[0]["archetype"] == "KNOWLEDGE_DOCUMENT", comps
    return comps[0]


@pytest.mark.asyncio
async def test_a_refused_draft_drawn_as_a_document_carries_its_refusal(m, monkeypatch):
    card = await _render(m, monkeypatch, dict(_REFUSED))
    assert m.REFUSAL_FIELD in card, sorted(card)
    assert card[m.REFUSAL_FIELD] == m._refusal_envelope(_REFUSED)
    for k in m.REFUSAL_ENVELOPE_REQUIRED:
        assert k in card[m.REFUSAL_FIELD], k
    assert card[m.REFUSAL_FIELD]["outcome"] == "hazard_closed"


@pytest.mark.asyncio
async def test_CONTROL_the_same_body_not_refused_has_no_refusal_key(m, monkeypatch):
    card = await _render(m, monkeypatch, dict(_REFUSED, refused=False))
    assert m.REFUSAL_FIELD not in card, sorted(card)
