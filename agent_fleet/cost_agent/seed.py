"""Notional production-cost data, and the consistency check that refuses a bad seed.

OBVIOUSLY NOTIONAL BY RULE (ADR-0045 Decision 4). One invented program, nine lots, round
rates, suppliers named after colours. No real program, lot, supplier or rate agreement
appears here or anywhere in this engine.

THE SEED CARRIES TWO SEALS, AND BOTH EXIST BECAUSE SOMEONE ALREADY PAID FOR THEIR ABSENCE:

  1. UNIT PRICE MUST TREND ACROSS LOTS. Engine F seeded constant factors and every period
     returned CPI 0.8367 -- identical to four decimals, six times -- for a verb that exists
     BECAUSE the trend is the question. A flat line is also what a broken instrument
     returns, so a demo over that data would have been indistinguishable from a bug. Here
     the trend is produced by a learning curve on touch hours fighting escalation on rates,
     which is both realistic and LUMPY: unit price falls steeply, then flattens, then ticks
     up as escalation overtakes learning. Lumpy is the point -- a uniform result is the tell.

  2. THE COMPOSITION MUST REPRODUCE THE SUM. Asserted by `pricing.compose_price` itself on
     every call, and re-asserted here across every lot, because a pricing engine whose stack
     does not add up is wrong in the one way a customer checks first.

`check_consistency` runs at BOOT and raises. Engine F learned this the expensive way twice:
a duplicate label made a question unroutable while every component reported healthy, and an
enumerable set derived from the wrong place answered `unsupported` for a class a live verb
routed on. A seed defect that raises at start is an outage; one that does not is a demo.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import CostState, LaborLine, Lot, SupplierShare, Unentitled
    from pricing import RateSet, compose_price, unit_price
except ImportError:
    from agent_fleet.cost_agent.entities import (
        CostState, LaborLine, Lot, SupplierShare, Unentitled,
    )
    from agent_fleet.cost_agent.pricing import RateSet, compose_price, unit_price

PROGRAM_NAME = "Notional Production Program Vermilion"

#: Two vintages per fiscal year for the first three years, ONE for the rest. The uneven
#: shape is deliberate: a caller asking for a vintage that exists in one year and not
#: another must meet a real refusal, and a uniformly-populated table could never produce one.
_VINTAGES = {
    2019: ["2019-02-01", "2019-08-01"],
    2020: ["2020-02-01", "2020-08-01"],
    2021: ["2021-02-01", "2021-08-01"],
    2022: ["2022-02-01"],
    2023: ["2023-02-01"],
    2024: ["2024-02-01"],
    2025: ["2025-02-01"],
    2026: ["2026-02-01"],
    2027: ["2027-02-01"],
}


def _rate_table() -> dict[tuple[int, str], RateSet]:
    """Rates by (fiscal year, vintage). Round numbers, drifting slowly upward."""
    table: dict[tuple[int, str], RateSet] = {}
    for i, (fy, vintages) in enumerate(sorted(_VINTAGES.items())):
        for j, vintage in enumerate(vintages):
            # The later vintage of a year is a small revision UP -- which is what makes
            # `cost_rate_comparison` non-trivial and the vintage slot load-bearing.
            bump = Decimal("0.01") * j
            table[(fy, vintage)] = RateSet(
                fiscal_year=fy,
                vintage=vintage,
                fringe=Decimal("0.32") + Decimal("0.005") * i + bump,
                overhead=Decimal("0.80") + Decimal("0.010") * i + bump,
                g_and_a=Decimal("0.11") + Decimal("0.002") * i,
                cost_of_money=Decimal("0.015"),
                profit=Decimal("0.10"),
                escalation=Decimal("1.00") + Decimal("0.025") * i,
            )
    return table


#: Wright's-law learning on TOUCH hours only. Support scales with touch but more slowly;
#: SEPM is broadly flat because programme management does not learn away.
_TOUCH_HOURS_LOT1 = Decimal("42000")
_LEARNING = Decimal("0.92")          # per doubling of cumulative quantity

#: THE SLOPE THE ENGINE ACTUALLY USED. Published because a scenario that re-runs the curve
#: needs it to know where identity is: at this value the scenario must reproduce the baseline
#: exactly. Hard-coding a default in the page builder instead is what made an untouched
#: scenario disagree with the baseline by $732k.
LEARNING_SLOPE = _LEARNING
_QUANTITIES = [12, 12, 18, 24, 24, 30, 30, 36, 36]

#: Purchased-value concentration. Fractions of the LOT'S material value, summing to 1 so the
#: concentration view covers what it claims to describe. Colour names, obviously notional.
_SUPPLIER_SHARES: tuple[tuple[str, Decimal], ...] = (
    ("Cobalt Components",     Decimal("0.41")),
    ("Amber Fabrication",     Decimal("0.27")),
    ("Sable Castings",        Decimal("0.19")),
    ("Verdigris Electronics", Decimal("0.13")),
)


def _touch_hours(lot_index: int, cumulative_units: int) -> Decimal:
    """Touch hours for a lot: Wright's law, CONTINUOUS in cumulative quantity.

    hours = T1 * N^b   where   b = ln(learning) / ln(2)

    THE FIRST VERSION STEPPED BY DOUBLINGS and a seal caught what that cost. Counting whole
    doublings makes the curve a staircase, so any two lots inside one tread receive IDENTICAL
    hours — lots 4 and 5 (both quantity 24, same bracket) came out equal to the cent, and
    `touch_per_unit` could not tell them apart. A frozen lot selector would have been
    undetectable in that metric, which is exactly what the seal asserts against.

    The staircase was also simply wrong as a model: Wright's law is continuous in cumulative
    quantity and the doubling form is a shorthand for reading it off a chart, not a
    definition. So this is a correctness fix that a UI-staleness seal happened to find.
    """
    import math

    b = Decimal(str(math.log(float(_LEARNING)) / math.log(2.0)))
    n = Decimal(cumulative_units)
    factor = Decimal(str(math.pow(float(n) / 12.0, float(b))))
    return (_TOUCH_HOURS_LOT1 * factor).quantize(Decimal("1"))


#: NOTIONAL RECIPIENTS, and the lots each may see. This is the ENTITLEMENT SURFACE the export
#: packages against (ADR-0047 §5): the filter runs ONCE, at packaging, and what survives it is
#: what gets embedded. There is no render-time filtering in a file the recipient owns.
#:
#: THE SCOPES DELIBERATELY OVERLAP AND DELIBERATELY DIFFER. A seal that discriminates between
#: two recipients whose scopes are disjoint proves less than one where they share lots and
#: differ at the edges -- disjoint scopes can pass by accident if the filter keys on the wrong
#: field entirely. Lot 5 is in both; lots 1-2 only in the first; lots 8-9 only in the second.
RECIPIENT_SCOPES: dict[str, tuple[int, ...]] = {
    "notional-customer-alpha": (1, 2, 3, 4, 5),
    "notional-customer-beta": (5, 6, 7, 8, 9),
}


def lots_for_recipient(recipient_scope: str) -> tuple[int, ...]:
    """The lots a recipient may see. RAISES on an unknown scope rather than returning empty.

    An empty package and an unentitled one must not look alike (ADR-0047 §5) -- an empty
    result would tell the caller "this recipient has no data" when the truth is "this is not
    a recipient".
    """
    try:
        return RECIPIENT_SCOPES[recipient_scope]
    except KeyError:
        raise Unentitled(
            f"{recipient_scope!r} is not a recipient this engine packages for; known scopes "
            f"are {sorted(RECIPIENT_SCOPES)}"
        ) from None


def build_state() -> CostState:
    """The notional program. Deterministic — no clock, no randomness, no I/O."""
    rates = _rate_table()
    lots: dict[int, Lot] = {}
    cumulative = 0

    for idx, qty in enumerate(_QUANTITIES):
        number = idx + 1
        fy = 2019 + idx
        cumulative += qty
        applied = rates[(fy, _VINTAGES[fy][0])]
        # The estimating rate set is the EARLIEST vintage of the lot's year, so the
        # comparison verb has two genuinely different sides to report.
        estimating = rates[(fy, _VINTAGES[fy][0])] if len(_VINTAGES[fy]) == 1 else rates[
            (fy, _VINTAGES[fy][1])
        ]

        touch = _touch_hours(idx, cumulative)
        support = (touch * Decimal("0.45")).quantize(Decimal("1"))
        sepm = Decimal("9000") + Decimal("250") * idx

        base_rate = Decimal("74") + Decimal("2") * idx      # escalating labour rate
        _material = (
            Decimal("58000") * qty * (Decimal("1") + Decimal("0.02") * idx)
        ).quantize(Decimal("0.01"))
        lots[number] = Lot(
            number=number,
            quantity=qty,
            cumulative_units=cumulative,
            fiscal_year=fy,
            labor=(
                LaborLine("touch", touch, base_rate),
                LaborLine("support", support, base_rate * Decimal("0.85")),
                LaborLine("sepm", sepm, base_rate * Decimal("1.40")),
            ),
            material=_material,
            other_direct=(Decimal("4200") * qty).quantize(Decimal("0.01")),
            warranty=(Decimal("1800") * qty).quantize(Decimal("0.01")),
            warranty_hours=(Decimal("18") * qty).quantize(Decimal("1")),
            contracts=(Decimal("310000") + Decimal("12000") * idx).quantize(Decimal("0.01")),
            suppliers=tuple(
                # Shares are struck on the LOT'S OWN material value, not on the unescalated
                # base. Caught by check_consistency on the first run: shares computed from
                # `58000 * qty` under-covered escalated material by 4% at lot 3 and grew
                # from there. The seal did its job; the arithmetic is fixed at the source
                # rather than the tolerance being widened to admit it.
                SupplierShare(name, (share * _material).quantize(Decimal("0.01")))
                for name, share in _SUPPLIER_SHARES
            ),
            estimating_rates=estimating,
        )

    return CostState(program_name=PROGRAM_NAME, lots=lots, rates=rates)


def unit_prices(state: CostState) -> list[tuple[int, Decimal]]:
    """(lot number, unit price) across the program, at each lot's own applied rates."""
    out: list[tuple[int, Decimal]] = []
    for n in state.lot_numbers:
        lot = state.lot(n)
        rates = state.rates[(lot.fiscal_year, _VINTAGES[lot.fiscal_year][0])]
        build = compose_price(
            direct_labor=lot.direct_labor,
            material=lot.material,
            other_direct=lot.other_direct + lot.warranty + lot.contracts,
            rates=rates,
        )
        out.append((n, unit_price(build, lot.quantity)))
    return out


