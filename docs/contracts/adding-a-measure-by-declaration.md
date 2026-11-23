# Adding a finance measure by declaration

**Who this is for:** a deployment's finance analyst and platform engineer who want people to be able to
ask engine-fin for a measure the product does not ship.

**What it covers:** what you supply, how the engine checks it, and what a declared measure cannot
express.

**Where the details are.** The key-by-key contract is
[finance-overlays.md](finance-overlays.md) §2. This guide links to it and does not repeat its
tables.

**Worked example.** The proof is
`policy/overlays/sample/measure_verbs/fin_flow_cost_variance.yaml`, a measure added as one row with
no engine change. `tests/finance/test_a_measure_added_by_declaration_alone.py` seals it.

## 1. What a declared measure is

A declared measure is **one YAML file in your overlay directory.** It *declares* the measure and never
calculates it:
- it names the inputs;
- it names one reviewed calculating function that already ships in the engine;
- it says how the result is drawn, who may see it, and who approved it.

Once it loads, people can ask for it in chat. It is routed by its verb, drawn as a card, and can be
the source of a CDRL export profile.

**Choose the row kind by where the numbers come from:**

| kind | reads | drawn as | reuses (shipped modules) |
|---|---|---|---|
| **state row** | the engine's program quantities: `program.bac`, and the period or cumulative `bcws`/`bcwp`/`acwp` | `MULTI_SERIES`, one value per period | `tcpi.tcpi_bac`, `vac.vac_cpi` |
| **dataset flow row** | named columns of one catalogued asset | `FLOW_DECOMPOSITION`, signed edges down a hierarchy | `variance_decomposition.flow_edges` |
| **dataset series row** | named columns of one catalogued asset, per period | `MULTI_SERIES` | `ev_series.cumulative`, `ev_series.eac_trend` |

**A new measure needs no code only when it reuses one of these functions.** Most do it in one of
two ways:
- a dataset flow row over a different column, or over the difference of two columns. The proof does
  this: `value: {minus: [bcwp, acwp]}` is cost variance.
- a state row wiring a shipped scalar function to the quantities it takes.

## 2. What the deployment supplies

1. **The row file**, `<measure_id>.yaml`, one row per file, in your private policy repo.
   - `measure_id` starts `fin_`.
   - The verb is new: it is neither a built-in's name nor another row's.
   - The keys are those of finance-overlays.md §2. Write the `description`, `synonyms` and
     `anti_synonyms` so that they name the neighbouring measures. The router picks among every live
     verb, so a row that does not say how it differs from a built-in can take that built-in's
     questions.
2. **The directory, mounted where engine-fin reads it**, named in `MEASURE_VERB_OVERLAY_DIRS`. A
   misspelt path loads nothing, without error.
3. **An approver**, named in `policy.granted_by`, and the cells that may see the measure, in
   `policy.cells`.
4. **For a dataset row, also:**
   - the asset's URN and its banner;
   - a **contract** file that declares every column the row names (`contracts/<id>.yaml`, or a
     directory named in `DATASET_CONTRACT_DIR`);
   - a **reader grant on that URN** for the people who will ask. The asset is always read as the
     caller.

   See [finance-deployment-checklist.md](finance-deployment-checklist.md).

## 3. How it is checked

**At load.** engine-fin refuses to start, naming the file and the reason, if anything below is
wrong. A catalogue never loads half.

- **The keys.** An unknown top-level key is refused, `formula` among them. So nothing written in a
  row can look as if it took effect.
- **Identity.** The id must have the `fin_` form. A built-in's id or verb is refused, except in a
  source-only row. Two files with one key are refused.
- **A state row's inputs** come only from a closed vocabulary of engine quantities. The function's
  keyword-only parameters must be exactly the row's `inputs.state` keys.
- **The module.** It must be importable, and its source is parsed: every import must be one of
  `decimal`, `typing`, `__future__`, `math` or `fractions`, so it does no I/O. The module's
  `VERSION` must equal the row's `computation.version`.
- **A dataset row is joined to its contract.**
  - Every named column must be declared, with the right type: a level is a string, and a value is
    numeric.
  - The root level must be the contract's `scope`.
  - A series row's keywords must equal the module's `READS`, and its series keys the module's
    `SERIES`.
  - A `per_program` or `status` column must be declared as determined by the scope.
- **The shape** must be one this kind of row computes.
- **`source: seed`** requires a `reason` and `ratified_by`.

**At startup.** Each loaded row registers its verb with the mesh, once. A row added later is live
only after engine-fin restarts.

**On every read** of a dataset row:
- the caller's grant on the URN is checked first: 403 `access_denied`;
- the **whole** contract is enforced, not only the columns the row names. A broken rule is a 502
  `asset_contract_violation` that names the rule and the column, never a value;
