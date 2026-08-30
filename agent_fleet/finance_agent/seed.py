"""The notional program. Invented names, round numbers, public EVM methodology only.

ADR-0045 DECISION 4 IS THE WHOLE CONTRACT OF THIS FILE. Nothing from the finance group's
actual work enters this repository — not as a fixture, not as a test case, not as an example
in a docstring. And the data must be OBVIOUSLY notional, so that a screenshot cannot be
mistaken for real program data by someone who did not author it. Hence: a program named after
a line of longitude, control accounts that read like a textbook WBS, and every figure a round
multiple of $5,000 - no cents anywhere, and no false precision.

── THE FACTS ARE GENERATED FROM DECLARED RATES, NOT TYPED OUT ────────────────────────────
Nine work packages over six reported periods is fifty-four rows of BCWS/BCWP/ACWP, and a
hand-typed table of fifty-four triples is a table nobody can check. Each work package instead
declares a monthly plan rate and two performance factors, and the triples are computed:

    bcws = monthly_bcws
    bcwp = bcws * spi_factor          (how much of the plan was actually claimed)
    acwp = bcwp / cpi_factor          (what claiming it cost)

The factors are chosen so every product lands on a round number — that is a property of the
chosen rates, and `check_consistency` asserts it rather than trusting it.

── WHAT THE SHAPE OF THIS DATA IS FOR ────────────────────────────────────────────────────
The seed is built so the six verbs have something true to say and the demo beats land:

  * ONE DOMINANT COST DRIVER. WP-3101's cost performance degrades from 1.00 to 0.40 over
    the six periods and accounts for $1,100,000 of the program's $1,130,000 cost variance.
    `fin_variance_analysis` decomposes to it in two levels and stops, because at that point
    the variance is explained.
  * A FAVOURABLE CONTRIBUTOR IN THE TAIL. WP-1102 underruns by $120,000. A driver ranking
    that reported only unfavourable rows would show contributors summing to more than the
    variance they explain — the tail has a sign, and hiding it makes the arithmetic lie.
  * COST AND SCHEDULE VARIANCE POINTING DIFFERENT WAYS, AND MOVING IN OPPOSITE
    DIRECTIONS. WP-2101 is late and on cost, and RECOVERING; WP-3101 is on schedule and
    badly over cost, and STILL DEGRADING. Cumulative CPI falls 0.995 -> 0.848 across the
    window while cumulative SPI climbs 0.870 -> 0.913. A single "variance" figure cannot say
    this, and a single period cannot either - which is why the indices verb reports two
    series rather than two numbers.
  * A LEVEL-OF-EFFORT PACKAGE. WP-4101 claims exactly its plan every period by construction,
    so its schedule variance is structurally zero and analytically meaningless. It is in the
    seed precisely so a driver ranking has to say so rather than let someone chase it.
  * THE THREE FUNDING STATES, one per appropriation, so the reused SHORTFALL_GRID has a cell
    of each colour.

── THE NUMBERS THE DEMO TURNS ON, stated here so they can be checked by hand ─────────────
Through FY26-06 (six of twelve periods reported):

    BAC   12,000,000     BCWS  6,900,000     BCWP  6,300,000     ACWP  7,430,000
    CV    -1,130,000     SV     -600,000     CPI  0.8479         SPI  0.9130

    EAC, remaining-work-at-budget   13,130,000
    EAC, CPI-based                  14,152,381
    EAC, CPI x SPI                  14,792,608

A SPREAD OF $1.66M — about 14% of the budget at completion — BETWEEN THREE DEFENSIBLE
FORMULAS OVER THE SAME PROGRAM. That spread is the argument for ADR-0045's mandatory method
slot, made in data rather than in prose: there is no defensible default because choosing one
silently is choosing an answer.
"""
from __future__ import annotations

from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import (
        FISCAL_PERIODS, ControlAccount, FinanceState, FundingLine, OBSElement, PeriodFact,
        Program, WBSElement, WorkPackage,
    )
except ImportError:
    from agent_fleet.finance_agent.entities import (
        FISCAL_PERIODS, ControlAccount, FinanceState, FundingLine, OBSElement, PeriodFact,
        Program, WBSElement, WorkPackage,
    )

