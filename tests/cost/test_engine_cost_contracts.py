"""Seals for engine-cost. Each is written to BITE, and several are proven to.

WHAT THESE DO NOT DO: assert that a component reports itself healthy, or count anything
whose count cannot change when the thing being claimed breaks. The runbook's governing rule
applies to unit tests as much as to cluster checks — ask at the resolution of the claim.

The cluster-side seals (verb edges by name, classes by name and parent, the routed question)
are runbook §9's and cannot run here; they are listed in the packet's completion bar.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_fleet.cost_agent import measures, slots
from agent_fleet.cost_agent.entities import NotInModel, VintageRequired
from agent_fleet.cost_agent.pricing import (
    CompositionError, RateSet, compose_price, rates_for, unit_price,
)
from agent_fleet.cost_agent.seed import build_state, check_consistency, unit_prices


@pytest.fixture(scope="module")
def state():
    s = build_state()
    check_consistency(s)
    return s


def _rates(**over) -> RateSet:
    base = dict(
        fiscal_year=2026, vintage="2026-02-01", fringe=Decimal("0.35"),
        overhead=Decimal("0.85"), g_and_a=Decimal("0.12"),
        cost_of_money=Decimal("0.015"), profit=Decimal("0.10"),
        escalation=Decimal("1.03"),
    )
    base.update(over)
    return RateSet(**base)


# ---------------------------------------------------------------------------------------
# SEAL 1 — the composition sums. ADR-0047 §3's arithmetic claim.
# ---------------------------------------------------------------------------------------
def test_composition_sums_to_its_own_price():
    b = compose_price(
        direct_labor=Decimal("1000000"), material=Decimal("2500000"),
        other_direct=Decimal("150000"), rates=_rates(),
    )
    assert b.sums()
    assert sum((s.amount for s in b.steps), Decimal("0")) == b.price


def test_composition_sums_for_every_seeded_lot(state):
    """The seal across the real seed, not one hand-picked case."""
    for n in state.lot_numbers:
        r = measures.cost_price_composition(state, lot=n, rate_vintage=state.vintages(
            state.lot(n).fiscal_year)[0])
        assert r["sums"] is True, f"lot {n} composition does not sum"
        assert sum(Decimal(s["amount"]) for s in r["steps"]) == Decimal(r["price"])


def test_the_sum_seal_BITES_when_THE_TWO_PATHS_DISAGREE(monkeypatch):
    """PROVEN TO BITE. A seal that has never failed is decoration.

    The seal's claim is that the step loop and the independent fold agree, so the bite check
    breaks ONE PATH and confirms compose_price refuses.

    ITS FIRST VERSION CORRUPTED THE Nth CALL TO quantize_money AND WENT SILENTLY VACUOUS when
    the composition became parameterised: three new quantize calls were added for the
    components dict, so index 3 moved onto `material` — which the default spec never uses as
    a basis. The mutation stopped touching anything load-bearing and the test passed while
    proving nothing. A bite check keyed on a CALL INDEX is a check on the neighbour of the
    claim; keyed on a PATH, it tests what the seal actually asserts.
    """
    import agent_fleet.cost_agent.pricing as pricing

    real_fold = pricing._fold_price
    monkeypatch.setattr(
        pricing, "_fold_price",
        lambda *a, **k: real_fold(*a, **k) + Decimal("0.01"),
    )
    with pytest.raises(CompositionError, match="does not sum"):
        pricing.compose_price(
            direct_labor=Decimal("1000000"), material=Decimal("2500000"),
            other_direct=Decimal("150000"), rates=_rates(),
        )


# ---------------------------------------------------------------------------------------
# SEAL 2 — the ORDER is the algorithm. Applying the same factors differently is wrong.
# ---------------------------------------------------------------------------------------
def test_overhead_is_struck_on_labor_plus_fringe_not_on_labor():
    """The basis is checkable from the payload, and it is the thing a reader verifies."""
    b = compose_price(
        direct_labor=Decimal("1000000"), material=Decimal("0"),
        other_direct=Decimal("0"), rates=_rates(),
    )
    steps = {s.name: s for s in b.steps}
    assert steps["Fringe"].basis == Decimal("1000000.00")
    assert steps["Overhead"].basis == Decimal("1350000.00")   # labour + fringe, not labour
    assert steps["Overhead"].amount == Decimal("1147500.00")


def test_g_and_a_is_struck_on_the_subtotal_including_overhead():
    b = compose_price(
        direct_labor=Decimal("1000000"), material=Decimal("0"),
        other_direct=Decimal("0"), rates=_rates(),
    )
    steps = {s.name: s for s in b.steps}
    assert steps["G&A"].basis == steps["Overhead"].running_total


# ---------------------------------------------------------------------------------------
# SEAL 3 — the TREND seal. A flat curve makes every trend verb vacuous.
# ---------------------------------------------------------------------------------------
def test_unit_price_actually_trends_across_lots(state):
    prices = [p for _, p in unit_prices(state)]
    assert len(set(prices)) == len(prices), "unit prices repeat — the curve is flat somewhere"
    spread = (max(prices) - min(prices)) / max(prices)
    assert spread > Decimal("0.10"), f"spread {spread} is too small to read as a trend"


def test_the_trend_is_LUMPY_not_a_straight_line(state):
    """A perfectly monotone curve is the uniform-result tell wearing a trend's clothes."""
    prices = [p for _, p in unit_prices(state)]
    deltas = [b - a for a, b in zip(prices, prices[1:])]
    assert not all(d < 0 for d in deltas), "every lot falls — this is a line, not a curve"
    assert any(d < 0 for d in deltas), "nothing falls — learning is not visible at all"


