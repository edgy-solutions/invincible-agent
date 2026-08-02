# ADR-0035 — Two planes: process and data, joined by embedded provenance

**Status:** Accepted (plane boundary + provenance doctrine). Data-plane exemplar deferred to its own work.
**Date:** 2026-08-01
**Deciders:** Platform team
**Related:**
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — the process-workflow model. This ADR
    **bounds** it: the definition model describes the PROCESS plane and is not responsible for ingestion.
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) — the trust
    lifecycle. Its rung model is reused here for **source freshness** (§4), and its decision records are the
    process plane's own provenance.
  - [ADR-0024](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md) — standards composition. **ODCS's
    filed adoption wake fires here**: the data plane's output contract to the process plane is the first
    real boundary ODCS was reserved for.
  - [ADR-0025](ADR-0025-instance-plane-access-control-as-provenance.md) — access control captured as
    provenance; the same "the claim carries its own facts" instinct, applied to authorization.

## Context

The product's purpose, stated by the person who owns it:

> "the main thing iagent is trying to solve is providing a solution for non-technical business savvy
> domain experts to codify their processes so that workflows can be extracted from them and these
> workflows can be driven from data driven decisions to increase efficiencies and productivity. So the
> process of data extraction must be included in the workflow that they build. However, we might be able
> to think of this as a different plane that the base BPMN-like workflow and be part of ODCS/ODPS adjacent
> workflows. Maybe something to accelerate data engineers in building the ingestion/aggregations planes
> which feed the BPMN-like processes that process owner use. So potentially at this layer the answer is no
> the substrate is not part of the workflow except as input and output? But there is a requirement for
> full end to end traceability/provenance/lineage which a process owner should be able to see but this
> might be visible (read only) not editable."

The tension is real: **data extraction genuinely is part of the work**, and yet a domain expert authoring a
disposition process should not be authoring an S3 sensor. Both halves have to be true at once.

The evidence that they already are: the extraction→review sensor arc was built over weeks and **never fit
the workflow definition model** — not because the model was wrong, but because the sensor is not a process
step. It has no human audience, no approval, no domain semantics; it has cursors, ETags and idempotency
keys. The model kept declining to absorb it, and that was the model being right.

## Decision

### 1. Two planes, distinguished by who authors them

| plane | artifact | author | this codebase |
|---|---|---|---|
| **Process** | BPMN-like `WorkflowDefinition` | domain expert / process owner | ADR-0029, M3 |
| **Data** | ingestion + aggregation pipelines, ODCS/ODPS-adjacent | data engineer | the sensor pentad, doc-tools, the projectors |

**THE AUTHORSHIP CRITERION — a step belongs to a plane if its author belongs to that plane's discipline.**

This is deliberately a *social* test, not a technical one, because the technical tests all fail. "Is it
durable?" — both planes are. "Does it have steps?" — both do. "Does it touch a graph?" — both. The thing
that actually differs is **who must be competent to change it**, and that is exactly what the product
exists to protect: a domain expert must be able to change their process without a data engineer, and a
data engineer must be able to re-shape an ingestion without asking a domain expert's permission.

### 2. The substrate is INPUT and OUTPUT to a process workflow, never a step within it

A process definition consumes data and emits decisions. It does not contain the extraction. Concretely:
the grouped review's definition says *"review these parts"* — it does not say *"list S3 objects newer than
a cursor."*

A reasonable engineer will argue the opposite ("the extraction is part of the process, so model it"), and
the ADR's job is to say why not: **modelling the data plane in the process language would force domain
experts to read it.** Every ingestion concern that enters the definition vocabulary is a concept a
non-technical author must now step over to reach their own process. The definition language's expressive
budget is spent on the people it is for.

### 3. Provenance is the join, and it is READ-ONLY in the process plane

The full-traceability requirement is met by the process owner **seeing** the data plane, not editing it: a
workflow's inputs are traceable back through extraction, pipeline version, source and quality. Read-only
is not a limitation here, it is the boundary being honest — an editable view would make the process owner
the author of a data-plane artifact, which is precisely what the authorship criterion forbids.

### 4. Provenance is a FIELD, never a join — the doctrine

**No assertion enters a graph without its provenance riding in the same write.**

This has now been decided piecemeal five times — `ruleset_ref` (which rules decided), `resolved_via`
(which ladder rung answered), `requested_by` (which identity initiated), the decision record's
inputs-not-verdicts, and `authoritative_source`/`obtained_via`/`as_of`. Every one is the same move: the
claim carries its own origin, in the record, not in a lookup.

**Sidecar provenance decays, because the join is optional and optional joins stop happening.** Embedded
provenance cannot be skipped, because reading the claim IS reading its origin.

The block (see `src/iagent/provenance.py`, and the conventions entry):

| field | meaning |
|---|---|
| `authoritative_source` | who owns the truth (for BOM: the PDM system, **always**) |
| `obtained_via` | the path travelled: `direct` \| `etl` \| `snowflake` \| `manual-export` |
| `as_of` | the truth-date where knowable; **`unknown` is a sentinel, never a blank** |
| `ingested_at` | when we wrote it |
| `ingest_run` | the pipeline run id — chains claim → run → sensor → source object → ETag for free |
| `standing` | the source's trust rung **at write time**, frozen |

Two rules ride it:
- **Write-side mandatory.** The writer REFUSES an assertion without a complete block — `validate_ruleset`
  discipline applied to instance data. Loud at ingest, not discovered at query.
