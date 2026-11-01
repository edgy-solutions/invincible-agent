"""A served `render.shape` selects the archetype BEFORE the output class does.

WHY. A measure an overlay adds has an output class on no caller's menu, so `select_presentation`
(which filters the menu by output_uri) ends `unrenderable` and the viewer sees raw fields. The
row now declares `render.shape`, engine-fin serves it, and `select_by_declared_shape` picks the
menu capability of that archetype. RULED by Chris 10-31: presentation_agent is the hop; built-ins
are unchanged; with no render block today's path runs byte for byte.

HONEST SEMANTICS (existing, not new): only CHART_WIDGET has a typed contract in `_evaluate`.
Every other archetype is NOT_EVALUATED, so a declaration wins on the declaration alone; a REFUSED
verdict (a CHART_WIDGET whose rows fail its contract) or a shape on no menu falls through.

Arms: d a declared shape renders; e undeclared stays raw (the control for d); f declared but unfit
(i on no menu, ii refused by its contract); g built-ins unchanged; h through `render_ui`.
No class or measure name is typed: the shape is READ from the sample yaml.

Run: uv run --no-sync pytest tests/planning/test_a_declared_render_selects_the_archetype.py -q
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi import Response

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "agent_fleet" / "presentation_agent"))

cr = pytest.importorskip("capability_registry")

SAMPLE = yaml.safe_load(
    (REPO / "policy/overlays/sample/measure_verbs/fin_tcpi.yaml").read_text(encoding="utf-8"))
SHAPE = SAMPLE["render"]["shape"]
UNMENUED_URI = "fin:" + SAMPLE["outputs"]["output_uri"]       # on no menu below
BUILTIN_URI = "http://invincible-agent/mesh#SomeBuiltinClass"
DOC = {"archetype": "KNOWLEDGE_DOCUMENT", "subject_uri": "http://invincible-agent/mesh#CatalogListing"}
SHAPED = {"archetype": SHAPE, "subject_uri": BUILTIN_URI}
CHART = {"archetype": "CHART_WIDGET", "subject_uri": "http://invincible-agent/mesh#DatasetAnalysisReport"}
PAYLOAD = {"chart_data": None, "chart_type": None}


def _menu(*caps):
    return {"frontend_id": "fe", "frontend_version": "1", "capabilities": list(caps)}


@pytest.fixture
def menu(monkeypatch):
    def put(*caps):
        m = _menu(*caps)
        monkeypatch.setattr(cr, "menu_for", lambda fid, *_a: m)
        return m
    return put


def _envelope():
    return {"rows": [{"period": "2026-01", "tcpi": 1.1}], "series": SAMPLE["render"]["series"],
            "reference": SAMPLE["render"]["target"], "value_label": SAMPLE["render"]["value_label"],
            "output_uri": UNMENUED_URI, "render": SAMPLE["render"]}


# -- d / e ------------------------------------------------------------------------------------

def test_d_a_declared_shape_selects_its_capability_though_the_class_is_on_no_menu(menu):
    menu(SHAPED, DOC)
    cap, prov = cr.select_by_declared_shape("fe", _envelope()["render"]["shape"], PAYLOAD,
                                            output_uri=UNMENUED_URI)
    assert cap is SHAPED
    assert prov["selection_basis"] == "declared_render"
    assert prov["declared_shape"] == SHAPE
    assert prov["presentation_source"] == "registered"


def test_e_the_same_menu_and_class_with_no_declaration_is_unrenderable(menu):
    """THE CONTROL FOR d: same menu, same class, same payload; only the declaration differs."""
    menu(SHAPED, DOC)
    cap, prov = cr.select_presentation("fe", UNMENUED_URI, PAYLOAD)
    assert cap is None
    assert prov["presentation_source"] == "unrenderable"


# -- f ----------------------------------------------------------------------------------------

def test_f_i_a_declared_shape_on_no_menu_falls_through_and_says_so(menu):
    menu(DOC)
    cap, prov = cr.select_by_declared_shape("fe", SHAPE, PAYLOAD, output_uri=UNMENUED_URI)
    assert cap is None
    assert "no registered menu" in prov["declared_unfit"]
    assert cr.select_presentation("fe", UNMENUED_URI, PAYLOAD)[0] is None


def test_f_ii_a_declared_chart_whose_payload_fails_its_contract_falls_through(menu):
    menu(CHART)
    verdict, _ = cr._evaluate(CHART, PAYLOAD)
    assert verdict == cr.REFUSED, "the premise: the chart contract refuses this payload"
    cap, prov = cr.select_by_declared_shape("fe", CHART["archetype"], PAYLOAD,
                                            output_uri=UNMENUED_URI)
    assert cap is None
    assert prov["refusals"] and prov["declared_unfit"] == prov["refusals"][0]["reason"]
    # the control: the same declaration with rows that satisfy the contract selects it
    ok = {"chart_data": '[{"name":"a","value":1}]', "chart_type": "BAR"}
    assert cr._evaluate(CHART, ok)[0] == cr.SATISFIED
    assert cr.select_by_declared_shape("fe", CHART["archetype"], ok)[0] is CHART


def test_f_a_live_view_refusal_still_precedes_a_declaration_for_an_anonymous_caller(monkeypatch):
    monkeypatch.setattr(cr, "menu_for", lambda *a: None)
    monkeypatch.setattr(cr, "_live_view_is_registered_for", lambda uri: True)
    cap, prov = cr.select_by_declared_shape(None, SHAPE, PAYLOAD, output_uri=UNMENUED_URI)
    assert cap is None and "ADR-0042" in prov["declared_unfit"]


# -- g ----------------------------------------------------------------------------------------

def test_g_a_builtin_class_on_the_menu_selects_as_it_always_did(menu):
    menu(SHAPED, DOC)
    cap, prov = cr.select_presentation("fe", BUILTIN_URI, PAYLOAD)
    assert cap is SHAPED
    assert prov["selection_basis"] == "output_uri+payload"
    assert "declared_shape" not in prov


# -- h: through render_ui ---------------------------------------------------------------------

_STUBS = ("baml_client", "baml_client.types", "baml_client.type_builder")
_MAIN = "agent_fleet.presentation_agent.main"


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
    reg = sys.modules[m._select_by_declared_shape.__module__]
    menu_ = _menu(SHAPED, DOC)
    monkeypatch.setattr(reg, "menu_for", lambda fid, *_a: menu_)
    raw = [{"persona": "P", "route_status": "matched", "expert_response": body}]
    out = await m.render_ui(
        m.RenderRequest(raw_data=raw, output_uri=body["output_uri"], user_persona="P",
                        frontend_id="fe"), Response())
    return out["components"][0]


@pytest.mark.asyncio
async def test_h_a_declared_envelope_gets_the_declared_archetype(m, monkeypatch):
    card = await _render(m, monkeypatch, _envelope())
    assert card["archetype"] == SHAPE, card


@pytest.mark.asyncio
async def test_h_control_the_same_envelope_without_render_stays_a_document(m, monkeypatch):
    body = _envelope()
    del body["render"]
    card = await _render(m, monkeypatch, body)
    assert card["archetype"] == "KNOWLEDGE_DOCUMENT", card