def test_the_trend_seal_BITES_on_a_flat_seed(state):
    """PROVEN TO BITE. Flatten the seed and confirm check_consistency refuses it."""
    import copy

    flat = copy.deepcopy(state)
    first = flat.lot(1)
    for n in flat.lot_numbers:
        flat.lots[n] = type(first)(
            number=n, quantity=first.quantity, cumulative_units=first.cumulative_units,
            fiscal_year=first.fiscal_year,
            labor=first.labor, material=first.material, other_direct=first.other_direct,
            warranty=first.warranty, warranty_hours=first.warranty_hours,
            contracts=first.contracts, suppliers=first.suppliers,
            estimating_rates=first.estimating_rates,
        )
    with pytest.raises(ValueError, match="identical across every lot|spread"):
        check_consistency(flat)


# ---------------------------------------------------------------------------------------
# SEAL 4 — the DESIGNED REFUSAL. A price without its rate vintage is not an answer.
# ---------------------------------------------------------------------------------------
def test_a_price_without_a_vintage_refuses_and_names_the_options(state):
    with pytest.raises(VintageRequired) as ei:
        measures.cost_price_composition(state, lot=1, rate_vintage=None)
    assert ei.value.available == ["2019-02-01", "2019-08-01"]


def test_there_is_no_nearest_vintage_fallback(state):
    """A silent fall back to the newest table is the defect the slot exists to prevent."""
    with pytest.raises(CompositionError, match="no rate set"):
        rates_for(state.rates, 2019, "2019-12-31")


def test_rate_assumptions_answers_WITHOUT_a_vintage(state):
    """The asymmetry is deliberate: listing the table is how a caller discovers vintages.

    Refusing here too would make the refusal above unanswerable — a refusal that guides
    versus one that stonewalls.
    """
    out = measures.cost_rate_assumptions(state)
    assert out["rows"], "the discovery verb must answer without a vintage"


# ---------------------------------------------------------------------------------------
# SEAL 5 — ADR-0049 Ruling 4: the three refusal states are DISTINGUISHABLE.
# ---------------------------------------------------------------------------------------
def test_refusal_states_are_distinct_types_not_one_message():
    from agent_fleet.cost_agent.entities import SourceUnavailable, Unentitled

    assert not issubclass(Unentitled, NotInModel)
    assert not issubclass(SourceUnavailable, NotInModel)
    assert not issubclass(Unentitled, SourceUnavailable)


def test_not_in_model_is_not_an_empty_result(state):
    """An unknown lot RAISES. Returning empty would make absence and ignorance identical."""
    with pytest.raises(NotInModel):
        measures.cost_lot_breakdown(state, lot=999, rate_vintage="2019-02-01")


# ---------------------------------------------------------------------------------------
# SEAL 6 — Contract D: both ends declared, and they match the TTL.
# ---------------------------------------------------------------------------------------
def test_every_verb_declares_both_contract_d_ends():
    assert set(measures.VERBS) == set(measures.OUTPUT_URI) == set(measures.INPUT_URI)


