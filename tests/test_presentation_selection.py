"""Slice 4: the archetype is chosen from the DATA, not from a type annotation.

WHAT THIS CLOSES. `archetype-chosen-before-data` -- the packet that started this arc when a
list of two identifiers got CHART_WIDGET. The output type said "analysis report", nothing
asked whether the payload could be DRAWN, and the viewer got an undrawable widget. The
degradation half shipped (the viewer sees honest text now), but the system still CHOSE WRONG
and then recovered. These tests pin choosing right.

THE STRUCTURAL CLAIM: the picker cannot return an archetype whose contract this payload does
not satisfy. `unrenderable` survives in the vocabulary but stops being reachable as a
DECISION -- it becomes a fact about the menu meeting the data, reported with the refusals
that produced it.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_presentation_selection.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.presentation_agent import capability_registry as reg  # noqa: E402

_CHART = {
    "subject_uri": "mesh:DatasetAnalysisReport",
    "object_uri": "mesh:ChartWidget",
    "archetype": "CHART_WIDGET",
    "persona_fit": ["DATA_STEWARD"],
    "domain_fit": ["DATA_ENGINEERING"],
}
_DOC = {
    "subject_uri": "mesh:DatasetAnalysisReport",
    "object_uri": "mesh:KnowledgeDocument",
    "archetype": "KNOWLEDGE_DOCUMENT",
    "persona_fit": [],
    "domain_fit": [],
}


@pytest.fixture(autouse=True)
def _clean():
    reg.clear()
    yield
    reg.clear()


def _payload(rows, ctype="BAR"):
    return {"chart_data": json.dumps(rows), "chart_type": ctype}


def test_THE_ORIGINAL_SYMPTOM_two_identifiers_do_NOT_get_a_chart():
    """The packet's founding case. `["00000", "00001"]` is a list of IDENTIFIERS -- no
    numeric column, nothing chartable. Chosen from output_uri alone it got CHART_WIDGET.
    Chosen from the data it cannot."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    cap, prov = reg.select_presentation(
        "cortex-ui-desktop", "mesh:DatasetAnalysisReport",
        _payload([{"cage": "00000"}, {"cage": "00001"}]),
    )
    assert cap is not None
    assert cap["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert prov["presentation_source"] == "registered"


def test_the_same_output_uri_yields_a_CHART_when_the_data_supports_one():
    """Same output_uri, different payload, different archetype -- which is the whole point:
    the type annotation cannot decide this, only the rows can."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    cap, _ = reg.select_presentation(
        "cortex-ui-desktop", "mesh:DatasetAnalysisReport",
        _payload([{"region": "n", "count": 3}, {"region": "s", "count": 5}]),
    )
    assert cap["archetype"] == "CHART_WIDGET"


def test_the_picker_can_NEVER_return_an_archetype_the_payload_fails():
    """The structural claim. Whatever comes back, its contract is satisfied."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    for rows in ([{"a": "x"}], [{"v": 1}], [], [{"n": 1, "label": "a"}]):
        cap, prov = reg.select_presentation(
            "cortex-ui-desktop", "mesh:DatasetAnalysisReport", _payload(rows))
        if cap is not None and cap["archetype"] == "CHART_WIDGET":
            assert reg._satisfies(cap, _payload(rows)) is None


def test_output_uri_is_a_FILTER_not_a_verdict_and_a_miss_widens_the_field():
    """A hint that matches nothing does not end the search -- the payload may still satisfy
    something on the menu."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    cap, prov = reg.select_presentation(
        "cortex-ui-desktop", "mesh:SomethingNobodyRegistered",
        _payload([{"region": "n", "count": 3}]),
    )
    assert cap is not None
    assert "payload-only" in prov["selection_basis"]


def test_unrenderable_now_carries_the_REFUSALS_that_produced_it():
    """When nothing on the menu fits, the answer names which requirement each candidate
    missed -- a fact about the menu meeting the data, not a decision made in ignorance."""
    reg.register("chart-only-ui", "1.0", [_CHART])
    cap, prov = reg.select_presentation(
        "chart-only-ui", "mesh:DatasetAnalysisReport", _payload([{"cage": "00000"}]))
    assert cap is None
    assert prov["presentation_source"] == "unrenderable"
    assert prov["refusals"] and prov["refusals"][0]["reason"] == "no numeric column"


def test_affinity_only_breaks_ties_among_archetypes_that_ALL_render():
    """Ranking never overrides satisfaction. Both fit here, so persona decides."""
    reg.register("cortex-ui-desktop", "1.0", [_DOC, _CHART])
    cap, _ = reg.select_presentation(
        "cortex-ui-desktop", "mesh:DatasetAnalysisReport",
        _payload([{"region": "n", "count": 3}]), persona="DATA_STEWARD",
    )
    assert cap["archetype"] == "CHART_WIDGET"


def test_affinity_does_NOT_rescue_an_unsatisfiable_archetype():
    """The inverse, and the one that matters: a strong persona match cannot promote an
    archetype the payload fails."""
    reg.register("cortex-ui-desktop", "1.0", [_DOC, _CHART])
    cap, _ = reg.select_presentation(
        "cortex-ui-desktop", "mesh:DatasetAnalysisReport",
        _payload([{"cage": "00000"}]), persona="DATA_STEWARD",
    )
    assert cap["archetype"] == "KNOWLEDGE_DOCUMENT"


def test_an_unregistered_caller_still_gets_the_LABELLED_default_menu():
    cap, prov = reg.select_presentation("ghost", "mesh:DatasetAnalysisReport", _payload([]))
    assert cap is None and prov["presentation_source"] == "default-menu"


def test_an_archetype_without_a_typed_contract_is_treated_as_satisfied():
    """Migration is row-by-row. Refusing the nine unconverted rows would make slice 4 a
    regression for every archetype except the one that happens to be finished."""
    reg.register("cortex-ui-desktop", "1.0", [_DOC])
    cap, _ = reg.select_presentation(
        "cortex-ui-desktop", "mesh:DatasetAnalysisReport", _payload([{"anything": "goes"}]))
    assert cap["archetype"] == "KNOWLEDGE_DOCUMENT"


def test_selection_basis_is_always_reported():
    """The discriminant that was missing when the choice came from a type annotation."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    _, prov = reg.select_presentation(
        "cortex-ui-desktop", "mesh:DatasetAnalysisReport", _payload([{"r": "n", "c": 1}]))
    assert prov["selection_basis"]


