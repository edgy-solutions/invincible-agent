---
id:         unbound-output-types-triage
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/planning_agent/measures.py, ../cortex-ui/src/components/planning
repo:       cortex-ui
summary:    PHASE C, 2026-08-24. Seven Engine P output types have no archetype binding. Each ruled by READING ITS PAYLOAD and applying the semantic-axis test — what does the colour or position MEAN to a reader — rather than by matching row shapes. THREE bind to existing archetypes (DependencyNeighborhoodSet and ConstraintViolationSet to INSTANCES_BY_PROPERTY, each needing a payload reshape to columns/rows/state-vocabulary), TWO need their own component (ContributionSequence and PlateauTimeline, both because they carry MILESTONE markers no existing contract expresses), and TWO are structured documents (FootprintSet, ChangeLog). CoverageGapSet is the honest list-not-grid. This is the morning's build list, pre-reasoned; nothing here is built.
---

# Seven unbound output types — one ruling each

**The instrument.** Tonight's `SHORTFALL_GRID` decision established it: three grids can be
*structurally* interchangeable — cells against a line — and *semantically* disjoint on what
colour means (breach→danger, distance→progress, deficit→risk). So each type below is ruled by
asking **what does the colour or position mean to a reader**, never by matching row shapes.

**All seven payloads were read**, not assumed. Samples are from the live seed.

---

## 1. `ContributionSequence` (`plan_capability_path`) — **needs own component**

```
{capability_id, capability_name,
 projects[{project_id, weight, planned_start, planned_end}],
 last_contribution_end,
 plateaus[{plateau_id, target_date, contributions_outstanding}]}
```

Position means **time**, and the reader's question is *"does the work land before the target?"*
— which is `INTERVAL_TIMELINE`'s axis. But the answer lives in the **plateau markers**, and
`INTERVAL_TIMELINE`'s contract has no milestone concept: its rows are group→phase→project
intervals, full stop. Binding would drop `target_date` and `contributions_outstanding`, which
*is* the question. `weight` has no home either.

**Not a reshape — a missing field family.** Milestones are free-tier in the timeline library
(`type: "milestone"`), so the component is cheap; the contract is what does not exist.

## 2. `PlateauTimeline` (`plan_process_evolution`) — **needs own component**

```
{process_id, process_name,
 plateaus[{plateau_id, name, target_date}],
 enabling_capabilities[{capability_id, trajectory_by_site: {S2: [{assessed_at, level, target_level}]}}]}
```

**Nested trajectories**: per capability, per site, a time-series of level-versus-target. The
reading is *"are these abilities rising fast enough to hit those dates?"* — multi-series lines
against milestone verticals. `MATRIX_GRID` holds level-vs-target but as ONE CELL, not a
trajectory; collapsing the series to its latest point deletes the slope, which is the entire
question. `PERIOD_SERIES` is one series against a threshold, not N series against dates.

**The richest payload in the set and the least served by anything existing.**

## 3. `FootprintSet` (`plan_tech_footprint`) — **structured document with contract**

```
{tech_id, tech_name, capabilities[{id, name}], projects[{id, name, initiative_id, planned_*}]}
```

Two flat lists hanging off one subject. **No axis, no verdict, no colour semantics** — nothing
is over, under, near, or trending. The reading is *"what does this component touch?"*, which is
a document with two sections. Forcing an axis on it would invent a comparison the payload does
not make.

## 4. `CoverageGapSet` (`plan_coverage_gap`) — **structured document with contract**

```
{uncovered_capabilities[{id, name, exposes_processes[]}], unmodelled_processes[],
 capability_count: 9, covered_count: 8}
```

**The honest list-not-grid.** An absence has no position: there is no axis on which "nobody is
working on this" sits. What it has is a **list plus a denominator** — 8 of 9 — and the
denominator is what makes the absence legible rather than alarming. A contract should require
the count pair, because a gap list without its whole is a number without a scale.

## 5. `DependencyNeighborhoodSet` — **binds to `INSTANCES_BY_PROPERTY`** (reshape needed)

```
{project_id, project_name, kind, direction,
 neighbors[{dependency_id, id, name, dep_type, lag_days, planned_start, planned_end, status}]}
```

Reads as graph-shaped and **is not**: the payload is a flat list of neighbours, each carrying a
**state from a closed vocabulary** (`satisfied | violated | unresolvable`). That is
`INSTANCES_BY_PROPERTY`'s exact contract — *"the payload carries the columns, rows, row identity
and state vocabulary, and the renderer knows none of them."*

**Reshape, not a new type**: emit `columns`, `rows`, `row_identity`, `state_vocabulary`. The
`direction` field becomes the scope label, which is the honest place for it — *upstream* and
*downstream* are two questions, and the card should say which it answered.

## 6. `ConstraintViolationSet` — **binds to `INSTANCES_BY_PROPERTY`** (reshape needed)

```
[{dependency_id, dep_type, lag_days, predecessor_id, successor_id,
  required_earliest_start, actual_start, shortfall_days, unresolvable}]
```

Same shape and the same instrument: rows with identity, a magnitude (`shortfall_days`) and a
state (`violated | unresolvable`). Its state vocabulary is smaller than #5's but the same kind.

**Note the empty case is load-bearing** and differs from #5's: an empty violation set is
GOOD NEWS at baseline, and a card must render it as such rather than as no-data. That belongs in
the reshape's contract, not in the renderer.

## 7. `ChangeLog` (`plan_session_changes`) — **structured document with contract**

```
{scenario_name, change_count, changes[{sequence, op, project_id, period, kind, amount}]}
```

An **ordered op log**. Position means sequence, not time — bar 3 is not later than bar 2 by
duration, it is later by decision. No verdict, no comparison, no threshold. A document with a
numbered list, and `sequence` is the only ordering a renderer may use.

---

## Summary — the morning's build list

| output type | ruling | cost |
|---|---|---|
| `DependencyNeighborhoodSet` | binds → `INSTANCES_BY_PROPERTY` | producer reshape only |
| `ConstraintViolationSet` | binds → `INSTANCES_BY_PROPERTY` | producer reshape only |
| `FootprintSet` | structured document + contract | contract + simple component |
| `CoverageGapSet` | structured document + contract | contract + simple component |
| `ChangeLog` | structured document + contract | contract + simple component |
| `ContributionSequence` | **needs own component** | contract + milestone-capable timeline |
| `PlateauTimeline` | **needs own component** | contract + multi-series trajectory |

**Cheapest first, and it is also the demo-relevant order**: the two reshapes bind with no new
frontend at all. The three documents share one shape and could plausibly share one component
with three contracts — worth checking before building three.

**The two expensive ones are the two the mockup leans on hardest**, which is not a coincidence:
milestones and trajectories are what makes a plan look like a plan rather than a table.
