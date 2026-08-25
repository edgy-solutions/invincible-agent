---
id:         producer-declarations-payload-preregistration
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/planning_agent/measures.py, agent_fleet/planning_agent/main.py
repo:       invincible-agent
summary:    PRE-REGISTRATION for the three producer declarations (cortex-ui e99fd59). Payload shapes written down BEFORE emitting, one sample per changed verb, so the emitted shape can be checked against an intention rather than explained after the fact. Three items: `value_unit: "USD"` top-level on the money family (its frontend half shipped in a03a960 and reads `comp.value_unit`); a `baseline` SERIES on PeriodSeriesRow present only when a comparison is in scope (frontend half NOT built — the ghost renderer is cortex's, flagged); and `risk_flag` VALUES from plan_schedule (mechanism exists, emit vocabulary only). Two design questions are RAISED not answered: risk_flag's case convention collides with the existing lowercase values, and MOVED-vs-violated precedence needs a ruling.
---

# Three producer declarations — payload shapes, pre-registered

The checklist entry (`e99fd59`) carries the reasoning; this carries the SHAPES, written before
the code so the result is checkable against an intention. Samples below are **measured from the
current seed**, not invented — the "today" rows are real output.

## 1. `value_unit` — top-level, money family

**Consumer is shipped** (`a03a960`): `SemanticInterpreter` passes `valueUnit={comp.value_unit}`
to ChartWidget, and `ChartWidget.contract.ts` declares it optional. It is read off the
**envelope**, not off rows.

```
today   {"measure":"plan_cost_curve","output_uri":"…#PeriodCostSeries","state_ref":"baseline",
         "state_version":0,"rows":[…]}

after   {"measure":"plan_cost_curve", …, "value_unit":"USD", "rows":[…]}
```

**A DECLARATION TABLE, not a guess.** `run_measure` is generic and must not infer money-ness
from a field name — `total` is money here and a count elsewhere. So a `VALUE_UNIT` map beside
`OUTPUT_URI`, listing the two money verbs explicitly, and the route attaches it only when the
verb declares one. A verb absent from the table emits no `value_unit`, and the renderer keeps
reading `1.5M` rather than guessing `$`.

Members: `plan_cost_curve`, `plan_funding_gap`.

## 2. `baseline` series on PeriodSeriesRow — scenario-dependent

**NOT a bolt-on column.** Per the entry, this is the diff machinery reaching the period payload,
so it appears only when the card's scope includes a comparison. `plan_diff` already pairs by
period (`{r["period"]: r["total"] for r in plan_cost_curve(baseline_state)}`); this is that same
projection, reaching one row.

```
today (baseline scope)
  {"period":"FY26-Q3","capex":4200000.0,"expense":850000.0,"total":5050000.0,
   "cap":4000000.0,"over_cap":true,"overage":1050000.0}

after (baseline scope — UNCHANGED, no key added)
  {"period":"FY26-Q3", … , "overage":1050000.0}

after (scenario scope)
  {"period":"FY26-Q3", … , "overage":1050000.0,
   "baseline":{"capex":4200000.0,"expense":850000.0,"total":5050000.0}}
```

**ABSENT, not null, when there is no comparison.** A `"baseline": null` on every baseline-scope
row would tell the renderer a comparison exists and is empty. Absent says the card is not a
comparison — which is the true statement, and the one the ghost's presence keys on.

**NESTED, not three sibling columns.** The entry calls it a *series*; `baseline_total`,
`baseline_capex`, `baseline_expense` would be three fields that must be added or dropped
together, which is a shape whose invariant lives in a convention. One object cannot half-arrive.

**FRONTEND HALF IS NOT BUILT** — contrary to the entry's grouping sentence, this one's consumer
does not exist: `PeriodSeriesRow` has no baseline field and no ghost renderer is present in
`src/`. The contract update rides this lane's commit; **the ghost renderer is cortex's item**
and is flagged rather than built here.

## 3. `risk_flag` VALUES from plan_schedule — vocabulary only

The mechanism exists: `IntervalRow.risk_flag` is a generic styling key the renderer never
interprets, already threaded to the SVAR task as `$risk_flag`. **Emit values, add no field.**

```
today   {"project_id":"P1", … ,"risk_flag":null}          # null unless color_by is set

after (scenario scope, P12 moved by an op)
        {"project_id":"P12", … ,"risk_flag":"MOVED"}

after (P5's FS dependency breached)
        {"project_id":"P5",  … ,"risk_flag":"CONSTRAINT_VIOLATED"}
```

**SCENARIO CONTEXT IS AN INPUT, not something the measure can read.** `plan_schedule` receives a
`PlanState`; ops live on the `Scenario`. "Op-touched" is therefore a parameter the route
computes (`touched_project_ids`) — the same shape as item 2's `baseline_state`, and for the same
reason: a measure is a pure function of what it is handed.

### TWO QUESTIONS RAISED, NOT ANSWERED

1. **Case convention collides.** The existing `_risk_flag` vocabulary is lowercase-hyphenated
   (`at-risk`, `unfunded`); the checklist specifies `MOVED`. Both will flow through the same
   field to the same never-interpreting renderer, so nothing breaks — but a styling map keyed on
   one convention will silently miss the other. **Emitting `MOVED` as written**, and flagging
   that the four values want one convention before a badge is built against them.
2. **Precedence is undefined.** A bar can be both op-touched and constraint-breaching. One
   field, one string. **Emitting `CONSTRAINT_VIOLATED` when both apply** — a broken constraint
   outranks a moved bar — and recording it as a choice rather than a discovery, because the
   opposite is defensible (the room moved it; the violation is the consequence they are being
   shown).

## Acceptance

Each verb's emitted payload matches the "after" sample above, asserted by test, with the
baseline-scope samples asserted UNCHANGED — a declaration that alters an existing shape is a
regression wearing a feature's commit message.