def test_declared_uris_exist_in_the_ontology_file():
    """DERIVED FROM THE TTL, not from a list someone remembered.

    This is the check that would have caught the planning engine's twelve 422s before
    deployment: it reads the file the prime ingests and asserts the registration's URIs are
    in it, rather than asserting a count.
    """
    import rdflib
    from rdflib.namespace import OWL, RDF

    g = rdflib.Graph()
    g.parse("setup/ontologies/cost_extension.ttl", format="turtle")
    declared = {str(s) for s in g.subjects(RDF.type, OWL.Class)}

    for verb in measures.VERBS:
        assert measures.INPUT_URI[verb] in declared, f"{verb}: input_uri not in the TTL"
        assert measures.OUTPUT_URI[verb] in declared, f"{verb}: output_uri not in the TTL"


def test_output_shapes_are_declared_response_subclasses():
    """The grounding-pool exclusion is inherited from this declaration, so assert it here.

    Without `subClassOf mesh:Response` a verb's OUTPUT re-enters Engine O's candidate pool
    and competes with its own INPUT subject — measured at 12/20 on Engine F's corpus.
    """
    import rdflib
    from rdflib.namespace import RDFS

    g = rdflib.Graph()
    g.parse("setup/ontologies/cost_extension.ttl", format="turtle")
    response = rdflib.URIRef("http://invincible-agent/mesh#Response")
    resp_classes = {str(s) for s in g.subjects(RDFS.subClassOf, response)}
    for verb, uri in measures.OUTPUT_URI.items():
        assert uri in resp_classes, f"{verb}'s output is not subClassOf mesh:Response"


# ---------------------------------------------------------------------------------------
# SEAL 7 — slots are DERIVED, and the mandatory set is what the engine actually enforces.
# ---------------------------------------------------------------------------------------
def test_slot_types_survive_postponed_annotations():
    """`lot` is an integer. Without eval_str=True it declares as a string to every consumer."""
    decl = {s["name"]: s for s in slots.slots_for("cost_lot_breakdown")}
    assert decl["lot"]["type"] == "integer"
    assert decl["lot"]["required"] is True
    assert decl["lot"]["referent"].endswith("ProductionLot")


def test_enum_values_are_read_out_of_the_type_not_transcribed():
    decl = {s["name"]: s for s in slots.slots_for("cost_unit_price_trend")}
    assert decl["category"]["values"] == [
        "labor", "material", "other_direct", "warranty", "contracts"
    ]


def test_mandatory_slots_match_what_the_verbs_refuse_without(state):
    """The declaration and the enforcement must agree, or the ask is for the wrong thing."""
    for verb in ("cost_lot_breakdown", "cost_rate_comparison", "cost_price_composition"):
        assert slots.mandatory_slots(verb) == ["lot", "rate_vintage"]


