"""Engine F's finance model — the shapes the six verbs compute over.

NOTIONAL BY RULE (ADR-0045 Decision 4). Every name in this model and its seed is invented,
every figure is round, and every formula referenced is public EVM methodology. Nothing from
the finance group's actual work appears here — not as a fixture, not as a test case, not as
an example in a docstring. That boundary is stated rather than left to be inferred from
absence, because absence is not a thing a later contributor can read.

WHY THE FIGURES ARE ROUND. Notional data must be OBVIOUSLY notional, so a screenshot cannot
be mistaken for real program data by someone who did not author it. `1_000_000` is a
declaration; `1_047_318.44` is a claim.

THE UNITS LAW. Every amount here is accompanied by its unit at the row level (`value_unit`),
never by convention. A number without a declared unit is not an amount — the same rule
`value_unit` carries on the planning side, applied to finance because "dollars or thousands
of dollars" is precisely the question that must not be answered by convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Periods
# ─────────────────────────────────────────────────────────────────────────────
#
# MONTHS, NOT QUARTERS, and that is a finance fact rather than a preference: EVM reporting
# is monthly, indices are read as a monthly trend, and a burn rate stated per quarter cannot
# show the month a program's spend turned. The planning engine's FY26-Q1 vocabulary is a
# different axis for a different question and the two are deliberately not merged.
#
# THE VOCABULARY IS DATA, NOT A `Literal`. It cannot be derived from a signature, which is
# exactly why slots.py attaches it at registration time rather than reading it off the type
# — the same split Lane 1 drew between what the CODE knows and what the DATA knows.

FISCAL_PERIODS: tuple[str, ...] = (
    "FY26-01", "FY26-02", "FY26-03", "FY26-04", "FY26-05", "FY26-06",
    "FY26-07", "FY26-08", "FY26-09", "FY26-10", "FY26-11", "FY26-12",
)

PERIOD_ORDER: dict[str, int] = {p: i for i, p in enumerate(FISCAL_PERIODS)}

FiscalPeriod = str

#: The five earned value techniques IPMDAR recognises, as the model's closed vocabulary.
#: LEVEL_OF_EFFORT is the one that matters analytically: its claimed value accrues with the
#: passage of time regardless of physical progress, so a schedule variance computed over it
#: is meaningless — and a driver ranking that does not say so invites someone to chase it.
EVTechnique = Literal[
    "MILESTONE", "FIXED_FORMULA", "PERCENT_COMPLETE", "APPORTIONED", "LEVEL_OF_EFFORT",
]

#: The three EAC formulas ADR-0045 names, and the reason the method slot is mandatory.
#: They disagree materially on the same program; choosing one silently is choosing an answer.
EACMethod = Literal["CPI", "CPI_SPI", "REMAINING_AT_BUDGET"]


class NotInModel(Exception):
    """The subject is absent from the model — never an empty result set.

    An empty list means "the query ran and found nothing", which is a different claim from
    "this thing is not something I hold". Collapsing the two is how a typo becomes a
    confident zero. Copied from the planning engine's discipline, not reinvented.
    """


class MethodRequired(Exception):
    """A method-bearing verb was called without its method, and it refuses.

    THE REFUSAL NAMES THE CHOICE (ADR-0045). It is not "missing parameter"; it is "which
    method — CPI, CPI x SPI, or remaining-work-at-budget?", because a refusal that does not
    say what would fix it is a dead end wearing a gate's clothes.

    This is the `the-cost-of-guessing-is-a-mutation` law one layer out: there the cost of a
    guess was an unrequested write, here it is an unrequested ASSERTION — a number someone
    repeats in a meeting. Both are worse than a question.
    """

    def __init__(self, options: tuple[str, ...]):
        self.options = options
        super().__init__(
            "which method — " + ", ".join(options) + "? There is no default: the formulas "
            "disagree materially on the same program, so choosing one silently would be "
            "choosing an answer."
        )


# ─────────────────────────────────────────────────────────────────────────────
# The model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Program:
    """The whole scope of effort under one authorization."""
    program_id: str
    name: str
    #: Budget at completion — the total budgeted cost of all authorized work.
    bac: float
    value_unit: str = "USD"


@dataclass(frozen=True)
class OBSElement:
    """Who is accountable. The organizational axis."""
    obs_id: str
    name: str
    program_id: str


@dataclass(frozen=True)
class WBSElement:
    """What is being built. The product axis, identified hierarchically."""
    wbs_id: str          # e.g. "1.2" — the hierarchy IS the id
    name: str
    program_id: str
    parent_wbs_id: Optional[str] = None


@dataclass(frozen=True)
class ControlAccount:
    """Where scope, schedule and budget meet one accountable manager.

    The intersection of a WBS element and an OBS element — which is the whole reason both
    axes exist in the model. A control account with only one of the two is not a control
    account, and `check_consistency` refuses a seed that contains one.
    """
    ca_id: str           # e.g. "3.1.2"
    name: str
    program_id: str
    wbs_id: str
    obs_id: str
    bac: float


@dataclass(frozen=True)
class WorkPackage:
    """The smallest unit carrying a measurement method of its own."""
    wp_id: str
    name: str
    ca_id: str
    bac: float
    technique: EVTechnique


@dataclass(frozen=True)
class PeriodFact:
    """One work package's reported figures for one period. The time-phased triple.

    BCWS / BCWP / ACWP are the standard's own names and are kept verbatim rather than
    renamed to planned/earned/actual, for the same reason the class vocabulary is IPMDAR:
    an analyst reading a row recognises it, and a future read of a real program system is a
    mapping rather than a translation.

    THESE ARE PERIOD AMOUNTS, NOT CUMULATIVE. Every cumulative figure in this engine is
    computed by summing these in `PERIOD_ORDER`. Storing a cumulative field beside them
    would be a second writer for a fact that already has one — the planning engine's rev-3
    refusal of a stored `funding_gap`, applied here before it could happen.
    """
    wp_id: str
    period: FiscalPeriod
    bcws: float          # budgeted cost for work scheduled — the plan
    bcwp: float          # budgeted cost for work performed  — the claim
    acwp: float          # actual cost of work performed     — the spend


@dataclass(frozen=True)
class FundingLine:
    """An appropriation, with its three nested quantities.

    A LADDER, NOT A COMPARISON. `expended <= obligated <= authorized` is an invariant of the
    model, not an observation about the seed — `check_consistency` refuses a seed that
    breaks it. That nesting is what distinguishes a funding line from the planning engine's
    requirement-versus-supply shape, and it is why the third quantity cannot be dropped.
    """
    line_id: str
    name: str
    program_id: str
    period: FiscalPeriod
    authorized: float
    obligated: float
    expended: float


@dataclass
class FinanceState:
    """Everything the verbs compute over. Pure data; the measures are pure functions of it."""
    programs: list[Program] = field(default_factory=list)
    obs: list[OBSElement] = field(default_factory=list)
    wbs: list[WBSElement] = field(default_factory=list)
    control_accounts: list[ControlAccount] = field(default_factory=list)
    work_packages: list[WorkPackage] = field(default_factory=list)
    facts: list[PeriodFact] = field(default_factory=list)
    funding: list[FundingLine] = field(default_factory=list)

    # ── lookups, so the measures never re-scan by hand ────────────────────────

    def program(self, program_id: str) -> Program:
        for p in self.programs:
            if p.program_id == program_id:
                return p
        raise NotInModel(f"unknown program {program_id!r}")

    def control_account(self, ca_id: str) -> ControlAccount:
        for c in self.control_accounts:
            if c.ca_id == ca_id:
                return c
        raise NotInModel(f"unknown control account {ca_id!r}")

    def work_package(self, wp_id: str) -> WorkPackage:
        for w in self.work_packages:
            if w.wp_id == wp_id:
                return w
        raise NotInModel(f"unknown work package {wp_id!r}")

    def packages_of(self, ca_id: str) -> list[WorkPackage]:
        return [w for w in self.work_packages if w.ca_id == ca_id]

    def accounts_of(self, program_id: str) -> list[ControlAccount]:
        return [c for c in self.control_accounts if c.program_id == program_id]

    def facts_for(
        self, wp_ids: set[str], window: Optional[list[FiscalPeriod]] = None
    ) -> list[PeriodFact]:
        periods = set(window) if window else None
        return [
            f for f in self.facts
            if f.wp_id in wp_ids and (periods is None or f.period in periods)
        ]

    def label_of(self, entity_id: str) -> Optional[str]:
        """The display name for any id in the model, or None if it names nothing.

        ONE LOOKUP RATHER THAN SIX. The resolver and the enumerator both need to turn an id
        into a label, and a per-kind map in each of them is the second registry this
        codebase keeps paying for.
        """
        for coll, key in (
            (self.programs, "program_id"), (self.control_accounts, "ca_id"),
            (self.work_packages, "wp_id"), (self.wbs, "wbs_id"), (self.obs, "obs_id"),
        ):
            for item in coll:
                if getattr(item, key) == entity_id:
                    return item.name
        return None


def periods_in(window: Optional[list[FiscalPeriod]]) -> list[FiscalPeriod]:
    """The periods to report over, ordered, with an unknown period REFUSED by name.

    THE MESSAGE NAMES THE PERIODS, NOT THE CHARACTERS. Engine P measured the alternative:
    a router filling a `list[str]` slot from a bare string sends the STRING, the measure
    iterates it, and the refusal reads `unknown fiscal period(s): F, Y, 2, 6, -, Q, 4` —
    a message that names characters and blames the engine for a declaration's lie. A
    string arriving here is wrapped rather than iterated, so the refusal names what was
    actually said.
    """
    if window is None:
        return list(FISCAL_PERIODS)
    if isinstance(window, str):     # a caller that sent a scalar meant one period
        window = [window]
    unknown = [p for p in window if p not in PERIOD_ORDER]
    if unknown:
        raise NotInModel("unknown fiscal period(s): " + ", ".join(repr(u) for u in unknown))
    return sorted(set(window), key=lambda p: PERIOD_ORDER[p])
