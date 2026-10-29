# Finance overlays: the contract your deployment's rows must meet

Status: describes the code as of 86673740. Synthetic examples only.

For finance analysts and the engineer who maintains your private policy repo: what you can add to
the finance service without changing the product, what each addition must contain, and what makes
the service refuse it. Everything below is invented (`NP-MERIDIAN`, `alice@example.com`, CDRL
`A001` / `DI-NOTIONAL-0001`).

Terms: **BAC** is budget at completion; **BCWS, BCWP, ACWP** are planned value, earned value and
actual cost; **CDRL** is a contract data requirements list item, the deliverable; **the finance
service** computes these figures; **the gateway** is the web front door users and downloads go
through; **the platform team** is us.

## 1. What an overlay is

Our repo ships a small set of seed rows plus clearly labelled samples (`# SAMPLE` on the first line).
Your deployment adds its own rows from a private policy repo that is never committed here. The
platform team arranges for that repo's directories to be present where the finance service can read
them, and sets one variable per kind of row to point at them.

The rules, the same for every kind:

- **Replace, whole.** A row in your overlay replaces a seed row with the same key. Nothing is merged
  field by field; your row must carry its complete definition.
- **Delete with a tombstone.** A file holding the key and `deleted: true` removes that row. A
  tombstone for a key that no earlier layer ships is an error, not a no-op.
- **Unset means no overlay.** If the variable is not set, only seed rows load. A variable pointing at
  an existing empty directory also means "none". A path that does not exist is read as empty with
  no error, so a misspelt path silently adds nothing. Check the spelling.
- **One variable per kind.** Several directories can be listed, separated by `:` in the service, and
  later ones win.
- **One row per file** (`*.yaml`). Two files declaring the same key is an error.
- **A bad row stops the service starting**, naming the file and the reason, so a catalogue never
  loads half.

| kind | seed directory | overlay variable | key that identifies a row |
|---|---|---|---|
| measure row | `policy/measure_verbs/` (ships none) | `MEASURE_VERB_OVERLAY_DIRS` | `measure_id` |
| method row | `policy/measures/` (three EAC rows) | `MEASURE_OVERLAY_DIRS` | `method_id` |
| export profile | `policy/fin_export_profiles/` (ships none) | `FIN_EXPORT_PROFILE_OVERLAY_DIRS` | `name` |

**Two variables with "measure" in the name.** `MEASURE_VERB_OVERLAY_DIRS` carries measure rows: the
measures people can ask for and see charted (section 2). `MEASURE_OVERLAY_DIRS` carries method rows:
the registry of alternative estimate-at-completion formulas (CPI-based and similar). Today the
running finance service reads the first and does not read the second at all; method rows are checked
only by the platform team's test suite. Do not plan on adding a method row and seeing it take effect.

## 2. Measure rows: adding a measure people can ask for

A measure row declares a number computed per month from a program's earned-value data. After it
loads, a user can ask for it in chat ("What is the to-complete performance index for NP-MERIDIAN?")
and it can be a source for an export profile (section 3). The row declares; it never calculates.

Top-level keys. Required unless marked optional. A key not in this table is ignored, not refused, so
nothing you put there takes effect.

| key | what it holds |
|---|---|
| `measure_id` | The row's key. Must be `fin_` then lower-case letters, digits or `_`. Cannot be a built-in measure's id. |
| `verb` | The name the question is routed by. Cannot be a built-in verb's name. |
| `name` | The title shown above the figure. |
| `description` | Optional. Plain words telling the router when this measure is the right one, and when it is not (name the neighbours). |
| `synonyms` | Optional. Phrases a user might say for this measure. |
| `anti_synonyms` | Optional. Phrases that mean a different measure, so the router does not pick this one. |
| `inputs` | Which program quantities the measure uses. Holds `params` and `state` only. |
| `computation` | The reviewed module that calculates it, and where the formula comes from. |
| `outputs` | What is shown: one series, its unit, a reference line, and what "undefined" means. |
| `policy` | Who may see it, who approved it, and why. |

