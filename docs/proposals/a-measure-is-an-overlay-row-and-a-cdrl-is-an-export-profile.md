---
status: proposed
owner: invincible-agent/lane/fin
date: 2026-10-28
directive: >-
  architect, 2026-10-28: "(1) overlay contract for a measure (inputs, computation, outputs,
  policy), one synthetic algorithm proven end to end through 'ask' and the canvas; (2) CDRL
  export: one tabular CDRL (synthetic) produced from an export profile + xlsx template. Spec
  first, then build."
builds-on: ADR-0053 (measure modules), ADR-0036 (seed/overlay composition), ADR-0045 (engine-f verbs)
ratifies: nothing. Every row this proposal adds is labelled `# SAMPLE`.
---

# A measure is an overlay row; a CDRL is an export profile

## Why

Today every finance measure is Python in `agent_fleet/finance_agent/measures.py`, registered from
the `VERBS` table in `main.py`. A deployment that wants a measure the platform does not ship (its
own index, its own variance cut) has no way to add one except a fork. ADR-0053 already makes the
*computation* a pure, versioned module and ADR-0036 already gives every policy kind a seed and an
overlay layer. What is missing is the row that joins them into a verb a user can ask for and a
panel a canvas can hold. The same gap exists for exports: the only formats are the HTML package and
its DuckDB, and a contract deliverable (a CDRL) is a spreadsheet laid out to someone else's
template.

## Part 1 — the measure row (`measure_verbs`)

