# Step 0 spec — idp Layer 1 (Wave 1 test rows, authored before any TTL change)

Companion to [STEP0_DOMAIN_BUILD_SPEC.md](STEP0_DOMAIN_BUILD_SPEC.md). This is
the Wave-1 requirements artifact for the idp domain — every row is a real or
plausible user-question shape and the class it must resolve to. **Authored
before the verbatim definition transcription and re-ingest** so that the
TTL's contents are driven by these questions, not the other way around.

## Status

Phase 4 (idp Layer 1) is being retrospectively corrected after a premature
ingest. The 6 classes (`idp:Dataset`, `idp:Table`, `idp:Column`,
`idp:Dashboard`, `idp:Pipeline`, `idp:Job`) were already landed at
`domain=DATA_ENGINEERING` via the canonical pipeline with explicit-domain
override, but **with freshly-authored definitions instead of verbatim
transcription** from the existing hand-curated `data:Dataset` / `data:Dashboard`
classes. This creates the two-identities split the mro migration was
designed to eliminate.

This spec is the precondition for the corrective re-ingest. After Wave 2
gate confirms (or denies) the matrix held, the TTL will be updated with
verbatim transcription and re-ingested.

## Verified existing-definition inventory

```cypher
MATCH (c:OntologyClass) WHERE c.uri STARTS WITH "data:" RETURN c.uri, c.domain
```

Existing hand-curated `data:*` classes in Weaviate at `domain=DATA_ENGINEERING`:

| URI | Label | Definition |
|---|---|---|
| `data:Dataset` | Dataset | "A catalog-tracked dataset, table, view, or chart in DataHub. Queries about ownership, schema, lineage, freshness, tags, catalog enumeration, or asset profiles target this class. Examples: tables, datasets, dashboards, charts in the data warehouse." |
| `data:Dashboard` | Dashboard | "A dashboard in the analytics catalog. Subtype of Dataset for catalog-routing purposes." |

These definitions are the load-bearing content the resolver hybrid-searches
against. The "verbatim transcription" requirement from the canonicalization
pilot means `idp:Dataset.definition` MUST equal `data:Dataset.definition`
(modulo a leading sentence acknowledging this is the idp: full-IRI form). If
not, the resolver may land on `data:Dataset` for some queries and
`idp:Dataset` for others, depending on hybrid-search scoring — exactly the
two-identities bug.

## Wave-1 test rows (the spec)

Each row is a candidate user question, the target subject class, the
expected verb (or expected-generalist if no verb covers it yet — Phase 5
work), and the verb-coverage prediction *after* Phase 5 lands.

### Currently-in-matrix catalog queries (must stay green)

| Query (verbatim from `test_classify_route.py`) | Subject (now) | Subject (target) | Verb (Phase 5 target) |
|---|---|---|---|
| `What tables do you have?` | `data:Dataset` | `idp:Dataset` | `mesh:enumerateCatalog` |
| `List all datasets in the warehouse` | `data:Dataset` | `idp:Dataset` | `mesh:enumerateCatalog` |
| `Who owns the customer_silver table?` | `data:Dataset` | `idp:Table` (via subClassOf Dataset) | `mesh:lookupOwnership` |
| `Trace lineage of customers_gold` | `data:Dataset` | `idp:Dataset` | `mesh:traceLineage` |
| `What columns does orders_raw have?` | `UNKNOWN` (today) | `idp:Table` | `mesh:findSchema` |
| `Tell me about gold.sales.revenue_summary` | `data:Dataset` | `idp:Dataset` | `mesh:describeAsset` |

These rows are the **intermediate gate**: when re-ingesting the corrected
TTL, they MUST stay green and resolve-confidences must hold within noise
of current values. If confidences drop, the verbatim transcription missed
something and the re-ingest must be revisited before any verb migration.

### New rows added to the matrix in Wave 1 (validation that new classes are well-targeted)

For each new class (Column, Pipeline, Job), one happy-path candidate
question. Expected behavior at Wave-1 time: subject resolves correctly,
verb routing falls to generalist (no Phase 5 yet).