The worked example, copied from the sample file. TCPI (to-complete performance index) is the
efficiency the remaining work must achieve to finish on budget.

```yaml
# loads-as: measure_verb
# SAMPLE -- invented in this repo to prove the measure-row contract end to end. A deployment
# replaces it with its own. Overlay layer: policy/overlays/sample/. Proposal:
# docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md
measure_id: fin_tcpi
verb: finToCompletePerformanceIndex
name: To-complete performance index (BAC)
description: >-
  The efficiency the remaining work must achieve for the program to finish on its budget at
  completion, reported period by period. Above 1.00 the rest of the work must be done more
  efficiently than budgeted; below 1.00, less. Undefined once the budget is spent. A dimensionless
  ratio, never an amount. NOT how efficiently the work has been done so far - that is
  finPerformanceIndices (CPI and SPI). NOT a forecast of the final cost - that is
  finEacCalculation. OWNS the phrasings: TCPI, to-complete performance index, what efficiency do we
  need to finish on budget.
synonyms:
  - to-complete performance index
  - TCPI
  - efficiency needed to finish on budget
anti_synonyms:
  - cost performance index
  - CPI
  - estimate at completion
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

**Inputs.** `params` lists what the question supplies: `program_id` is required, `window` (a period
range) is optional; nothing else is accepted. `state` maps each argument of the calculating function
to a program quantity. The quantities are a closed list: `program.bac`; `period.bcws`, `period.bcwp`,
`period.acwp` (that month alone); `cumulative.bcws`, `cumulative.bcwp`, `cumulative.acwp` (summed
from the first month of the window, skipping months with nothing reported). Adding a quantity is a
product change. A row cannot carry its own query or formula.

**Computation.**

| computation key | meaning |
|---|---|
| `module`, `function` | The calculating code. It is a small reviewed module shipped with the product, takes exactly the `state` names as keyword arguments, and may import only `decimal`, `typing`, `math`, `fractions`. A module that reads files or the network is refused. Code specific to your organisation is not covered yet (section 6). |
| `version` | Must equal the version the module declares. It is printed beside every figure ("TCPI (BAC) v1.0.0") on screen and in exports. |
| `derived_from.authority` | The standard the formula is taken from. |
| `derived_from.clause` | The clause or formula name in that standard. |
| `derived_from.citation` | Optional, default `unstated`. Write `name-only` where you can name the formula but have no numbered clause. Do not invent a clause number: a precise-looking number nobody checked is worse than an honest "name-only". |
| `derived_from.transcription` | The formula as the standard writes it. The platform team's tests run it against the module, so the two cannot disagree silently. |

**Outputs.** `archetype` is always `PERIOD_SERIES`. `output_uri` is a short local name (not a URL)
for the result type; the platform team registers a matching type in the finance vocabulary, as our
sample's `ToCompletePerformanceIndexSeries` is. `series` holds exactly one series (`key`, `label`,
optional `unit`; leave `unit` out for a ratio). `reference` is an optional line with a meaning (1.0
here). `undefined` is optional; if the function can return nothing for a month, it must give a
`reason`, which is shown instead of a number.

**Policy.** `status` is `sample`, `proposed` or `ratified`. `cells` is a non-empty list naming the
access cells that may see the measure (the sample uses `PROGRAM_FINANCE`). `granted_by` is the
person who approved it and `reason` is why. Replace the sample's `<accountable approver>` with a
real name before you send a row. There is no visibility key: a measure is only ever shown for a
program the user has been granted, and nothing in a row can widen that.

**What is refused at load.** The file is named in each message.

- You gave a `measure_id` that does not start `fin_`, or that is a built-in measure's id, or a
  `verb` that is a built-in's name.
- You left out a required key (including `derived_from.authority`, `clause`, `transcription`).
- You put anything but `params` and `state` under `inputs` (a formula, an expression, a query).
- You asked for a quantity outside the closed list, or a parameter other than `program_id`/`window`.
- You pointed at a module that imports outside the allowed four, declares no `VERSION`, or declares
  one that differs from the row's `version`; or at a function whose keyword arguments are not
  exactly your `state` names.
- You set `archetype` to anything but `PERIOD_SERIES`, gave an `output_uri` that is a URL, listed
  more than one series, or gave an `undefined` with no `reason`.
- You set a `status` outside the three, left `cells` empty, or added a `visibility` key.
- You wrote a tombstone for a key no earlier layer ships, or two files with the same `measure_id`.

## 3. Export profiles: producing a CDRL deliverable

A profile declares one deliverable per program: which measures fill it, where each figure goes, and
(for Word and Excel) the template it fills. Every number in the file is a figure a measure returned;
an undefined month is written as `undefined: <reason>`. A profile cannot calculate: a `formula`,
`compute` or `expression` key is refused like any other unknown key. The file is named
`fin-cdrl-<name>-<program_id>.<format>`.

Top-level keys. The first four are the shared header.

| key | what it holds |
|---|---|
| `name` | The row's key, and part of the file name. |
| `format` | `xlsx`, `docx`, `csv` or `json` (table below). |
| `scope` | Always `program`: one file per program. |
| `label` | The title shown in the download list. |
| `audience` | Optional. Free text. |
| `cdrl` | `item` (required), and optional `title`, `data_item`, `frequency`. These are the facts a title-block cell can show. |
| `template` | `file` (a file beside this row, no path) and `sha256`. xlsx and docx only. |
| `sheet` | The template sheet to fill. xlsx only. |
| `cells` | Title block: coordinate to fact. Facts: `program.name`, `program.id`, `as_of`, `cdrl.item`, `cdrl.title`, `cdrl.data_item`, `cdrl.frequency`. Not for csv. |
| `sources` | List of `{fn: <measure>}`, built-in measures (for example `fin_performance_indices`) or your own `measure_id`s. |
| `table` | `key` (the field rows are joined on, usually `period`), `columns`, and `start` or `at` (below). |
| `methods_sheet` | Optional name for the methods sheet. Default `Methods`. xlsx only. |
| `manifest_sheet` | Optional name for the hidden record sheet. Default `_manifest`. xlsx only. |
| `provenance_sheets` | Optional true or false, default true. xlsx only. |

Each column is `{from: <source>.<field>}`, or `{from: period}` for the key. A column may take only
a field its source returns: for your own measure that is `period` plus its series `key`; for a built-in,
a fixed list (`fin_performance_indices` returns, among others, `cum_bcws`, `cum_bcwp`, `cum_acwp`,
`cum_cpi`, `cum_spi`).

| format | template? | how cells are addressed | how the table is written | provenance sheets |
|---|---|---|---|---|
| `xlsx` | required, plus `sheet` | `B2`; `table.start` is a cell such as `A8`; column `format` is an Excel number format | rows down from `start`, one column per `from` | optional (default on) |
| `docx` | required | `T1!B2` (first body table, cell B2); `table.start` is `T1!A2`; rows are added if the table is short | same, column `format` from the text list below | not allowed |
| `csv` | none | no title block (`cells` refused); every column needs `as`, the header text | a header row then one row per period | not allowed |
| `json` | none | `cells` keys are object paths such as `/header/as_of`; `table.at` is the path of the row array; every column needs `as`; no `format` | an object in declaration order; an absent value is an omitted key, never `null` | not allowed |

Text formats for docx and csv (numbers are written as text): `#,##0` `#,##0.00` `0` `0.0` `0.00`
`0.000` `0.0%`. Paths use object keys only: no array indexes, no `~`, no empty segment, and no two
paths may be equal or nested.