PROGRAM_ID = "NP-MERIDIAN"

#: Periods with reported performance. The remaining six are authorized and unreported, which
#: is what makes an estimate at completion a forecast rather than a subtraction.
REPORTED_PERIODS: tuple[str, ...] = FISCAL_PERIODS[:6]

#: work package -> (name, control account, BAC, technique, monthly BCWS, spi factor, cpi factor)
#:
#: SPI AND CPI ARE FACTORS APPLIED PER PERIOD, not observed outcomes: the seed states the
#: performance it intends and the facts follow from it. That direction is deliberate — a
#: seed that stated fifty-four triples and left the reader to infer the intent would be a
#: seed whose shape nobody could confirm was the shape the tests assume.
#:
#: ── A FACTOR MAY BE A SCALAR OR ONE VALUE PER REPORTED PERIOD ──────────────────────────
#: The first version of this table held scalars only, and the seed it produced was WRONG in
#: a way that only showed up when the verbs ran against it: every period returned CPI 0.8367
#: and SPI 0.9130, IDENTICAL TO FOUR DECIMAL PLACES, six times over. A constant factor
#: cannot produce a trend.
#:
#: That is not a cosmetic flaw in the fixture. `fin_performance_indices` exists BECAUSE the
#: direction of travel is the question — an index of 0.84 that was 0.95 last month is a
#: different program from one that was 0.75 — and a seed with no direction cannot demonstrate
#: the claim its own verb is built on. A flat line is also exactly what a broken instrument
#: returns, so a demo over that data would have been indistinguishable from a bug.
#:
#: Two packages therefore carry per-period factors:
#:   WP-3101 DEGRADES  — cost performance falls from 1.00 to 0.40 across the six periods,
#:                       so the cumulative CPI turns downward and the drill has a story.
#:   WP-2101 RECOVERS  — schedule performance climbs from 0.60 back to 1.00, so SPI moves
#:                       the OTHER WAY over the same window. One trend could be read as the
#:                       whole program drifting; two opposing trends can only be read as two
#:                       packages behaving differently, which is what the verb is for.
_PACKAGES: tuple[tuple[str, str, str, float, str, float, Any, Any], ...] = (
    # wp_id       name                          ca      bac        technique          bcws/mo    spi   cpi
    ("WP-1101", "Requirements Baseline",       "1.1", 1_200_000, "MILESTONE",         100_000, 1.00, 1.00),
    ("WP-1102", "Architecture Definition",     "1.1",   800_000, "PERCENT_COMPLETE",  100_000, 1.00, 1.25),
    ("WP-2101", "Core Services Build",         "2.1", 2_500_000, "PERCENT_COMPLETE",  250_000,
     (0.60, 0.60, 0.80, 0.80, 1.00, 1.00), 1.00),
    ("WP-2102", "Interface Adapters",          "2.1", 1_500_000, "FIXED_FORMULA",     150_000, 1.00, 1.00),
    ("WP-3101", "Integration Lab Standup",     "3.1", 1_800_000, "MILESTONE",         200_000, 1.00,
     (1.00, 1.00, 0.50, 0.40, 0.40, 0.40)),
    ("WP-3102", "Qualification Test Campaign", "3.1", 1_200_000, "PERCENT_COMPLETE",  100_000, 0.50, 1.00),
    ("WP-4101", "Program Management Effort",   "4.1", 1_500_000, "LEVEL_OF_EFFORT",   125_000, 1.00, 1.00),
    ("WP-5101", "Spares Provisioning",         "5.1",   900_000, "APPORTIONED",        75_000, 1.00, 0.75),
    ("WP-5102", "Technical Publications",      "5.1",   600_000, "PERCENT_COMPLETE",   50_000, 1.00, 1.00),
)