| Query | Subject (target) | Verb (Phase 5+ target) | Expected pre-Phase-5 |
|---|---|---|---|
| `What feeds the revenue column?` | `idp:Column` | `mesh:traceLineage` (extended) or new column-lineage verb | subject resolves, route = generalist |
| `Which pipeline populates customers_gold?` | `idp:Pipeline` | `mesh:describeAsset` (extended) or new pipeline-source verb | subject resolves, route = generalist |
| `When did the daily_kpi job last succeed?` | `idp:Job` | future job-run verb | subject resolves, route = generalist |

The Wave-1 "expected generalist" outcome is **deliberate** — Phase 5's verb
migration is what changes generalist → dispatch for these rows. Telemetry
will show `no_compatible_verbs_in_neo4j` rate rise temporarily for these
subjects; that's noted here so it isn't re-misdiagnosed at 1am.

## Hierarchy decisions (made explicit as routing-behavior choices, not modeling nicety)

```
prov:Entity
├── idp:Dataset
│   ├── idp:Table       ← subClassOf Dataset (compat-walk: 9 catalog verbs inherit Table coverage free)
│   └── idp:Dashboard   ← subClassOf Dataset (per existing data:Dashboard definition: "Subtype of Dataset for catalog-routing purposes")
├── idp:Column          ← prov:Entity directly (column-level queries are distinct from Table-level)
├── idp:Pipeline        ← prov:Entity (pragmatic: routing layer treats Pipelines as queryable objects, not processes; can move to prov:Activity if multi-hop queries need it)
└── idp:Job             ← prov:Entity (same pragmatic reasoning as Pipeline)
```

**Why Table + Dashboard subClassOf Dataset is a routing decision:**
After Phase 5, the 7 catalog-asset verbs (`describeAsset`, `traceLineage`,
`lookupOwnership`, `findSchema`, `filterByTag`, `checkFreshness`,
`assessImpact`) re-type their `_input_uri` to `idp:Dataset`. The compat-walk
walks `subClassOf*` from a subject up the hierarchy until it finds a verb
edge. So queries that resolve to `idp:Table` or `idp:Dashboard` reach those
7 verbs via subClassOf inheritance — zero per-subclass verb edges needed.
This is exactly how DataHub itself models the catalog and minimizes the
verb-migration surface.

## Predictions to log before the corrective re-ingest

Per the canonicalization pilot discipline: write predictions BEFORE running
so a surprise is a finding.

1. **Existing catalog matrix rows stay green** at 5/5 after re-ingest.
   Confidences for `data:Dataset`-resolved queries shift to `idp:Dataset`
   resolution at confidences within ±0.05 of current values (noise band).
   If confidences drop more than 0.05, transcription missed something.

2. **New Wave-1 rows resolve correctly** (subject → `idp:Column`/Pipeline/Job)
   with route = generalist (no compat-walk hits a typed verb yet).

3. **No existing non-catalog matrix rows perturb** (rotor, manuals, weather)
   — they're in a different domain and untouched by this work.

4. **Standing guard `test_no_compact_form_for_migrated_subjects` stays
   green** — the data: classes are NOT in that guard's migrated set yet.
   Phase 5 will add them when their verbs migrate.

5. **`no_compatible_verbs_in_neo4j` telemetry rate rises** for the 3 new
   no-verb-coverage classes (Column, Pipeline, Job), and ONLY for those
   subjects. Any other rise points at unrelated breakage.

## Sequencing reminder

- Wave 1: this spec (DONE — authored before TTL is corrected)
- Layer 1 corrective re-ingest: transcribe data:Dataset / data:Dashboard
  definitions verbatim, ingest via canonical pipeline at DATA_ENGINEERING,
  Weaviate UUID is deterministic so the upsert overwrites the prior
  fresh-definition records
- Wave 2: matrix 5x + Wave-1-new-row resolution test (the intermediate gate)
- Phase 5: re-type 10 catalog verbs onto idp:* subjects
- Wave 3: full route tests on the new dispatch paths, plus `data:*` retirement

## Mystery-seed scope re-scope

Discovery during this phase: the 41 `data:*` / PROV-O entries in
DATA_ENGINEERING are mystery-seeded (no reproducible TTL source in any
repo, same pattern as the 614 MAINTENANCE class problem). Phase 6 (shadow
rebuild) scope expands from "the 614" to **"all mystery-seeded classes
across MAINTENANCE and DATA_ENGINEERING"** — approximately 655 entries
across two domains. Shadow rebuild discipline holds: parallel namespace,
diff against live, run matrix against shadow, only cut over if green.