**The template's sha pin.** `template.sha256` fixes the exact bytes the profile was reviewed
against. If anyone edits the template, the profile is refused until the pin is updated and
re-approved. Compute it on the final file, after every layout edit:

    certutil -hashfile cdrl_a001_ev_summary.xlsx SHA256        (Windows)
    sha256sum cdrl_a001_ev_summary.xlsx                        (Linux, macOS)

**`provenance_sheets`.** With true (the default) an xlsx gets a `Methods` sheet (each source's
measure id, name, version and code fingerprint) and a hidden `_manifest` sheet holding the record
of what produced the file. Set it to `false` when the customer's form accepts no extra sheets: the
file then has exactly the template's sheets. The provenance still travels outside the file, in the
JSON `envelope` the service returns and in the `X-Cells-Sha256` response header the gateway sets.
A false row that also names `methods_sheet` or `manifest_sheet` is refused.

**The cells hash.** `cells_sha256` is a SHA-256 over every cell the service wrote (container,
coordinate, value, in a fixed order): the title block, the table and, when provenance sheets are on,
the Methods sheet; not the hidden manifest, not formatting. The same CDRL from the same data gives
the same hash, and a reader can recompute it from the delivered file's cells. The file's own bytes
are not claimed reproducible: an Excel or Word file records when it was written.

