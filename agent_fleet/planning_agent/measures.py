"""The ten planning measures — VERBS, each with a fixed output type.

ADR-0042 §3: a measure is a verb and runs where verbs run. Not because server-side is
inherently better, but because a browser-computed row set has no verb to be the output of,
therefore no `output_uri`, therefore it cannot enter `/render_ui` at all.

ADR-0030: each verb's output type is FIXED — declared before the rows exist, never chosen
from them. That is precisely what lets an intent declare an `output_uri` at slot-fill time
and let `select_presentation` pick the archetype from the PAYLOAD afterwards. The
`OUTPUT_URI` table below is the whole of that contract.

WHAT THESE FUNCTIONS MUST NEVER DO:
  * choose a view, a chart type, or an archetype   (ADR-0042 §2 — the selector's job)
  * return an empty result to mean "not in the model"  (raise NotInModel instead)
  * invent a threshold, a cap, or a rate            (governance-defined fields only)

Every function is PURE over `PlanState`, which is what makes a diff cheap: run it over two
states and subtract. It is also what makes ADR-0042 OQ2 resolvable as one verb over two
state refs.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

try:  # flat in the image (/app), packaged in the repo — see tests/test_agent_modules_survive_flat_layout.py
    from entities import FISCAL_PERIODS, PERIOD_ORDER, Dependency, FiscalPeriod, Interval, PlanState
except ImportError:
    from agent_fleet.planning_agent.entities import FISCAL_PERIODS, PERIOD_ORDER, Dependency, FiscalPeriod, Interval, PlanState

# The op types the reschedule policy CO-EMITS. Imported under the same flat/packaged idiom —
# see tests/test_agent_modules_survive_flat_layout.py for why a bare packaged import fails in
# the image.
try:
    from state import MoveProject, MoveSiteImpact
except ImportError:
    from agent_fleet.planning_agent.state import MoveProject, MoveSiteImpact

# ─────────────────────────────────────────────────────────────────────────────
# The output-type contract. Declared, fixed, and the ONLY thing an intent names.
# ─────────────────────────────────────────────────────────────────────────────
MESH = "http://invincible-agent/mesh#"

OUTPUT_URI: dict[str, str] = {
    "plan_cost_curve":            MESH + "PeriodCostSeries",
    "plan_funding_gap":           MESH + "FundingGapSet",
    "plan_site_load":             MESH + "LoadThresholdGrid",
    "plan_dependency_violations": MESH + "ConstraintViolationSet",
    "plan_maturity_grid":         MESH + "MaturityMatrix",
    "plan_capability_path":       MESH + "ContributionSequence",
    "plan_process_evolution":     MESH + "PlateauTimeline",
    "plan_tech_footprint":        MESH + "FootprintSet",
    "plan_schedule":              MESH + "IntervalSchedule",
    "plan_session_changes":       MESH + "ChangeLog",
    "plan_diff":                  MESH + "EffectSet",
    "plan_coverage_gap":          MESH + "CoverageGapSet",
    "plan_dependency_neighborhood": MESH + "DependencyNeighborhoodSet",
    "plan_commit_scenario":       MESH + "DecisionArtifact",
}


# The unit a verb's numbers are IN. A DECLARATION, never an inference: `run_measure` is generic
# and must not read money-ness off a field name, because `total` is dollars here and a count in
# plan_site_load. ABSENT MEANS SILENT — a verb not listed emits no `value_unit`, and the shipped
# renderer keeps showing `1.5M` rather than guessing a `$` the payload never sent.
VALUE_UNIT: dict[str, str] = {
    "plan_cost_curve":  "USD",
    "plan_funding_gap": "USD",
}


class NotInModel(LookupError):
    """The question named something the model does not contain.

    RAISED, never swallowed into an empty result. An empty row set renders as "no
    contributing projects for this capability", which is a false statement about a
    capability that does not exist — the refusal path exists so the answer can be "the
    model doesn't capture X", and it cannot fire if the measure quietly returns nothing.
    """


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _add_days(iso: str, n: int) -> str:
    from datetime import timedelta
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def _periods(window: Optional[list[FiscalPeriod]]) -> list[FiscalPeriod]:
    if window is None:
        return list(PERIOD_ORDER)
    unknown = [p for p in window if p not in FISCAL_PERIODS]
    if unknown:
        raise NotInModel(f"unknown fiscal period(s): {', '.join(unknown)}")
    return [p for p in PERIOD_ORDER if p in window]


# ─────────────────────────────────────────────────────────────────────────────
# 1. plan_cost_curve  ->  mesh:PeriodCostSeries        (Q12, Q16, Q17)
# ─────────────────────────────────────────────────────────────────────────────

def plan_cost_curve(
    state: PlanState,
    *,
    window: Optional[list[FiscalPeriod]] = None,
    scope_initiative_id: Optional[str] = None,
    baseline_state: Optional[PlanState] = None,
) -> list[dict[str, Any]]:
    """Per-period requirement sums by kind, against the governed cap line.

    `cap` is None where no cap is recorded — HONESTLY UNCAPPED, never zero. A zero cap would
    paint every uncapped bar red, which is the "a zero that looks like data" failure the
    honest-empty discipline names, arriving through a default rather than through a bug.
    """
    if scope_initiative_id is not None and not any(
        i.initiative_id == scope_initiative_id for i in state.initiatives
    ):
        raise NotInModel(f"unknown initiative {scope_initiative_id!r}")

    def in_scope(project_id: str) -> bool:
        if scope_initiative_id is None:
            return True
        init = state.initiative_of_project(project_id)
        return init is not None and init.initiative_id == scope_initiative_id

    rows: list[dict[str, Any]] = []
    for period in _periods(window):
        capex = sum(r.amount for r in state.requirements
                    if r.period == period and r.kind == "capex" and in_scope(r.project_id))
        expense = sum(r.amount for r in state.requirements
                      if r.period == period and r.kind == "expense" and in_scope(r.project_id))
        total = capex + expense
        cap = state.period_caps.get(period)
        rows.append({
            "period": period,
            "capex": capex,
            "expense": expense,
            "total": total,
            "cap": cap,
            "over_cap": cap is not None and total > cap,
            "overage": (total - cap) if (cap is not None and total > cap) else None,
        })

    # THE BASELINE SERIES — the diff machinery reaching this payload, not a bolt-on column.
    # `plan_diff` already pairs periods this way; this is that same projection, one row deep.
    #
    # ABSENT, NOT NULL, when there is no comparison. A `baseline: None` on every row would tell
    # the renderer a comparison EXISTS and is empty; the key's absence says the card is not a
    # comparison at all, which is the true statement and the one the ghost keys on.
    #
    # NESTED because it is a SERIES. Three sibling columns would have to be added or dropped
    # together — an invariant that would live in a convention nobody enforces. One object
    # cannot half-arrive.
    if baseline_state is not None:
        base = {
            r["period"]: {"capex": r["capex"], "expense": r["expense"], "total": r["total"]}
            for r in plan_cost_curve(
                baseline_state, window=window, scope_initiative_id=scope_initiative_id
            )
        }
        for row in rows:
            # A period present in the scenario and absent from baseline is NEW spend; its
            # baseline is honestly zero rather than missing, so the ghost draws a floor.
            row["baseline"] = base.get(
                row["period"], {"capex": 0.0, "expense": 0.0, "total": 0.0}
            )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 2. plan_funding_gap  ->  mesh:FundingGapSet          (Q13, Q14, Q15)
# ─────────────────────────────────────────────────────────────────────────────

def plan_funding_gap(
    state: PlanState,
    *,
    group_by: Literal["org", "initiative"] = "org",
    window: Optional[list[FiscalPeriod]] = None,
) -> list[dict[str, Any]]:
    """Required minus committed, per group per period, split by kind.

    Grouping by ORG requires care that grouping by initiative does not: a requirement has no
    org (demand is org-agnostic), so a project's requirement is attributed to the org(s) that
    committed to it. A project with requirements and NO commitment at all is attributed to
    the sentinel org id `"(uncommitted)"` — visible as an unfunded row rather than vanishing,
    which is the whole point of splitting demand from supply.

    REV 3 — SECURED IS NOT THE SAME AS COMMITTED-ON-PAPER. A `pending` commitment is a hope.
    `secured` counts only `committed` + `approved`; `at_risk` is the part of the requirement
    covered by nothing or by pending money only. A gap measure that counted hopes as money
    would be the measure a portfolio review exists to replace.

    NOTHING HERE IS STORED. `gap`, `secured` and `at_risk` are all computed from requirement
    and commitment rows on every call. A stored field beside them would be a second writer for
    a fact that already has one — see the rev-3 delta's refusal of a `funding_gap` field.
    """
    SECURED_STATUSES = ("committed", "approved")
    if group_by not in ("org", "initiative"):
        raise NotInModel(f"cannot group funding by {group_by!r}")

    rows: list[dict[str, Any]] = []
    for period in _periods(window):
        reqs = [r for r in state.requirements if r.period == period]
        commits = [k for k in state.commitments if k.period == period]

        if group_by == "initiative":
            groups = sorted({
                i.initiative_id for i in state.initiatives
            })
            for gid in groups:
                def in_g(pid: str, gid: str = gid) -> bool:
                    init = state.initiative_of_project(pid)
                    return init is not None and init.initiative_id == gid
                required = sum(r.amount for r in reqs if in_g(r.project_id))
                committed = sum(k.amount for k in commits if in_g(k.project_id))
                secured = sum(k.amount for k in commits
                              if in_g(k.project_id) and k.status in SECURED_STATUSES)
                if required == 0 and committed == 0:
                    continue  # deliberate-absent: a group with no activity is not a zero row
                rows.append({
                    "group_by": "initiative", "initiative_id": gid, "period": period,
                    "required": required, "committed": committed,
                    "secured": secured,
                    "gap": required - committed,
                    # What the requirement leaves uncovered by SECURED money. Never negative:
                    # over-securing one group is not negative risk elsewhere.
                    "at_risk": max(0.0, required - secured),
                })
            continue

        # group_by == "org"
        org_of_project: dict[str, set[str]] = {}
        for k in commits:
            org_of_project.setdefault(k.project_id, set()).add(k.org_id)

        blank = {"required": 0.0, "committed": 0.0, "secured": 0.0}
        by_org: dict[str, dict[str, float]] = {}
        for r in reqs:
            owners = org_of_project.get(r.project_id) or {"(uncommitted)"}
            # Split evenly when several orgs co-fund a project — the honest apportionment
            # absent a per-requirement funder, and it keeps the column totals correct.
            share = r.amount / len(owners)
            for oid in owners:
                by_org.setdefault(oid, dict(blank))["required"] += share
        for k in commits:
            entry = by_org.setdefault(k.org_id, dict(blank))
            entry["committed"] += k.amount
            if k.status in SECURED_STATUSES:
                entry["secured"] += k.amount

        for oid in sorted(by_org):
            v = by_org[oid]
            rows.append({
                "group_by": "org", "org_id": oid, "period": period,
                "required": v["required"], "committed": v["committed"],
                "secured": v["secured"],
                "gap": v["required"] - v["committed"],
                "at_risk": max(0.0, v["required"] - v["secured"]),
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 3. plan_site_load  ->  mesh:LoadThresholdGrid        (Q9, Q11)
# ─────────────────────────────────────────────────────────────────────────────

def plan_site_load(
    state: PlanState,
    *,
    site_id: Optional[str] = None,
    window: Optional[list[FiscalPeriod]] = None,
) -> list[dict[str, Any]]:
    """Per site per period: the summed load of impacts whose window overlaps the period.

    The threshold is `Site.saturation_threshold` — a GOVERNANCE-DEFINED field, never a
    constant invented here. "Overloaded" is a judgement someone owns; a measure that picks
    its own line is an invented measure.
    """
    if site_id is not None and state.site(site_id) is None:
        raise NotInModel(f"unknown site {site_id!r}")

    sites = [s for s in state.sites if site_id is None or s.site_id == site_id]
    rows: list[dict[str, Any]] = []
    for site in sites:
        impacts = [i for i in state.site_impacts if i.site_id == site.site_id]
        for period in _periods(window):
            pv = FISCAL_PERIODS[period]
            hits = [i for i in impacts if i.window.overlaps(pv)]
            if not hits:
                # DELIBERATE-ABSENT, not a zero row. A site with nothing happening in a
                # quarter has no load story; emitting 0.0 makes an empty grid look measured.
                continue
            load = sum(i.load_weight for i in hits)
            rows.append({
                "site_id": site.site_id,
                "site_name": site.name,
                "period": period,
                "load": load,
                "threshold": site.saturation_threshold,
                "over_threshold": load > site.saturation_threshold,
                "contributors": sorted(i.project_id for i in hits),
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 4. plan_dependency_violations  ->  mesh:ConstraintViolationSet   (Q10)
# ─────────────────────────────────────────────────────────────────────────────

_DEP_RULES = {
    # (predecessor anchor, successor anchor) — the four standard scheduling constraints.
    "FS": ("end", "start"),
    "SS": ("start", "start"),
    "FF": ("end", "end"),
    "SF": ("start", "end"),
}


def plan_dependency_violations(state: PlanState) -> list[dict[str, Any]]:
    """Dependencies whose successor violates dep_type + lag against its predecessor.

    Reports the SHORTFALL IN DAYS, not just a boolean. "P5 starts 13 days too early" is a
    sentence the room can act on; "D4 violated" sends someone to open the schedule.
    """
    out: list[dict[str, Any]] = []
    for d in state.dependencies:
        # ONE EVALUATOR, shared with plan_dependency_neighborhood. This verb reports the
        # subset where the answer is "violated"; that one reports every neighbour with its
        # answer. Two implementations would disagree about `>=` versus `>` eventually, and
        # the disagreement would surface as a card saying "satisfied" beside one saying
        # "13 days short" about the same edge.
        ev = _dep_evaluation(state, d)

        if ev["status"] == "unresolvable":
            # A dangling dependency is a MODEL defect, surfaced as its own row rather than
            # skipped — a constraint nobody can evaluate must not read as a constraint met.
            out.append({
                "dependency_id": d.dependency_id, "dep_type": d.dep_type,
                "unresolvable": True,
                "reason": ev["reason"],
            })
            continue

        if ev["status"] == "satisfied":
            continue

        out.append({
            "dependency_id": d.dependency_id,
            "dep_type": d.dep_type,
            "lag_days": d.lag_days,
            "predecessor_id": d.predecessor_id,
            "successor_id": d.successor_id,
            "required_earliest_start": ev["required_earliest_start"],
            "actual_start": ev["actual_start"],
            "shortfall_days": ev["shortfall_days"],
            "unresolvable": False,
        })
    return out


_DIRECTIONS = ("upstream", "downstream")


def _dep_evaluation(state: PlanState, d: Dependency) -> dict[str, Any]:
    """Is this one dependency satisfied, and by how much is it missed?

    EXTRACTED so there is ONE place that answers it. `plan_dependency_violations` reports the
    subset where the answer is "no"; `plan_dependency_neighborhood` reports every neighbour
    WITH its answer. Two implementations would disagree about `>=` versus `>` on the day it
    mattered — the same two-writers rule the model applies to derived edges.
    """
    pred = state.interval_of(d.predecessor_kind, d.predecessor_id)
    succ = state.interval_of(d.successor_kind, d.successor_id)
    if pred is None or succ is None:
        return {
            "status": "unresolvable",
            "reason": f"{d.predecessor_id} or {d.successor_id} has no planned interval",
            "shortfall_days": None,
        }
    pred_anchor, succ_anchor = _DEP_RULES[d.dep_type]
    pred_date = pred.end if pred_anchor == "end" else pred.start
    succ_date = succ.end if succ_anchor == "end" else succ.start
    earliest = _add_days(pred_date, d.lag_days)
    if succ_date >= earliest:
        return {"status": "satisfied", "shortfall_days": 0,
                "required_earliest_start": earliest, "actual_start": succ_date}
    return {"status": "violated", "shortfall_days": _days_between(succ_date, earliest),
            "required_earliest_start": earliest, "actual_start": succ_date}


# ─────────────────────────────────────────────────────────────────────────────
# 13. plan_dependency_neighborhood  ->  mesh:DependencyNeighborhoodSet
# ─────────────────────────────────────────────────────────────────────────────

def plan_dependency_neighborhood(
    state: PlanState,
    *,
    project_id: str,
    direction: str = "upstream",
    kind: str = "project",
) -> dict[str, Any]:
    """What one item waits on, or what waits on it — TRAVERSAL, not constraint evaluation.

    WHY THIS IS NOT A PARAMETER ON plan_dependency_violations. That verb evaluates a
    constraint and reports the subset that fails; this one walks the edges and reports every
    neighbour WITH its state. The distinction is not stylistic: measured on the seed, the
    violations verb returns **[]**, so "what blocks P5?" routed there answers with silence —
    and silence reads as "nothing depends on P5" rather than "P5's predecessor is satisfied".
    Those are different facts and only one is true.

    THREE OUTCOMES THAT MUST NOT COLLAPSE INTO EACH OTHER:
      * neighbours exist          -> rows, each carrying its own satisfied/violated status;
      * the item is a ROOT/LEAF   -> an empty list, which is the real answer "nothing here";
      * the item is not modelled  -> NotInModel, RAISED.
    An empty list for an unknown id would be a false statement about something that does not
    exist, which is the failure this whole verb was commissioned to remove.
    """
    if direction not in _DIRECTIONS:
        raise NotInModel(
            f"cannot traverse dependencies {direction!r} — "
            f"known directions are {', '.join(_DIRECTIONS)}"
        )
    if kind not in ("project", "phase"):
        raise NotInModel(f"cannot traverse from a {kind!r} end")

    subject = state.project(project_id) if kind == "project" else state.phase(project_id)
    if subject is None:
        raise NotInModel(f"no {kind} {project_id!r} in the plan")

    neighbors: list[dict[str, Any]] = []
    for d in state.dependencies:
        if direction == "upstream":
            if d.successor_kind != kind or d.successor_id != project_id:
                continue
            other_kind, other_id = d.predecessor_kind, d.predecessor_id
        else:
            if d.predecessor_kind != kind or d.predecessor_id != project_id:
                continue
            other_kind, other_id = d.successor_kind, d.successor_id

        other = (state.project(other_id) if other_kind == "project"
                 else state.phase(other_id))
        interval = state.interval_of(other_kind, other_id)
        row = {
            "dependency_id": d.dependency_id,
            "kind": other_kind,
            "id": other_id,
            # A dangling end still gets a NAME slot rather than being dropped — a neighbour
            # nobody can resolve is a model defect worth seeing, not an absence.
            "name": getattr(other, "name", None) or other_id,
            "dep_type": d.dep_type,
            "lag_days": d.lag_days,
            "planned_start": interval.start if interval else None,
            "planned_end": interval.end if interval else None,
        }
        row.update(_dep_evaluation(state, d))
        neighbors.append(row)

    neighbors.sort(key=lambda n: (n["planned_start"] or "", n["id"]))
    return {
        "project_id": project_id,
        "project_name": getattr(subject, "name", None) or project_id,
        "kind": kind,
        "direction": direction,
        "neighbors": neighbors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. plan_maturity_grid  ->  mesh:MaturityMatrix       (Q3)
# ─────────────────────────────────────────────────────────────────────────────

def plan_maturity_grid(
    state: PlanState, *, as_of: Optional[str] = None
) -> list[dict[str, Any]]:
    """Capability × site: the LATEST assessment at or before `as_of`, versus target.

    Assessments are append-only, so "current" is always a query and never a stored field —
    which is exactly what makes `as_of` answerable at all. A cell with no assessment on or
    before the date is absent, not zero: "never assessed" and "assessed at level 0" are
    different facts and the grid must not merge them.
    """
    cutoff = as_of or "9999-12-31"
    rows: list[dict[str, Any]] = []
    cells = {(a.capability_id, a.site_id) for a in state.assessments}
    for cap_id, site_id in sorted(cells):
        history = sorted(
            (a for a in state.assessments
             if a.capability_id == cap_id and a.site_id == site_id and a.assessed_at <= cutoff),
            key=lambda a: a.assessed_at,
        )
        if not history:
            continue
        latest = history[-1]
        rows.append({
            "capability_id": cap_id,
            "site_id": site_id,
            "level": latest.level,
            "target_level": latest.target_level,
            "gap": latest.target_level - latest.level,
            "assessed_at": latest.assessed_at,
            "assessed_by": latest.assessed_by,
            "evidence_ref": latest.evidence_ref,
            "assessment_count": len(history),
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 6. plan_capability_path  ->  mesh:ContributionSequence    (Q7)
# ─────────────────────────────────────────────────────────────────────────────

def plan_capability_path(state: PlanState, *, capability_id: str) -> dict[str, Any]:
    """The projects maturing a capability, ordered by when they finish, against the
    plateaus of every process the capability enables.

    THE PLATEAU COMPARISON IS THE POINT. A list of contributing projects answers "what is
    being done"; comparing the last contribution against the enabled process's plateau dates
    answers "will it be done in time", which is the question a portfolio review is for.

    WHAT THE FLAG IS CALLED, AND WHY IT IS NOT CALLED `missed`. The honest claim this model
    can support is "contributions to this capability are STILL LANDING after that plateau's
    target date" — not "the plateau was missed." Those differ: a capability may reach the
    maturity an early plateau needs well before its last contributing project finishes. The
    model has no per-plateau maturity REQUIREMENT edge, so nothing here can know which.

    Naming the field `missed` was the first draft, and it overclaimed in exactly the way
    `decide-the-meaning-before-the-measurement` warns about — the label would have been read
    as a verdict and repeated in a room as one. `contributions_outstanding` says only what is
    computed. A per-plateau maturity requirement is a MODEL EXTENSION and belongs in the
    miss-log as a Phase-7 candidate, not in a rename here.
    """
    cap = state.capability(capability_id)
    if cap is None:
        raise NotInModel(f"unknown capability {capability_id!r}")

    contribs = [c for c in state.contributions if c.capability_id == capability_id]
    projects = []
    for c in contribs:
        proj = state.project(c.project_id)
        if proj is None:
            continue
        init = state.initiative_of_project(c.project_id)
        projects.append({
            "project_id": proj.project_id,
            "project_name": proj.name,
            "initiative_id": init.initiative_id if init else None,
            "weight": c.weight,
            "planned_start": proj.planned.start,
            "planned_end": proj.planned.end,
        })
    projects.sort(key=lambda r: (r["planned_end"], r["project_id"]))
    last_end = projects[-1]["planned_end"] if projects else None

    plateaus: list[dict[str, Any]] = []
    for proc in state.processes:
        if proc.process_id not in cap.enables_process_ids:
            continue
        for pl in proc.plateaus:
            outstanding = last_end is not None and last_end > pl.target_date
            plateaus.append({
                "process_id": proc.process_id,
                "process_name": proc.name,
                "plateau_id": pl.plateau_id,
                "plateau_name": pl.name,
                "target_date": pl.target_date,
                # NOT `missed` — see the docstring. This says work is still landing after
                # the target date, which is all the model can support.
                "contributions_outstanding": outstanding,
                "outstanding_days": _days_between(pl.target_date, last_end) if outstanding else None,
            })

    return {
        "capability_id": capability_id,
        "capability_name": cap.name,
        "projects": projects,
        "last_contribution_end": last_end,
        "plateaus": plateaus,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. plan_process_evolution  ->  mesh:PlateauTimeline   (Q1, Q2)
# ─────────────────────────────────────────────────────────────────────────────

def plan_process_evolution(state: PlanState, *, process_id: str) -> dict[str, Any]:
    """A process's plateaus on a timeline, with the capabilities that enable it and each
    capability's current maturity trajectory."""
    proc = next((p for p in state.processes if p.process_id == process_id), None)
    if proc is None:
        raise NotInModel(f"unknown process {process_id!r}")

    enabling = [c for c in state.capabilities if process_id in c.enables_process_ids]
    caps: list[dict[str, Any]] = []
    for cap in enabling:
        history = sorted(
            (a for a in state.assessments if a.capability_id == cap.capability_id),
            key=lambda a: a.assessed_at,
        )
        by_site: dict[str, list[dict[str, Any]]] = {}
        for a in history:
            by_site.setdefault(a.site_id, []).append(
                {"assessed_at": a.assessed_at, "level": a.level, "target_level": a.target_level}
            )
        caps.append({
            "capability_id": cap.capability_id,
            "capability_name": cap.name,
            "trajectory_by_site": by_site,
            "contributing_projects": sorted(
                c.project_id for c in state.contributions if c.capability_id == cap.capability_id
            ),
        })

    return {
        "process_id": proc.process_id,
        "process_name": proc.name,
        "plateaus": [
            {"plateau_id": pl.plateau_id, "name": pl.name, "target_date": pl.target_date}
            for pl in proc.plateaus
        ],
        "enabling_capabilities": caps,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. plan_tech_footprint  ->  mesh:FootprintSet        (Q8)
# ─────────────────────────────────────────────────────────────────────────────

def plan_tech_footprint(state: PlanState, *, tech_id: str) -> dict[str, Any]:
    """For a technology: the capabilities it enables and the projects it participates in,
    with those projects' windows."""
    tech = next((t for t in state.technologies if t.tech_id == tech_id), None)
    if tech is None:
        raise NotInModel(f"unknown technology {tech_id!r}")

    cap_ids = [tc.capability_id for tc in state.tech_capabilities if tc.tech_id == tech_id]
    proj_ids = [tp.project_id for tp in state.tech_projects if tp.tech_id == tech_id]

    projects = []
    for pid in sorted(proj_ids):
        proj = state.project(pid)
        if proj is None:
            continue
        init = state.initiative_of_project(pid)
        projects.append({
            "project_id": pid, "project_name": proj.name,
            "initiative_id": init.initiative_id if init else None,
            "planned_start": proj.planned.start, "planned_end": proj.planned.end,
        })

    return {
        "tech_id": tech_id,
        "tech_name": tech.name,
        "capabilities": [
            {"capability_id": c, "capability_name": (state.capability(c).name if state.capability(c) else None)}
            for c in sorted(cap_ids)
        ],
        "projects": projects,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. plan_schedule  ->  mesh:IntervalSchedule          (Q4, Q5, Q6)
# ─────────────────────────────────────────────────────────────────────────────

_GROUP_BY = ("initiative", "capability", "target")
_COLOR_BY = ("funding_risk", "status", "confidence")


def plan_schedule(
    state: PlanState,
    *,
    scope_initiative_id: Optional[str] = None,
    site_id: Optional[str] = None,
    group_by: str = "initiative",
    color_by: Optional[str] = None,
    touched_project_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Initiative → phase → project rows with intervals. The timeline's data.

    Flat rows carrying their parentage rather than a nested tree: the renderer groups, and a
    flat row set diffs cleanly against another state, which a tree does not.

    REV 3 -- `group_by` IS THE MARQUEE PIVOT AND IT IS ONE PARAMETER. Grouping by capability
    reads `CapabilityContribution`, the project-capability many-to-many that has existed
    since Phase 0; initiative-capability is derived from it rather than stored in parallel.
    A project contributing to two capabilities APPEARS UNDER BOTH -- that is what
    many-to-many means, and it is the thing the source model could not express. A project
    contributing to nothing lands in an explicit `(none)` bucket rather than being dropped:
    a pivot that silently drops rows makes the timeline lie about what the portfolio holds.

    `color_by` names a STYLING KEY and the value rides the payload. The renderer receives a
    flag; it never learns that today's flag means funding risk (GENERIC-AT-BIRTH).
    """
    if scope_initiative_id is not None and not any(
        i.initiative_id == scope_initiative_id for i in state.initiatives
    ):
        raise NotInModel(f"unknown initiative {scope_initiative_id!r}")
    if site_id is not None and state.site(site_id) is None:
        raise NotInModel(f"unknown site {site_id!r}")
    if group_by not in _GROUP_BY:
        # REFUSED, never a silent fallback to the default. Falling back would answer a
        # different question than the one asked, and look correct doing it.
        raise NotInModel(f"cannot group a schedule by {group_by!r}")
    if color_by is not None and color_by not in _COLOR_BY:
        raise NotInModel(f"cannot colour by {color_by!r}")

    site_projects = (
        {i.project_id for i in state.site_impacts if i.site_id == site_id}
        if site_id is not None else None
    )

    # Computed ONCE, not per row. plan_dependency_violations walks every dependency; calling it
    # inside the loop would make a schedule render quadratic in the plan's size.
    _violating = {
        v["successor_id"] for v in plan_dependency_violations(state)
        if not v.get("unresolvable") and v.get("successor_id")
    }

    rows: list[dict[str, Any]] = []
    for init in state.initiatives:
        if scope_initiative_id is not None and init.initiative_id != scope_initiative_id:
            continue
        phases = sorted(
            (p for p in state.phases if p.initiative_id == init.initiative_id),
            key=lambda p: p.sequence_order,
        )
        for ph in phases:
            projects = sorted(
                (p for p in state.projects if p.phase_id == ph.phase_id),
                key=lambda p: (p.planned.start, p.project_id),
            )
            for proj in projects:
                if site_projects is not None and proj.project_id not in site_projects:
                    continue
                base_row = {
                    "initiative_id": init.initiative_id,
                    "initiative_name": init.name,
                    "initiative_status": init.status,
                    "phase_id": ph.phase_id,
                    "phase_name": ph.name,
                    "phase_sequence": ph.sequence_order,
                    "phase_start": ph.planned.start,
                    "phase_end": ph.planned.end,
                    "project_id": proj.project_id,
                    "project_name": proj.name,
                    "planned_start": proj.planned.start,
                    "planned_end": proj.planned.end,
                    "actual_start": proj.actual.start if proj.actual else None,
                    "actual_end": proj.actual.end if proj.actual else None,
                    "risk_flag": _risk_flag(state, proj.project_id, color_by,
                                                     touched_project_ids, _violating),
                }
                rows.extend(_pivot(state, proj.project_id, base_row, group_by, init))
    return rows


def _risk_flag(
    state: PlanState,
    project_id: str,
    color_by: Optional[str],
    touched: Optional[set[str]] = None,
    violating: Optional[set[str]] = None,
) -> Optional[str]:
    """A generic styling flag. The VALUE is domain vocabulary and rides the payload; the
    renderer styles whatever string arrives and knows none of them.

    VOCABULARY, NOT NEW FIELDS. The 2026-08-24 declarations add two values to this one key
    rather than a parallel `violation` field, because a second field would duplicate a seam
    that is already generic by design.

    LOWERCASE-HYPHENATED, conforming to the incumbent vocabulary (`at-risk`, `unfunded`).
    Nothing breaks either way — the renderer styles an unknown string and stops — but the
    styling map that eventually keys these will be written against ONE convention, and two
    conventions in one field means it silently misses half its vocabulary.

    PRECEDENCE IS A CHOICE, not a discovery: a broken constraint OUTRANKS a moved bar, because
    a constraint breach is the STATE and the move is the CAUSE, and a status flag reports
    state. The opposite reading is defensible — "the room moved it, show them their
    fingerprint" — but that is the DIFF CARD's job. The diff attributes causes; the bar reports
    conditions.
    """
    if violating and project_id in violating:
        return "constraint-violated"
    if touched and project_id in touched:
        return "moved"
    if color_by is None:
        return None
    if color_by == "funding_risk":
        req = sum(r.amount for r in state.requirements if r.project_id == project_id)
        secured = sum(k.amount for k in state.commitments
                      if k.project_id == project_id and k.status in ("committed", "approved"))
        if req > 0 and secured < req:
            return "at-risk" if secured > 0 else "unfunded"
        return None
    if color_by == "status":
        init = state.initiative_of_project(project_id)
        return init.status if init else None
    if color_by == "confidence":
        proj = state.project(project_id)
        ph = state.phase(proj.phase_id) if proj else None
        return ph.timing_confidence if ph else None
    return None  # pragma: no cover - guarded at the entry


def _pivot(state: PlanState, project_id: str, base: dict[str, Any],
           group_by: str, init: Any) -> list[dict[str, Any]]:
    """One project becomes N rows under a many-to-many pivot. That fan-out IS the feature."""
    if group_by == "initiative":
        return [{**base, "group_kind": "initiative", "group_id": init.initiative_id,
                 "group_name": init.name, "group_weight": None}]
    if group_by == "capability":
        contribs = [c for c in state.contributions if c.project_id == project_id]
        if not contribs:
            # EXPLICIT, not dropped. A pivot that silently loses rows makes the timeline lie
            # about what the portfolio contains.
            return [{**base, "group_kind": "capability", "group_id": "(none)",
                     "group_name": "no capability recorded", "group_weight": None}]
        out = []
        for c in sorted(contribs, key=lambda x: x.capability_id):
            cap = state.capability(c.capability_id)
            out.append({**base, "group_kind": "capability", "group_id": c.capability_id,
                        "group_name": cap.name if cap else c.capability_id,
                        "group_weight": c.weight})
        return out
    impacts = [i for i in state.site_impacts if i.project_id == project_id]
    if not impacts:
        return [{**base, "group_kind": "target", "group_id": "(none)",
                 "group_name": "no target recorded", "group_weight": None}]
    out = []
    for i in sorted(impacts, key=lambda x: x.site_id):
        site = state.site(i.site_id)
        out.append({**base, "group_kind": "target", "group_id": i.site_id,
                    "group_name": site.name if site else i.site_id,
                    "group_weight": i.load_weight})
    return out


# -----------------------------------------------------------------------------
# 12. plan_coverage_gap  ->  mesh:CoverageGapSet          (B4)
# -----------------------------------------------------------------------------

def plan_coverage_gap(state: PlanState) -> dict[str, Any]:
    """What NOTHING is working on -- an absence query.

    THE ONLY GENUINELY NEW VERB IN REVISION 3, and the one a spreadsheet cannot answer: a row
    that is not there cannot be filtered for. Finding it needs the capability-process edge and
    the project-capability edge together, which is exactly what the graph shape buys.

    TWO FINDINGS, KEPT SEPARATE because they send you to different meetings:
      uncovered_capabilities  a capability nobody is maturing  -> a PORTFOLIO problem
      unmodelled_processes    a process with no capability     -> a MODEL problem
    Folding them would send someone to the wrong one.
    """
    contributed = {c.capability_id for c in state.contributions}
    uncovered = []
    for cap in state.capabilities:
        if cap.capability_id in contributed:
            continue
        uncovered.append({
            "capability_id": cap.capability_id,
            "capability_name": cap.name,
            # A capability nobody is maturing only MATTERS because a process depends on it.
            # Reporting the capability alone makes the reader do a join the model already holds.
            "exposes_processes": sorted(cap.enables_process_ids),
        })

    enabled = {pid for c in state.capabilities for pid in c.enables_process_ids}
    unmodelled = [
        {"process_id": p.process_id, "process_name": p.name}
        for p in state.processes if p.process_id not in enabled
    ]

    return {
        # Empty LISTS, never omitted keys. A missing key reads as "not computed"; an empty list
        # reads as "computed, and clean".
        "uncovered_capabilities": sorted(uncovered, key=lambda c: c["capability_id"]),
        "unmodelled_processes": sorted(unmodelled, key=lambda p: p["process_id"]),
        "capability_count": len(state.capabilities),
        "covered_count": len(contributed),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 10. plan_session_changes  ->  mesh:ChangeLog          (INV-4)
# ─────────────────────────────────────────────────────────────────────────────

def plan_session_changes(
    state: PlanState,
    *,
    ops: list[Any],
    scenario_name: Optional[str] = None,
) -> dict[str, Any]:
    """The ops accumulated this session, rendered as a change log.

    Takes ops rather than reading a store, so it stays pure and so a decision artifact can
    be built from a recorded op list long after the session that produced it — which is
    what makes INV-4's "why did we move this?" answerable later rather than only live.
    """
    entries = []
    for i, op in enumerate(ops):
        kind = getattr(op, "op", "unknown")
        entry: dict[str, Any] = {"sequence": i + 1, "op": kind}
        for f in ("project_id", "site_id", "org_id", "period", "kind", "amount"):
            if hasattr(op, f):
                entry[f] = getattr(op, f)
        for f in ("new_planned", "new_window"):
            iv = getattr(op, f, None)
            if isinstance(iv, Interval):
                entry[f] = {"start": iv.start, "end": iv.end}
        entries.append(entry)
    return {
        "scenario_name": scenario_name,
        "change_count": len(entries),
        "changes": entries,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. plan_diff  ->  mesh:EffectSet                     (INV-3)
# ─────────────────────────────────────────────────────────────────────────────
#
# ADR-0042 OQ2, resolved: ONE VERB OVER TWO STATE REFS. Expressible only because Seam 1 made
# scenarios server-addressable and `apply_ops` never mutates its input — a mutating apply
# could not be asked about two worlds at once.
#
# NO LLM TOUCHES A NUMBER HERE. Every magnitude is computed and formatted from computed
# values. The plan's highest-severity correctness risk is "diff magnitudes wrong in the room";
# this function and its tests are the whole of the mitigation.

def _fmt_money(n: float) -> str:
    a = abs(n)
    if a >= 1_000_000:
        return f"${a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"${a / 1_000:.0f}K"
    return f"${a:.0f}"


# Below these, a change is NOISE and is suppressed. A card listing a $50 move beside a $1M
# move has made both unreadable.
#
# NOTE THE ABSENCES, which are deliberate: `plan_dependency_violations` has no floor because
# violations are COUNTED, not measured — "you broke a dependency" has no small version, and a
# floor that hid it would hide the thing most worth seeing. `plan_site_load` uses a threshold
# CROSSING rather than a magnitude for the same reason.
_MATERIALITY = {
    "plan_cost_curve": 10_000.0,   # $10K — below a rounding error at portfolio scale
    "plan_funding_gap": 10_000.0,
}


def plan_diff(state: PlanState, *, baseline_state: PlanState) -> dict[str, Any]:
    """Effects of `state` versus `baseline_state`, in leader language, computed not generated.

    DIRECTION IS A JUDGEMENT AND THE MEASURE OWNS IT. Cost down is improved; load up is
    degraded; a violation appearing is degraded regardless of size. A diff that reported raw
    deltas without direction would hand the interpretation back to the room, which is the work
    the tool exists to remove.
    """
    effects: list[dict[str, Any]] = []

    # ── cost: per-period totals ──
    base_cost = {r["period"]: r["total"] for r in plan_cost_curve(baseline_state)}
    new_cost = {r["period"]: r["total"] for r in plan_cost_curve(state)}
    moved = {p: new_cost.get(p, 0.0) - base_cost.get(p, 0.0)
             for p in set(base_cost) | set(new_cost)}
    material = {p: d for p, d in moved.items() if abs(d) >= _MATERIALITY["plan_cost_curve"]}
    if material:
        total = sum(material.values())
        periods = sorted(material)
        effects.append({
            "metric": "plan_cost_curve",
            "direction": "improved" if total < 0 else "degraded" if total > 0 else "neutral",
            "delta": total,
            "magnitude": f"{'-' if total < 0 else '+'}{_fmt_money(total)} in {', '.join(periods)}",
            "affected": periods,
        })

    # ── funding gap ──
    def _gap_total(s: PlanState) -> float:
        return sum(max(0.0, r["gap"]) for r in plan_funding_gap(s, group_by="org"))
    gap_delta = _gap_total(state) - _gap_total(baseline_state)
    if abs(gap_delta) >= _MATERIALITY["plan_funding_gap"]:
        effects.append({
            "metric": "plan_funding_gap",
            "direction": "improved" if gap_delta < 0 else "degraded",
            "delta": gap_delta,
            "magnitude": f"{'-' if gap_delta < 0 else '+'}{_fmt_money(gap_delta)} unfunded",
            "affected": ["portfolio"],
        })

    # ── site load: THRESHOLD CROSSINGS, not magnitudes ──
    # A load rising within tolerance is not news; a cell crossing its line is. Reporting the
    # crossing rather than the delta is what keeps this effect actionable.
    def _breached(s: PlanState) -> set[tuple[str, str]]:
        return {(r["site_id"], r["period"]) for r in plan_site_load(s) if r["over_threshold"]}
    was, now = _breached(baseline_state), _breached(state)
    newly, cleared = sorted(now - was), sorted(was - now)
    if newly:
        effects.append({
            "metric": "plan_site_load",
            "direction": "degraded",
            "delta": len(newly),
            "magnitude": f"{len(newly)} cell(s) newly over threshold",
            "affected": [f"{s}/{p}" for s, p in newly],
        })
    if cleared:
        effects.append({
            "metric": "plan_site_load",
            "direction": "improved",
            "delta": -len(cleared),
            "magnitude": f"{len(cleared)} cell(s) back under threshold",
            "affected": [f"{s}/{p}" for s, p in cleared],
        })

    # ── dependency violations: COUNTED, never floored ──
    base_v = {v["dependency_id"] for v in plan_dependency_violations(baseline_state)}
    new_v = {v["dependency_id"] for v in plan_dependency_violations(state)}
    broke, fixed = sorted(new_v - base_v), sorted(base_v - new_v)
    if broke:
        effects.append({
            "metric": "plan_dependency_violations",
            "direction": "degraded",
            "delta": len(broke),
            "magnitude": f"{len(broke)} dependency violated ({', '.join(broke)})",
            "affected": broke,
        })
    if fixed:
        effects.append({
            "metric": "plan_dependency_violations",
            "direction": "improved",
            "delta": -len(fixed),
            "magnitude": f"{len(fixed)} dependency resolved ({', '.join(fixed)})",
            "affected": fixed,
        })

    return {
        "effects": effects,
        "improved": sum(1 for e in effects if e["direction"] == "improved"),
        "degraded": sum(1 for e in effects if e["direction"] == "degraded"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 14. plan_commit_scenario  ->  mesh:DecisionArtifact       (Beat 6)
# ─────────────────────────────────────────────────────────────────────────────
#
# THE DEGENERATE SINGLE-APPROVER CASE of the review flow. A DecisionArtifact is structurally
# a DISPOSITION RECORD with a planning payload: ops are the disposed items, the rationale is
# the override-reason, the alternatives are the considered-set. `requested_by` and `acted_by`
# are the same person, which is exactly what "degenerate" means — Phase 7 adds AUDIENCES to a
# flow that already names one rather than translating a lookalike into the real thing.
#
# WHY THE MUTATION IS NOT HERE. `PlanStore.commit` applies the ops and archives, and its own
# docstring says the ceremony's gate "lives at the route, not here, because this class must
# stay a store". These two functions are pure so the artifact's SHAPE and the rationale GATE
# are testable with neither a store nor a route in the loop.


def check_rationale(rationale: Optional[str]) -> None:
    """RAISE unless a real reason was given. Called BEFORE the commit, always.

    WHITESPACE IS NOT A REASON. `"   "` satisfies `if rationale:` and says nothing, and it is
    the exact shape that defeats a naive gate — so the check is on the STRIPPED value.

    ORDERING IS THE POINT. A ceremony that refused AFTER applying ops would move the plan by a
    decision the system declined to record: no artifact, no actor, no reason, and a changed
    baseline. That is worse than having no gate at all, because the change would be
    unattributable rather than merely ungoverned.
    """
    if rationale is None or not str(rationale).strip():
        raise NotInModel(
            "a commit requires a rationale — the decision record has nowhere to put the "
            "reason, and a decision with no reason is not reviewable"
        )


def plan_commit_scenario(
    *,
    scenario_id: str,
    scenario_name: str,
    rationale: str,
    actor: str,
    ops: list[Any],
    baseline_version: int,
    audience: str = "PORTFOLIO_LEAD",
    alternatives: Optional[list[dict[str, Any]]] = None,
    question_trail: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build the DecisionArtifact for a commit. PURE — the store has already moved.

    The `decision` block carries the disposition family's vocabulary verbatim, because
    DECISION_RECORD's contract composes those fields BY REFERENCE and an artifact missing one
    refuses at the card rather than rendering wrong.
    """
    check_rationale(rationale)
    if not ops:
        raise NotInModel(
            f"scenario {scenario_id!r} has no ops — a decision that disposed nothing is not "
            f"a decision"
        )

    return {
        "decision": {
            # Identity + routing. `subject_ref` names WHAT was decided about, which is the
            # scenario — the artifact is about a fork, not about a project.
            "task_id": f"commit:{scenario_id}",
            "kind": "portfolio_commit",
            "task_state": "approved",
            "audience": audience,
            "requested_by": actor,
            "subject_ref": scenario_id,
            # The act. `acted_at` is a FACT and is written exactly once — DECISION_RECORD does
            # not recompute, so there is no later evaluation to restamp it.
            "acted_by": actor,
            "acted_at": _now_iso(),
            "decision": "approved",
            # `comment` IS the rationale. The disposition family's override-reason field, and
            # the one DECISION_RECORD blocks on when empty.
            "comment": rationale.strip(),
        },
        "ops": [_op_row(o) for o in ops],
        # EMPTY, never absent. "No alternatives were considered" is a real statement about a
        # decision and must render differently from "this card was not told."
        "alternatives": list(alternatives or []),
        "question_trail": list(question_trail or []),
        "scope_label": scenario_name,
        "committed_baseline_version": baseline_version,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _op_row(op: Any) -> dict[str, Any]:
    """One op as a plain row. Dataclasses are frozen, so `__dict__` is safe to copy."""
    if isinstance(op, dict):
        return dict(op)
    return {k: v for k, v in vars(op).items()}


# ─────────────────────────────────────────────────────────────────────────────
# The reschedule POLICY — a drag is two ops, and this is their one home.
# ─────────────────────────────────────────────────────────────────────────────
#
# `MoveProject` stays innocent: it sets proj.planned and never touches impact windows,
# because a rollout's DISRUPTIVE PHASE is deliberately narrower than the rollout (P12 runs
# Apr-Sep; its Site B impact is a Jul-Sep subset). Fusing them would delete the distinction
# that makes site load a different measure from schedule.
#
# So the ops stay SEPARATE and this policy CO-EMITS them. It lives server-side because that is
# where the state is: site impacts do not exist in cortex-ui at all, so no client can compute
# an offset for data it does not have.


def derive_reschedule(
    state: PlanState, *, project_id: str, new_planned: Interval
) -> list[Any]:
    """The ops a reschedule really is: move the project, then move its disruption with it.

    OFFSET-PRESERVED. Each impact shifts by the SAME DELTA as the project, keeping its
    position RELATIVE to the rollout intact — a window three months into a six-month project
    stays three months in. Clamping or recomputing would silently re-author the model's
    semantics; shifting preserves them.

    Returns ORDINARY ops in order, so the store learns no new shape and the scenario log reads
    as what happened: the schedule move first, its consequences after.
    """
    from datetime import date, timedelta

    proj = state.project(project_id)
    if proj is None:
        raise NotInModel(f"no project {project_id!r} in the plan")
    if not new_planned.is_well_formed():
        # REFUSE FIRST. Returning ops for an impossible move would push the failure into
        # apply_ops, after the caller had already been told the reschedule was valid.
        raise NotInModel(
            f"reschedule of {project_id}: interval {new_planned.start}..{new_planned.end} "
            f"is inverted"
        )

    delta = date.fromisoformat(new_planned.start) - date.fromisoformat(proj.planned.start)

    ops: list[Any] = [MoveProject(project_id=project_id, new_planned=new_planned)]
    for impact in state.site_impacts:
        if impact.project_id != project_id:
            continue
        shifted = Interval(
            (date.fromisoformat(impact.window.start) + delta).isoformat(),
            (date.fromisoformat(impact.window.end) + delta).isoformat(),
        )
        # ONE OP PER IMPACT. A project loading three sites produces three ops, never a single
        # fused "move everything" — each is separately reviewable and separately undoable.
        ops.append(MoveSiteImpact(
            project_id=project_id, site_id=impact.site_id, new_window=shifted,
        ))
    return ops