# ---------------------------------------------------------------------------------------
# SEAL 8 — ADR-0047 §3: the pricing module is importable with NO application context.
# ---------------------------------------------------------------------------------------
def test_pricing_module_imports_standalone(tmp_path):
    """The export precondition, asserted rather than hoped.

    Copies pricing.py alone into an empty directory and imports it with the repository
    removed from sys.path. If this ever fails, ADR-0047 §3's byte-identical claim has
    quietly become false and the export cannot be built.
    """
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    src = Path("agent_fleet/cost_agent/pricing.py").resolve()
    shutil.copy(src, tmp_path / "pricing.py")
    code = (
        "import sys; sys.path=[p for p in sys.path if 'invincible-agent' not in p];"
        "import pricing; from decimal import Decimal as D;"
        "r=pricing.RateSet(fiscal_year=2026,vintage='v',fringe=D('0.35'),overhead=D('0.85'),"
        "g_and_a=D('0.12'),cost_of_money=D('0.015'),profit=D('0.10'),escalation=D('1.0'));"
        "b=pricing.compose_price(direct_labor=D('100'),material=D('0'),other_direct=D('0'),rates=r);"
        "assert b.sums(); print('OK')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert out.returncode == 0, f"pricing.py is not standalone-importable:\n{out.stderr}"
    assert "OK" in out.stdout


def test_pricing_imports_nothing_from_its_own_package():
    """The import arrow must not invert. pricing.py -> (nothing in this package)."""
    src = open("agent_fleet/cost_agent/pricing.py", encoding="utf-8").read()
    for forbidden in ("entities", "seed", "measures", "slots", "iagent_mesh", "fastapi"):
        assert f"import {forbidden}" not in src, (
            f"pricing.py imports {forbidden}; the export stops being isolable"
        )


# ---------------------------------------------------------------------------------------
# SEAL 9 — THE EXTENSION SURFACE. Parameters, never code (ADR-0047 §3).
#
# A recipient with a different burden structure supplies a different RateSet and a different
# STEP SEQUENCE, both DATA, validated against a closed vocabulary. What they cannot do is
# author or edit the computation — because a subclassed step is not our algorithm, and every
# guarantee ADR-0047 §3 makes rests on the algorithm being ours and pinned.
# ---------------------------------------------------------------------------------------
def test_a_customer_can_supply_a_different_burden_STRUCTURE_as_data():
    """The real extension case: no fringe, overhead struck straight on labour."""
    from agent_fleet.cost_agent.pricing import DEFAULT_COMPOSITION, StepSpec

    theirs = (
        StepSpec("Overhead", "overhead", "component", component="direct_labor"),
        StepSpec("G&A", "g_and_a", "running_total"),
        StepSpec("Profit", "profit", "running_total"),
    )
    ours = compose_price(
        direct_labor=Decimal("1000000"), material=Decimal("500000"),
        other_direct=Decimal("0"), rates=_rates(), spec=DEFAULT_COMPOSITION,
    )
    theirs_built = compose_price(
        direct_labor=Decimal("1000000"), material=Decimal("500000"),
        other_direct=Decimal("0"), rates=_rates(), spec=theirs,
    )
    assert theirs_built.sums() and ours.sums()
    assert theirs_built.price != ours.price, "a different structure must produce a different price"
    assert [s.name for s in theirs_built.steps] == [
        "Base cost", "Overhead", "G&A", "Profit"
    ]


def test_an_undeclared_basis_kind_is_REFUSED_not_defaulted():
    from agent_fleet.cost_agent.pricing import StepSpec, validate_composition

    with pytest.raises(CompositionError, match="basis_kind"):
        validate_composition((StepSpec("X", "fringe", "whatever_i_like"),))


def test_an_undeclared_rate_key_is_REFUSED():
    from agent_fleet.cost_agent.pricing import StepSpec, validate_composition

    with pytest.raises(CompositionError, match="not a declared rate"):
        validate_composition((StepSpec("X", "my_secret_markup", "running_total"),))


def test_a_FORWARD_step_reference_is_refused_rather_than_treated_as_zero():
    """Resolving it as zero would silently UNDERSTATE the price — the dangerous direction."""
    from agent_fleet.cost_agent.pricing import StepSpec, validate_composition

    with pytest.raises(CompositionError, match="has not run yet"):
        validate_composition((
            StepSpec("Overhead", "overhead", "component",
                     component="direct_labor", plus_steps=("Fringe",)),
            StepSpec("Fringe", "fringe", "component", component="direct_labor"),
        ))


def test_duplicate_step_names_are_refused():
    from agent_fleet.cost_agent.pricing import StepSpec, validate_composition

    with pytest.raises(CompositionError, match="duplicate"):
        validate_composition((
            StepSpec("Fringe", "fringe", "component", component="direct_labor"),
            StepSpec("Fringe", "overhead", "running_total"),
        ))


def test_the_default_composition_is_itself_valid():
    """The shipped default must satisfy the validator it ships with."""
    from agent_fleet.cost_agent.pricing import DEFAULT_COMPOSITION, validate_composition

    validate_composition(DEFAULT_COMPOSITION)


def test_validation_runs_BEFORE_any_arithmetic():
    """A bad spec must be refused where it is read, not after producing a wrong number."""
    from agent_fleet.cost_agent.pricing import StepSpec

    with pytest.raises(CompositionError, match="not a declared rate"):
        compose_price(
            direct_labor=Decimal("1"), material=Decimal("0"), other_direct=Decimal("0"),
            rates=_rates(), spec=(StepSpec("X", "nope", "running_total"),),
        )


# ---------------------------------------------------------------------------------------
# SEAL 10 — the two verbs minted to close the gate's honest reds
# (docs/plans/cost-category-and-supplier-need-verbs.md)
# ---------------------------------------------------------------------------------------
def test_category_breakdown_reports_SHARE_and_MOVEMENT_not_amount(state):
    """The distinction from cost_lot_breakdown, asserted rather than left to the prose."""
    r = measures.cost_category_breakdown(state, lot=4)
    assert r["compared_to_lot"] == 3
    shares = {x["category"]: Decimal(x["share_of_total"]) for x in r["rows"]}
    assert abs(sum(shares.values()) - Decimal("1")) < Decimal("0.001"), "shares must total 1"
    assert all(x["share_delta_vs_prior_lot"] is not None for x in r["rows"])
    assert {x["direction"] for x in r["rows"]} <= {"up", "down", "flat"}


def test_the_FIRST_lot_reports_absent_movement_not_zero(state):
    """A flat delta and an absent one mean different things; lot 1 has no prior."""
    r = measures.cost_category_breakdown(state, lot=1)
    assert r["compared_to_lot"] is None
    assert all(x["share_delta_vs_prior_lot"] is None for x in r["rows"])
    assert all(x["direction"] is None for x in r["rows"])


def test_category_breakdown_needs_NO_rate_vintage(state):
    """A share is a ratio of recorded costs, so demanding a vintage would be ceremony."""
    assert slots.mandatory_slots("cost_category_breakdown") == ["lot"]
    measures.cost_category_breakdown(state, lot=5)


def test_concentration_ALWAYS_discloses_its_threshold_and_whether_it_defaulted(state):
    """A verdict against a bound the caller never saw is the EAC-without-method shape."""
    d = measures.cost_supplier_concentration(state, lot=4)
    assert d["threshold_defaulted"] is True and d["threshold"] == "0.25"

    n = measures.cost_supplier_concentration(state, lot=4, threshold=0.5)
    assert n["threshold_defaulted"] is False and n["threshold"] == "0.5"


def test_the_threshold_actually_CHANGES_the_verdict(state):
    """Otherwise the parameter is decorative and the disclosure is decorative with it."""
    low = measures.cost_supplier_concentration(state, lot=4, threshold=0.1)
    high = measures.cost_supplier_concentration(state, lot=4, threshold=0.5)
    assert low["suppliers_above_threshold"] > high["suppliers_above_threshold"]


def test_a_threshold_outside_0_to_1_is_refused(state):
    """Concentration is a proportion; an amount-shaped threshold is a category error."""
    with pytest.raises(NotInModel, match="between 0 and 1"):
        measures.cost_supplier_concentration(state, lot=4, threshold=25000)


def test_concentration_rows_are_ordered_largest_first(state):
    r = measures.cost_supplier_concentration(state, lot=6)
    shares = [Decimal(x["share_of_purchased"]) for x in r["rows"]]
    assert shares == sorted(shares, reverse=True)
    assert r["largest_share"] == str(shares[0])


def test_both_new_verbs_declare_both_contract_d_ends_in_the_TTL():
    """The check that would have caught the planning engine's twelve 422s, for the new two."""
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS

    g = rdflib.Graph()
    g.parse("setup/ontologies/cost_extension.ttl", format="turtle")
    declared = {str(s) for s in g.subjects(RDF.type, OWL.Class)}
    response = {str(s) for s in g.subjects(
        RDFS.subClassOf, rdflib.URIRef("http://invincible-agent/mesh#Response"))}

    for verb in ("cost_category_breakdown", "cost_supplier_concentration"):
        assert measures.INPUT_URI[verb] in declared, f"{verb}: input_uri absent from the TTL"
        assert measures.OUTPUT_URI[verb] in declared, f"{verb}: output_uri absent from the TTL"
        assert measures.OUTPUT_URI[verb] in response, (
            f"{verb}: output is not subClassOf mesh:Response, so it would re-enter the "
            "grounding pool and compete with its own subject"
        )


def test_the_declaration_uses_the_key_THE_CONSUMER_READS():
    """`required`, not `mandatory` — and the consumer is the reason, not convention.

    ontology_service/main.py builds the slot-filling prompt and marks a slot REQUIRED from
    `d.get("required")`. This engine emitted `mandatory`, which that line never reads, so
    every spoken-mandatory slot reached the filler UNMARKED — a weaker fill and a needless
    ask, and nothing failed, which is why it survived. Engines F and P both emit `required`.
    """
    for verb in measures.VERBS:
        for d in slots.slots_for(verb):
            assert "required" in d, f"{verb}.{d['name']}: no `required` key for the filler"
            assert "mandatory" not in d, (
                f"{verb}.{d['name']}: still emits `mandatory`, which no consumer reads"
            )
