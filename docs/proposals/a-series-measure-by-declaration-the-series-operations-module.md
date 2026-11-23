---
status: proposed; decision 1 ruled yes (architect, 2026-11-23); decisions 2 and 3 open
owner: invincible-agent/lane/fin
date: 2026-11-22
directive: >-
  architect, 2026-11-22, via Chris: "The line-chart measure type that needs a new calculating
  module: write what the module would be and how it could become declarable. Proposal only."
builds-on: ADR-0053 (measure modules) section 3, the measure-by-declaration proof (#513), the
  dataset series rows (ev_series.py)
ratifies: nothing. No code, no row, no engine change ships with this page.
---

# A series measure by declaration: the series-operations module

## The question

A **flow** measure (`FLOW_DECOMPOSITION`) can now be added as one overlay row, with no engine code
(#513). A **line-chart** measure (`MULTI_SERIES`) cannot. This page says why, what module would
change that, and how its rows could be declared. It also says what it would still refuse, and
which decision belongs to the architect.

## Why a series row cannot add a measure today

A dataset series row names a function in a module, and the function decides what it computes:

- **The function takes exactly `periods`** (`_SERIES_FN_KEYWORDS = {"periods"}`,
  `measure_verbs.py:148`). Nothing from the row reaches it except the per-period values.
- **The module fixes what it reads and returns.** It must declare `READS[fn]` and `SERIES[fn]`, and
  the loader holds the row's `per_period`/`per_program` keywords and `render.series` keys to
  exactly those sets (`measure_verbs.py:689-704`).
- **The only shipped module is `ev_series.py` 1.0.0:** `cumulative` reads
  `bcws`/`bcwp`/`acwp`/`bac` and returns `pv`/`ev`/`ac`/`bac`; `eac_trend` reads `eac`/`bac` and
  returns `eac`/`bac`.

So a series row can only re-point those keywords at other columns, and the served keys would then
misname them. Cumulative cost variance, cumulative schedule variance, or the period's actual cost
alone are each a new module today.

The flow row escaped this because its one variable part is small and closed: `value` is one column
or exactly `{minus: [a, b]}` (`measure_verbs.py:245-246`, validated at `:329-338`). A row selects
which columns and whether to subtract. This proposal gives series rows the same kind of closed
choice.

## The module: `measure_modules/series_ops.py`

A pure, standard-library-only, Decimal module, like `ev_series.py`. It has a `VERSION` and one
function, `compose(*, periods, spec)`. It also declares the closed set of operations it performs:

| op | operands | per period *t* | dimension |
|---|---|---|---|
| `period` | one `per_period` keyword | the period's amount as read | the column's |
| `running` | one `per_period` keyword | the sum of the amounts from the first period held through *t* | the column's |
| `constant` | one `per_program` keyword | the program's value, the same at every *t* | the column's |
| `minus` | two leaf ops | the first less the second | both must share it |
| `ratio` | two leaf ops | the first divided by the second | none (an index) |

A **leaf op** is `period`, `running` or `constant`. `minus` and `ratio` take two leaf ops only.

Three limits make the set closed:
- **Depth two at most.** There is no `minus` of a `ratio`, and no op inside a `minus` other than a
  leaf.
- **No numeric literals.** No operand is a number, so there is no scaling, weighting or threshold
  in a row.
- **Operands are only the row's declared keywords.** Every keyword names a contract column through
  `per_period` or `per_program`, and the loader already checks that the contract declares it.

The set of expressible series is finite and can be listed in full. With *L* possible leaves (two
per `per_period` keyword, one per `per_program` keyword), a row can serve at most *L* + 2*L*²
distinct series.

**A new op is a new module version with a seal**, reviewed like any module (ADR-0053 §3). It is
never a row change.

`running` keeps `ev_series`'s rule: it starts at the first period the asset holds for the program,
so a period with no rows is no point at all, not a point of zero.

## The row

The operations go under `inputs.dataset.series`, one entry per series key. They cannot go in
`render.series`, because the SDK's `MeasureSeries` is `extra="forbid"`
(`iagent_mesh/measure_series.py:41`), and `render` describes drawing, not computation. This is the
same place the flow row keeps `value`. A sample, with sample names only:

```yaml
inputs:
  params: {program_id: {required: true}}
  dataset:
    urn: "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
    banner: "SYNTHETIC earned-value fixture, not a real program."
    contract: ev_fixture
    scope: program_id
    period: period
    status: status_period
    per_period: {bcws: bcws, bcwp: bcwp, acwp: acwp}
    series:
      cv: {minus: [{running: bcwp}, {running: acwp}]}
      sv: {minus: [{running: bcwp}, {running: bcws}]}
computation:
  module: agent_fleet.finance_agent.measure_modules.series_ops
  function: compose
  version: "1.0.0"
render:
  shape: MULTI_SERIES
  value_label: Cumulative variance
  series:
    - {key: cv, label: Cost variance (EV - AC), unit: USD, cumulative: true}
    - {key: sv, label: Schedule variance (EV - PV), unit: USD, cumulative: true}
```

## What the loader would check, all at boot

A malformed row still stops engine-fin with a `MeasureVerbError` that names the file, as every row
does today.

1. **Every op is in the module's `OPS`**, with its arity, and has depth two at most. A number
   anywhere, an unknown op, or a third level is refused.
2. **Every operand is a keyword of the row.** `running` and `period` take only `per_period`
   keywords, and `constant` takes only `per_program` keywords.
3. **No keyword is unused.** The row's `per_period`/`per_program` must equal the keywords the
   ops name. This replaces the `READS` check: what the function reads is now derived from the row.
4. **`series` keys equal `render.series` keys.** This replaces the `SERIES` check in the same way.
5. **Units follow the dimension.**
   - A `ratio` series declares no `unit`.
   - Every other series declares the unit, and `minus` operands share it.
   - The existing one-unit-per-card rule (`_check_series`) still holds, so a row is either all
     money or all index. A CPI line is never drawn on a cost card.
6. **`cumulative: true` is declared exactly when the module served a running sum,** that is when
   the op is `running` or a `minus` of two `running`s. A ratio of running sums is a to-date index,
   not a running sum, so it is never `cumulative`.

## What changes in the engine

Every change below is in `measure_verbs.py`. The served shape does not change, so the BFF, the SDK
and cortex need nothing for phase 1.

- **`_check_dataset_series`** accepts a `series` key, and only when the row names `series_ops`.
  For any other module the key is refused, as it is today.
- **The signature check** accepts `compose(*, periods, spec)` for a module that declares `OPS`.
  For every other module it stays exactly `periods`.
- **`READS`/`SERIES`** are derived from the row for `series_ops`, as described above.
- **`run_dataset_series`** passes `spec`. Its result check is unchanged: one mapping per period,
  exactly the declared keys, each a `Decimal`.
- **`method` carries the composition.** Today it carries the module's `sha256`. With
  `series_ops`, two rows share one module sha and compute different things. So `method` gains
  `composition`: the canonical JSON of the row's `series`, and its sha256. That is the
  `composition` half of ADR-0053 §4's manifest, and it lets a recipient reproduce the figure.

## Why this is selection, not a formula language (ruled yes, 2026-11-23)

ADR-0053 §3 refuses "a verb that accepts a formula, expression or code as a slot", and lists "not a
formula language, in any form" among its non-goals. The case that `series_ops` is on the right side
of that line:

- **Each op is a ratified method.** Each has a transcribed clause and a seal, which is what
  ADR-0053 asks of an algorithm. The row selects among them, and selects which declared columns
  they act on. Those are the "ratified parameters" of the §3 title.
- **The vocabulary is closed, and so is the set it can express.** Five ops, depth two, no literals,
  no free names. The full list of series a row can serve on a given contract can be printed in
  advance. A formula language is open by design.
- **It is structured data, checked at boot.** Nothing is parsed from text or evaluated at request
  time. A row the loader cannot fully classify never reaches a user.
- **The precedent shipped.** The flow row's `{minus: [a, b]}` is the same move at depth one, and
  #513 was accepted with it.

The case against: `minus` and `ratio` over named operands **is** arithmetic in a row, and every
op added later moves the line. The pressure will come from TCPI, weighted sums, windows and
literals. The proposal's answer is that the line is the vocabulary: a new op is a reviewed module
version, never a row. **That is a policy judgement, and it is the architect's call.** Fin will not
build any of this before that ruling.

**Ruled 2026-11-23 (architect, via Chris):** "yes, a closed set of operations chosen by a row
satisfies the ADR." So the line is the vocabulary. A new op is a reviewed module version with its
clause and seal, never a row. A row that asks for anything outside the closed set is refused at boot.

## What it still cannot express

These are deliberately outside, and they are the evidence that the limits are real:

- **TCPI**, (BAC − BCWP) / (BAC − ACWP), as the `fin_tcpi` sample transcribes it. That is a `ratio`
  of two `minus`es, depth three. The sample stays a state row on its own module
  (`measure_modules.tcpi`, `tcpi_bac`).
- A weighted sum, a percentage, or anything scaled by a constant (no literals).
- A window ("the last six periods"), a filter other than the program, or a second asset. These are
  unchanged from the flow row's limits (guide §4).
- A forecast. Every op is a restatement of what the asset holds.

## Phasing

- **Phase 1: `period`, `running`, `constant`, `minus`.** Every value is defined at every period,
  so the runner's "a `Decimal` per period" holds as it is. This covers cumulative cost and schedule
  variance, period amounts, and BAC lines. It is fin-only.
- **Phase 2: `ratio`, after one more decision.** A ratio has no value where its denominator is zero,
  and early periods often have zero cumulative actual cost. The options are:
  - (a) **A null point.** This needs `run_dataset_series` and `_emit_money` to accept `None`. The
    SDK has no point model to change, but **whether cortex draws a gap is unexamined**, so it is a
    question for `cortex-ui` and lane/74.
  - (b) **Refuse the whole answer** with a 422 when any denominator is zero. This is simple, but it
    refuses most young programs.
  - (c) **Drop the leading periods** until the denominator is nonzero. This breaks the
    one-row-per-period contract that the verdict and the x axis rely on.

  Fin recommends (a), once the drawing hop is confirmed. Note that CPI and SPI trends are already
  drawn by the hand-written row `fin:PerformanceIndexSeries` from the built-in measures, so phase 2
  adds the same lines over a deployment's own asset, not a new figure.

## The seals it would ship with

| seal | mutation | expected |
|---|---|---|
| each op equals its transcribed clause on the EV fixture, read through polars | swap `minus` operands; `running` restarts at a gap | red |
| `{pv: running bcws, ev: running bcwp, ac: running acwp, bac: constant bac}` equals `ev_series.cumulative`, period by period | `running` starts at period two | red |
| the loader refuses: a literal, an unknown op, depth three, an undeclared operand, `running` on a `per_program` keyword, an unused keyword, a ratio with a unit, mixed units, a wrong `cumulative` | each refusal deleted in turn | red on its own case |
| `method.composition` changes when the row's `series` changes and the module does not | the composition hash drops the spec | red |
| the census: no engine file names a declared series measure | a hard-coded key | red |

The second seal is the strongest available: an independent, already-sealed module, recomputed
through the new path.

## Cost

| item | owner | size |
|---|---|---|
| `series_ops.py`, with its five clauses | fin | about 100 lines |
| `measure_verbs.py` changes | fin | about 120 lines |
| the seals above, and one sample row | fin | one test module |
| the guide's §4 and §5, updated | fin | docs |
| phase 2's null point | fin, plus `cortex-ui` and lane/74 to confirm the drawing | after phase 1 |

No BFF, projector or chart change. Drawing is unchanged: a declared series answer reaches the UI
exactly as the existing sample series rows do today.

## Decisions asked for

1. **Does a closed op vocabulary selected by a row satisfy ADR-0053 §3?** (Architect.)
   **Ruled yes, 2026-11-23.**
2. **Phase 1 alone first?** Fin recommends it, and it is fin's next build once this is answered:
   `period`, `running`, `constant` and `minus`, with the seals above and one sample row.
3. **For phase 2: null point, refusal, or truncation?** Fin recommends a null point, once cortex
   confirms it draws a gap.
