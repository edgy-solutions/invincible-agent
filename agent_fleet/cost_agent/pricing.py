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

WHY THE ORDER IS DATA AND NOT CODE. Fringe applies to labor; overhead applies to labor
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
    "BASIS_KINDS",
    "COMPONENT_NAMES",
    "COMPOSITION_ORDER",
    "DEFAULT_COMPOSITION",
    "StepSpec",
    "validate_composition",
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
    fringe: Decimal              # applied to direct labor
    overhead: Decimal            # applied to labor + fringe
    g_and_a: Decimal             # applied to the subtotal, including overhead
    cost_of_money: Decimal       # facilities capital, applied to total cost
    profit: Decimal              # applied to total cost + cost of money
    escalation: Decimal          # year-over-year index applied to base cost


@dataclass(frozen=True)
class CompositionStep:
    """One rung of the build-up: what it is, what it added, and where that left the total.

    `basis` names WHAT THE FACTOR WAS APPLIED TO. It is carried because a reader checking
    the arithmetic needs it and cannot recover it from the amounts -- an overhead figure is
    unverifiable without knowing it was struck on labor-plus-fringe rather than on labor.
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


# =======================================================================================
# THE COMPOSITION SPEC -- the extension surface, and the ONLY one.
#
# EXTENSION IS BY DECLARED PARAMETER, NEVER BY CODE. A recipient with a different burden
# structure supplies a different RateSet and a different STEP SEQUENCE; both are DATA,
# validated against a closed vocabulary before anything runs. What they cannot do is author
# or edit the computation -- no subclassing, no injected callables, no new basis kinds.
#
# WHY THE LINE IS THERE AND NOT SOMEWHERE MORE GENEROUS. ADR-0047 §3's guarantee is that a
# divergence between the recipient's re-run and ours can mean DATA or RUNTIME but never
# ALGORITHM. Code extension breaks that BY DESIGN: a subclassed step is not our algorithm,
# so the verification manifest cannot check it, the package cannot refuse on divergence
# (divergence is the point), and "which version did they validate against" stops having an
# answer because they validated against their own fork. Parameter extension keeps all three:
# the pinned modules still produce the pinned outputs on the pinned inputs, and the
# customer's tweak produces THEIR number beside ours, both traceable.
#
# This is OKF §10's attested-computation shape, which ADR-0037 already pointed at for
# exactly this case: the caller MAY supply values for the declared parameters; it MUST NOT
# author or edit the computation.
# =======================================================================================

#: Basis kinds a step may be struck on. CLOSED SET -- a spec naming anything else is refused
#: rather than defaulted, which is the select-from-authorized-set discipline applied to
#: arithmetic. Adding a kind is a change to THIS module, reviewed and pinned, never a thing a
#: recipient can do from a data file.
BASIS_KINDS = ("base", "running_total", "component")


@dataclass(frozen=True)
class StepSpec:
    """One declared rung: what it is called, which rate it applies, and to what.

    `basis_kind`:
      * ``base``          -- the seed amount (all components, escalated if asked)
      * ``running_total`` -- the total after every preceding step
      * ``component``     -- a named base component, optionally PLUS named earlier steps
    """
    name: str
    rate_key: str
    basis_kind: str
    component: str | None = None            # for basis_kind == "component"
    plus_steps: tuple[str, ...] = ()        # earlier step names added to that component


#: The default build-up. THE SEQUENCE IS THE ALGORITHM: fringe applies to labor, overhead to
#: labor plus fringe, G&A to the subtotal INCLUDING overhead, then cost of money, then
#: profit. The same factors in a different order produce a different, wrong price -- which is
#: why the order is stated as data a reader can see rather than inferred from control flow.
DEFAULT_COMPOSITION: tuple[StepSpec, ...] = (
    StepSpec("Fringe",        "fringe",        "component", component="direct_labor"),
    StepSpec("Overhead",      "overhead",      "component", component="direct_labor",
             plus_steps=("Fringe",)),
    StepSpec("G&A",           "g_and_a",       "running_total"),
    StepSpec("Cost of money", "cost_of_money", "running_total"),
    StepSpec("Profit",        "profit",        "running_total"),
)

#: Base components a `component` basis may name. Closed, like BASIS_KINDS.
COMPONENT_NAMES = ("direct_labor", "material", "other_direct")

#: Kept as a name so existing readers land somewhere. The spec above supersedes it.
COMPOSITION_ORDER = DEFAULT_COMPOSITION


def validate_composition(spec: "tuple[StepSpec, ...]") -> None:
    """Refuse a spec that is not expressible in the declared vocabulary.

    FAIL-CLOSED AND BEFORE ANY ARITHMETIC. A spec that is wrong should be refused where it is
    read, not produce a number that is wrong somewhere a recipient has to notice. Every
    refusal names the offending step, because "invalid composition" is not actionable.
    """
    if not spec:
        raise CompositionError("composition spec is empty; a price needs at least one step")

    seen: list[str] = []
    rate_fields = {f for f in RateSet.__dataclass_fields__ if f not in
                   ("fiscal_year", "vintage")}

    for i, s in enumerate(spec):
        where = f"step {i} ({s.name!r})"
        if not s.name:
            raise CompositionError(f"{where}: step name is empty")
        if s.name in seen:
            raise CompositionError(
                f"{where}: duplicate step name -- a later step's basis could not name it "
                "unambiguously"
            )
        if s.rate_key not in rate_fields:
            raise CompositionError(
                f"{where}: rate_key {s.rate_key!r} is not a declared rate. "
                f"Declared: {sorted(rate_fields)}"
            )
        if s.basis_kind not in BASIS_KINDS:
            raise CompositionError(
                f"{where}: basis_kind {s.basis_kind!r} is not declared. "
                f"Declared: {list(BASIS_KINDS)}"
            )
        if s.basis_kind == "component":
            if s.component not in COMPONENT_NAMES:
                raise CompositionError(
                    f"{where}: component {s.component!r} is not declared. "
                    f"Declared: {list(COMPONENT_NAMES)}"
                )
            for ref in s.plus_steps:
                if ref not in seen:
                    # FORWARD REFERENCE. Refused rather than resolved: a step whose basis
                    # depends on a step that has not run has no defined value, and computing
                    # it as zero would silently understate the price.
                    raise CompositionError(
                        f"{where}: plus_steps names {ref!r}, which has not run yet. "
                        f"Steps available at this point: {seen or '(none)'}"
                    )
        elif s.component is not None or s.plus_steps:
            raise CompositionError(
                f"{where}: component/plus_steps are only meaningful for basis_kind "
                "'component'"
            )
        seen.append(s.name)


def compose_price(
    *,
    direct_labor: Decimal,
    material: Decimal,
    other_direct: Decimal,
    rates: RateSet,
    escalate: bool = False,
    spec: "tuple[StepSpec, ...] | None" = None,
) -> PriceBuildUp:
    """Build a price from its components, in the one order that is correct.

    `escalate` applies the rate set's escalation index to the BASE amounts before any
    burden is struck -- which is where escalation belongs, because escalating a burdened
    figure compounds the burden with the index and overstates the result. Defaulted to
    False because escalation is a forward-looking choice and a silent default would be the
    same defect as a defaulted rate vintage.
    """
    spec = DEFAULT_COMPOSITION if spec is None else tuple(spec)
    validate_composition(spec)

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
    components: dict[str, Decimal] = {
        "direct_labor": quantize_money(base_labor),
        "material": quantize_money(base_material),
        "other_direct": quantize_money(base_other),
    }
    running = seed
    by_name: dict[str, Decimal] = {}

    for s in spec:
        rate: Decimal = getattr(rates, s.rate_key)
        if rate < 0:
            raise CompositionError(f"{s.name} rate is negative ({rate})")
        if s.basis_kind == "base":
            basis = seed
        elif s.basis_kind == "running_total":
            basis = running
        else:  # "component" -- validated above, so component is a declared name
            basis = components[s.component]
            for ref in s.plus_steps:
                basis = basis + by_name[ref]
            basis = quantize_money(basis)
        amount = quantize_money(basis * rate)
        running = quantize_money(running + amount)
        by_name[s.name] = amount
        steps.append(
            CompositionStep(
                name=s.name, rate=rate, basis=basis, amount=amount, running_total=running
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
    price_closed_form = _fold_price(spec, rates, seed, components)

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


def _fold_price(
    spec: "tuple[StepSpec, ...]",
    rates: RateSet,
    seed: Decimal,
    components: Mapping[str, Decimal],
) -> Decimal:
    """Compute the price again, by a different traversal, for the sum seal to compare against.

    WHAT THIS SEAL PROVES, AND WHAT IT STOPPED PROVING WHEN THE SEQUENCE BECAME DATA -- stated
    because quietly weakening a seal is worse than not having one.

    BEFORE: the price was re-derived by a hand-written closed form. That was independent of
    the step loop in both CODE and SPEC, so it caught an error in either.

    NOW: both paths read the SAME declared spec, so the seal no longer cross-checks the spec
    against an independent statement of the algorithm -- it cross-checks two DIFFERENT
    TRAVERSALS of one spec. It still catches accumulation, rounding and basis-resolution bugs
    in either path, which is what it was introduced for (the original version compared the
    steps against their own accumulator and could not fail at all). It does NOT catch a spec
    that is internally consistent and wrong.

    THAT GAP IS COVERED ELSEWHERE, ON PURPOSE: `validate_composition` refuses a spec outside
    the declared vocabulary before any arithmetic runs, and the verification manifest
    (ADR-0047 §3) compares against outputs captured from the PRODUCING ENGINE, which is the
    independent statement a shipped package actually needs.
    """
    running = seed
    amounts: dict[str, Decimal] = {}
    for s in spec:
        if s.basis_kind == "base":
            basis = seed
        elif s.basis_kind == "running_total":
            basis = running
        else:
            basis = components[s.component]
            for ref in s.plus_steps:
                basis = basis + amounts[ref]
            basis = quantize_money(basis)
        amount = quantize_money(basis * getattr(rates, s.rate_key))
        amounts[s.name] = amount
        running = quantize_money(running + amount)
    return running


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