- a read with too many rows is a 422 `asset_too_large`;
- an asset that cannot be reached is a 503 `asset_unavailable`;
- there is no fallback to notional figures.

**By the proof's tests.** The worked example is held to an oracle computed independently, and to
the built-in's own figure for the same quantity. A census holds that no engine file names it.

## 4. What a declared measure cannot express

Each of these needs engine code and a review, or is not supported at all.

- **A calculation no shipped function performs.** A row cannot carry a formula. A new calculation is
  a new module under `agent_fleet/finance_agent/measure_modules/`, which is code. **Not decided yet:**
  where a deployment's own, private module would live (finance-overlays.md §6).
- **A new series measure, in practice.** A series row's keys must equal its function's `SERIES`:
  `pv`/`ev`/`ac`/`bac` for `cumulative`, and `eac`/`bac` for `eac_trend`. A row can map other
  columns onto those keywords, but the served keys would then misname them. A genuinely new
  `MULTI_SERIES` measure is a new module. Today the declaration-only path is the flow row.
- **Being drawn, for a flow row (as of 2026-11-22).** A `FLOW_DECOMPOSITION` answer is computed and
  served, but the UI has no card registered for that shape. The hops it waits on are listed in
  cortex-ui's 11-21 page "what a new finance measure needs served":
  - **`/menu_blocks` serving the row's `menu:` block (lane/74).** The route is on master (0.4.91),
    but it does not serve a measure row yet, for two reasons:
    - it reads only `<overlay>/menu_blocks/*.yaml`, never a measure row's own `menu:` block;
    - it keys a placement by `(subject, archetype)`, and every finance row declares the subject
      `fin:DeclaredMeasureSeries`. The three flow rows therefore collide, and the registry serves
      none of them.

    Which of the two changes fixes the key (key by the declaring verb, or a subject per row) is
    the architect's to rule.
  - **The projector row (Lane 1).** It is built on a branch and held until the menu block is served.
  - **Cortex reading it.**

  A `MULTI_SERIES` answer draws today only because hand-written rows for other subjects carry that
  archetype. And no measure *appears* in a list anywhere: it is found only by asking for it.
- **More than one asset per row,** or a join between assets.
- **A flow value beyond one column or one difference.** `value` is a single numeric column or
  exactly `{minus: [a, b]}`.
  - Not a ratio. Cost performance index, BCWP / ACWP, cannot be a flow row.
  - Not a weighted sum, and not three or more terms.
- **A period window on a flow row.** `window` is refused there. A flow always sums every row the
  program has, to date. "This month's cost variance by account" is not expressible.
- **A filter other than the program.** The read is selected by the contract's scope only. A row
  cannot restrict itself to one control account or to one status.
- **A state quantity the engine does not know.** The state vocabulary is closed. Extending it is a
  code change.
- **Mixed units in one series row.** A row's series share one unit.
- **A package export.** A package page recomputes its panels in its embedded `measures.py`, so a
  package naming a declared measure is a 503 from the builder, naming the panel. A CDRL export
  profile *can* source a declared measure.
- **Alternative EAC method rows.** `MEASURE_OVERLAY_DIRS` is not read by the running engine.
- **Looser visibility.** A row cannot widen who sees a program. The program check runs before any
  declared verb.

## 5. Step by step, for a finance team member

This section uses only the shipped sample: the row `fin_flow_cost_variance`, the contract
`ev_fixture`, and the synthetic asset `urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)`.
Your own measure follows the same steps with your names.

### 5.1 The files you write

**One file, in the usual case: the row.** Copy
`policy/overlays/sample/measure_verbs/fin_flow_cost_variance.yaml` into your overlay directory, as
`<measure_id>.yaml`. Your platform engineer tells you which directory engine-fin reads; it lives in
your deployment's private policy repo, not in this one. Then change these keys:

| key | what to write | in the sample |
|---|---|---|
| `measure_id` | `fin_` and a lower-case name, the same as the file name | `fin_flow_cost_variance` |
| `verb` | a new camel-case name, not used by any other measure | `finFlowCostVariance` |
| `name` | the title a reader sees | `Cost variance flow` |
| `description` | what it is, and **which neighbouring measures it is not** | names `finVarianceAnalysis`, `finVarianceDrivers`, `finFlowActualCost` |
| `synonyms` | phrases a person would type to mean this measure | `cost variance flow`, … |
| `anti_synonyms` | phrases that mean a neighbour, so this one is not chosen for them | `explain the cost variance`, … |
| `inputs.dataset.value` | one column, or exactly `{minus: [a, b]}` | `{minus: [bcwp, acwp]}` |
| `inputs.dataset.levels` | the hierarchy, top first; the first must be the contract's `scope` | `[program_id, control_account, work_package]` |
| `other_threshold` | the share below which small siblings are grouped as "All other" | `"0.05"` |
| `render.value_label` | the label of the figure | `Cost variance (EV - AC)` |
| `policy.cells`, `policy.granted_by`, `policy.reason` | who may see it, who approved it, and why | `[PROGRAM_FINANCE]`, `seed`, … |

