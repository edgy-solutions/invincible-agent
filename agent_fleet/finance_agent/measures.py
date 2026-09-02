"""Engine F's six finance verbs. Deterministic, typed, pure over `FinanceState`.

ADR-0030: one verb, one fixed output type. The `OUTPUT_URI` table below is the whole of that
contract, and every URI in it is declared in `setup/ontologies/finance_extension.ttl` — both
ends, in one file, because the planning engine's split (inputs in the domain file, outputs in
mesh_system.ttl) is what let its input half go missing for twelve registrations.

WHAT THESE FUNCTIONS MUST NEVER DO — inherited verbatim from the planning engine, because
each prohibition is a defect somebody already paid for:
  * choose a view, a chart type, or an archetype       (ADR-0042 §2 — the selector's job)
  * return an empty result to mean "not in the model"  (raise NotInModel instead)
  * invent a threshold, a rate, or a METHOD            (see the EAC verb below)

And one this engine adds:
  * emit a monetary figure without its unit. Every row carries `value_unit`. A number without
    a declared unit is not an amount, and "dollars or thousands of dollars" is the single
    question a finance answer must never leave to convention.

EVERY FORMULA HERE IS PUBLIC EVM METHODOLOGY. CV = BCWP - ACWP. SV = BCWP - BCWS.
CPI = BCWP / ACWP. SPI = BCWP / BCWS. EAC by three named formulas, none of them defaulted.
Nothing proprietary, nothing derived from any real program.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, get_args

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import (
        PERIOD_ORDER, EACMethod, FinanceState, FiscalPeriod, MethodRequired, NotInModel,
        periods_in,
    )
except ImportError:
    from agent_fleet.finance_agent.entities import (
        PERIOD_ORDER, EACMethod, FinanceState, FiscalPeriod, MethodRequired, NotInModel,
        periods_in,
    )

FIN = "http://invincible-agent/fin#"

#: ONE VERB, ONE FIXED OUTPUT TYPE (ADR-0030). Read twice — by the route, to stamp the
#: response, and by the registration, to fill Contract D's output end — so the two cannot
#: disagree about what a verb produces.
OUTPUT_URI: dict[str, str] = {
    "fin_variance_analysis":   FIN + "VarianceDecomposition",
    "fin_eac_calculation":     FIN + "EstimateAtCompletion",
    "fin_performance_indices": FIN + "PerformanceIndexSeries",
    "fin_burn_rate":           FIN + "BurnRateSeries",
    "fin_variance_drivers":    FIN + "VarianceDriverRanking",
    "fin_funding_status":      FIN + "FundingStatusGrid",
}

#: DECLARED, NEVER INFERRED — the planning engine's absent-means-silent contract. A verb
#: absent from a table below emits no such key, and the renderer keeps showing a bare number
#: rather than guessing a currency this payload never sent. Every finance verb IS in
#: VALUE_UNIT, because every one of them answers in money or in a ratio derived from money.
VALUE_UNIT: dict[str, str] = {
    "fin_variance_analysis":   "USD",
    "fin_eac_calculation":     "USD",
    "fin_burn_rate":           "USD",
    "fin_variance_drivers":    "USD",
    "fin_funding_status":      "USD",
    # NOT fin_performance_indices. CPI and SPI are DIMENSIONLESS RATIOS, and stamping them
    # "USD" would put a dollar sign on 0.84. The absence is the assertion.
}

#: WHICH KEYS ARE SERIES, for MULTI_SERIES. Declared, never inferred — and the inference is
#: not merely unavailable, it is REFUSED by the archetype: cortex's contract makes `series`
#: required precisely so a renderer cannot fall back to "plot every numeric key I can find".
#: On a live burn-rate row that fallback draws `trailing_periods: 6` as a third line beside
#: burn and planned — a confident wrong picture, which is the honest-absence doctrine applied
#: to a chart.
#:
#: THE UNIT BELONGS TO THE SERIES, and that is what retires accommodation A2. `amount_unit`
#: was named to defeat an envelope-level lift that would have promoted a currency onto a
#: ratio chart; here CPI and SPI declare NO unit and render as bare ratios while burn and
#: planned declare USD. The lift has nothing to lift.
#:
#: ⛔ SERIES ON ONE CARD MUST SHARE A UNIT. Two quantities on one y-axis is a claim that they
#: are comparable, and the archetype refuses mixed units rather than drawing a second axis.
#: So a verb may not declare a USD series beside a dimensionless one.
SERIES: dict[str, list[dict[str, Any]]] = {
    "fin_burn_rate": [
        {"key": "burn",    "label": "Spent",  "unit": "USD"},
        {"key": "planned", "label": "Planned", "unit": "USD"},
    ],
    # NO `unit` KEY AT ALL, not `"unit": None`. Absent means DIMENSIONLESS by the contract —
    # a ratio, not an unknown currency — which is the same assertion VALUE_UNIT makes above
    # by omitting this verb.
    "fin_performance_indices": [
        {"key": "cpi", "label": "CPI"},
        {"key": "spi", "label": "SPI"},
    ],
}

#: The archetype contracts' `value_label` / `scope_label` passthroughs, supplied at the
#: response envelope rather than left for a renderer to invent. Engine P supplies only
#: `value_unit` and leaves the other two absent; they are cheap to state and a grid that has
#: to guess what its cells count is a grid captioned by convention.
VALUE_LABEL: dict[str, str] = {
    "fin_variance_analysis":   "Variance",
    "fin_eac_calculation":     "Estimate at completion",
    "fin_performance_indices": "Performance index",
    "fin_burn_rate":           "Spend per period",
    "fin_variance_drivers":    "Contribution to variance",
    "fin_funding_status":      "Unobligated balance",
}


# ─────────────────────────────────────────────────────────────────────────────
# Shared arithmetic — one implementation, so two verbs cannot disagree about CPI
# ─────────────────────────────────────────────────────────────────────────────

def _totals(
    state: FinanceState, wp_ids: set[str], window: Optional[list[FiscalPeriod]]
) -> tuple[float, float, float]:
    """Cumulative (BCWS, BCWP, ACWP) over the given work packages and periods.

    CUMULATIVE IS COMPUTED, NEVER STORED. The seed holds period amounts only; every
    to-date figure in this engine is a sum over `PERIOD_ORDER`. A stored cumulative field
    beside them would be a second writer for a fact that already has one.
    """
    facts = state.facts_for(wp_ids, window)
    return (
        sum(f.bcws for f in facts),
        sum(f.bcwp for f in facts),
        sum(f.acwp for f in facts),
    )


def _variance(kind: str, bcws: float, bcwp: float, acwp: float) -> float:
    """CV or SV. Sign convention: NEGATIVE IS UNFAVOURABLE, which is the standard's.

    Stated here once because the two variances answer different questions with the same
    word: cost variance asks what the claimed work cost against its budget, schedule
    variance asks how much of the planned work was claimed at all. A single "variance"
    figure cannot say both, and this seed contains a package that is late and on cost
    beside one that is on schedule and badly over cost precisely so that is visible.
    """
    if kind == "cost":
        return bcwp - acwp
    if kind == "schedule":
        return bcwp - bcws
    raise NotInModel(f"cannot compute a {kind!r} variance; kinds are cost and schedule")


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    """A performance index, or None where the denominator is zero.

    NONE, NOT 1.0 AND NOT 0.0. A period in which nothing was spent has no cost performance
    index — the ratio is undefined, not perfect and not catastrophic. Both of the tempting
    substitutes are assertions about performance that nobody made, and both would be
    charted as a real point on a trend line.
    """
    if denominator == 0:
        return None
    return numerator / denominator


def _require_program(state: FinanceState, program_id: str) -> Any:
    return state.program(program_id)


# ─────────────────────────────────────────────────────────────────────────────
# 1. fin_variance_analysis  ->  fin:VarianceDecomposition
# ─────────────────────────────────────────────────────────────────────────────
#
# ONE VERB, NOT A CHAIN (ADR-0045 Decision 3). The recursive playbook — decompose the
# variance, drill into the drivers, recurse until explained — is many steps and ONE
# QUESTION. The caller asks one thing; the recursion is this function's implementation, not
# the caller's problem, and exposing it as three chained verbs would make the caller
# responsible for a traversal policy they have no basis to choose.

def fin_variance_analysis(
    state: FinanceState,
    *,
    program_id: str,
    variance_kind: Literal["cost", "schedule"] = "cost",
    window: Optional[list[FiscalPeriod]] = None,
    materiality: float = 0.05,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    """Decompose a variance into the parts that produced it, recursing until explained.

    THE NESTING IS THE ANSWER. A variance stated without what produced it is a number
    nobody can act on, so the decomposition is the output type rather than a rendering
    choice — which is also why this returns a one-element list holding a TREE rather than a
    flat row set. The single element is the program; its `contributors` are the control
    accounts that matter; theirs are the work packages.

    WHEN THE RECURSION STOPS, and each reason is reported on the node in `stop_reason`
    rather than left for a reader to infer from an absent list:

      * `explained`     — the node's own variance is immaterial against the root's, so
                          drilling further would enumerate noise.
      * `leaf`          — a work package has nothing beneath it in this model.
      * `depth`         — `max_depth` reached. Reported, never silent: a truncated tree
                          that looks complete is the failure this field exists to prevent.

    `materiality` IS A FRACTION OF THE ROOT VARIANCE, not of the parent's. Against the
    parent, a $1,000 variance inside a $2,000 account is 50% and drills; against the root it
    is noise. The root is the question that was asked, so the root is the scale that matters.
    """
    program = _require_program(state, program_id)
    periods = periods_in(window)
    if not 0 < materiality < 1:
        raise NotInModel(
            f"materiality must be a fraction between 0 and 1, got {materiality!r}"
        )

    all_wps = {w.wp_id for w in state.work_packages
               if w.ca_id in {c.ca_id for c in state.accounts_of(program_id)}}
    root_bcws, root_bcwp, root_acwp = _totals(state, all_wps, periods)
    root_variance = _variance(variance_kind, root_bcws, root_bcwp, root_acwp)
    floor = abs(root_variance) * materiality

    def node(
        level: str, entity_id: str, entity_name: str, wp_ids: set[str],
        depth: int, extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        bcws, bcwp, acwp = _totals(state, wp_ids, periods)
        variance = _variance(variance_kind, bcws, bcwp, acwp)
        rec: dict[str, Any] = {
            "level": level,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "variance_kind": variance_kind,
            "variance": variance,
            "share_of_root": (variance / root_variance) if root_variance else None,
            "bcws": bcws, "bcwp": bcwp, "acwp": acwp,
            "value_unit": program.value_unit,
            "period_count": len(periods),
        }
        if extra:
            rec.update(extra)

        children = _children_of(level, entity_id)
        if not children:
            rec["stop_reason"] = "leaf"
        elif abs(variance) < floor:
            rec["stop_reason"] = "explained"
        elif depth >= max_depth:
            # SAY SO. A tree truncated by a depth limit and a tree that genuinely ended
            # look identical from the outside, and only one of them is a complete answer.
            rec["stop_reason"] = "depth"
        else:
            kids = [
                node(child_level, cid, cname, cwps, depth + 1, cextra)
                for child_level, cid, cname, cwps, cextra in children
            ]
            # MATERIAL CHILDREN ONLY, and the immaterial remainder is REPORTED rather than
            # dropped. Contributors that do not sum to their parent's variance is the
            # arithmetic lie this engine is most likely to tell, so the residual is a row.
            material = [k for k in kids if abs(k["variance"]) >= floor]
            residual = variance - sum(k["variance"] for k in material)
            rec["contributors"] = material
            if abs(residual) > 0:
                rec["residual"] = residual
                rec["residual_note"] = (
                    f"{len(kids) - len(material)} contributor(s) below the "
                    f"{materiality:.0%} materiality floor, netting "
                    f"{residual:,.0f} {program.value_unit}"
                )
            rec["stop_reason"] = "decomposed"
        return rec

    def _children_of(level: str, entity_id: str):
        if level == "program":
            return [
                ("control_account", c.ca_id, c.name,
                 {w.wp_id for w in state.packages_of(c.ca_id)},
                 {"wbs_id": c.wbs_id, "obs_id": c.obs_id, "bac": c.bac})
                for c in state.accounts_of(entity_id)
            ]
        if level == "control_account":
            return [
                ("work_package", w.wp_id, w.name, {w.wp_id},
                 # THE TECHNIQUE TRAVELS WITH THE PACKAGE, because it changes what the
                 # number means. A schedule variance on a level-of-effort package is
                 # structurally zero and analytically meaningless; a reader who cannot see
                 # the technique cannot know that.
                 {"technique": w.technique, "bac": w.bac})
                for w in state.packages_of(entity_id)
            ]
        return []

    return [node("program", program.program_id, program.name, all_wps, depth=0,
                 extra={"bac": program.bac})]


# ─────────────────────────────────────────────────────────────────────────────
# 2. fin_eac_calculation  ->  fin:EstimateAtCompletion
# ─────────────────────────────────────────────────────────────────────────────
#
# METHOD IS MANDATORY AND HAS NO DEFAULT (ADR-0045). This is the engine's designed refusal
# and its demo beat, so it is worth being exact about where the refusal lives.
#
# `method: EACMethod` carries NO DEFAULT, which is what makes `slots_for` declare it
# `spoken-mandatory` with the three values read out of the `Literal`. The router therefore
# knows the slot is missing — the information gap this fleet's `NO_VERB_CLASSIFIED`
# symptom was hiding — and the route refuses BY NAME before the call is made, using the
# declaration itself to build the message so it cannot drift from the signature.
#
# The check below is the SECOND gate, not the first, and it is here because ADR-0045 says
# the behaviour "must be written into the verb, not left to the caller's discipline." A
# caller reaching this function directly gets the same refusal the router gives.

#: Read out of the `Literal`, never re-typed. A fourth formula added to `EACMethod` appears
#: in the refusal message, in the slot declaration and in the validation on the same edit.
EAC_METHODS: tuple[str, ...] = get_args(EACMethod)

#: The formula each method applies, stated in the response beside the number it produced.
#: A forecast that does not carry its method is not an estimate at completion, it is a
#: figure — and the whole argument for the mandatory slot is that the figure alone is
#: ambiguous by up to 13% of the budget on this very seed.
EAC_FORMULA: dict[str, str] = {
    "CPI": "EAC = BAC / CPI",
    "CPI_SPI": "EAC = ACWP + (BAC - BCWP) / (CPI x SPI)",
    "REMAINING_AT_BUDGET": "EAC = ACWP + (BAC - BCWP)",
}


def fin_eac_calculation(
    state: FinanceState,
    *,
    program_id: str,
    method: EACMethod,
    window: Optional[list[FiscalPeriod]] = None,
) -> list[dict[str, Any]]:
    """Forecast total cost at completion by ONE NAMED METHOD. There is no default.

    The three formulas disagree materially on the same program — on this engine's own
    notional seed they span $13.13M, $14.15M and $14.79M against a $12.00M budget, a spread
    of $1.66M, about 14% of BAC. Choosing one silently is choosing an answer, and the answer
    is a number somebody repeats in a meeting.

    Which is why a bare "what's the EAC" is REFUSED, with the refusal naming the choice.
    """
    if method is None or method not in EAC_METHODS:
        # NAMES THE CHOICE, NOT THE FIELD. "missing required parameter: method" is a dead
        # end wearing a gate's clothes; a refusal that does not say what would fix it costs
        # the asker a round trip to find out.
        raise MethodRequired(EAC_METHODS)

    program = _require_program(state, program_id)
    periods = periods_in(window)
    wp_ids = {w.wp_id for w in state.work_packages
              if w.ca_id in {c.ca_id for c in state.accounts_of(program_id)}}
    bcws, bcwp, acwp = _totals(state, wp_ids, periods)
    bac = program.bac

    cpi = _ratio(bcwp, acwp)
    spi = _ratio(bcwp, bcws)

    if method == "REMAINING_AT_BUDGET":
        eac: Optional[float] = acwp + (bac - bcwp)
    elif method == "CPI":
        eac = (bac / cpi) if cpi else None
    else:  # CPI_SPI
        eac = (acwp + (bac - bcwp) / (cpi * spi)) if (cpi and spi) else None

    if eac is None:
        # UNDEFINED IS NOT ZERO. With no cost or schedule performance reported there is no
        # index to project forward, and every substitute figure would be an invention.
        raise NotInModel(
            f"cannot compute a {method} estimate at completion for {program_id}: no "
            f"performance has been reported in the requested periods, so there is no index "
            f"to project. A different method or a wider window may be answerable."
        )

    return [{
        "program_id": program.program_id,
        "program_name": program.name,
        # THE METHOD AND ITS FORMULA RIDE ON THE ROW. Not metadata: they are the half of
        # the answer that makes the number interpretable, and a card that shows the figure
        # without them reproduces exactly the ambiguity the mandatory slot exists to refuse.
        "method": method,
        "formula": EAC_FORMULA[method],
        "eac": eac,
        # Variance at completion — how far the forecast lands from the budget.
        "vac": bac - eac,
        # Estimate to complete — what the remaining work is forecast to cost from here.
        "etc": eac - acwp,
        "bac": bac, "bcws": bcws, "bcwp": bcwp, "acwp": acwp,
        "cpi": cpi, "spi": spi,
        "percent_complete": _ratio(bcwp, bac),
        "as_of_period": periods[-1] if periods else None,
        "reported_periods": len({f.period for f in state.facts_for(wp_ids, periods)}),
        "value_unit": program.value_unit,
        "scope_label": program.name,
    }]


# ─────────────────────────────────────────────────────────────────────────────
# 3. fin_performance_indices  ->  fin:PerformanceIndexSeries        (PERIOD_SERIES)
# ─────────────────────────────────────────────────────────────────────────────

def fin_performance_indices(
    state: FinanceState,
    *,
    program_id: str,
    ca_id: Optional[str] = None,
    window: Optional[list[FiscalPeriod]] = None,
) -> list[dict[str, Any]]:
    """CPI and SPI per period, with the raw quantities each ratio came from.

    A SERIES, NOT A POINT. The direction of travel is the question — an index of 0.84 that
    was 0.95 last month is a different program from one that was 0.75 — and a single ratio
    cannot show it. Both the period index and the cumulative index are reported, because
    they answer different questions and are routinely confused: the period index says how
    this month went, the cumulative says where the program stands.

    `ca_id` narrows to one control account. Optional, because the program-level series is
    the question that is asked first and requiring the narrowing would make the common case
    the harder one.
    """
    program = _require_program(state, program_id)
    if ca_id is not None:
        account = state.control_account(ca_id)   # raises NotInModel by name
        if account.program_id != program_id:
            raise NotInModel(
                f"control account {ca_id!r} does not belong to program {program_id!r}"
            )
        wp_ids = {w.wp_id for w in state.packages_of(ca_id)}
        scope_label = f"{account.name} ({ca_id})"
    else:
        wp_ids = {w.wp_id for w in state.work_packages
                  if w.ca_id in {c.ca_id for c in state.accounts_of(program_id)}}
        scope_label = program.name

    periods = periods_in(window)
    rows: list[dict[str, Any]] = []
    cum_bcws = cum_bcwp = cum_acwp = 0.0
    for period in periods:
        bcws, bcwp, acwp = _totals(state, wp_ids, [period])
        if bcws == 0 and bcwp == 0 and acwp == 0:
            # DELIBERATE-ABSENT. A period with nothing reported is not a period of zero
            # performance; emitting a row would draw a point on the trend line asserting
            # the program stopped, which is a claim the data does not make.
            continue
        cum_bcws += bcws
        cum_bcwp += bcwp
        cum_acwp += acwp
        rows.append({
            "period": period,
            "scope_label": scope_label,
            "cpi": _ratio(bcwp, acwp),
            "spi": _ratio(bcwp, bcws),
            "cum_cpi": _ratio(cum_bcwp, cum_acwp),
            "cum_spi": _ratio(cum_bcwp, cum_bcws),
            "bcws": bcws, "bcwp": bcwp, "acwp": acwp,
            "cum_bcws": cum_bcws, "cum_bcwp": cum_bcwp, "cum_acwp": cum_acwp,
            "cost_variance": bcwp - acwp,
            "schedule_variance": bcwp - bcws,
            # THE RATIOS ARE DIMENSIONLESS; the amounts beside them are not. Stating the
            # unit of the amounts on the row keeps the response honest without putting a
            # currency on a ratio — the reason this verb is absent from VALUE_UNIT.
            "amount_unit": program.value_unit,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 4. fin_burn_rate  ->  fin:BurnRateSeries                          (PERIOD_SERIES)
# ─────────────────────────────────────────────────────────────────────────────

def fin_burn_rate(
    state: FinanceState,
    *,
    program_id: str,
    window: Optional[list[FiscalPeriod]] = None,
) -> list[dict[str, Any]]:
    """Money leaving per period against the money the plan phased for it.

    THIS COUNTS CASH LEAVING, NOT VALUE CLAIMED. `fin_performance_indices` asks whether the
    money bought what it was supposed to; this asks how fast it is going out and when it
    runs out at this rate. A program can look healthy here and be performing badly — which
    is the whole reason the two are separate verbs rather than two columns of one.

    THE RUNWAY IS COMPUTED FROM THE TRAILING RATE, and the window it averages is stated on
    the row. A runway figure whose basis is invisible is a prediction the reader cannot
    challenge.
    """
    program = _require_program(state, program_id)
    periods = periods_in(window)
    wp_ids = {w.wp_id for w in state.work_packages
              if w.ca_id in {c.ca_id for c in state.accounts_of(program_id)}}

    rows: list[dict[str, Any]] = []
    cum_acwp = cum_bcws = 0.0
    burns: list[float] = []
    for period in periods:
        bcws, _bcwp, acwp = _totals(state, wp_ids, [period])
        if bcws == 0 and acwp == 0:
            continue
        cum_acwp += acwp
        cum_bcws += bcws
        burns.append(acwp)
        # A THREE-PERIOD TRAILING MEAN, and three is declared rather than tuned: it is short
        # enough to follow a turn and long enough not to chase one month. The window length
        # rides on the row so the figure can be argued with.
        trailing = burns[-3:]
        rate = sum(trailing) / len(trailing)
        remaining = program.bac - cum_acwp
        rows.append({
            "period": period,
            "scope_label": program.name,
            "burn": acwp,
            "planned": bcws,
            "variance_to_plan": bcws - acwp,
            "cum_burn": cum_acwp,
            "cum_planned": cum_bcws,
            "budget_remaining": remaining,
            "trailing_rate": rate,
            "trailing_periods": len(trailing),
            # PERIODS, NOT A DATE. Converting to a calendar date would require a period-to-
            # date map this model does not hold, and inventing one is how a forecast
            # acquires a precision its inputs never had.
            "runway_periods": (remaining / rate) if rate > 0 else None,
            "value_unit": program.value_unit,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 5. fin_variance_drivers  ->  fin:VarianceDriverRanking   (INSTANCES_BY_PROPERTY)
# ─────────────────────────────────────────────────────────────────────────────

def fin_variance_drivers(
    state: FinanceState,
    *,
    program_id: str,
    variance_kind: Literal["cost", "schedule"] = "cost",
    level: Literal["control_account", "work_package"] = "control_account",
    window: Optional[list[FiscalPeriod]] = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """The contributors to a variance, ranked by how much of it each accounts for.

    FAVOURABLE CONTRIBUTORS ARE RANKED TOO, and that is not a completeness gesture. Ranking
    only the unfavourable rows produces a list whose magnitudes sum to MORE than the
    variance they claim to explain, and a reader doing the obvious arithmetic finds the
    numbers do not add up. Ordering is by absolute contribution; the sign is on the row.

    THE TECHNIQUE IS REPORTED ON EVERY ROW, because it decides whether a row is worth
    chasing. A schedule variance on a level-of-effort package is structurally zero — value
    accrues with the passage of time regardless of physical progress — so such a row is
    flagged rather than silently ranked among things somebody could act on.
    """
    program = _require_program(state, program_id)
    periods = periods_in(window)
    if top_n < 1:
        raise NotInModel(f"top_n must be at least 1, got {top_n!r}")

    if level == "control_account":
        units = [
            (c.ca_id, c.name, {w.wp_id for w in state.packages_of(c.ca_id)},
             {"wbs_id": c.wbs_id, "obs_id": c.obs_id, "bac": c.bac, "technique": None})
            for c in state.accounts_of(program_id)
        ]
    elif level == "work_package":
        ca_ids = {c.ca_id for c in state.accounts_of(program_id)}
        units = [
            (w.wp_id, w.name, {w.wp_id},
             {"ca_id": w.ca_id, "bac": w.bac, "technique": w.technique})
            for w in state.work_packages if w.ca_id in ca_ids
        ]
    else:
        raise NotInModel(
            f"cannot rank drivers at level {level!r}; levels are control_account and "
            f"work_package"
        )

    total = _variance(
        variance_kind,
        *_totals(state, {wid for _, _, wps, _ in units for wid in wps}, periods),
    )

    scored: list[dict[str, Any]] = []
    for entity_id, name, wp_ids, extra in units:
        bcws, bcwp, acwp = _totals(state, wp_ids, periods)
        contribution = _variance(variance_kind, bcws, bcwp, acwp)
        if contribution == 0:
            continue  # a contributor of nothing is not a driver
        technique = extra.get("technique")
        row: dict[str, Any] = {
            # INSTANCES_BY_PROPERTY's generic keys, so the archetype can draw this without
            # knowing what a control account is...
            "instance_id": entity_id,
            "instance_label": name,
            "property_label": (
                "Cost variance" if variance_kind == "cost" else "Schedule variance"
            ),
            "value": contribution,
            # ...and the finance names beside them, so an analyst reading the payload sees
            # their own vocabulary rather than a generic projection of it. Both, because
            # renaming the domain fields to fit a renderer is the translation layer ADR-0045
            # refused at the ontology layer for the same reason.
            "entity_id": entity_id,
            "entity_name": name,
            "variance_kind": variance_kind,
            "contribution": contribution,
            "share_of_total": (contribution / total) if total else None,
            "favourable": contribution > 0,
            "bcws": bcws, "bcwp": bcwp, "acwp": acwp,
            "value_unit": program.value_unit,
            "scope_label": program.name,
        }
        row.update({k: v for k, v in extra.items() if v is not None})
        if variance_kind == "schedule" and technique == "LEVEL_OF_EFFORT":
            row["note"] = (
                "LEVEL_OF_EFFORT: claimed value accrues with time regardless of physical "
                "progress, so a schedule variance here is structurally zero and carries no "
                "information about progress."
            )
        scored.append(row)

    scored.sort(key=lambda r: abs(r["contribution"]), reverse=True)
    ranked = scored[:top_n]
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    # THE TAIL IS DECLARED WHERE IT IS TRUNCATED. `top_n` hiding contributors without saying
    # so is the same defect as the depth limit in the decomposition above: a partial list
    # that looks complete.
    if len(scored) > len(ranked):
        withheld = sum(r["contribution"] for r in scored[top_n:])
        for row in ranked:
            row["withheld_contributors"] = len(scored) - len(ranked)
            row["withheld_contribution"] = withheld
    return ranked


# ─────────────────────────────────────────────────────────────────────────────
# 6. fin_funding_status  ->  fin:FundingStatusGrid              (SHORTFALL_GRID)
# ─────────────────────────────────────────────────────────────────────────────
#
# NO NEW ARCHETYPE (ADR-0045 Decision 3). SHORTFALL_GRID already asks "how far below what is
# owed" with three quantities per cell, and authorized / obligated / expended maps to
# required / committed / secured nearly field-for-field. Minting a fourth grid whose colour
# means the same thing is precisely what the grid-splitting ruling refused.
#
# WHY THE PLANNING VOCABULARY IS EMITTED TOO, and this is the practical half of "reuse it":
# the renderer colours on `state`, whose three values are the grid's own
# (short / pledged-not-firm / met). Emitting finance-specific state strings would leave the
# card falling through to no colour at all, and fixing that means editing a registry in
# another repository. So each cell carries BOTH vocabularies — the grid's names so the
# existing renderer works UNCHANGED, and the IPMDAR names so the payload speaks the
# analyst's words. That is the field-for-field mapping made literal rather than asserted.


def _funding_state(authorized: float, obligated: float, expended: float) -> str:
    """The grid's verdict on one cell, STATED BY THE PRODUCER because it cannot be inferred.

    THE MIDDLE STATE IS THE WHOLE REASON THIS IS A FUNCTION, exactly as it is on the
    planning side. A line fully obligated and barely expended is INVISIBLE to any comparison
    of authorized against obligated: the ceiling is fully committed, the balance is zero,
    and the risk — money committed that is not moving — is real. A renderer looking at two
    of the three quantities sees a covered row and colours it green.
    """
    if authorized - obligated > 0:
        # Unobligated balance remains. In an appropriation with a period of availability
        # this is the condition that expires, which is why it is the attention state.
        return "short"
    if expended >= authorized:
        return "met"
    return "pledged-not-firm"


def fin_funding_status(
    state: FinanceState,
    *,
    program_id: str,
    window: Optional[list[FiscalPeriod]] = None,
) -> list[dict[str, Any]]:
    """Authorized, obligated and expended per funding line per period.

    A LADDER, NOT A COMPARISON. Each quantity is a subset of the one above it, which is what
    distinguishes this from the planning engine's requirement-against-supply shape and why
    the third number cannot be dropped without changing what the grid can say.
    """
    _require_program(state, program_id)
    periods = set(periods_in(window))

    rows: list[dict[str, Any]] = []
    for line in state.funding:
        if line.program_id != program_id or line.period not in periods:
            continue
        verdict = _funding_state(line.authorized, line.obligated, line.expended)
        rows.append({
            # ── the grid's contract: subject x period, three quantities, a verdict ──
            # `subject_id` is the cell's POSITION and `line_id` is what it is ABOUT — the
            # same split the planning grid draws, and the reason the archetype cannot name
            # the subject itself.
            "subject_id": line.line_id,
            "subject_name": line.name,
            "period": line.period,
            "required": line.authorized,
            "committed": line.obligated,
            "secured": line.expended,
            "shortfall": max(0.0, line.authorized - line.obligated),
            "gap": line.authorized - line.obligated,
            "at_risk": max(0.0, line.authorized - line.expended),
            "state": verdict,
            # ── the same cell in IPMDAR's words ──
            "line_id": line.line_id,
            "authorized": line.authorized,
            "obligated": line.obligated,
            "expended": line.expended,
            "unobligated_balance": line.authorized - line.obligated,
            "unexpended_balance": line.obligated - line.expended,
            "funding_state": {
                "short": "unobligated-balance",
                "pledged-not-firm": "obligated-not-expended",
                "met": "expended",
            }[verdict],
            "value_unit": "USD",
            "value_label": "Unobligated balance",
            "scope_label": line.name,
        })
    rows.sort(key=lambda r: (r["subject_id"], PERIOD_ORDER[r["period"]]))
    return rows