The xlsx sample (its template, `cdrl_a001_ev_summary.xlsx`, sits beside it):

```yaml
# loads-as: export_profile
# SAMPLE -- a notional CDRL. A001 / DI-NOTIONAL-0001 name no real contract or data item.
name: cdrl_a001_ev_summary
format: xlsx
scope: program                       # one file per program
label: CDRL A001 - Notional EV summary (synthetic)
audience: program_office
cdrl: {item: A001, title: Notional Earned Value Summary, data_item: DI-NOTIONAL-0001, frequency: monthly}
template: {file: cdrl_a001_ev_summary.xlsx, sha256: 041f60148f0a6fb3aedc9c382151482d0e77c7eb48a6e7506ef01a8653d52f4a}
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
manifest_sheet: _manifest            # hidden; the ADR-0053 section 4 envelope as JSON
provenance_sheets: true            # false = deliver exactly the template sheets (no Methods/_manifest)
```

The json sample, which needs no template:

```yaml
# loads-as: export_profile
# SAMPLE -- a notional CDRL as JSON. A001 / DI-NOTIONAL-0001 name no real contract or data item.
# Same sources and fields as cdrl_a001_ev_summary.yaml; NO template: a profile alone is a deliverable.
name: cdrl_a001_ev_summary_json
format: json
scope: program                       # one file per program
label: CDRL A001 - Notional EV summary, JSON (synthetic)
audience: program_office
cdrl: {item: A001, title: Notional Earned Value Summary, data_item: DI-NOTIONAL-0001, frequency: monthly}
cells:                               # /a/b pointers, object keys only; written in this order
  /header/program_name: program.name
  /header/program_id: program.id
  /header/as_of: as_of
  /header/cdrl_item: cdrl.item
sources:
  - fn: fin_performance_indices
  - fn: fin_tcpi
table:
  at: /summary/periods               # the row array: one object per period
  key: period
  columns:
    - {from: period, as: period}
    - {from: fin_performance_indices.cum_bcws, as: cum_bcws}
    - {from: fin_performance_indices.cum_bcwp, as: cum_bcwp}
    - {from: fin_performance_indices.cum_acwp, as: cum_acwp}
    - {from: fin_performance_indices.cum_cpi, as: cum_cpi}
    - {from: fin_performance_indices.cum_spi, as: cum_spi}
    - {from: fin_tcpi.tcpi, as: tcpi}
```

**What is refused at load.**

- You used a key not in the tables above, including `formula`, `compute` or `expression`.
- You named a `format` other than the four, or a `scope` other than `program`.
- You gave a key the format does not have (a template on csv or json, `sheet` or provenance keys
  outside xlsx, `cells` on csv, `table.start` on csv or json, `table.at` on xlsx or docx), or left out
  one it needs.