def _per_period(factor: Any) -> tuple[float, ...]:
    """A scalar factor broadcast across the reported periods, or a per-period tuple as-is.

    REFUSES A MIS-LENGTHED TUPLE rather than zipping to the shorter one. A five-element
    factor over six periods would silently drop the last period's facts, and a seed missing
    a period is a seed whose totals are wrong by an amount nobody can see.
    """
    if isinstance(factor, (int, float)):
        return tuple(float(factor) for _ in REPORTED_PERIODS)
    factor = tuple(float(f) for f in factor)
    if len(factor) != len(REPORTED_PERIODS):
        raise ValueError(
            f"per-period factor has {len(factor)} values for "
            f"{len(REPORTED_PERIODS)} reported periods"
        )
    return factor

#: control account -> (CA name, WBS id, WBS name, OBS id, OBS name, BAC)
#:
#: ── EVERY AXIS GETS ITS OWN NAME, AND THE RESOLVER IS WHY ─────────────────────────────
#: The first version of this table carried ONE name per row and gave it to all three
#: objects, so the control account, the WBS element and the OBS element were all called
#: "Integration and Test". Measured against the live resolver the moment it was first run:
#:
#:     resolve "Integration and Test" -> [ {WBSElement "3", 1.0}, {ControlAccount "3.1", 1.0} ]
#:
#: TWO EXACT MATCHES IN DIFFERENT CLASSES. That is the router's fuzzy-mixed-class case and
#: it ABSTAINS on it — correctly, since the class is what sets the routing subject and two
#: classes tied at 1.0 name no subject. So the seed's own naming would have made the
#: flagship question unanswerable while every component reported healthy.
#:
#: The names are now distinct BY AXIS, which is also what the axes mean: the WBS names the
#: PRODUCT ("Integrated System"), the OBS names the ORGANIZATION ("Test and Evaluation
#: Directorate"), and the control account names the WORK where they intersect.
#: `check_consistency` refuses a duplicate label outright, so this cannot come back.
_ACCOUNTS: tuple[tuple[str, str, str, str, str, str, float], ...] = (
    ("1.1", "Systems Engineering",  "1", "System Definition",   "OBS-ENG",  "Engineering Directorate",           2_000_000),
    ("2.1", "Software Development", "2", "Mission Software",    "OBS-SW",   "Software Directorate",              4_000_000),
    ("3.1", "Integration and Test", "3", "Integrated System",   "OBS-TEST", "Test and Evaluation Directorate",   3_000_000),
    ("4.1", "Program Management",   "4", "Program Support",     "OBS-PMO",  "Program Management Office",         1_500_000),
    ("5.1", "Logistics Support",    "5", "Sustainment Products", "OBS-LOG", "Logistics Directorate",             1_500_000),
)

#: funding line -> (name, authorized, obligated per reported period, expended per reported period)
#:
#: ONE LINE PER FUNDING STATE, so the reused SHORTFALL_GRID shows a cell of each kind at the
#: latest period:
#:   FL-RDTE  8.0M authorized / 7.0M obligated  -> a $1.0M unobligated balance          (short)
#:   FL-PROC  3.0M authorized / 3.0M obligated / 0.5M expended -> fully obligated, barely
#:            paid out. THE MIDDLE STATE, and it is invisible to any comparison of
#:            authorized against obligated                              (pledged-not-firm)
#:   FL-OM    1.0M authorized / 1.0M obligated / 1.0M expended -> spent down       (met)
_FUNDING: tuple[tuple[str, str, float, tuple[float, ...], tuple[float, ...]], ...] = (
    ("FL-RDTE", "Research, Development, Test and Evaluation", 8_000_000,
     (2_000_000, 3_000_000, 4_000_000, 5_000_000, 6_000_000, 7_000_000),
     (0, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000)),
    ("FL-PROC", "Procurement", 3_000_000,
     (500_000, 1_000_000, 1_500_000, 2_000_000, 2_500_000, 3_000_000),
     (0, 0, 0, 0, 250_000, 500_000)),
    ("FL-OM", "Operations and Maintenance", 1_000_000,
     (1_000_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000),
     (0, 200_000, 400_000, 600_000, 800_000, 1_000_000)),
)


