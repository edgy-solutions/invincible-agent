"""The served-menu probe's decision, sealed offline against the real backend table.

`scripts/probes/served_render_menus.py` is the live seal for "where-used has no card". It runs in
the presentation engine's pod and asks one question: is every backend presentation row on every
registered frontend menu? This file seals its decision, `menu_gaps()` and `verdict()`, with the real
`PRESENTATION_CAPABILITIES` table and the selector's real IRI folding.

THE MEASURED CASE (2026-11-16, live). The cortex desktop menu carried every backend row except
mesh:WhereUsedSet. The probe must name exactly that row, and nothing else. A menu that carries the
whole table must pass. A read without the control, or of an empty menu, is suspect, never a pass.

Run: uv run pytest tests/test_served_render_menus_probe.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES as BACKEND
from agent_fleet.presentation_agent.capability_registry import _canonical

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("served_render_menus",
                                               REPO / "scripts" / "probes" / "served_render_menus.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

WHERE_USED = "mesh:WhereUsedSet"


def _menu(*, drop=(), iri_form=lambda s: s):
    """A frontend menu built from the backend table, with some rows dropped."""
    rows = [{"subject_uri": iri_form(b["subject_uri"])} for b in BACKEND if b["subject_uri"] not in drop]
    return {"frontend_version": "v", "capabilities": rows}


def test_THE_TABLE_CARRIES_THE_SUBJECT_AND_THE_CONTROL():
    subjects = {b["subject_uri"] for b in BACKEND}
    assert WHERE_USED in subjects and probe.DEFAULT_CONTROL in subjects


def test_THE_MEASURED_GAP_IS_NAMED_AND_NOTHING_ELSE():
    gaps = probe.menu_gaps({"desktop": _menu(drop={WHERE_USED})}, BACKEND, _canonical)
    assert gaps["desktop"]["missing"] == [WHERE_USED]
    assert gaps["desktop"]["control_present"]
    assert probe.verdict(gaps) == 1


def test_CONTROL_A_MENU_WITH_THE_WHOLE_TABLE_PASSES():
    gaps = probe.menu_gaps({"desktop": _menu(), "default": _menu()}, BACKEND, _canonical)
    assert all(not g["missing"] for g in gaps.values())
    assert probe.verdict(gaps) == 0


def test_A_FULL_IRI_ON_THE_MENU_MATCHES_A_COMPACT_ONE_IN_THE_TABLE():
    """The frontend registers some rows by full IRI. The selector folds both, so the probe must too."""
    full = _menu(iri_form=lambda s: "http://example.org/mesh#" + s.split(":", 1)[1])
    gaps = probe.menu_gaps({"desktop": full}, BACKEND, _canonical)
    assert gaps["desktop"]["missing"] == [] and probe.verdict(gaps) == 0


def test_ONE_GAP_ON_ONE_MENU_FAILS_THE_READ():
    gaps = probe.menu_gaps({"default": _menu(), "desktop": _menu(drop={WHERE_USED})}, BACKEND, _canonical)
    assert gaps["default"]["missing"] == [] and probe.verdict(gaps) == 1


def test_A_READ_WITHOUT_THE_CONTROL_IS_SUSPECT_NOT_A_GAP():
    gaps = probe.menu_gaps({"desktop": _menu(drop={probe.DEFAULT_CONTROL})}, BACKEND, _canonical)
    assert probe.verdict(gaps) == 4


def test_AN_EMPTY_MENU_OR_NO_MENU_IS_SUSPECT_NEVER_A_PASS():
    assert probe.verdict(probe.menu_gaps({"desktop": {"capabilities": []}}, BACKEND, _canonical)) == 4
    assert probe.verdict(probe.menu_gaps({}, BACKEND, _canonical)) == 4
