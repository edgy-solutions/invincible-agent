# ADR-0064 — Classification propagates through derivation

**Status:** Proposed. This is design only: there is no code and no roll. It extends ADR-0052.
**Date:** 2026-11-05
**Deciders:** architect; governance board for the labels and the downgrade rules
**Related:**
  - iagent: [ADR-0052](ADR-0052-customer-data-enters-through-dlt-to-datahub-never-into-an-engine.md) —
    customer data enters through `dlt` into the catalog. This ADR extends it and does not supersede
    it (see "Relation to ADR-0052").
  - iagent: `invincible-agent#229` — the Keycloak token exchange for warehouse external OAuth.
    `passthrough` depends on it.
  - dag-tools: the six build steps below ride dag-tools 0.12.0 and later.

---

## Context

A dataset-level label is not enough. A derived product mixes columns of different sensitivity: one
column may be public while its neighbour identifies a person. Giving the whole product the label of
its most sensitive source column over-restricts it, and giving it the label of its least sensitive
one leaks. The label has to live on the column and move with the column.

A dataset that is scoped by row is not one level either. The same table can be open to one program's
people for their own rows and closed to everyone else for the rest. Calling the whole dataset
"restricted" erases that difference, and calling it "open" gives the rows away.

So this ADR decides three things: where a label lives, how it moves when data is derived, and who
may lower it.

## Decision

Three sentences are normative. They are quoted in full.

1. **Classification is per column and propagates along column lineage: an output column's label is
   the maximum of the source columns it was computed from. Undeclared column lineage falls back to
   the table-level maximum. An unlabelled source is the most restrictive. Deny by default.**
2. **Row scope is a cell: a label carried as a predicate on a column, enforced by the broker as a
   filter at ticket time, never as a classification of the whole dataset.**
3. **A source is an asset with a declared access mode: `brokered` (the service identity reads, and
   the ticket is cut to the product's labels) or `passthrough` (the caller's token is exchanged for
   their own session, and the read runs as them).**

Beyond the three sentences:

- **Every read is attributed.** The warehouse query tag names the principal: either
  `pipeline:<name>` or the verified on-behalf-of identity of the person who asked. A read with no
  attribution is a defect.
- **Downgrades are recorded decisions.** A downgrade is a record of three things: the new level,
  the reason, and the steward who decided it. A downgrade without a reason is refused.
- **One downgrade is automatic.** An aggregation that removes every identifying column is
  downgraded automatically, with a fixed reason. Every other downgrade is a steward's decision.
- **The standing rule.** Levels, sources, access modes and downgrade rules are registry rows.
  Nothing in dag-tools or iagent names a database, schema, table, column, program or level in code.

## Who decides what

- **Source labels** are set by the board, or by the catalog. Each label records its origin: `board`
  or `catalog_tag`. When the catalog's own tags exist, they take precedence over the board's rows
  without any code change.
- **Downgrades** are decided by stewards, one recorded decision at a time. The automatic downgrade is
  the only exception, and its reason is fixed.
- **The read rights** per level are a rail the owner ratifies: for each level, which groups may read
  it. The levels themselves are a registry the rail checks against. The governance lane owns both
  files. No code reads them until build step 5 serves a dataset's level.

What a reader of a product can see follows from this. A reader sees the columns whose labels the
reader's groups may read, and within those columns only the cells they hold. A column the reader may
not read is absent from the ticket, not blanked. A source nobody labelled is closed to everyone
until someone labels it.

## Access modes

- **`brokered`.** The service identity reads the source. The broker then cuts the ticket to what the
  product's labels and the caller's rights allow. The caller never holds a warehouse session.
- **`passthrough`.** The caller's own token is exchanged for their own warehouse session, and the
  read runs as them. If the caller has no entitlement of their own, the read is refused.

`passthrough` depends on the existing token exchange tracked as `invincible-agent#229`. This ADR
builds nothing new for it.

## Rollout

Six steps, in order. Steps 1 and 2 come first, this week, because they produce the scope numbers the
board needs. Steps 3 to 5 follow once this ADR is Proposed. The work happens in its own worktree, and
the qualification session is separate. Chris merges dag-tools, and the versions ride dag-tools 0.12.0
and later. The full text of each step is in the appendix.