- **PROV terms where they fit** (`prov:wasDerivedFrom`, `prov:generatedAtTime`), per the standards
  posture's cherry-pick rule, so a future auditor meets vocabulary they already know.

**`standing` is frozen at write** because the record is immutable and *"what this source's standing is
now"* is a different fact from *"what it was when this was written."* Conflating them would let a later
promotion retroactively upgrade evidence gathered under weaker standing — the same regime-mixing ADR-0034
refuses.

### 5. Source authority is DISTANCE FROM TRUTH, not a ranking of peers

Where an authoritative system is guarded and hard to reach, groups build convenient copies — manual
exports, annotated sheets — and those copies become load-bearing while their export date recedes. **If the
graph ingests them as "sources", the architecture launders a stopgap into infrastructure.**

So the model encodes **lineage from the authoritative system**, not source identity: every assertion names
the same `authoritative_source` and differs in `obtained_via` + `as_of`. A consumer then reads *"per the
PDM system, as reflected by a manual export of unknown vintage"* — a materially different fact from *"per
last night's ETL"*, and one the HUD can show without anyone explaining it.

**The rule:** *a stopgap source is one whose freshness cannot be contracted — its assertions carry that
fact forever, and consumers decide what it is worth.*

### 6. Source freshness is trust-lifecycle shaped — reuse, don't reinvent

ADR-0034's rungs apply almost verbatim to data sources: a stopgap in commissioning-like standing (usable,
flagged, every consumer sees the caveat); promotable as its freshness contract firms up; **demotable when
it goes dark** — a manual export not refreshed in N days degrades its assertions' standing automatically.
That is ADR-0034's demotion tripwire applied to data, and it is what makes "stopgap" a *governed state*
rather than a vibe.

### 7. Stopgaps are instrumented to argue for their own retirement

Because provenance is structural, the question that matters becomes a query: *"every part whose only
usage evidence is a manual export older than 90 days."* That single query is the staleness policy, the
demotion tripwire, **and** the negotiating instrument for direct access to the authoritative system —
because the blocker there is organizational, not technical, and an owner can act on *"decisions are
keying off data averaging N days stale via manual exports."*

**A stopgap that generates the argument for its own removal is the only dignified end a stopgap gets.**

## Consequences

- **The sensor pentad is data-plane machinery** — retroactively explaining why it never fit the definition
  model. Not a gap in ADR-0029; a boundary neither document had drawn.
- **M3.2's definition model is NOT responsible for ingestion concerns.** This is the scope decision that
  had to precede the executor build, or M3.2 would absorb them by default.
- **ODCS's adoption wake fires** — the data plane's output contract to the process plane is the boundary it
  was reserved for. `as_of` / `obtained_via` are first-class in that contract, not annotations.
- Provenance queries become ordinary: the `instances_by_property` machinery already serves them and the
  HUD's provenance panel already has the slot.

## Non-goals

- **Specifying the data plane's authoring UX.** Accelerating data engineers is named as a goal in the
  quote above and deliberately not designed here.
- **A second workflow engine.** The data plane already runs on Dagster; this ADR draws a boundary, it does
  not commission a runtime.
- **Deciding the BOM vocabulary.** Its own work, authored in the ontology pass.

## Standards context (ARCHITECT-ASSERTED — recorded as claims, not as facts this ADR verified)

These are attributed rather than checked, per the standards posture's honesty rule:

- **S3000L** is in the prime manifest as sustainment's backbone (tagged SUSTAINMENT, original ingest).
- **Architect's assertion:** S3000L builds on **ISO 10303-239 / PLCS**, which would make S3000L-derived
  product-structure vocabulary simultaneously standards-cited and consistent with the committed ontology.
  *Not independently verified here.*
- **IOF Core** (also in the manifest) carries the upper-level part-of / component-of pattern.
- **ODCS/ODPS** were previously filed as adopt-as-export/import-schemas **on trigger**, the trigger being
  "when the boundary they serve goes live." §4's output contract is that boundary.

Where a `derivedFrom` citation cannot name a clause, it is **left empty and labelled** — the honest state,
not a TODO. The PCN classes shipped exactly that way.

## Open questions

1. **Does the process plane ever need to *trigger* a data-plane run?** ("re-extract this notice") — the
   triage card's Re-drive is the first instance, currently a direct call. If that becomes common, the
   boundary needs a declared request/response shape rather than a point-to-point call.
2. **What does the read-only provenance view actually render?** §3 rules it visible; the shape is UI work.
4. **CAPABILITY degradation is a second axis, and it has no query yet.** Sources differ in what
   they CAN SAY, not only in when they last spoke — a source that structurally cannot carry
   effectivity is degraded along an axis no `as_of` measures, and the mapping contract's
   `cannot_populate` section was always secretly recording it. So `staleness-by-consumer` should
   eventually gain a sibling: **capability-by-consumer** — *"which downstream decisions rest on
   sources that cannot express the field the decision needs?"* The data already exists (declared
   per mapping, before ingestion); only the query is missing. **Wake:** the first time someone
   asks why an answer fed by a lossy path cannot do effectivity-scoped matching — because the
   honest answer is in the contract and nobody will think to look there.

3. **Where do human annotations on a stopgap source live?** They are process knowledge, not source truth,
   and must not blend into it — arguably proto-decision-records. Ruled at ingestion time, per source.