**Where.** Seed: `policy/measure_verbs/` (README only; the platform's seven verbs stay in code).
Overlay: `policy/overlays/<name>/measure_verbs/*.yaml`, selected by `MEASURE_VERB_OVERLAY_DIRS`
(os.pathsep list, default empty). Composed by `iagent_mesh.declarations.compose_rows`, key
`measure_id`: an overlay row replaces a row whole, `deleted: true` tombstones one.

**The four parts.**

| part | what the row says | what the row may NOT say |
|---|---|---|
| **inputs** | `params`: what the caller supplies (`program_id` required; optional `window`). `state`: which engine quantities feed the computation, named from a CLOSED vocabulary | an expression, a query, a field outside the vocabulary |
| **computation** | `module`, `function`, `version`, and `derived_from` (authority, clause, citation, `transcription`) | a formula as data (ADR-0053 §3); a module without `VERSION`; a module that does I/O |
| **outputs** | `archetype` (today: `PERIOD_SERIES`), `output_uri`, the `series` (key, label, unit), optional `reference` line, and `undefined` (the reason a period carries instead of a value) | a mixed-unit series on one card; a value without the method name beside it |
| **policy** | `status` (`sample`, `proposed`, `ratified`), the `cells` (domains) whose holders see the verb, `granted_by`, `reason` | any loosening of program visibility: every finance measure is `can_view_program(program_id)`, deny by default, and a row cannot change that |

**The input vocabulary** (closed; extending it is a platform code change, reviewed as one):

| name | meaning |
|---|---|
| `program.bac` | the program's budget at completion |
| `period.bcws`, `period.bcwp`, `period.acwp` | that period's planned value, earned value, actual cost, summed over the program's work packages |
| `cumulative.bcws`, `cumulative.bcwp`, `cumulative.acwp` | the same, summed from the FIRST PERIOD OF THE WINDOW through that period, skipping a period with nothing reported (all three quantities zero). This is the basis of the built-in `cum_*` columns (`index_series.build` accumulates over the periods it is handed), measured 2026-10-28; with no `window` it is the program's first period |

The engine computes these exactly (Decimal) per period in the window and calls the module once per
period with keyword arguments named as the row's `state` keys. The module returns a Decimal, or
`None` when the measure is undefined for that period; the row's `outputs.undefined.when` says when,
and the period carries `undefined: <reason>` and a null value instead of a number.

**The figure carries its method.** Every envelope from a declared measure carries
`method: {measure_id, name, version, module_sha256}` (ADR-0053 §5), and the card and the export
show `name vVERSION` beside the figure.

**How it reaches a user.**
- *ask*: engine-fin registers each composed row as a mesh verb at startup, with the row's synonyms,
  exactly as it registers its built-in verbs; the supervisor routes a question to it like any other.
  `POST /measure/{measure_id}` dispatches it; the program-visibility check (#130) runs first.
- *canvas*: a canvas template names the verb in a panel. Templates gain the same overlay layer
  (`CANVAS_OVERLAY_DIRS`, `policy/overlays/<name>/canvases/`), so a deployment's panel for its own
  measure lives in its own overlay, not in a platform template.

**The seal.** For every composed row, a test evaluates `derived_from.transcription` against the
module on fixture inputs (the §2a seal `test_the_method_registry_rows.py` already applies to the
EAC rows), checks `VERSION`, and checks the module imports nothing outside the standard library and
`decimal`.

**Where a deployment's module code lives — OPEN.** Today a module must ship in the engine image
(`agent_fleet/finance_agent/measure_modules/`). A deployment's own module in its private policy
repo needs a packaging decision this proposal does not take.

### The synthetic algorithm: TCPI (to-complete performance index)

Chosen because finance can check it by hand, it is not computed anywhere in the platform today,
and its undefined case is real.

```yaml
# SAMPLE — invented in this repo to prove the contract. A deployment replaces it with its own.
measure_id: fin_tcpi
verb: finToCompletePerformanceIndex
name: To-complete performance index (BAC)
inputs:
  params: {program_id: {required: true}, window: {required: false}}
  state: {bac: program.bac, bcwp: cumulative.bcwp, acwp: cumulative.acwp}
computation:
  module: agent_fleet.finance_agent.measure_modules.tcpi
  function: tcpi_bac
  version: "1.0.0"
  derived_from:
    authority: Public EVM methodology (DoD/DAU EVM Gold Card formulation)
    clause: TCPI (BAC)
    citation: name-only
    transcription: TCPI = (BAC - BCWP) / (BAC - ACWP)
outputs:
  archetype: PERIOD_SERIES
  output_uri: ToCompletePerformanceIndexSeries
  series: [{key: tcpi, label: TCPI}]          # dimensionless: no unit key
  reference: {value: 1.0, label: at budgeted efficiency}
  undefined: {reason: budget_spent, when: BAC <= cumulative ACWP (the budget is spent; no efficiency completes the work within it)}
policy:
  status: sample
  cells: [PROGRAM_FINANCE]
  granted_by: <accountable approver>
  reason: proves the measure-row contract end to end on synthetic NP-MERIDIAN data
```

Reading it: above 1.00 the remaining work must be done *more* efficiently than budgeted to finish
on budget; below 1.00, less.

## Part 2 — the export profile and the CDRL

**Where.** Seed `policy/fin_export_profiles/` (README only). Overlay
`policy/overlays/<name>/fin_export_profiles/`, selected by `FIN_EXPORT_PROFILE_OVERLAY_DIRS`. The
xlsx template sits beside its row. Kept out of `policy/exports/`, which lane/01 is about to create
for the ingest-review export; the row's first four keys are the ones cortex asked lane/01 for
(`name, format, scope, label`) so one picker can list both.

**The row.**

```yaml
# SAMPLE — a notional CDRL. A001 / DI-NOTIONAL-0001 name no real contract or data item.
name: cdrl_a001_ev_summary
format: xlsx
scope: program                       # one file per program
label: CDRL A001 - Notional EV summary (synthetic)
audience: program_office
cdrl: {item: A001, title: Notional Earned Value Summary, data_item: DI-NOTIONAL-0001, frequency: monthly}
template: {file: cdrl_a001_ev_summary.xlsx, sha256: <hex of the file>}
sheet: EV Summary
cells: {B2: program.name, B3: program.id, B4: as_of, B5: cdrl.item}
sources:
  - fn: fin_performance_indices
  - fn: fin_tcpi
table:
  start: A8                          # row 7 is the template's own header row
  key: period
  columns:
    - {from: period}
    - {from: fin_performance_indices.cum_bcws, format: "#,##0"}
    - {from: fin_performance_indices.cum_bcwp, format: "#,##0"}
    - {from: fin_performance_indices.cum_acwp, format: "#,##0"}
    - {from: fin_performance_indices.cum_cpi, format: "0.000"}
    - {from: fin_performance_indices.cum_spi, format: "0.000"}
    - {from: fin_tcpi.tcpi, format: "0.000"}
methods_sheet: Methods               # every source's method name, version, module sha256
manifest_sheet: _manifest            # hidden; the ADR-0053 §4 envelope as JSON
```

**What the profile may not do.** Compute anything: every number in the file is a value a verb
returned, joined on `key`. A column naming a field the source does not return refuses the profile
at load. A template whose bytes do not match `template.sha256` refuses the profile at load.

**The output.** `fin-cdrl-<name>-<program_id>.xlsx`, written into the template (the template's
styling, column widths and header rows are kept), plus the §4 envelope: `{schema: "fin-export/1",
kind: "cdrl", profile, template_sha256, sources[{fn, params, method, rows_sha256}], cells_sha256,
as_of}`. `cells_sha256` is the hash of every written cell (sheet, coordinate, value) in canonical
JSON; it is the reproducibility claim. **The file's own bytes are not claimed reproducible** (an
xlsx is a zip with write times in it).

**Who may export.** The program-visibility check (#130), same 403 envelope, before anything is
measured.

**Routes.** engine-fin `POST /cdrl_export {profile, program_id, as_of?}`; BFF
`GET /export/cdrl/profiles` → `[{name, format, scope, label}]` and
`GET /export/cdrl?profile=&program_id=` → the file (`Content-Type`
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `Content-Disposition` with
the filename). Refusals: 404 `unknown_profile`, 403 `program_not_visible` (relayed with
`grantable_by`).

**Dependency.** `openpyxl` (pure Python, MIT), uv-managed, in engine-fin and the root
`agent-fleet` extra. No xlsx writer exists in the repo today.

## Not decided here

- Where a deployment's own module code ships (above).
- Whether a `status: sample` row should register outside a sandbox overlay at all.
- A DID-conformant layout: the sample proves the mechanism, not any real data item.
- Merging this profile kind with lane/01's ingest-export profiles; the shared header is offered.
