"""engine-cost's six verbs. Deterministic, typed, pure over `CostState`.

ADR-0030: one verb, one fixed output type. `OUTPUT_URI` below is the whole of that contract,
and every URI in it is declared in `setup/ontologies/cost_extension.ttl` — both Contract D
ends in one file, because the planning engine's split is what let its input half go missing
for twelve registrations while the engine served /health normally throughout.

WHAT THESE FUNCTIONS MUST NEVER DO — inherited verbatim from Engines P and F, each
prohibition being a defect somebody already paid for:
  * choose a view, a chart type, or an archetype        (ADR-0042 §2 — the selector's job)
  * return an empty result to mean "not in the model"   (raise NotInModel instead)
  * invent a threshold, a rate, or a VINTAGE            (see the vintage-bearing verbs)
  * emit a monetary figure without its unit             (every row carries value_unit)

AND ONE THIS ENGINE ADDS, FROM ADR-0049 RULING 4. These verbs will be INNER CALLS in an
affordability composition, so their refusals must let a composing verb tell EMPTY from
UNAVAILABLE from UNENTITLED. Three distinct exception types, never one message — a composing
verb cannot report honestly over a source that cannot say which of the three happened, and
the collapse is invisible because all three render as "no data" to a reader.

EVERY CONCEPT HERE IS PUBLIC COST-ESTIMATING PRACTICE. Nothing is derived from any real
program, supplier or rate agreement.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import (
        COST, CostState, LaborKind, NotInModel, VintageRequired,
    )
    from pricing import compose_price, rates_for, unit_price
except ImportError:
    from agent_fleet.cost_agent.entities import (
        COST, CostState, LaborKind, NotInModel, VintageRequired,
    )
    from agent_fleet.cost_agent.pricing import compose_price, rates_for, unit_price

#: ONE VERB, ONE FIXED OUTPUT TYPE (ADR-0030). Read twice — by the route, to stamp the
#: response, and by the registration, to fill Contract D's output end — so the two cannot
#: disagree about what a verb produces.
OUTPUT_URI: dict[str, str] = {
    "cost_lot_breakdown":      COST + "LotCostBreakdown",
    "cost_unit_price_trend":   COST + "UnitPriceTrend",
    "cost_rate_comparison":    COST + "RateComparison",
    "cost_labor_composition":  COST + "LaborComposition",
    "cost_price_composition":  COST + "PriceComposition",
    "cost_rate_assumptions":   COST + "RateAssumptions",
    "cost_category_breakdown": COST + "CategoryBreakdown",
    "cost_supplier_concentration": COST + "SupplierConcentration",
}

#: The SUBJECT each verb is asked about — Contract D's input end.
INPUT_URI: dict[str, str] = {
    "cost_lot_breakdown":      COST + "ProductionLot",
    "cost_unit_price_trend":   COST + "ProductionProgram",
    "cost_rate_comparison":    COST + "ProductionLot",
    "cost_labor_composition":  COST + "ProductionLot",
    "cost_price_composition":  COST + "ProductionLot",
    "cost_rate_assumptions":   COST + "RateTable",
    "cost_category_breakdown": COST + "CostCategory",
    "cost_supplier_concentration": COST + "Supplier",
}

#: Money is dollars throughout. Declared per row rather than assumed, because "dollars or
#: thousands of dollars" is the one question a cost answer must never leave to convention.
VALUE_UNIT = "USD"
HOURS_UNIT = "hours"

#: The default concentration bound, ONE QUARTER of purchased value. A round, defensible
#: figure rather than a tuned one -- and it is DISCLOSED in every answer that uses it
#: (see `cost_supplier_concentration`), because a threshold the caller cannot see makes
#: the verdict unreproducible.
DEFAULT_CONCENTRATION_THRESHOLD = Decimal("0.25")


def _require_vintage(state: CostState, fiscal_year: int, rate_vintage: Optional[str]) -> str:
    """The designed refusal: a forward-looking figure needs its assumption set NAMED.

    Analogue of Engine F's mandatory EAC method. Defaulting to the newest vintage would hand
    back a price whose basis the caller never chose and cannot see — and a caller acting on
    it could not reproduce it, which is the whole property this engine exists to provide.
    """
    if rate_vintage:
        return rate_vintage
    available = state.vintages(fiscal_year)
    raise VintageRequired(
        f"a price for fiscal year {fiscal_year} depends on which rate vintage is applied, "
        f"and the vintages for that year differ. Name one of: {', '.join(available)}",
        available=available,
    )


def _applied_rates(state: CostState, lot_number: int, rate_vintage: Optional[str]):
    lot = state.lot(lot_number)
    vintage = _require_vintage(state, lot.fiscal_year, rate_vintage)
    return lot, rates_for(state.rates, lot.fiscal_year, vintage)


# ---------------------------------------------------------------------------------------
# 1. cost_lot_breakdown — per-category price and hours for one lot
# ---------------------------------------------------------------------------------------
def cost_lot_breakdown(state: CostState, *, lot: int, rate_vintage: str) -> dict[str, Any]:
    """Decompose one lot's cost into its five accounting buckets."""
    lot_obj, rates = _applied_rates(state, lot, rate_vintage)
    rows = [
        {"category": "labor",        "price": lot_obj.direct_labor,
         "hours": sum((l.hours for l in lot_obj.labor), Decimal("0"))},
        {"category": "material",     "price": lot_obj.material,     "hours": None},
        {"category": "other_direct", "price": lot_obj.other_direct, "hours": None},
        {"category": "warranty",     "price": lot_obj.warranty,     "hours": lot_obj.warranty_hours},
        {"category": "contracts",    "price": lot_obj.contracts,    "hours": None},
    ]
    for r in rows:
        r["price"] = str(r["price"])
        r["hours"] = None if r["hours"] is None else str(r["hours"])
        r["value_unit"] = VALUE_UNIT
        r["hours_unit"] = HOURS_UNIT
    return {
        "output_uri": OUTPUT_URI["cost_lot_breakdown"],
        "lot": lot_obj.number,
        "quantity": lot_obj.quantity,
        "fiscal_year": lot_obj.fiscal_year,
        "rate_vintage": rates.vintage,
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 2. cost_unit_price_trend — unit price per lot across the program, by category
# ---------------------------------------------------------------------------------------
def cost_unit_price_trend(state: CostState, *, category: Optional[str] = None) -> dict[str, Any]:
    """Cost per unit at each successive lot. The ORDER is the answer, not the values.

    Takes no rate vintage: each lot is priced at the rates that were actually applied to it,
    which is what makes the series comparable across years. A single vintage imposed across
    nine fiscal years would be a counterfactual, not a trend.
    """
    series: list[dict[str, Any]] = []
    for n in state.lot_numbers:
        lot_obj = state.lot(n)
        vintage = state.vintages(lot_obj.fiscal_year)[0]
        rates = rates_for(state.rates, lot_obj.fiscal_year, vintage)
        build = compose_price(
            direct_labor=lot_obj.direct_labor,
            material=lot_obj.material,
            other_direct=lot_obj.other_direct + lot_obj.warranty + lot_obj.contracts,
            rates=rates,
        )
        series.append({
            "lot": n,
            "quantity": lot_obj.quantity,
            "fiscal_year": lot_obj.fiscal_year,
            "unit_price": str(unit_price(build, lot_obj.quantity)),
            "value_unit": VALUE_UNIT,
            "rate_vintage": rates.vintage,
        })
    return {
        "output_uri": OUTPUT_URI["cost_unit_price_trend"],
        "program": state.program_name,
        "category": category or "all",
        "series": series,
    }


# ---------------------------------------------------------------------------------------
# 3. cost_rate_comparison — applied rates against the rates assumed at estimate
# ---------------------------------------------------------------------------------------
def cost_rate_comparison(state: CostState, *, lot: int, rate_vintage: str) -> dict[str, Any]:
    """Applied versus estimating rates for one lot, factor by factor."""
    lot_obj, applied = _applied_rates(state, lot, rate_vintage)
    est = lot_obj.estimating_rates
    factors = ("fringe", "overhead", "g_and_a", "cost_of_money", "profit", "escalation")
    rows = []
    for f in factors:
        a, e = getattr(applied, f), getattr(est, f)
        rows.append({
            "factor": f,
            "applied": str(a),
            "estimating": str(e),
            "delta": str(a - e),
            # A rate is a factor, not an amount — it carries no monetary unit, and saying
            # so explicitly stops a renderer appending one.
            "value_unit": None,
        })
    return {
        "output_uri": OUTPUT_URI["cost_rate_comparison"],
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "applied_vintage": applied.vintage,
        "estimating_vintage": est.vintage,
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 4. cost_labor_composition — touch / support / SEPM split for one lot
# ---------------------------------------------------------------------------------------
def cost_labor_composition(state: CostState, *, lot: int) -> dict[str, Any]:
    """Worked effort by kind of work. No vintage: these are recorded hours and rates."""
    lot_obj = state.lot(lot)
    total = lot_obj.direct_labor
    rows = []
    for kind in ("touch", "support", "sepm"):
        line = lot_obj.labor_of(kind)  # type: ignore[arg-type]
        rows.append({
            "labor_kind": kind,
            "hours": str(line.hours),
            "rate": str(line.rate),
            "cost": str(line.cost),
            "share_of_labor": str((line.cost / total).quantize(Decimal("0.0001"))),
            "value_unit": VALUE_UNIT,
            "hours_unit": HOURS_UNIT,
        })
    return {
        "output_uri": OUTPUT_URI["cost_labor_composition"],
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "total_labor": str(total),
        "value_unit": VALUE_UNIT,
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 5. cost_price_composition — base -> ... -> price, the full ordered stack
#
# THE VERB ADR-0047's EXPORT PACKAGE IS BUILT AROUND. Its output is the one shape no
# existing archetype renders — a waterfall — which the packet flags as a real cortex build
# rather than a binding row. The verb returns the ordered steps and does NOT flatten them:
# flattening here would be the variance-tree defect repeated, where the shape a reader needs
# is destroyed by the producer to fit an archetype that was never right.
# ---------------------------------------------------------------------------------------
def cost_price_composition(state: CostState, *, lot: int, rate_vintage: str) -> dict[str, Any]:
    """The ordered build-up from base cost to final price for one lot."""
    lot_obj, rates = _applied_rates(state, lot, rate_vintage)
    build = compose_price(
        direct_labor=lot_obj.direct_labor,
        material=lot_obj.material,
        other_direct=lot_obj.other_direct + lot_obj.warranty + lot_obj.contracts,
        rates=rates,
    )
    return {
        "output_uri": OUTPUT_URI["cost_price_composition"],
        "lot": lot_obj.number,
        "quantity": lot_obj.quantity,
        "fiscal_year": build.fiscal_year,
        "rate_vintage": build.rate_vintage,
        "price": str(build.price),
        "unit_price": str(unit_price(build, lot_obj.quantity)),
        "value_unit": VALUE_UNIT,
        # The steps are the answer. `sums` is carried so a consumer can assert the
        # invariant without re-adding — and so a card can show that it was checked.
        "sums": build.sums(),
        "steps": [
            {
                "name": s.name,
                "rate": None if s.rate is None else str(s.rate),
                "basis": str(s.basis),
                "amount": str(s.amount),
                "running_total": str(s.running_total),
                "value_unit": VALUE_UNIT,
            }
            for s in build.steps
        ],
    }


# ---------------------------------------------------------------------------------------
# 6. cost_rate_assumptions — the rate table at a vintage
# ---------------------------------------------------------------------------------------
def cost_rate_assumptions(
    state: CostState, *, fiscal_year: Optional[int] = None, rate_vintage: Optional[str] = None
) -> dict[str, Any]:
    """The assumption set in force, so any figure elsewhere can be reproduced.

    Unlike the priced verbs this one may answer WITHOUT a vintage — listing the table is how
    a caller discovers which vintages exist, and refusing here would make the refusal
    elsewhere unanswerable. That asymmetry is deliberate and is the difference between a
    refusal that guides and one that stonewalls.
    """
    keys = sorted(state.rates)
    if fiscal_year is not None:
        keys = [k for k in keys if k[0] == fiscal_year]
        if not keys:
            raise NotInModel(
                f"fiscal year {fiscal_year} is not in the rate table; known years are "
                f"{sorted({fy for fy, _ in state.rates})}"
            )
    if rate_vintage is not None:
        keys = [k for k in keys if k[1] == rate_vintage]
        if not keys:
            raise NotInModel(f"no rate set at vintage {rate_vintage!r}")

    rows = []
    for fy, vintage in keys:
        r = state.rates[(fy, vintage)]
        rows.append({
            "fiscal_year": fy,
            "rate_vintage": vintage,
            "fringe": str(r.fringe),
            "overhead": str(r.overhead),
            "g_and_a": str(r.g_and_a),
            "cost_of_money": str(r.cost_of_money),
            "profit": str(r.profit),
            "escalation": str(r.escalation),
            "value_unit": None,          # factors, not amounts
        })
    return {
        "output_uri": OUTPUT_URI["cost_rate_assumptions"],
        "program": state.program_name,
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 7. cost_category_breakdown - SHARE and MOVEMENT, not amount
#
# DELIBERATELY DISTINCT FROM cost_lot_breakdown, and the anti-synonyms carry the split:
# that verb reports what each bucket COST (absolute figures, hours, and therefore the rate
# assumptions behind them); this one reports what SHARE each bucket is and how that share
# MOVED against the preceding lot. Two lots with identical totals can divide them
# differently, and the division is the thing a reader acts on.
#
# NO rate_vintage, and that is a consequence rather than an omission: a share is a ratio of
# recorded costs, so it does not depend on which assumption set produced the amounts. A verb
# that demanded a vintage it does not use would be ceremony.
# ---------------------------------------------------------------------------------------
def cost_category_breakdown(state: CostState, *, lot: int) -> dict[str, Any]:
    """How one lot's cost divides across its buckets, and how the division moved."""
    lot_obj = state.lot(lot)
    prior = state.lots.get(lot - 1)

    def buckets(l) -> dict[str, Decimal]:
        return {
            "labor": l.direct_labor,
            "material": l.material,
            "other_direct": l.other_direct,
            "warranty": l.warranty,
            "contracts": l.contracts,
        }

    mine = buckets(lot_obj)
    total = sum(mine.values(), Decimal("0"))
    if total <= 0:  # pragma: no cover - the seed guards against it, but a share of zero
        raise NotInModel(f"lot {lot} has no recorded cost, so it has no division")
    prior_shares = None
    if prior is not None:
        p = buckets(prior)
        ptotal = sum(p.values(), Decimal("0"))
        prior_shares = {k: (v / ptotal) for k, v in p.items()} if ptotal > 0 else None

    rows = []
    for name, amount in mine.items():
        share = (amount / total).quantize(Decimal("0.0001"))
        row = {
            "category": name,
            "share_of_total": str(share),
            "amount": str(amount),
            "value_unit": VALUE_UNIT,
            # A share is a ratio, not an amount. Saying so stops a renderer appending a
            # currency to it.
            "share_unit": None,
        }
        if prior_shares is not None:
            delta = (share - prior_shares[name]).quantize(Decimal("0.0001"))
            row["share_delta_vs_prior_lot"] = str(delta)
            row["direction"] = "up" if delta > 0 else ("down" if delta < 0 else "flat")
        else:
            # FIRST LOT HAS NO PRIOR, and that is reported rather than rendered as zero
            # movement — a flat delta and an absent one mean different things.
            row["share_delta_vs_prior_lot"] = None
            row["direction"] = None
        rows.append(row)

    return {
        "output_uri": OUTPUT_URI["cost_category_breakdown"],
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "total": str(total),
        "value_unit": VALUE_UNIT,
        "compared_to_lot": None if prior is None else prior.number,
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 8. cost_supplier_concentration - exposure to any single party, against a STATED bound
#
# THE THRESHOLD IS ALWAYS DISCLOSED, INCLUDING WHEN IT WAS DEFAULTED. A verdict of
# "concentrated" against a bound the caller never saw is the EAC-without-method ambiguity in
# another costume: the number is unactionable without the assumption that produced it. So
# the parameter defaults to None and is resolved HERE, which is what lets the payload report
# `threshold_defaulted` honestly — a signature default could not tell the two apart.
# ---------------------------------------------------------------------------------------
def cost_supplier_concentration(
    state: CostState, *, lot: int, threshold: Optional[float] = None
) -> dict[str, Any]:
    """Which suppliers hold more than `threshold` of a lot's purchased value."""
    lot_obj = state.lot(lot)
    defaulted = threshold is None
    bound = DEFAULT_CONCENTRATION_THRESHOLD if defaulted else Decimal(str(threshold))
    if not (Decimal("0") < bound < Decimal("1")):
        raise NotInModel(
            f"threshold {bound} is not a share between 0 and 1; concentration is a "
            "proportion of purchased value, not an amount"
        )

    purchased = sum((s.amount for s in lot_obj.suppliers), Decimal("0"))
    if purchased <= 0:  # pragma: no cover - guarded by the seed's own consistency check
        raise NotInModel(f"lot {lot} records no purchased value to concentrate")

    ranked = sorted(lot_obj.suppliers, key=lambda s: s.amount, reverse=True)
    rows = []
    for s in ranked:
        share = (s.amount / purchased).quantize(Decimal("0.0001"))
        rows.append({
            "supplier": s.name,
            "amount": str(s.amount),
            "share_of_purchased": str(share),
            "above_threshold": share > bound,
            "value_unit": VALUE_UNIT,
        })

    above = [r for r in rows if r["above_threshold"]]
    top = Decimal(rows[0]["share_of_purchased"]) if rows else Decimal("0")
    return {
        "output_uri": OUTPUT_URI["cost_supplier_concentration"],
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "purchased_value": str(purchased),
        "value_unit": VALUE_UNIT,
        # THE BOUND TRAVELS WITH THE VERDICT, always, and says whether the caller chose it.
        "threshold": str(bound),
        "threshold_defaulted": defaulted,
        "suppliers_above_threshold": len(above),
        "largest_share": str(top),
        "rows": rows,
    }


#: The catalogue, read ONCE and consumed twice — by the router's dispatch table and by the
#: registration. One table, so a verb cannot be servable and unregistered or the reverse.
VERBS = {
    "cost_lot_breakdown":     cost_lot_breakdown,
    "cost_unit_price_trend":  cost_unit_price_trend,
    "cost_rate_comparison":   cost_rate_comparison,
    "cost_labor_composition": cost_labor_composition,
    "cost_price_composition": cost_price_composition,
    "cost_rate_assumptions":  cost_rate_assumptions,
    "cost_category_breakdown": cost_category_breakdown,
    "cost_supplier_concentration": cost_supplier_concentration,
}
