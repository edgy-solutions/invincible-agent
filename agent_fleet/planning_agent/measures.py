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

from .types import FISCAL_PERIODS, PERIOD_ORDER, FiscalPeriod, Interval, PlanState

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
    """
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
                if required == 0 and committed == 0:
                    continue  # deliberate-absent: a group with no activity is not a zero row
                rows.append({
                    "group_by": "initiative", "initiative_id": gid, "period": period,
                    "required": required, "committed": committed,
                    "gap": required - committed,
                })
            continue

        # group_by == "org"
        org_of_project: dict[str, set[str]] = {}
        for k in commits:
            org_of_project.setdefault(k.project_id, set()).add(k.org_id)

        by_org: dict[str, dict[str, float]] = {}
        for r in reqs:
            owners = org_of_project.get(r.project_id) or {"(uncommitted)"}
            # Split evenly when several orgs co-fund a project — the honest apportionment
            # absent a per-requirement funder, and it keeps the column totals correct.
            share = r.amount / len(owners)
            for oid in owners:
                by_org.setdefault(oid, {"required": 0.0, "committed": 0.0})["required"] += share
        for k in commits:
            by_org.setdefault(k.org_id, {"required": 0.0, "committed": 0.0})["committed"] += k.amount

        for oid in sorted(by_org):
            v = by_org[oid]
            rows.append({
                "group_by": "org", "org_id": oid, "period": period,
                "required": v["required"], "committed": v["committed"],
                "gap": v["required"] - v["committed"],
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
        pred = state.interval_of(d.predecessor_kind, d.predecessor_id)
        succ = state.interval_of(d.successor_kind, d.successor_id)
        if pred is None or succ is None:
            # A dangling dependency is a MODEL defect, surfaced as its own row rather than
            # skipped — a constraint nobody can evaluate must not read as a constraint met.
            out.append({
                "dependency_id": d.dependency_id, "dep_type": d.dep_type,
                "unresolvable": True,
                "reason": f"{d.predecessor_id} or {d.successor_id} has no planned interval",
            })
            continue

        pred_anchor, succ_anchor = _DEP_RULES[d.dep_type]
        pred_date = pred.end if pred_anchor == "end" else pred.start
        succ_date = succ.end if succ_anchor == "end" else succ.start
        earliest = _add_days(pred_date, d.lag_days)
        if succ_date >= earliest:
            continue
        out.append({
            "dependency_id": d.dependency_id,
            "dep_type": d.dep_type,
            "lag_days": d.lag_days,
            "predecessor_id": d.predecessor_id,
            "successor_id": d.successor_id,
            "required_earliest_start": earliest,
            "actual_start": succ_date,
            "shortfall_days": _days_between(succ_date, earliest),
            "unresolvable": False,
        })
    return out


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

def plan_schedule(
    state: PlanState,
    *,
    scope_initiative_id: Optional[str] = None,
    site_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Initiative → phase → project rows with intervals. The timeline's data.

    Flat rows carrying their parentage rather than a nested tree: the renderer groups, and a
    flat row set diffs cleanly against another state, which a tree does not.
    """
    if scope_initiative_id is not None and not any(
        i.initiative_id == scope_initiative_id for i in state.initiatives
    ):
        raise NotInModel(f"unknown initiative {scope_initiative_id!r}")
    if site_id is not None and state.site(site_id) is None:
        raise NotInModel(f"unknown site {site_id!r}")

    site_projects = (
        {i.project_id for i in state.site_impacts if i.site_id == site_id}
        if site_id is not None else None
    )

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
                rows.append({
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
                })
    return rows


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
