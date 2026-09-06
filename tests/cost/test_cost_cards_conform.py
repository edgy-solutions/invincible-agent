"""Every bound cost verb emits the AXIS KEYS its archetype requires.

THE DEFECT THIS EXISTS FOR cannot be caught on either side alone. The producer's own tests pass
- the rows are correct domain data. The component's own tests pass - it refuses a payload with
no axes, exactly as its contract says. Only the PAIR is wrong, and the pair is assembled in a
browser, which is why the planning side found three of these by looking at screenshots.

REQUIRED KEYS ARE READ OUT OF CORTEX-UI'S CONTRACTS when the sibling repo is checked out, so
this cannot go stale against a contract that grows a field. The mirror is used only when it is
absent, and is asserted equal to the parsed result whenever both are available.

THE POPULATION IS DERIVED from the binding table filtered to `cost:`, never listed here. A verb
bound without a case would otherwise be a gap nobody can see.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.cost_agent import measures
from agent_fleet.cost_agent.seed import build_state
from agent_fleet.presentation_agent.capabilities import (
    PRESENTATION_CAPABILITIES, canonical_iri_for_lookup,
)

_CORTEX = Path(__file__).resolve().parents[2].parent / "cortex-ui" / "src" / "components" / "planning"

_CONTRACTS = {
    "CONTRIBUTION_RANKING": ("ContributionRanking.contract.ts", "ContributionRow"),
    "MULTI_SERIES": ("MultiSeries.contract.ts", "MultiSeriesRow"),
    "DELTA_SET": ("DeltaSet.contract.ts", "DeltaEffect"),
}

_MIRROR = {
    "CONTRIBUTION_RANKING": {"entity_id", "entity_name", "contribution"},
    "MULTI_SERIES": {"period"},
    "DELTA_SET": {"metric", "direction", "magnitude", "affected"},
}

#: Where each archetype's rows live in the payload. `DELTA_SET` calls them `effects`, which is
#: its contract's word, not a synonym we chose.
_ROW_KEY = {"CONTRIBUTION_RANKING": "rows", "MULTI_SERIES": "rows", "DELTA_SET": "effects"}

#: One representative call per bound verb. Arguments only - the payload is the engine's.
_CALLS = {
    "cost_lot_breakdown": dict(lot=3, rate_vintage="2021-02-01"),
    "cost_unit_price_trend": {},
    "cost_labor_composition": dict(lot=3),
    "cost_rate_assumptions": dict(fiscal_year=2021),
    "cost_rate_comparison": dict(lot=3, rate_vintage="2021-02-01"),
    "cost_category_breakdown": dict(lot=3),
    "cost_supplier_concentration": dict(lot=3),
}

#: output class -> verb, derived from the engine's own table rather than restated.
_VERB_FOR = {uri.rsplit("#", 1)[-1]: fn for fn, uri in measures.OUTPUT_URI.items()}

COST_BINDINGS = [b for b in PRESENTATION_CAPABILITIES
                 if b["subject_uri"].startswith("cost:")]


def _parse_required(archetype: str) -> set[str] | None:
    fname, iface = _CONTRACTS[archetype]
    path = _CORTEX / fname
    if not path.is_file():
        return None
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"export interface {iface} \{{(.*?)^\}}", src, re.S | re.M)
    if not m:
        return None
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    body = re.sub(r"//.*", "", body)
    return {n for n, opt in re.findall(r"^\s*(\w+)(\??):", body, re.M) if not opt}


def required_keys(archetype: str) -> set[str]:
    parsed = _parse_required(archetype)
    if parsed is None:
        return _MIRROR[archetype]
    assert parsed == _MIRROR[archetype], (
        f"{archetype}: the contract requires {sorted(parsed)} but the mirror in this file says "
        f"{sorted(_MIRROR[archetype])} - a hand-copied list nobody checks is the "
        "second-source-of-truth problem this repo has been bitten by before")
    return parsed


@pytest.fixture(scope="module")
def state():
    return build_state()


@pytest.mark.parametrize("binding", COST_BINDINGS,
                         ids=[b["subject_uri"] for b in COST_BINDINGS])
def test_every_bound_cost_verb_emits_its_archetypes_axis_keys(binding, state):
    shape = binding["subject_uri"].split(":", 1)[1]
    fn_name = _VERB_FOR[shape]
    payload = measures.VERBS[fn_name](state, **_CALLS[fn_name])
    rows = payload[_ROW_KEY[binding["archetype"]]]
    assert rows, f"{fn_name} produced no rows to draw"
    missing = required_keys(binding["archetype"]) - set(rows[0])
    assert not missing, (
        f"{fn_name} -> {binding['archetype']}: rows are missing {sorted(missing)}. The card "
        f"renders blank; both sides' own tests pass.")


@pytest.mark.parametrize("binding", COST_BINDINGS,
                         ids=[b["subject_uri"] for b in COST_BINDINGS])
def test_the_expected_fields_on_the_row_are_ACTUALLY_EMITTED(binding, state):
    """A binding advertising a field the producer does not emit is a promise to the selector."""
    shape = binding["subject_uri"].split(":", 1)[1]
    fn_name = _VERB_FOR[shape]
    payload = measures.VERBS[fn_name](state, **_CALLS[fn_name])
    for field in binding["expected_fields"]:
        present = field in payload or field in payload[_ROW_KEY[binding["archetype"]]][0]
        assert present, f"{fn_name} advertises {field!r} and emits it nowhere"


def test_EVERY_cost_output_class_is_bound_or_REFUSED_IN_WRITING():
    """DERIVED FROM THE ENGINE'S TABLE. A verb quietly unbound renders as
    'Knowledge Document - No content available', which is indistinguishable from a verb that
    was never built - so an absence has to be a written claim, not a gap.
    """
    bound = {b["subject_uri"].split(":", 1)[1] for b in COST_BINDINGS}
    every = {uri.rsplit("#", 1)[-1] for uri in measures.OUTPUT_URI.values()}
    unbound = every - bound
    assert unbound == {"PriceComposition", "ExportPackage"}, (
        f"unbound cost shapes changed: {sorted(unbound)}. Bind it, or record the refusal here "
        "and in capabilities.py beside the rows.")
    src = Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent" / "capabilities.py"
    text = src.read_text(encoding="utf-8")
    assert "cost_price_composition` IS DELIBERATELY ABSENT" in text, (
        "the refusal for PriceComposition is no longer written down beside the rows")


def test_the_cost_prefix_EXPANDS(binding=None):
    """Without it every row above registers, reports accepted, and never matches a payload."""
    assert canonical_iri_for_lookup("cost:LotCostBreakdown") == (
        "http://invincible-agent/cost#LotCostBreakdown")
    for b in COST_BINDINGS:
        assert canonical_iri_for_lookup(b["subject_uri"]).startswith("http://"), b["subject_uri"]


def test_the_MULTI_SERIES_declarations_appear_in_every_row(state):
    """The real guard for MULTI_SERIES is not a key list: a declared series whose key is absent
    from a row draws a line with a hole in it and no error anywhere."""
    for b in COST_BINDINGS:
        if b["archetype"] != "MULTI_SERIES":
            continue
        fn_name = _VERB_FOR[b["subject_uri"].split(":", 1)[1]]
        payload = measures.VERBS[fn_name](state, **_CALLS[fn_name])
        keys = [s["key"] for s in payload["series"]]
        assert keys, f"{fn_name} declares no series"
        for row in payload["rows"]:
            for key in keys:
                assert key in row, f"{fn_name}: row {row.get('period')} lacks declared {key!r}"
                assert isinstance(row[key], (int, float)), (
                    f"{fn_name}: {key!r} is {type(row[key]).__name__}, not a number")


def test_DELTA_SET_direction_is_the_MEASURES_judgement_not_a_sign_test(state):
    """The contract is explicit: a renderer inferring direction from the sign of `delta` would
    call a rising capability level a degradation. So the measure must state it - and must state
    something a sign test could not: `neutral` at zero."""
    out = measures.cost_rate_comparison(state, lot=3, rate_vintage="2021-02-01")
    directions = {e["direction"] for e in out["effects"]}
    assert directions <= {"improved", "degraded", "neutral"}
    for e in out["effects"]:
        if e["delta"] == 0:
            assert e["direction"] == "neutral"
        elif e["delta"] > 0:
            assert e["direction"] == "degraded", "a rate above estimate raises the price"


def test_DELTA_SET_affected_is_NOT_EMPTY_and_names_real_steps(state):
    """A required field with nothing to put in it is the declared-but-unwired shape. Every rate
    factor here feeds named composition steps, so the list is fact rather than filler."""
    from agent_fleet.cost_agent.pricing import DEFAULT_COMPOSITION

    names = {s.name for s in DEFAULT_COMPOSITION} | {'Base cost'}
    out = measures.cost_rate_comparison(state, lot=3, rate_vintage="2021-02-01")
    unwired = [e["metric"] for e in out["effects"] if not e["affected"]]
    assert not unwired, f"these factors affect nothing: {unwired}"
    for e in out["effects"]:
        assert set(e["affected"]) <= names, f"{e['metric']} names a step that does not exist"


def test_the_generic_keys_did_not_REPLACE_the_domain_names(state):
    """Engine F's rule, and its reason: renaming the domain fields to fit a renderer is the
    translation layer ADR-0045 refused at the ontology layer. An analyst reading the payload
    must still see their own vocabulary."""
    checks = [
        ("cost_lot_breakdown", dict(lot=3, rate_vintage="2021-02-01"), "rows", "category"),
        ("cost_labor_composition", dict(lot=3), "rows", "labor_kind"),
        ("cost_supplier_concentration", dict(lot=3), "rows", "supplier"),
        ("cost_category_breakdown", dict(lot=3), "rows", "share_delta_vs_prior_lot"),
        ("cost_rate_comparison", dict(lot=3, rate_vintage="2021-02-01"), "effects", "factor"),
    ]
    for fn_name, kw, row_key, domain_field in checks:
        rows = measures.VERBS[fn_name](state, **kw)[row_key]
        assert domain_field in rows[0], f"{fn_name} dropped {domain_field!r}"


def test_money_stays_EXACT_in_the_domain_field(state):
    """`contribution` is a float because the renderer needs a number. The exact Decimal string
    stays in the domain field, and the two must agree to the cent."""
    from decimal import Decimal

    out = measures.cost_lot_breakdown(state, lot=3, rate_vintage="2021-02-01")
    for row in out["rows"]:
        assert isinstance(row["price"], str), "the exact figure stopped being a string"
        assert abs(Decimal(row["price"]) - Decimal(str(row["contribution"]))) < Decimal("0.005")
