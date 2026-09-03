"""The deterministic pricing composition: base cost -> ... -> final price.

THIS MODULE IS THE ONE ADR-0047's EXPORT PACKAGE SHIPS, BYTE-IDENTICAL, AT A PINNED SHA.
Everything about how it is written follows from that, and none of it is stylistic:

  * NO CONFIG READ AT IMPORT. No os.environ, no settings object, no file read.
  * NO MODULE-LEVEL I/O. Importing this module performs no side effect at all.
  * NO FRAMEWORK IMPORTS. Not FastAPI, not the mesh SDK, not the engine's own state.
  * PURE FUNCTIONS OF THEIR INPUTS. Same inputs, same outputs, on any machine, forever.

ADR-0047 §3's premise -- that a divergence between the customer's re-run and ours can only
mean DATA or RUNTIME, never ALGORITHM -- is only true while those four hold. They are a
construction constraint rather than a discovered property (see the retired fork in
docs/plans/register-cost-tool-as-engine.md), which is why this module is written first and
imports nothing from its own package.

WHY Decimal AND NOT float. The composition's acceptance seal is that the ordered steps SUM
to the reported price. Binary floating point cannot promise that for decimal currency: a
step list that visibly adds up in the card and disagrees in the eleventh place is exactly
the "renderer never sums" complaint arriving from the other direction, and a customer
checking our arithmetic by hand is the whole use case. Decimal makes the seal assertable
with `==` instead of a tolerance nobody can justify.

WHY THE ORDER IS DATA AND NOT CODE. Fringe applies to labour; overhead applies to labour
plus fringe; G&A applies to the subtotal INCLUDING overhead; cost of money and profit apply
after G&A. Applying the same factors in a different sequence produces a different, wrong
price. `COMPOSITION_ORDER` states the sequence once so the order cannot drift from the
narrative the card renders -- and so a reader of the export can see the sequence rather than
infer it from control flow.

EVERY FACTOR NAMED HERE IS PUBLIC GOVERNMENT-CONTRACT COST-ESTIMATING PRACTICE. Nothing in
this file is derived from any real program, supplier or rate agreement.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

__all__ = [
    "COMPOSITION_ORDER",
    "CompositionStep",
    "PriceBuildUp",
    "RateSet",
    "compose_price",
    "quantize_money",
]

#: Money is carried to the cent. Rates are NOT quantized -- a rate is a factor, not an
#: amount, and rounding it would change the arithmetic rather than present it.
_CENTS = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    """Round a monetary amount to cents, half-up, the way a price sheet does.

    Banker's rounding (Decimal's default) is correct for statistics and wrong for a price
    a person checks with a calculator: 0.005 rounding DOWN half the time reads as an error
    to the recipient even when it is defensible. Stated here rather than left to the
    context's default, because the default differs between runtimes and this module must
    produce the same cents in the customer's browser as in the engine.
    """
    return value.quantize(_CENTS, rounding="ROUND_HALF_UP")


@dataclass(frozen=True)
class RateSet:
    """The factors in force for one fiscal year, at one vintage.

    A rate set is IDENTIFIED by (fiscal_year, vintage) rather than by fiscal year alone:
    two vintages of the same year are both correct and are not comparable, which is why
    `rate_vintage` is a mandatory slot on every forward-looking verb rather than a default.
    """
    fiscal_year: int
    vintage: str                 # ISO date the set was fixed; part of the identity
    fringe: Decimal              # applied to direct labour
    overhead: Decimal            # applied to labour + fringe
    g_and_a: Decimal             # applied to the subtotal, including overhead
    cost_of_money: Decimal       # facilities capital, applied to total cost
    profit: Decimal              # applied to total cost + cost of money
    escalation: Decimal          # year-over-year index applied to base cost


@dataclass(frozen=True)
class CompositionStep:
    """One rung of the build-up: what it is, what it added, and where that left the total.

    `basis` names WHAT THE FACTOR WAS APPLIED TO. It is carried because a reader checking
    the arithmetic needs it and cannot recover it from the amounts -- an overhead figure is
    unverifiable without knowing it was struck on labour-plus-fringe rather than on labour.
    """
    name: str
    rate: Decimal | None         # None for the seed step, which is an amount not a factor
    basis: Decimal               # the amount the rate was applied to
    amount: Decimal              # what this step added
    running_total: Decimal       # the total after this step


@dataclass(frozen=True)
class PriceBuildUp:
    """The full ordered composition, and the price it arrives at.

    INVARIANT, and it is the acceptance seal: ``sum(step.amount) == price``. Asserted by
    `compose_price` itself on every call rather than only in a test, because this object
    crosses the building line -- a customer opening the export runs this code, and a
    composition that does not add up must fail where it is produced, not where it is read.

    THE INVARIANT ONLY MEANS SOMETHING BECAUSE `price` IS COMPUTED INDEPENDENTLY of the
    steps (see `compose_price`). When it was the steps' own running total, this comparison
    held for every possible corruption and tested nothing.
    """
    steps: tuple[CompositionStep, ...]
    price: Decimal
    fiscal_year: int
    rate_vintage: str

    def sums(self) -> bool:
        """True when the ordered steps add to the reported price. See the invariant."""
        return sum((s.amount for s in self.steps), Decimal("0")) == self.price


class CompositionError(ValueError):
    """The composition could not be performed as specified.

    Raised rather than returned so it cannot be mistaken for a priced answer. A caller that
    wants a refusal shape converts it at the boundary; nothing inside this module knows what
    a mesh refusal looks like, and that is deliberate -- see the module docstring.
    """


#: THE SEQUENCE IS THE ALGORITHM. Each entry is (step name, rate attribute, basis rule).
#: The basis rule names which earlier subtotal the factor applies to, and it is the part
#: that makes the order load-bearing rather than cosmetic.
COMPOSITION_ORDER: tuple[tuple[str, str, str], ...] = (
    ("Fringe",         "fringe",        "direct_labor"),
    ("Overhead",       "overhead",      "labor_plus_fringe"),
    ("G&A",            "g_and_a",       "subtotal_with_overhead"),
    ("Cost of money",  "cost_of_money", "total_cost"),
    ("Profit",         "profit",        "total_cost_plus_com"),
)


def compose_price(
    *,
    direct_labor: Decimal,
    material: Decimal,
    other_direct: Decimal,
    rates: RateSet,
    escalate: bool = False,
) -> PriceBuildUp:
    """Build a price from its components, in the one order that is correct.

    `escalate` applies the rate set's escalation index to the BASE amounts before any
    burden is struck -- which is where escalation belongs, because escalating a burdened
    figure compounds the burden with the index and overstates the result. Defaulted to
    False because escalation is a forward-looking choice and a silent default would be the
    same defect as a defaulted rate vintage.
    """
    for name, amount in (
        ("direct_labor", direct_labor), ("material", material), ("other_direct", other_direct)
    ):
        if amount < 0:
            raise CompositionError(f"{name} is negative ({amount}); a component cost cannot be")

    index = rates.escalation if escalate else Decimal("1")
    base_labor = direct_labor * index
    base_material = material * index
    base_other = other_direct * index

    seed = quantize_money(base_labor + base_material + base_other)
    steps: list[CompositionStep] = [
        CompositionStep(
            name="Base cost",
            rate=None,
            basis=Decimal("0"),
            amount=seed,
            running_total=seed,
        )
    ]

    # The bases each factor is struck on. Computed as we go, because every one of them
    # depends on a step above it -- which is the whole reason the order is data.
    bases: dict[str, Decimal] = {"direct_labor": quantize_money(base_labor)}
    running = seed

    for step_name, rate_attr, basis_key in COMPOSITION_ORDER:
        rate: Decimal = getattr(rates, rate_attr)
        if rate < 0:
            raise CompositionError(f"{step_name} rate is negative ({rate})")
        if basis_key not in bases:
            # Bases that only exist once earlier steps have run.
            if basis_key == "labor_plus_fringe":
                bases[basis_key] = bases["direct_labor"] + _amount_of(steps, "Fringe")
            elif basis_key == "subtotal_with_overhead":
                bases[basis_key] = running
            elif basis_key == "total_cost":
                bases[basis_key] = running
            elif basis_key == "total_cost_plus_com":
                bases[basis_key] = running
            else:  # pragma: no cover - guarded by the tuple above being a closed set
                raise CompositionError(f"unknown basis rule {basis_key!r}")
        basis = bases[basis_key]
        amount = quantize_money(basis * rate)
        running = quantize_money(running + amount)
        steps.append(
            CompositionStep(
                name=step_name, rate=rate, basis=basis, amount=amount, running_total=running
            )
        )

    # THE PRICE IS COMPUTED INDEPENDENTLY OF THE STEP ACCUMULATOR, and that is the whole
    # point of this block rather than a duplication to be tidied away.
    #
    # WHY, and it was found by proving the seal rather than by writing it: the first version
    # set `price = running`, the accumulator the steps themselves built. `sums()` then
    # compared the step amounts against a total DERIVED FROM those same amounts, so it held
    # for any corruption that propagated -- which is every corruption. The bite-check
    # (corrupt one step amount, expect a refusal) DID NOT RAISE, because the running total
    # had absorbed the same error. The seal was asserting on its own neighbour.
    #
    # So the price is re-derived here by the closed form, and the two paths must agree. A
    # single wrong quantization now shows up as a disagreement between two independent
    # computations, which is what the seal was always supposed to be testing.
    _fringe = quantize_money(quantize_money(base_labor) * rates.fringe)
    _overhead = quantize_money((quantize_money(base_labor) + _fringe) * rates.overhead)
    _subtotal = quantize_money(seed + _fringe + _overhead)
    _ga = quantize_money(_subtotal * rates.g_and_a)
    _total_cost = quantize_money(_subtotal + _ga)
    _com = quantize_money(_total_cost * rates.cost_of_money)
    _profit = quantize_money(quantize_money(_total_cost + _com) * rates.profit)
    price_closed_form = quantize_money(_total_cost + _com + _profit)

    build = PriceBuildUp(
        steps=tuple(steps),
        price=price_closed_form,
        fiscal_year=rates.fiscal_year,
        rate_vintage=rates.vintage,
    )

    # THE SEAL, ASSERTED WHERE THE ANSWER IS PRODUCED. See PriceBuildUp's invariant.
    if not build.sums():
        raise CompositionError(
            "composition does not sum: steps total "
            f"{sum((s.amount for s in build.steps), Decimal('0'))} but the price computed "
            f"independently is {build.price}"
        )
    return build


def _amount_of(steps: Sequence[CompositionStep], name: str) -> Decimal:
    """The amount a named step contributed, for use as a later step's basis."""
    for s in steps:
        if s.name == name:
            return s.amount
    raise CompositionError(f"step {name!r} has not run yet; COMPOSITION_ORDER is out of order")


def unit_price(build: PriceBuildUp, quantity: int) -> Decimal:
    """Price per unit for a quantity. Raises rather than returning zero on an empty lot."""
    if quantity <= 0:
        raise CompositionError(f"quantity must be positive, got {quantity}")
    return quantize_money(build.price / Decimal(quantity))


def total_of(builds: Iterable[PriceBuildUp]) -> Decimal:
    """Sum a set of build-ups. Present so callers never re-implement money addition."""
    return quantize_money(sum((b.price for b in builds), Decimal("0")))


def rates_for(table: Mapping[tuple[int, str], RateSet], fiscal_year: int, vintage: str) -> RateSet:
    """Look up one rate set. Raises on a miss -- there is no nearest-vintage fallback.

    A silent fall back to the newest vintage is the defect `rate_vintage` exists to prevent:
    the caller would receive a price computed against assumptions they did not name and
    could not see, which is the EAC-without-method ambiguity in another costume.
    """
    try:
        return table[(fiscal_year, vintage)]
    except KeyError:
        raise CompositionError(
            f"no rate set for fiscal year {fiscal_year} at vintage {vintage!r}"
        ) from None