def check_consistency(state: CostState) -> None:
    """Refuse a seed that would make a verb vacuous or an arithmetic claim false.

    RAISES AT BOOT. A seed defect that raises at start is an outage; one that does not is a
    demo over data indistinguishable from a bug.
    """
    if len(state.lots) < 8:
        raise ValueError(f"seed has {len(state.lots)} lots; the trend verbs need at least 8")

    # SEAL 1 — unit price must actually MOVE across lots, and move by an amount a reader
    # would call a trend. Asserted on the spread rather than on adjacent pairs, because a
    # curve can wobble locally and still be flat overall.
    prices = [p for _, p in unit_prices(state)]
    lo, hi = min(prices), max(prices)
    if lo == hi:
        raise ValueError("unit price is identical across every lot — trend verbs are vacuous")
    spread = (hi - lo) / hi
    if spread < Decimal("0.10"):
        raise ValueError(
            f"unit price spread is {spread:.4f} across the program; below 10% the trend "
            "verbs cannot show a movement a reader would act on"
        )
    # And it must not be MONOTONE-BY-CONSTRUCTION either — a perfectly smooth curve is the
    # uniform-result tell wearing a trend's clothes.
    deltas = [b - a for a, b in zip(prices, prices[1:])]
    if all(d < 0 for d in deltas):
        raise ValueError(
            "unit price falls at every single lot; the seed is a straight line, not a curve"
        )

    # SEAL 2 — every lot's composition must reproduce its own sum. compose_price asserts
    # this per call; re-asserted here across the whole seed so a bad lot cannot hide.
    for n in state.lot_numbers:
        lot = state.lot(n)
        rates = state.rates[(lot.fiscal_year, _VINTAGES[lot.fiscal_year][0])]
        build = compose_price(
            direct_labor=lot.direct_labor,
            material=lot.material,
            other_direct=lot.other_direct + lot.warranty + lot.contracts,
            rates=rates,
        )
        if not build.sums():
            raise ValueError(f"lot {n}: price composition does not sum to its own price")

    # Supplier shares are a CONCENTRATION view; they must cover the material they describe.
    for n in state.lot_numbers:
        lot = state.lot(n)
        total = sum((s.amount for s in lot.suppliers), Decimal("0"))
        if abs(total - lot.material) > lot.material * Decimal("0.02"):
            raise ValueError(
                f"lot {n}: supplier shares total {total} against material {lot.material}"
            )

    # A duplicate label makes a question unroutable while every component reports healthy
    # (Engine F, measured). Suppliers are the only free-text names this engine carries.
    names = [s.name for n in state.lot_numbers for s in state.lot(n).suppliers]
    for n in state.lot_numbers:
        lot_names = [s.name for s in state.lot(n).suppliers]
        if len(set(lot_names)) != len(lot_names):
            raise ValueError(f"lot {n} names the same supplier twice")
    del names