- Your template file is missing, is a path rather than a file beside the row, or its bytes do not
  match `template.sha256` (which must be 64 lowercase hex digits).
- You named a `sheet` the template lacks, a docx coordinate outside the template's tables, or a
  `methods_sheet` or `manifest_sheet` that collides with a template sheet or with each other.
- You gave `provenance_sheets` as anything but a YAML true or false.
- A `cells` key is not a valid coordinate for the format, its fact is not in the list above, or it
  uses a `cdrl.*` fact the `cdrl` block does not give.
- A source is neither a built-in measure nor a loaded measure row, or a column names a source not in
  `sources`, or a field that source does not return, or `table.key` is not a field of every source.
- A docx or csv column `format` is outside the text list, a json column has a `format`, a csv or json
  column lacks `as` (or repeats one), or an xlsx or docx column has `as`.
- A docx table's columns run off the template's table.

## 4. What a work overlay looks like

A synthetic private policy repo:

```
finance-policy/
  measure_verbs/
    fin_tcpi.yaml                       one measure row per file
  fin_export_profiles/
    cdrl_a001_ev_summary.yaml           the profile
    cdrl_a001_ev_summary.xlsx           its template, beside it
```

There is no `measures/` directory: method rows are not read by the running service (section 1).

The deployment sets, under the finance service's environment in the chart values (placeholder path;
the platform team fills in the real one):

```yaml
agentFleet:
  env:
    MEASURE_VERB_OVERLAY_DIRS: "/path/to/finance-policy/measure_verbs"
    FIN_EXPORT_PROFILE_OVERLAY_DIRS: "/path/to/finance-policy/fin_export_profiles"
```

**Before you send it.**

1. Validate each kind locally, from a checkout of the platform repo. These commands load the sample
   overlay; point them at `finance-policy` instead. Each prints the loaded names, or ends with a
   line containing `MeasureVerbError` or `ExportProfileError` naming the file and the reason.

   Measure rows:

       uv run --no-sync python -c "import sys; from pathlib import Path; from agent_fleet.finance_agent import measure_verbs as m; print([r.measure_id for r in m.load_measure_verbs(overlay_dirs=[Path(sys.argv[1])])])" policy/overlays/sample/measure_verbs

   Export profiles (measure rows are loaded first, because a profile may use them):

       uv run --no-sync python -c "import sys; from pathlib import Path; from agent_fleet.finance_agent import measure_verbs as m, export_profiles as e; d = Path(sys.argv[1]); v = {r.measure_id: r for r in m.load_measure_verbs(overlay_dirs=[d / 'measure_verbs'])}; print([p.name for p in e.load_export_profiles(overlay_dirs=[d / 'fin_export_profiles'], declared=v)])" policy/overlays/sample

   (Lines such as `api docs: DISABLED` printed before the result are normal.)
2. Recompute the template's sha256 after the last edit to the template and paste it into the profile.
3. Fill in `granted_by` and `reason` on every measure row with the real approver and the real reason.
   Do not leave `<accountable approver>`.

## 5. What we need from you

1. **For a measure:** the formula exactly as your standard states it, and the document and clause
   number. If you have no clause number, say so and we write `name-only`.
2. **For a deliverable:**
   - the data item's layout (the Excel or Word template);
   - a map from each column to the measure (and field) that supplies it;
   - which cells hold the title-block facts, and which table row the data starts on.
3. **An approver** for each measure and each profile: the person whose name goes in `granted_by`.
4. **Which format the customer's data item requires:** xlsx, docx, csv or json.

## 6. Not covered yet

- **Where organisation-specific measure code lives.** A measure's calculating module ships inside
  the product today. A private module needs a packaging decision that has not been made.
- **Narrative sections and multiple tabs.** A profile covers one table plus a title block.
- **Answer exports** (plan and review exports under `policy/exports/`). They are a separate kind of
  row, with their own variable, and are not documented here.
- **Boards.** A measure can also be a panel on a board; boards are a separate overlay kind.