Leave `computation` as it is: it names the reviewed function the row reuses. Keep the asset's
`urn`, `banner` and `contract` unless your measure reads a different asset.

**Two more items, only if the asset is new to engine-fin.** Your platform engineer supplies both
(see [finance-deployment-checklist.md](finance-deployment-checklist.md)):
- a contract file declaring every column your row names;
- a reader grant on the asset's URN for each person who will ask.

### 5.2 How to check it locally

Run these from a checkout of this repository, with its environment synced (`uv sync --extra
agent-fleet`).

**Step 1: does it load?** Point engine-fin at a directory holding only your row, and import it:

```bash
MEASURE_VERB_OVERLAY_DIRS=/path/to/your/measure_verbs \
  uv run python -I -c "import sys; sys.path.insert(0, '.'); from agent_fleet.finance_agent import main as m; print('LOADED', sorted(m.DECLARED))"
```

- **If the row is good,** it prints `LOADED ['fin_flow_cost_variance']`.
- **If it is not,** the import stops with a `MeasureVerbError` that names the file and the reason.
  Two real examples, from the sample row with one thing broken:
  - with a `formula:` key added: `fin_flow_cost_variance.yaml is not a valid measure verb row:
    row carries ['formula'], which no part of the engine reads; a measure row cannot carry a
    formula, expression or query -- the computation lives in the named module`;
  - with `acwp` misspelt `acwq`: `... inputs.dataset names ['acwq'], which contract 'ev_fixture'
    does not declare`.

  The running engine refuses to start in the same way, so a row that fails here would never
  reach a user.

`MEASURE_VERB_OVERLAY_DIRS` replaces the list of directories. Pointed at your directory alone, it
loads only your rows; the engine's own measures are unaffected, and none of the other sample rows
load.

**Step 2: does it compute what you expect?** This step is for whoever writes your tests.
1. Copy `tests/finance/test_a_measure_added_by_declaration_alone.py`.
2. Change `FN`, `VERB` and the expected figures to yours. The oracle, `expected_edges`, sums
   `bcwp − acwp` with polars, so change that expression to match your `value`.
3. Run it:

```bash
uv run python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -q tests/finance/<your test>.py
```

It calls the real route as an allowed caller and as a refused one, and compares the answer with
the polars sum. Its census also checks that no engine file names your measure.

**Step 3: what to tell your platform engineer.** Give them the row's file name and verb. The
measure goes live only when engine-fin restarts with the directory mounted, because verbs register
once, at startup.

### 5.3 What you will see

**The answer** to `POST /measure/fin_flow_cost_variance` for the sample program, as an allowed
caller (measured locally on the synthetic fixture; nothing here ran on a cluster):

| field | what it holds | in the sample |
|---|---|---|
| `verdict` | one sentence restating the figures, never a judgement | `Cost variance (EV - AC): net -1130000.00 across 14 edges over 2 levels, 0 'All other' sink(s) from the collapse, 8 edge(s) at zero` |
| `rows` | one edge per parent and child, the program's own edge first | 15 rows; the first is the program, `negative`, `1130000.00` |
| `data_provenance` | the banner, the as-of and ticket, and the source URN | `SYNTHETIC earned-value fixture, not a real program. (as of …, ticket: …) Source: urn:li:dataset:…` |
| `method` | the measure, the function's version, and its source's sha256 | `version 1.3.0` |
| `render` | the shape, the label and the unit | `FLOW_DECOMPOSITION`, `Cost variance (EV - AC)`, `USD` |

Each edge carries:
- `value`: the size, always positive;
- `sign`: `positive`, `negative` or `zero`;
- `level`: 0 for the program's own edge, then one per level down;
- `value_exact`: the figure as a string with two decimals.

**In chat,** a person asks in their own words: "show me the cost variance flow for the program".
The router chooses your verb from its synonyms and anti-synonyms. As of 2026-11-22 the UI draws no
card for a flow answer (section 4 lists what that waits on).

**A person without access** gets a refusal, never a figure:
- without program membership: 403 `program_not_visible`;
- without the reader grant on the asset: 403 `access_denied`, with the message "You are not
  authorized to read this dataset (<urn>). You can request access."
- if the row sets `policy.cells` and the person holds none of them: 403 `measure_not_in_cell`.

The checks run in that order (program, then cells, then the asset), so a person outside the program
learns nothing about the measure.
