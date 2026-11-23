# ADR-0064 — Classification propagates through derivation

**Status:** Proposed. This is design only: there is no code and no roll. It extends ADR-0052.
Amended 2026-11-06 to align with OpenDDIL ADR-0055 (see "Amendment 2026-11-06" at the end).
**Date:** 2026-11-05
**Deciders:** architect; governance board for the dimensions, the labels and the standing downgrade
rules
**Related:**
  - openddil: ADR-0055 — this ADR's classification model is aligned with it (amendment 2026-11-06).
  - iagent: [ADR-0052](ADR-0052-customer-data-enters-through-dlt-to-datahub-never-into-an-engine.md) —
    customer data enters through `dlt` into the catalog. This ADR extends it and does not supersede
    it (see "Relation to ADR-0052").
  - iagent: `invincible-agent#229` — the Keycloak token exchange for warehouse external OAuth.
    `passthrough` depends on it.
  - dag-tools: the six build steps below ride dag-tools 0.12.0 and later.
  - standards, cited by concept:
    - the unique identifier of the physical item that the asset of record names: ISO/IEC 15459
      (issuing agency, enterprise, serial), the scheme that IUID's unique item identifier also
      uses;
    - record identifiers: RFC 9562 (UUIDs);
    - the shared model of products, parts and serialized items: S-Series SX002D, the common data
      model.

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
   Since the 2026-11-06 amendment a label has several dimensions, and "the maximum" is taken one
   dimension at a time, as the most restrictive combination for that dimension's type (see
   "Classification is a label of declared dimensions").
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
- **No downgrade is automatic.** A standing downgrade is a declared rule with a named owner. Each
  time it applies, it applies as that owner's decision, and each application is recorded with the
  rule, its owner, the new level and the reason. The de-identifying aggregation (an aggregation that
  removes every identifying column) is the first such rule. Every other downgrade is a steward's
  decision.
- **The standing rule.** Dimensions, their vocabularies, sources, access modes and standing
  downgrade rules are registry rows. Nothing in dag-tools or iagent names a database, schema, table,
  column, program, dimension or level in code.

## Classification is a label of declared dimensions

*Added by the 2026-11-06 amendment.*

A label is a value for each of a set of declared dimensions. A dimension is a registry row with a
name, a type, a vocabulary and an owner. There are four types:

| type | the label carries | a reader may read when | the derived label takes |
| --- | --- | --- | --- |
| hierarchical | one value from an ordered vocabulary | the reader is cleared at that value or above | the most restrictive value of its sources |
| permissive set | a set of values | the reader holds at least one of them | the intersection of its sources' sets |
| restrictive set | a set of values | the reader holds every one of them | the union of its sources' sets |
| exclusionary | a set of values | the reader holds none of them | the union of its sources' sets |

**Access is the conjunction.** A reader may read a column only when every dimension of its label
admits them. One dimension that refuses is a refusal.

**The first dimensions:**
- `level`, hierarchical: the ordered levels this ADR began with.
- `program`, a restrictive set: the program cell of decision 2. It stays a row filter at ticket
  time, and decision 2 is unchanged (architect, 2026-11-06).
- `data_rights_holder`, a restrictive set.
- `nation`, a permissive set, which arrives from OpenDDIL.

The registry takes all four types. No exclusionary dimension is declared yet. Adding one, or adding
a value to a vocabulary, is a new row, not a code change.

**The rails.** The hierarchical dimension keeps `cleared_for:<level>`. A set dimension uses
`holds:<dimension>:<value>`. The validator refuses a label value outside its dimension's
vocabulary.

**Composition per type (architect, 2026-11-06).** The "derived label takes" column is decision 1's
"maximum" read one type at a time: the most restrictive combination of the sources' values.
- It is openddil ADR-0055 §3b's high-water table, unchanged: hierarchical takes the maximum,
  permissive the intersection of effective audiences, restrictive the union, and exclusionary the
  union.
- An unlabelled input gives an unlabelled result (§3b).
- openddil ADR-0055 §3a's rule is adopted too: a composable rollup splits by audience class. Our
  cell filter at ticket time already gives a reader exactly their classes' rows, so a rollup
  computed per cell is the same rule.

**An empty set.** For a permissive set it releases to nobody on that dimension. For a restrictive
or exclusionary set it means that dimension adds no restriction. A hierarchical dimension always
has a value. This is openddil ADR-0055 §1's table.

## A default is not a declaration

*Added by the 2026-11-06 amendment. The wording is adopted from openddil ADR-0055 §1a.*

> "A default is a label nobody stated about this record. It is not a declaration, and it labels
> nothing." (openddil ADR-0055 §1a)

§1a was signed 2026-11-06. This ADR adopts the wording; the signature belongs to openddil's record.

Here is how it applies in this ADR:
- **"An unlabelled source is the most restrictive" does not mean the source is stamped at the top
  level.** No default level is written for it, and nothing is emitted to the catalog for it as a
  label. It is closed to everyone until someone declares its label, as "Who decides what" already
  says.
- **A label is a declaration.** It names its owner and its origin (`board` or `catalog_tag`). A
  source row without an owner is a default, and it labels nothing.
- **A standing downgrade rule is a declaration too.** A rule with no named owner applies to nothing.

## Who decides what