1. **Audit the reads.** A read-only report of which tables the service identity reads, which asset
   explains each, and which tables no asset explains. It comes first because it measures the problem.
2. **Attribute every read.** The warehouse resource tags each query with who asked, which asset, and
   which run. A query without a tag fails its test.
3. **Classify the sources.** A registry of ordered levels, and a registry of dataset-to-column-to-level
   rows with an owner and an origin. Anything unlisted is the most restrictive.
4. **Declare source assets and propagate.** Each source becomes an asset with a declared access mode.
   On materialisation each output column takes the maximum of its sources, and labels and downgrade
   decisions are emitted to the catalog. An asset whose inputs carry no label fails.
5. **Enforce at the broker.** The ticket is cut to the columns and cells the caller may see, and
   `passthrough` sources use the caller's own session. Nothing hard-codes a level.
6. **The data plane inherits step 5.** No dag-tools work; the two-tier rule becomes one policy row.

## Relation to ADR-0052

This ADR extends ADR-0052. ADR-0052 decides how customer data enters: through `dlt` into the catalog,
never into an engine. This ADR decides how the sensitivity of that data is recorded and carried once
it is in. It does not supersede ADR-0052, and nothing in ADR-0052 changes.

## Open questions

1. **Which URN is the asset of record for a product?** Either the catalog's dataset URN (the
   `dagster` platform object that `datahub_topaz_sync` creates) or the physical storage URN. This is
   open. Step 4a's "carrying the catalog's dataset URN" answers it for sources, not for derived
   products.

---

## Appendix: build detail

For agents and engineers. Field names, file names and seals are here; the sections above carry the
decisions.

### Files and seals named by the steps

- `dagtools audit reads` — step 1's command; its output is a file, and test fixtures are synthetic.
- `classification/levels.yaml` — ordered levels (step 3).
- `classification/sources.yaml` — dataset, column, level, owner, origin of the label (`board` or
  `catalog_tag`) (step 3). Read this through the addendum at the end: these rows are instances of
  the source component, not a second file.
- `warehouse_source` — the generic asset kind of step 4a. Its `access` field is `brokered` or
  `passthrough`.
- `TableColumnLineage` metadata — required on Python assets that read a labelled source (step 4b).
- `can_read:<level>` — the PDP answer step 5 reads. The rail file has one row per level mapped to
  groups, `ratified_by: owner`.
- `assets.authorize` — the broker call step 5 changes.
- Seals: a query issued through the resource without a tag fails (step 2); an asset whose inputs carry
  no label fails, and a declared downgrade without a reason fails (step 4d).

### Source text, block A (verbatim)

```
A. ADR-0064 "classification propagates through derivation",
   Proposed, with three load-bearing sentences:
   1. Classification is per column and propagates along column
      lineage: an output column's label = max of the source
      columns it was computed from. Undeclared column lineage
      falls back to table-level max. Unlabelled source = most
      restrictive. Deny by default.
   2. Row scope is a cell: a label carried as a predicate on a
      column, enforced by the broker as a filter at ticket time,
      never as a classification of the whole dataset.
   3. A source is an asset with a declared access mode:
      `brokered` (service identity reads; ticket cut to the
      product's labels) or `passthrough` (caller's token
      exchanged for their own session; read runs as them).
   Plus: every read is attributed (`pipeline:<name>` or
   on_behalf_of in the warehouse query tag); downgrades are
   recorded decisions {level, reason, steward}; aggregation
   that removes every identifying column is an automatic
   downgrade with a fixed reason, everything else is a
   steward's. Six build steps below, in order, as the ADR's
   rollout section. Written for a governance board reader
   first; the agents' detail in an appendix. Extends ADR-0052.
B. Topaz rails (gov): `can_read:<level>` as a rail file — one
   row per level → groups, ratified_by: owner; levels
   themselves a registry file the rail validates against. No
   code reads it until dag-tools step 5 serves a dataset's
   level.
C. Keycloak exchange for warehouse external OAuth is the
   existing #229 exchange item; note in the ADR that
   `passthrough` depends on it, nothing new to build here.
```

### The standing rule (verbatim)

```
levels, sources, access modes and downgrade rules are registry
rows; nothing in dag-tools or iagent names a database, schema,
table, column, program or level in code.
```

### The rollout (verbatim)