# ── the three anonymous-caller cases the seam's ruling specified ─────────────────────
def test_ANONYMOUS_caller_gets_the_DERIVED_UNION_not_a_collapse_to_text():
    """RULED 2026-08-20. curl and scripts are not UIs that forgot to register -- they are
    consumers of the ANSWER, and the answer's presentation metadata is part of its truth. A
    script receiving CHART_WIDGET plus shaped data can render or forward it; collapsing
    every non-UI caller to prose would make the API strictly less useful to exactly the
    consumers who cannot register.

    The union-that-lies objection does not apply: it was fatal for a SPECIFIC caller
    (backend picks what THIS UI cannot render), and an anonymous caller has no menu to
    contradict."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    cap, prov = reg.select_presentation(
        None, "mesh:DatasetAnalysisReport", _payload([{"region": "n", "count": 3}]))
    assert cap is not None
    assert cap["archetype"] == "CHART_WIDGET"
    # ...and it is still LABELLED, so the state stays named.
    assert prov["presentation_source"] == "default-menu"


def test_the_union_is_DERIVED_from_registrations_never_a_hand_kept_table():
    """capabilities.py's lookup used to serve this path. Deriving the union means the
    fallback reads the same source everything else reads, so it cannot drift the day a
    contract changes."""
    reg.register("a", "1.0", [_CHART])
    reg.register("b", "1.0", [_DOC])
    archetypes = {c["archetype"] for c in reg.union_menu()["capabilities"]}
    assert archetypes == {"CHART_WIDGET", "KNOWLEDGE_DOCUMENT"}


def test_EMPTY_REGISTRY_means_the_union_is_empty_and_we_fall_to_the_labelled_floor():
    """The post-restart state. Presentation capabilities are RUNTIME state, so a restart
    empties the registry until frontends re-register -- and an anonymous caller then gets
    the universal floor, labelled. Survivable only because the honest-degradation work
    shipped, which is why the runbook names it."""
    cap, prov = reg.select_presentation(
        None, "mesh:DatasetAnalysisReport", _payload([{"region": "n", "count": 3}]))
    assert cap is None
    assert prov["presentation_source"] == "default-menu"
    assert "KNOWLEDGE_DOCUMENT" in prov["presentation_menu"]


def test_the_union_dedupes_identical_capabilities_from_two_surfaces():
    """Two surfaces registering the same capability is AGREEMENT, not two options."""
    reg.register("a", "1.0", [_CHART])
    reg.register("b", "1.0", [_CHART])
    assert len(reg.union_menu()["capabilities"]) == 1
