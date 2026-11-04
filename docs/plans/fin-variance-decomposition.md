# A variance decomposition as a flow map: the measure

**Status:** built behind the forks below, off-cluster only. Lane: `invincible-agent/lane/fin`.
**Brief** (architect, via Chris, 2026-11-04): one measure and one render archetype, both declared.
fin's measure comes first and proves on the EV fixture, with the levels declared in a test overlay.
cortex builds against the served edge table, and not before the finance data path is live on the
sandbox. This page covers only the measure.

## What the brief fixes

- **The measure** is a row in the same family as VAC and TCPI. Its inputs are a dataset URN, a
  `levels:` list of the columns that form the hierarchy (root → … → terminal attribute), a `value:`
  column, and `other_threshold`: the share below which rows collapse into an "All other" sink.
- **The output** is an edge table, `{source, target, value, sign, level}`, and nothing else.
- **The measure names no case.** It never says EAC, WBS or any category. EAC is the first row that
  uses it, with `levels` set to the program's own columns.
- **The render block** is served with `archetype: flow_decomposition`.

## The row: a second kind

Today a row's `inputs.state` names quantities from a closed vocabulary (`program.bac`, `period.*`,
`cumulative.*`), and the runner calls the module once per period. This measure reads named columns
of a named dataset and answers once, so it's a second kind of row, told apart by `inputs.dataset`:

```yaml
inputs:
  params: {program_id: {required: true}}     # window is refused for this kind (no period axis yet)
  dataset:
    urn: "urn:li:dataset:(...)"              # the row's own; FIN_DATASET_URN is not consulted
    banner: "<what a reader is told about these figures>"   # required, as FIN_DATASET_BANNER is
    levels: [<root column>, <column>, ..., <terminal column>]  # >= 2, distinct
    value: <numeric column>                  # not one of the levels
  other_threshold: "0.05"                    # a Decimal string, 0 <= t < 1; 0 collapses nothing
computation:
  module: agent_fleet.finance_agent.measure_modules.variance_decomposition
  function: flow_edges
render:
  shape: FLOW_DECOMPOSITION                  # the brief's `archetype: flow_decomposition`, below
  value_label: <label>
  unit: <unit>                               # optional
```

- **`levels[0]` is the root, selected by `program_id`.** The read keeps the rows whose root column
  equals the requested program, so there's one root node.
- **The shape must match the kind.** A dataset row draws as `FLOW_DECOMPOSITION`, and a state row
  draws as `MULTI_SERIES`. `render.series` is required only for the second.
- **There's no seed fallback.** The seed has no such dataset, so every call is a governed read of the
  row's URN as the caller, through the same `mesh_ticketed_read`. A refused or failed read is the
  same typed error the resolver gives: 403 `access_denied`, 422 `asset_too_large`, 502
  `asset_contract_violation` naming the rule, 503 unavailable.
- **The contract is the row's columns.** They must be present, level values non-null (read as
  strings), and the value numeric, finite and non-null. Other columns aren't selected.

## The computation

`flow_edges(*, root, paths, other_threshold)` is pure, Decimal and standard library only.

- A node is a path: `[root]`, then `[root, v1]`, and so on. Its signed value is the exact sum of
  `value` over the rows beneath it.
- There's one edge per (parent, child): `source` and `target` are the two paths, `value` is the
  absolute value of the child's signed sum, `sign` is `1` or `-1`, `level` is the child's depth
  (1 for the root's children), and `node_kind` is `other` for a sink and `item` for anything else.
- **The sink is marked, never matched by label** (ruled 2026-11-04). A consumer finds it by
  `node_kind`. The engine serves `render.other_label` for display, taken from the module's
  `OTHER_LABEL`, which is also the sink path's last element. A row doesn't declare it.
- **Conservation is the invariant.** At every node, the signed children, the sink included, sum to
  the node's signed value. A child whose signed sum is exactly zero carries no flow and gets no edge,
  and its whole subtree drops with it, even where its own children are nonzero and offset each other.
- **The collapse:** a child's share is its absolute value over the sum of its siblings' absolute
  values. When two or more siblings fall below `other_threshold`, they're replaced by one
  `[..parent, "All other"]` child carrying their signed sum. That child is terminal. A lone sibling
  below the threshold keeps its name, because an "All other" of one only renames it. A real level
  value named "All other" under a parent that gets a sink would share the sink's path, so the read
  is a 502 `asset_contract_violation` with rule `refused_by_module`, naming no row value.
- **The order is deterministic:** by level, then source, then value descending, then target.

## Forks, with the default built

| # | fork | built | the other reading |
| --- | --- | --- | --- |
| 1 | the sink's scope | **one per parent**, so the output stays a tree and conserves at every node. `level` lets the renderer merge a level's sinks | one sink node per level shared by every parent (a DAG) |
| 2 | the share's denominator | the parent's children, by absolute value | the level's total, or the root's |
| 3 | a lone child below the threshold | **keeps its name** | collapses into an "All other" of one |
| 4 | `source`/`target` | **paths** (lists of strings), unique by construction; the renderer labels by the last element | joined strings, which can collide |
| 5 | the shape's name | `FLOW_DECOMPOSITION`, because the vocabulary is upper case and the key is `render.shape` | `archetype: flow_decomposition` as written |
| 6 | the period axis | **none**: the sum is over every row of the program, and `window` is refused | a `period:` column and the `window` param |
| 7 | how the sink is marked | **ruled 2026-11-04:** `node_kind: item \| other` on each edge, and `render.other_label` for display | a label match, which cortex refused |

## Not met by this change

- **EAC.** No dataset carries an EAC-variance column. The EV fixture has period amounts
  (`bcws`, `bcwp`, `acwp`), and a row can't carry a formula. So the test overlay decomposes `acwp`
  over `[program_id, control_account, work_package]`, which proves the mechanics, not EAC. That
  overlay never shows a negative sign, so the signs are sealed in the module's tests.
  **Ruled 2026-11-04:** the EV fixture gets `bac` and `eac` columns (dag-tools, on asset #7's
  contract), and the EAC row declares value = `eac − bac`. Two things that ruling needs, neither
  built:
  - **The value is an expression.** Today `value:` names one column. The proposed form is
    `value: {minus: [eac, bac]}`: two numeric columns, each checked as `value` is now.
  - **A work-package figure must not be summed over its periods.** The fixture has one row per
    work package per period. If `bac` and `eac` are carried on every row, as `program_bac` is,
    a plain sum counts each work package once per period. The proposal is
    `inputs.dataset.per_path: once`: the value must be the same on every row of a terminal path,
    and it's taken once. Otherwise the read is a 502.
- **The archetype.** `FLOW_DECOMPOSITION` has to be in `capability_admission.KNOWN_ARCHETYPES` for
  the row to load (`test_a_measure_row_declares_its_render`). That's Lane 1's file. The ontology,
  binding and cortex contract registries are cortex's build, which comes after this.
- **Live.** Nothing has run on a cluster. A live leg like
  `tests/sandbox_e2e/test_variance_set_reads_the_ev_fixture.py` follows once the data path is live
  and the row is in an overlay the pod reads.