def build_seed() -> FinanceState:
    """The notional program, assembled from the declared tables above."""
    state = FinanceState()

    state.programs.append(Program(
        program_id=PROGRAM_ID,
        name="Notional Program Meridian",
        # INDEX-FREE ON PURPOSE. This read was `a[4]` while `_ACCOUNTS` had five columns;
        # widening the table to seven (each axis got its own name) silently moved the BAC
        # and `a[4]` became an OBS name. It failed loudly here only because summing a string
        # onto an int raises — had the two columns both been numeric, the program's budget
        # would have quietly become the wrong number and `check_consistency`'s roll-up
        # assertion would have been the only thing standing between that and a wrong answer.
        # Destructuring from the END is stable under further widening.
        bac=sum(bac for *_, bac in _ACCOUNTS),
        value_unit="USD",
    ))

    for ca_id, ca_name, wbs_id, wbs_name, obs_id, obs_name, bac in _ACCOUNTS:
        # THE TWO AXES ARE SEPARATE OBJECTS, not two fields on one. A control account IS the
        # intersection of a WBS element and an OBS element; modelling either axis as a string
        # attribute would make "how is the software organization doing across everything it
        # owns" unanswerable without a second registry of org names.
        if not any(w.wbs_id == wbs_id for w in state.wbs):
            state.wbs.append(WBSElement(
                wbs_id=wbs_id, name=wbs_name, program_id=PROGRAM_ID, parent_wbs_id=None,
            ))
        if not any(o.obs_id == obs_id for o in state.obs):
            state.obs.append(OBSElement(obs_id=obs_id, name=obs_name, program_id=PROGRAM_ID))
        state.control_accounts.append(ControlAccount(
            ca_id=ca_id, name=ca_name, program_id=PROGRAM_ID,
            wbs_id=wbs_id, obs_id=obs_id, bac=bac,
        ))

    for wp_id, name, ca_id, bac, technique, monthly, spi, cpi in _PACKAGES:
        state.work_packages.append(WorkPackage(
            wp_id=wp_id, name=name, ca_id=ca_id, bac=bac, technique=technique,  # type: ignore[arg-type]
        ))
        spi_by_period = _per_period(spi)
        cpi_by_period = _per_period(cpi)
        for i, period in enumerate(REPORTED_PERIODS):
            bcwp = monthly * spi_by_period[i]
            state.facts.append(PeriodFact(
                wp_id=wp_id, period=period,
                bcws=monthly, bcwp=bcwp, acwp=bcwp / cpi_by_period[i],
            ))

    for line_id, name, authorized, obligated, expended in _FUNDING:
        for i, period in enumerate(REPORTED_PERIODS):
            state.funding.append(FundingLine(
                line_id=line_id, name=name, program_id=PROGRAM_ID, period=period,
                authorized=authorized, obligated=obligated[i], expended=expended[i],
            ))

    return state


