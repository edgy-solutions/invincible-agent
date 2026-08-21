"""The planning verbs meet the presentation selector — the seam, pinned.

WHY THIS FILE EXISTS. Probed 2026-08-21 against the live selector, a planning cost series was
**absorbed by CHART_WIDGET**: `output_uri` matched nothing on cortex-ui's menu,
`select_presentation` widened the search (a miss widens rather than ends), and a
`[{period, total}]` payload satisfies the chart contract. The card drew, plausibly, as the
wrong archetype — with `presentation_source: "registered"`.

That finding produced two rulings (ADR-0042 §5 amendment) and this file pins both:

  1. `presentation_source` alone is NOT a sufficient gate. `selection_basis` is the
     discriminant between *my contract was found* and *something else absorbed my payload*.
  2. A contract is not a tidying step after a widget. Until the binding exists, the payload
     is absorbed — so a planning card that "already renders" is evidence of absorption.

These tests construct the menu explicitly rather than importing it from cortex-ui, because
that menu lives in a sibling repo and crosses at RUNTIME via `/register_frontend_capabilities`.
Importing it would be a compile-time coupling the architecture deliberately does not have; the
cross-repo agreement is a separate concern from the selector's behaviour, which is what this
file is about.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PRESENTATION = Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent"
sys.path.insert(0, str(_PRESENTATION))

import capability_registry as cr  # noqa: E402

from agent_fleet.planning_agent import measures  # noqa: E402
from agent_fleet.planning_agent.seed import build_seed  # noqa: E402

FRONTEND = "cortex-ui-desktop"

CHART = {
    "subject_uri": "mesh:DatasetAnalysisReport", "archetype": "CHART_WIDGET",
    "component": "ChartWidget", "persona_fit": ["DATA_STEWARD"], "domain_fit": ["DATA_ENGINEERING"],
    "contract": {"archetype": "CHART_WIDGET", "fields": {"chart_data": {}, "chart_type": {}}},
}
DOC = {
    "subject_uri": "mesh:OwnershipFact", "archetype": "KNOWLEDGE_DOCUMENT",
    "component": "MarkdownRenderer", "persona_fit": ["DATA_STEWARD"], "domain_fit": ["DATA_ENGINEERING"],
    "contract": {"archetype": "KNOWLEDGE_DOCUMENT", "fields": {}},
}
# Mirrors cortex-ui's DERIVED_BINDINGS row for PeriodSeries. Compact IRI on this side, full
# IRI on the engine side — `_canonical` folds both to the same token, which is the mechanism
# that lets the two repos spell it differently and still meet.
PERIOD_SERIES = {
    "subject_uri": "mesh:PeriodCostSeries", "archetype": "PERIOD_SERIES",
    "component": "PeriodSeries", "persona_fit": ["PORTFOLIO_LEAD"],
    "domain_fit": ["PORTFOLIO_PLANNING"],
    "contract": {"archetype": "PERIOD_SERIES", "component": "PeriodSeries",
                 "recomputes": True, "fields": {"rows": {}, "scope_label": {}}},
}


@pytest.fixture(autouse=True)
def _clean_registry():
    cr.clear()
    yield
    cr.clear()


def _planning_payload() -> dict:
    """A REAL verb's output, not a hand-written fixture. If the verb's row shape drifts, this
    seam test drifts with it — which is the point: the absorption depended on the shape."""
    rows = measures.plan_cost_curve(build_seed())
    return {
        "rows": rows,
        # The chart-shaped keys are present because a payload crossing /render_ui carries
        # whatever the envelope carries. Their presence is exactly why absorption was possible.
        "chart_data": json.dumps([{"period": r["period"], "total": r["total"]} for r in rows]),
        "chart_type": "BAR",
    }


COST_SERIES_URI = measures.OUTPUT_URI["plan_cost_curve"]


def test_without_its_binding_a_planning_payload_is_ABSORBED_not_refused():
    """The finding, pinned so it cannot be forgotten and re-discovered.

    This is NOT a bug in the selector — widening on an output_uri miss is deliberate and
    documented. It is a fact about what an unregistered planning verb gets, and the reason
    contracts come before widgets.
    """
    cr.register(FRONTEND, "1.0", [CHART, DOC])
    cap, prov = cr.select_presentation(FRONTEND, COST_SERIES_URI, _planning_payload(),
                                       persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
    assert cap is not None
    assert cap["archetype"] == "CHART_WIDGET", "absorbed by something — but not by the chart?"
    assert prov["presentation_source"] == "registered"
    assert prov["selection_basis"].startswith("payload-only")


def test_presentation_source_alone_cannot_tell_the_two_apart():
    """The gate's failure mode, stated as an assertion.

    Both worlds report `registered`. A gate reading only this field is green while the
    archetype is wrong — a-green-check-proves-only-its-scope, arriving through the very field
    ADR-0042 §5 originally told the reader to trust.
    """
    payload = _planning_payload()

    cr.register(FRONTEND, "1.0", [CHART, DOC])
    _, absorbed = cr.select_presentation(FRONTEND, COST_SERIES_URI, payload,
                                         persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
    cr.clear()
    cr.register(FRONTEND, "1.0", [CHART, DOC, PERIOD_SERIES])
    _, correct = cr.select_presentation(FRONTEND, COST_SERIES_URI, payload,
                                        persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")

    assert absorbed["presentation_source"] == correct["presentation_source"] == "registered"
    assert absorbed["selection_basis"] != correct["selection_basis"]


def test_with_its_binding_the_planning_contract_wins():
    """The closure. Gate 1's full assertion, in both halves."""
    cr.register(FRONTEND, "1.0", [CHART, DOC, PERIOD_SERIES])
    cap, prov = cr.select_presentation(FRONTEND, COST_SERIES_URI, _planning_payload(),
                                       persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
    assert cap["archetype"] == "PERIOD_SERIES"
    assert prov["presentation_source"] == "registered"
    assert prov["selection_basis"] == "output_uri+payload"


def test_the_recomputes_flag_reaches_the_selector_with_no_shape_change():
    """ADR-0042 Ruling 9's amendment predicted this and it holds: `recomputes` rides inside
    the contract object the assembled row already carries, so the selector can read it without
    any registration-shape change. Without a discriminant the anonymous-refusal ruling would
    be ruled and unimplementable, which is how it was first drafted."""
    cr.register(FRONTEND, "1.0", [CHART, DOC, PERIOD_SERIES])
    cap, _ = cr.select_presentation(FRONTEND, COST_SERIES_URI, _planning_payload(),
                                    persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
    assert cap["contract"]["recomputes"] is True
    # And the non-live archetypes say nothing, rather than saying False — absence is the
    # honest default for a flag a contract never declared.
    assert "recomputes" not in CHART["contract"]


def test_the_compact_and_full_iri_forms_fold_to_the_same_capability():
    """cortex-ui registers `mesh:PeriodCostSeries`; Engine P declares
    `http://invincible-agent/mesh#PeriodCostSeries`. If this folding ever stops working, every
    planning card silently reverts to absorption — the failure would look like nothing."""
    cr.register(FRONTEND, "1.0", [CHART, DOC, PERIOD_SERIES])
    payload = _planning_payload()
    for uri in ("mesh:PeriodCostSeries",
                "http://invincible-agent/mesh#PeriodCostSeries",
                "PeriodCostSeries"):
        cap, prov = cr.select_presentation(FRONTEND, uri, payload,
                                           persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
        assert cap["archetype"] == "PERIOD_SERIES", uri
        assert prov["selection_basis"] == "output_uri+payload", uri


# ─────────────────────────────────────────────────────────────────────────────
# The second archetype — proving the pattern replicates rather than being
# a property of the first renderer
# ─────────────────────────────────────────────────────────────────────────────

THRESHOLD_GRID = {
    "subject_uri": "mesh:LoadThresholdGrid", "archetype": "THRESHOLD_GRID",
    "component": "ThresholdGrid", "persona_fit": ["PORTFOLIO_LEAD"],
    "domain_fit": ["PORTFOLIO_PLANNING"],
    "contract": {"archetype": "THRESHOLD_GRID", "component": "ThresholdGrid",
                 "recomputes": True, "fields": {"rows": {}, "value_label": {}, "scope_label": {}}},
}


@pytest.mark.parametrize("verb,binding,archetype", [
    ("plan_cost_curve", PERIOD_SERIES, "PERIOD_SERIES"),
    ("plan_site_load", THRESHOLD_GRID, "THRESHOLD_GRID"),
])
def test_each_registered_planning_verb_reaches_its_own_archetype(verb, binding, archetype):
    """Parametrised deliberately. The first renderer proving the seam could be a property of
    that renderer; two proves it is a property of the MECHANISM, which is the claim ADR-0042
    §2 actually makes."""
    state = build_seed()
    rows = getattr(measures, verb)(state)
    payload = {"rows": rows,
               # chart-shaped keys present, because absorption depended on their presence
               "chart_data": json.dumps([{"k": 1, "v": 2}]), "chart_type": "BAR"}

    cr.register(FRONTEND, "1.0", [CHART, DOC, binding])
    cap, prov = cr.select_presentation(FRONTEND, measures.OUTPUT_URI[verb], payload,
                                       persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
    assert cap["archetype"] == archetype
    assert prov["presentation_source"] == "registered"
    assert prov["selection_basis"] == "output_uri+payload"
    assert cap["contract"]["recomputes"] is True


def test_registering_one_planning_archetype_does_not_capture_the_others_output():
    """The failure this guards: with PERIOD_SERIES registered and THRESHOLD_GRID not, a site
    load payload must NOT quietly land on PeriodSeries. It will still be absorbed by
    something — that is the documented widening — but the gate's selection_basis says so, and
    the absorbed archetype must not be a planning one, because that would look correct."""
    rows = measures.plan_site_load(build_seed())
    payload = {"rows": rows, "chart_data": json.dumps([{"k": 1}]), "chart_type": "BAR"}

    cr.register(FRONTEND, "1.0", [CHART, DOC, PERIOD_SERIES])   # grid NOT registered
    cap, prov = cr.select_presentation(FRONTEND, measures.OUTPUT_URI["plan_site_load"], payload,
                                       persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")
    assert prov["selection_basis"].startswith("payload-only"), "the gate must be able to say so"
    assert cap["archetype"] != "THRESHOLD_GRID", "unregistered archetype cannot win"


def test_every_planning_output_uri_is_distinct_so_none_can_shadow_another():
    """Ten verbs, ten fixed output types. Two verbs sharing one would make the selector's
    output_uri filter ambiguous between them, and the tie would be broken by affinity — a
    coin-flip dressed as a decision."""
    uris = list(measures.OUTPUT_URI.values())
    assert len(set(uris)) == len(uris)
