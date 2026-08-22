"""The seed's vocabulary overlay — C3's loader, and why it swaps LABELS and not STRUCTURE.

THE DESIGN DECISION WORTH ARGUING WITH. An overlay could have replaced the whole dataset —
same schema, different file. It does not, and the reason is that the gates depend on the
shipped dataset's STRUCTURE: six seeded tensions, each asserted by a test, each a beat in the
demo script. A full-replacement overlay would run the demo on a dataset no gate has ever seen,
and the first time anyone discovered a tension had been flattened would be in the room.

So the overlay swaps NAMES ONLY. Structure, intervals, amounts, thresholds and every seeded
tension are the shipped generic dataset's, and stay under test. What changes is the vocabulary
a room reads off the screen.

That also makes the C-series' promise mechanically true rather than a discipline: there is no
code path by which customer STRUCTURE enters this repo, because the overlay cannot express
structure at all.

ABSENT BY DEFAULT. No overlay configured means the shipped dataset renders with its own
invented names, which is what every gate and every test in this suite runs against.
"""
from __future__ import annotations

import json

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed, check_consistency


def test_absent_overlay_yields_the_shipped_dataset():
    """The default, and the state every gate runs in."""
    s = build_seed()
    assert s.initiatives[0].name == "ERP Modernization"
    assert check_consistency(s) == []


def test_an_overlay_swaps_names_and_nothing_else(tmp_path):
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({
        "initiatives": {"I1": "Programme Alpha"},
        "sites": {"S2": "Northern Works"},
        "capabilities": {"C1": "Ledger Automation"},
    }), encoding="utf-8")

    plain = build_seed()
    themed = build_seed(overlay_path=str(overlay))

    assert themed.initiatives[0].name == "Programme Alpha"
    assert themed.site("S2").name == "Northern Works"
    assert themed.capability("C1").name == "Ledger Automation"

    # STRUCTURE IS UNTOUCHED — same ids, same intervals, same amounts.
    assert [i.initiative_id for i in themed.initiatives] == [i.initiative_id for i in plain.initiatives]
    assert themed.project("P3").planned == plain.project("P3").planned
    assert sum(r.amount for r in themed.requirements) == sum(r.amount for r in plain.requirements)
    assert themed.site("S2").saturation_threshold == plain.site("S2").saturation_threshold


def test_every_seeded_tension_survives_an_overlay(tmp_path):
    """THE POINT OF THE WHOLE DESIGN. If a themed dataset can lose a tension, the demo runs on
    something no gate has tested — and the discovery happens in the room."""
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({
        "initiatives": {"I1": "A", "I2": "B", "I3": "C"},
        "sites": {"S1": "W", "S2": "X", "S3": "Y", "S4": "Z"},
        "capabilities": {f"C{i}": f"Cap{i}" for i in range(1, 10)},
        "organizations": {"O1": "Alpha", "O2": "Beta", "O3": "Gamma"},
    }), encoding="utf-8")
    s = build_seed(overlay_path=str(overlay))

    assert check_consistency(s) == []
    # (a) Q3 over cap
    q3 = next(r for r in measures.plan_cost_curve(s) if r["period"] == "FY26-Q3")
    assert q3["over_cap"] is True
    # (b) baseline clean
    assert measures.plan_dependency_violations(s) == []
    # (c) exactly one over-threshold cell
    over = [(r["site_id"], r["period"]) for r in measures.plan_site_load(s) if r["over_threshold"]]
    assert over == [("S2", "FY26-Q4")]
    # (d) a visible funding gap
    assert any(r["gap"] > 0 for r in measures.plan_funding_gap(s, group_by="org"))
    # (e) outstanding contributions past a plateau
    path = measures.plan_capability_path(s, capability_id="C4")
    assert any(m["contributions_outstanding"] for m in path["plateaus"])
    # (f) a capability nobody covers
    assert measures.plan_coverage_gap(s)["uncovered_capabilities"]


def test_an_overlay_naming_something_unknown_REFUSES(tmp_path):
    """A typo'd id must not silently do nothing. An overlay that appears to apply and does not
    is how a demo runs half-themed and nobody notices until a screenshot."""
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"initiatives": {"I99": "Ghost"}}), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        build_seed(overlay_path=str(overlay))
    assert "I99" in str(exc.value)


def test_an_overlay_cannot_express_STRUCTURE(tmp_path):
    """The C-series promise, made mechanical. There is no code path by which customer structure
    enters this repo, because the overlay has no vocabulary for it — a key that is not a known
    label collection is refused rather than ignored."""
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({
        "projects": {"P1": "Renamed"},
        "requirements": [{"project_id": "P1", "amount": 999}],
    }), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        build_seed(overlay_path=str(overlay))
    assert "requirements" in str(exc.value)


def test_a_missing_overlay_file_is_a_loud_error_not_a_silent_default(tmp_path):
    """Configured-but-absent is a DIFFERENT state from not-configured. Falling back silently
    would run the customer demo on the generic dataset and look entirely normal."""
    with pytest.raises(FileNotFoundError):
        build_seed(overlay_path=str(tmp_path / "nope.json"))