def check_consistency(state: FinanceState) -> list[str]:
    """Structural problems in the seed, as messages. Empty means the seed is coherent.

    FAIL LOUD AT BOOT, and the planning engine's reason applies unchanged: a seed with
    dangling references produces measures that are QUIETLY WRONG rather than absent, which is
    the failure mode with no symptom. `main.py` raises on a non-empty return.

    Every check below corresponds to an invariant this engine's arithmetic depends on. None
    of them is a taste check.
    """
    problems: list[str] = []
    ca_ids = {c.ca_id for c in state.control_accounts}
    wbs_ids = {w.wbs_id for w in state.wbs}
    obs_ids = {o.obs_id for o in state.obs}
    wp_ids = {w.wp_id for w in state.work_packages}

    for c in state.control_accounts:
        # A CONTROL ACCOUNT WITHOUT BOTH AXES IS NOT A CONTROL ACCOUNT. It is the
        # intersection by definition, and a half-placed account silently disappears from
        # whichever roll-up it is missing an axis for.
        if c.wbs_id not in wbs_ids:
            problems.append(f"control account {c.ca_id} references unknown WBS {c.wbs_id}")
        if c.obs_id not in obs_ids:
            problems.append(f"control account {c.ca_id} references unknown OBS {c.obs_id}")

    for w in state.work_packages:
        if w.ca_id not in ca_ids:
            problems.append(f"work package {w.wp_id} references unknown control account {w.ca_id}")

    for f in state.facts:
        if f.wp_id not in wp_ids:
            problems.append(f"period fact references unknown work package {f.wp_id}")
        # ROUNDNESS IS AN INVARIANT, NOT AN OBSERVATION. The seed's whole claim is that its
        # figures are obviously notional; a factor that produced $103,333.33 would break that
        # claim silently, and the docstring above would become a lie nobody checked.
        #
        # THIS CHECK CAUGHT ITS OWN AUTHOR, 2026-08-29, and the threshold is the finding. It
        # first read `% 50_000`, transcribed from the phrase "round multiple of $50,000" in
        # the docstring above — and immediately refused thirty-six rows of a seed that is
        # entirely round: $75,000, $80,000 and $125,000 are round figures that are not
        # multiples of fifty thousand. The DATA was right and the ASSERTION was wrong.
        # $5,000 is the real invariant, and it is what "no cents, no false precision" means.
        for label, amount in (("bcws", f.bcws), ("bcwp", f.bcwp), ("acwp", f.acwp)):
            if amount % 5_000 != 0:
                problems.append(
                    f"{f.wp_id} {f.period} {label}={amount} is not a round multiple of 5,000 "
                    f"- notional data must be OBVIOUSLY notional (ADR-0045 Decision 4)"
                )

    for p in state.programs:
        rolled = sum(c.bac for c in state.control_accounts if c.program_id == p.program_id)
        if rolled != p.bac:
            problems.append(
                f"program {p.program_id} BAC {p.bac} != sum of control account BACs {rolled}"
            )

    for c in state.control_accounts:
        rolled = sum(w.bac for w in state.work_packages if w.ca_id == c.ca_id)
        if rolled != c.bac:
            problems.append(
                f"control account {c.ca_id} BAC {c.bac} != sum of work package BACs {rolled}"
            )

    # NO TWO ENTITIES MAY SHARE AN EXACT LABEL, and this is a resolver constraint rather
    # than a tidiness one. `resolve_instance` scores an exact label match at 1.0 regardless
    # of class, and the router ABSTAINS when the top candidates tie across different classes
    # — because the class is what sets the routing subject, and two classes tied at 1.0 name
    # no subject at all. A seed with a duplicate label therefore produces a question that
    # cannot be routed while every component reports healthy. Measured on this seed's own
    # first run: "Integration and Test" was a control account, a WBS element and an OBS
    # element simultaneously.
    seen: dict[str, str] = {}
    for kind, items, id_field in (
        ("program", state.programs, "program_id"),
        ("control account", state.control_accounts, "ca_id"),
        ("work package", state.work_packages, "wp_id"),
        ("WBS element", state.wbs, "wbs_id"),
        ("OBS element", state.obs, "obs_id"),
        ("funding line", state.funding, "line_id"),
    ):
        for item in items:
            key = item.name.strip().lower()
            here = f"{kind} {getattr(item, id_field)}"
            if key in seen and seen[key] != here:
                problems.append(
                    f"duplicate label {item.name!r}: {seen[key]} and {here} — the resolver "
                    f"scores both at 1.0 in different classes and the router abstains, so "
                    f"this name cannot be spoken"
                )
            seen[key] = here

    for fl in state.funding:
        # THE LADDER. expended <= obligated <= authorized is what a funding line IS; a seed
        # that broke it would make `fin_funding_status` report a state no appropriation can
        # be in, and the grid would colour it confidently.
        if not (fl.expended <= fl.obligated <= fl.authorized):
            problems.append(
                f"funding line {fl.line_id} {fl.period}: expended {fl.expended} / obligated "
                f"{fl.obligated} / authorized {fl.authorized} violates the nesting invariant"
            )

    return problems


def notional_banner(state: Optional[FinanceState] = None) -> str:
    """The one-line disclosure every response carries. Not decoration.

    A finance figure that leaves this engine without saying it is notional is a figure
    somebody can paste into a deck. The banner rides on the response envelope, not only in
    a docstring, because a docstring is not visible from a screenshot.
    """
    return (
        "NOTIONAL DATA — invented program, round figures, public EVM formulas. "
        "Not derived from any real program (ADR-0045 Decision 4)."
    )