- **Source labels** are set by the board, or by the catalog. Each label records its origin: `board`
  or `catalog_tag`. When the catalog's own tags exist, they take precedence over the board's rows
  without any code change.
- **Downgrades** are decided by stewards, one recorded decision at a time. A standing downgrade rule
  is declared once, with a named owner. Each application is that owner's decision and is recorded
  on its own. Nothing is downgraded without an owner.
- **The read rights** are rails the owner ratifies. For each level, the rail says which groups are
  cleared for it. For each value of a set dimension, it says which groups hold that value. The
  dimensions themselves are a registry that the rails check against. The governance lane owns these
  files. No code reads them until build step 5 serves a dataset's label.

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
3. **Classify the sources.** A registry of declared dimensions (since the 2026-11-06 amendment; the
   ordered levels are the first, hierarchical, one), and dataset-to-column-to-label rows with an
   owner and an origin. Anything unlisted is the most restrictive.
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

No question is open. The one that was:

1. **Which URN is the asset of record for a product?** *Closed 2026-11-06.* The choice was the
   catalog's dataset URN (the `dagster` platform object that `datahub_topaz_sync` creates) or the
   physical storage URN. Ruled 2026-11-05: the asset of record is the physical platform's URN, and
   the catalog sync registers under it. Step 4a's "carrying the catalog's dataset URN", in the
   verbatim rollout below, is read through this ruling.

---

## Appendix: build detail

For agents and engineers. Field names, file names and seals are here; the sections above carry the
decisions.

### Files and seals named by the steps

- `dagtools audit reads` — step 1's command; its output is a file, and test fixtures are synthetic.
- `classification/dimensions.yaml` — the declared dimensions, each with a name, a type, a vocabulary
  and an owner (step 3). It replaces `classification/levels.yaml` since the 2026-11-06 amendment.
  The ordered levels are the vocabulary of the hierarchical dimension. dag-tools mounts it at the
  path the levels file used.
- `classification/sources.yaml` — dataset, column, level, owner, origin of the label (`board` or
  `catalog_tag`) (step 3). Read this through the addendum at the end: these rows are instances of
  the source component, not a second file.
- `warehouse_source` — the generic asset kind of step 4a. Its `access` field is `brokered` or
  `passthrough`. Since the 2026-11-06 amendment its column labels are `{dimension: values}` maps, and
  the hierarchical dimension is required in each.
- `TableColumnLineage` metadata — required on Python assets that read a labelled source (step 4b).
- `cleared_for:<level>` — the PDP answer step 5 reads for the hierarchical dimension. Chris ruled the
  name on 2026-11-05 (ruling (c), quoted in `policy/level_readers.yaml`): "Relation:
  `cleared_for:<level>` -- `can_read` stays what it is." The rail file has one row per level mapped
  to groups, `ratified_by: owner`. The verbatim source text below still says `can_read:<level>`.
- `holds:<dimension>:<value>` — the rail for set dimensions (amendment 2026-11-06).
- `assets.authorize` — the broker call step 5 changes.
- Seals: a query issued through the resource without a tag fails (step 2); an asset whose inputs carry
  no label fails, and a declared downgrade without a reason fails (step 4d). Since the 2026-11-06
  amendment, three more fail: a standing downgrade rule with no named owner, an application of one
  that is not recorded, and a label value outside its dimension's vocabulary.

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
restrictive against. Since the 2026-11-06 amendment, that file is `classification/dimensions.yaml`,
and the ordering is the `level` dimension's vocabulary. The row's URN is the asset of record's: the
physical platform's (ruled 2026-11-05).

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

---

## Amendment 2026-11-06 — aligned to OpenDDIL ADR-0055

The architect directed three changes, so that this ADR and OpenDDIL ADR-0055 describe one model,
and closed open question 1 in the same amendment.
This ADR is still Proposed. The changes are made in place above, and this section records them.

1. **No automatic downgrade.** The bullet "One downgrade is automatic" is replaced by "No downgrade
   is automatic". A standing downgrade is a declared rule with a named owner, applied as that
   owner's decision and recorded per application. The de-identifying aggregation is the first such
   rule.
2. **Classification is a label of declared dimensions, of four types:** hierarchical, permissive
   set, restrictive set and exclusionary. Access is the conjunction. Our levels are the first
   hierarchical dimension, and the program cell is the first restrictive one. The new section
   "Classification is a label of declared dimensions" carries this. The architect ruled two
   readings on 2026-11-06:
   - composition per type is openddil ADR-0055 §3b, and its §3a is adopted;
   - the program dimension stays a row filter at ticket time.
3. **A default is not a declaration.** openddil ADR-0055 §1a's wording is adopted and cited. It has
   a section of its own, "A default is not a declaration". The three ways it applies here are Lane
   1's reading of the wording.
4. **Open question 1 is closed.** The asset of record is the physical platform's URN (ruled
   2026-11-05). See "Open questions".

Not changed: the verbatim source text in the appendix (blocks A, the standing rule, the rollout).
It records what was directed on 2026-11-05. Where it differs from the sections above, the sections
above hold.

## Edit 2026-11-07, directed by the architect

- openddil ADR-0055 §1a is recorded as signed 2026-11-06. It had been "recommended for signature".
- Three standards are cited, by concept, under **Related**: ISO/IEC 15459 with IUID, RFC 9562, and
  SX002D.
- No decision changes.
