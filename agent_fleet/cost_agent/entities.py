"""Types engine-cost's verbs are written against, and the refusals they raise.

SEPARATE FROM pricing.py ON PURPOSE. `pricing.py` is exported to a recipient byte-identical
(ADR-0047 §3) and therefore imports nothing from this package; this module may import it,
never the reverse. If that arrow ever inverts, the export stops being isolable and the
premise ADR-0047 §3 rests on quietly becomes false.

THE THREE REFUSAL STATES ARE DISTINCT TYPES, NOT ONE ERROR WITH A MESSAGE. ADR-0049
Ruling 4 requires a composing verb to tell EMPTY (the source answered and legitimately has
nothing) from UNAVAILABLE (the source did not answer) from UNENTITLED (the caller may not
see it). These verbs will be inner calls to an affordability composition, so collapsing the
three here would make honest composition impossible upstream -- and the collapse would be
invisible, because all three render as "no data" to a reader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from pricing import RateSet
except ImportError:
    from agent_fleet.cost_agent.pricing import RateSet

#: The five accounting buckets a price decomposes into. Read out of this Literal by
#: `slots.py` so the declared enum cannot drift from what the verbs accept -- the same
#: derivation Engine F uses for its EAC methods, for the same reason.
CostCategory = Literal["labor", "material", "other_direct", "warranty", "contracts"]

#: Labour is reported by the KIND of work, because two lots with identical labour totals
#: and different mixes have different cost drivers and respond to different actions.
LaborKind = Literal["touch", "support", "sepm"]

COST = "http://invincible-agent/cost#"


class NotInModel(Exception):
    """The named thing is not in the model at all. Distinct from 'has no data'."""


class Unentitled(Exception):
    """The caller may not see this. NEVER collapse into an empty result (ADR-0049 R4)."""


class SourceUnavailable(Exception):
    """A required input could not be reached. NEVER collapse into an empty result."""


class VintageRequired(Exception):
    """A forward-looking figure was requested without naming a rate vintage.

    The designed refusal of this engine, and the analogue of Engine F's mandatory EAC
    method: a price computed against unnamed assumptions is not checkable, and defaulting
    to the newest vintage would hand back a number whose basis the caller never chose.
    Carries the available vintages so the caller's next question is answerable.
    """

    def __init__(self, message: str, available: list[str]) -> None:
        super().__init__(message)
        self.available = available


@dataclass(frozen=True)
class MonthlyEffort:
    """Hours booked in one calendar month, for a kind of work that runs continuously.

    SEPM is a LEVEL OF EFFORT: it is staffed by month, not consumed per unit, so a per-lot
    total answers "how much" and hides the shape entirely. A month-by-month series with its
    own average is what makes an over- or under-staffed period visible at all.
    """
    period: str          # "YYYY-MM"
    hours: Decimal


@dataclass(frozen=True)
class LaborLine:
    """Hours and applied rate for one kind of work within one lot."""
    kind: LaborKind
    hours: Decimal
    rate: Decimal

    @property
    def cost(self) -> Decimal:
        return self.hours * self.rate


@dataclass(frozen=True)
class SupplierShare:
    """One supplier's share of purchased value in a lot. No contract or contact data."""
    name: str
    amount: Decimal


@dataclass(frozen=True)
class Lot:
    """One numbered quantity, costed as a self-contained whole."""
    number: int
    quantity: int
    #: Units delivered through the END of this lot. The learning curve is a function of this,
    #: not of `quantity` — and a scenario that re-runs the curve at a different slope cannot
    #: do so without it, which is why it is carried rather than re-derived from a lot list.
    cumulative_units: int
    fiscal_year: int
    labor: tuple[LaborLine, ...]
    #: SEPM by calendar month. Sums EXACTLY to the sepm `LaborLine`'s hours - sealed, because a
    #: monthly view that does not reconcile to the annual figure is two answers to one question.
    sepm_monthly: tuple[MonthlyEffort, ...]
    material: Decimal
    other_direct: Decimal
    warranty: Decimal
    warranty_hours: Decimal
    contracts: Decimal
    suppliers: tuple[SupplierShare, ...]
    #: The rates that were ASSUMED when this lot was estimated, kept alongside the rates
    #: actually applied so `cost_rate_comparison` has both halves. An engine that stored
    #: only the applied rates could report a comparison only by inventing the other side.
    estimating_rates: RateSet

    @property
    def direct_labor(self) -> Decimal:
        return sum((l.cost for l in self.labor), Decimal("0"))

    def labor_of(self, kind: LaborKind) -> LaborLine:
        for l in self.labor:
            if l.kind == kind:
                return l
        raise NotInModel(f"lot {self.number} has no {kind} labour line")


@dataclass
class CostState:
    """Everything the verbs read. Constructed by `seed.py`; never mutated by a verb."""
    program_name: str
    lots: dict[int, Lot] = field(default_factory=dict)
    #: Keyed (fiscal_year, vintage) -- two vintages of one year are both correct.
    rates: dict[tuple[int, str], RateSet] = field(default_factory=dict)

    def lot(self, number: int) -> Lot:
        try:
            return self.lots[number]
        except KeyError:
            raise NotInModel(
                f"lot {number} is not in the model; known lots are "
                f"{sorted(self.lots)}"
            ) from None

    def vintages(self, fiscal_year: int | None = None) -> list[str]:
        return sorted({
            v for (fy, v) in self.rates
            if fiscal_year is None or fy == fiscal_year
        })

    @property
    def lot_numbers(self) -> list[int]:
        return sorted(self.lots)
