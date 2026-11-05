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
    value: <numeric column>                  # or {minus: [<a>, <b>]}; never one of the levels
    per_path: sum                            # optional: sum (default) or once
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
  strings), and every value column numeric, finite and non-null. Other columns aren't selected.
- **A row's amount** is `value`, or `a − b` for `{minus: [a, b]}`, read exactly as `Decimal(str(x))`.
- **`per_path: once`** is for a figure that belongs to a terminal path and is carried on each of
  its rows, as a work package's budget is carried on each of its period rows. Every row of a path
  must have the same amount, and it's taken once. If they differ, the read is a 502 with rule
  `varies_within_path`, naming the column and no value. Under `sum` (the default) the rows add.

## The computation

`flow_edges(*, root, paths, other_threshold)` is pure, Decimal and standard library only.

- A node is a path: `[root]`, then `[root, v1]`, and so on. Its signed value is the exact sum of
  `value` over the rows beneath it.
- There's one edge per (parent, child): `source` and `target` are the two paths, `value` is the
  absolute value of the child's signed sum, `sign` is `positive`, `negative` or `zero`, `level` is
  the child's depth (1 for the root's children), and `node_kind` is `other` for a sink and `item` for anything else.
- **The sink is marked, never matched by label** (ruled 2026-11-04). A consumer finds it by
  `node_kind`. The engine serves `render.other_label` for display, taken from the module's
  `OTHER_LABEL`, which is also the sink path's last element. A row doesn't declare it.
- **Conservation is the invariant.** At every node, the signed children, the sink included, sum to
  the node's signed value.
- **A zero is emitted** (ruled 2026-11-04). A child whose signed sum is exactly zero gets an edge with
  `value` 0 and `sign: zero`, and its subtree is emitted below it, so each level still reconciles to
  its parent. A zero child is outside the collapse: it isn't in the share's denominator, it never
  falls below the threshold, and it doesn't count toward the two-below rule. A sink whose collapsed
  siblings net to zero is emitted the same way.
- **The collapse:** a child's share is its absolute value over the sum of its siblings' absolute
  values. When two or more siblings fall below `other_threshold`, they're replaced by one
  `[..parent, "All other"]` child carrying their signed sum. That child is terminal. A lone sibling
  below the threshold keeps its name, because an "All other" of one only renames it. A real level
  value named "All other" under a parent that gets a sink would share the sink's path, so the read
  is a 502 `asset_contract_violation` with rule `refused_by_module`, naming no row value.
- **The order is deterministic:** by level, then source, then value descending, then target.

## The served table: the contract cortex reads

The envelope of `POST /finance/measure/<id>` has `rows` set to the edge table and `render` copied
from the row, plus `render.other_label`. Each edge:

| field | what it is |
| --- | --- |
| `source`, `target` | paths: lists of strings, root first. The display label is the last element |
| `value` | non-negative: the absolute net, a cent-quantized float, with `value_exact` (the exact Decimal string) beside it |
| `sign` | `positive`, `negative` or `zero`: the sign of the target's net |
| `level` | the target's depth, `len(target) - 1`; 1 for the root's children |
| `node_kind` | `other` for a sink, `item` for everything else |

1. **Level is data.** Each edge carries `level`, and a node's depth is also `len(path) - 1`. A sink
   is terminal at its own depth, and no edge spans levels.
2. **The sink is marked by `node_kind == "other"`, never by its label.** Show `render.other_label`.
   No real node shares the sink's path: that is a 502 with rule `refused_by_module`.
3. **Sign is on the edge, and it's the target's.** The table is a tree, so every non-root node has
   exactly one incoming edge and its sign is that edge's sign. The root's net is only in `verdict`.
4. **`value` is non-negative, with `sign` beside it.** A zero edge arrives with `value` 0 and
   `sign: zero`. The renderer draws no band for it and lists the zeros on the parent's hover, e.g.
   "n items at zero".
5. **Every level closes by construction.** At each node the signed children, sinks and zeros
   included, sum to the node's own value, which is on its incoming edge. A mismatch is a defect in
   transit. A row missing from the asset isn't visible, because the table is the sum of the rows read.
6. **It's a tree.** One sink per parent, and paths make every node unique, so a node has one parent
   and its subtree is well-defined.
7. **Units and label are per table, in `render`:** `value_label` and the optional `unit`. No scale
   is applied; the figures are full units.

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
| 8 | a zero | **ruled 2026-11-04:** `sign: zero`, the edge emitted with its subtree, no band drawn | no edge, and the subtree dropped |
| 9 | a path figure carried on each row | **ruled 2026-11-04:** `per_path: once`, a 502 if it varies | per-row increments, or a separate snapshot asset |

## Not met by this change

- **EAC on the sandbox.** As ruled 2026-11-04, the EV fixture carries `bac` and `eac` (dag-tools
  #11), each repeated on all six of a work package's period rows, and the EAC row declares
  `value: {minus: [eac, bac]}` with `per_path: once`. That row is the test overlay
  `tests/finance/overlays/variance_decomposition_eac/`, proved here on a frame carrying #11's
  figures (three work packages at zero variance). A deployed row follows the data path going live.
- **The archetype.** `FLOW_DECOMPOSITION` has to be in `capability_admission.KNOWN_ARCHETYPES` for
  the row to load (`test_a_measure_row_declares_its_render`). That's Lane 1's file. The ontology,
  binding and cortex contract registries are cortex's build, which comes after this.
- **Live.** Nothing has run on a cluster. A live leg like
  `tests/sandbox_e2e/test_variance_set_reads_the_ev_fixture.py` follows once the data path is live
  and the row is in an overlay the pod reads.