```
Step 1 — `dagtools audit reads` (read-only, first). Query
  history for the service identity → tables read → mapped to
  the asset that read them (run id from query tag where
  present, schedule correlation otherwise) → report: tables
  per asset, assets per table, and tables no asset explains.
  Output is a file, no names in the repo's tests (fixtures
  synthetic).
Step 2 — attribution. The warehouse resource sets the query
  tag to {principal, asset_key, run_id}; principal is
  `pipeline:<name>` or the gateway's verified on_behalf_of
  (#6, observe mode is enough to read it). Seal: a query
  issued through the resource without a tag fails the test.
Step 3 — source classification registry. `classification/
  levels.yaml` (ordered levels) and `classification/
  sources.yaml` (dataset → column → level, owner, origin of
  the label: `board` | `catalog_tag`). Unlisted dataset or
  column = most restrictive. The catalog's own tag ingestion
  (what the governance tool will write) replaces yaml rows by
  precedence, no code change.
Step 4 — source assets + propagation.
  a. `snowflake_source` (name generic: `warehouse_source`)
     asset kind: observable source asset carrying the
     catalog's dataset URN so lineage joins the catalog's own
     ingestion; column labels from step 3; `access: brokered |
     passthrough` declared on the asset.
  b. On materialisation, each output column's label = max
     over its source columns via column lineage (dbt column
     lineage; `TableColumnLineage` metadata required on Python
     assets that read a labelled source; absent → table max).
  c. Emitted to the catalog as column-level terms plus a
     decision aspect for any downgrade {level, reason,
     steward}; automatic downgrade when the SQL/plan removes
     every identifying column, reason fixed.
  d. Seal: an asset whose inputs carry no label fails; a
     declared downgrade without a reason fails.
Step 5 — broker enforcement. `assets.authorize` reads the
  dataset's column terms and the caller's `can_read:<level>`
  answers from the PDP; the ticket is cut to the columns the
  caller may see (projection) and the cells they hold
  (filter); `passthrough` sources exchange the caller's token
  instead of using the service identity, refusing when the
  caller has no own entitlement. Nothing hard-codes a level.
Step 6 — (iagent, no dag-tools work) the data plane inherits
  step 5 unchanged; the two-tier rule is one policy row.

Order: 1 → 2 this week (they produce the scope numbers for the
board); 3 → 4 → 5 after the ADR is Proposed. Own worktree; the
qual session is separate. Chris merges; versions ride 0.12.0+.
```


### Addendum: the two dag-tools answers, accepted 2026-11-05

Both were questions the dag-tools lane was asked to settle before step 4 began. Both were measured
rather than argued, and both are held by named regression tests in dag-tools; this section records
what was accepted, not where it is enforced.

**The component's YAML is the registry row, and there is no second sources file.** Step 3's
`classification/sources.yaml` collapses into instances of step 4a's `warehouse_source`: one
instance's `attributes:` block *is* a row — the catalog's dataset URN, the column labels, the
declared access mode, and any downgrade declaration. dag-tools ships the kind, the deployment's YAML
carries the rows, and a row arrives and leaves as data, which is the standing rule restated rather
than relaxed. A parallel file would have been a second place for the same fact to be wrong in. The
ordered levels stay a file of their own, because an ordered vocabulary is not an instance of
anything, and because "anything unlisted is the most restrictive" needs one ordering to be most
restrictive against.

**The compat floor holds, and the one thing that would move it is scheduling in YAML.** The Dagster
the deployment runs was measured against step 1's shipped component rather than assumed about: the
component loads there, materialises there, and reports numbers identical to current. What that
version refuses is an unknown *top-level* key in a component file, and the refusal fails the whole
code-location load rather than just the unrecognised block — so staying inside `type:` and
`attributes:`, with every attribute a plain scalar or mapping the component validates itself instead
of handing to the resolver, is not a style preference but the condition of being deployable at all.
Steps 3 to 5 stay inside that envelope, and the floor does not move for them. The known exception is
an automation condition expressed in YAML: that is exactly the block the floor rejects, already
measured on another component. If step 4 wants a schedule, the schedule comes from Python.

Step 1 is built and merged (dag-tools `#17`), which is what let both answers be measurements rather
than positions. Its report — the reads no asset explains — is also the number step 2 exists to drive
to zero.
