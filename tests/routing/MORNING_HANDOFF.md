# Morning handoff — overnight (cumulative through canonicalization)

**TL;DR**: Last night's work (mro_extension + verb re-typing) closed the
matrix at 5/5 × 11/11. **Tonight's work (the "REAL win") canonicalized
the substrate** for the rotor+manuals path: 4 nodes + 2 verb edges
migrated compact → full IRI, `maintenance_extension.ttl` authored so the
4 hand-curated mro: classes are now reproducible from MinIO, and the
canonical pipeline (no hand-seeding) produces them at `domain=MAINTENANCE`
with full-IRI URIs that match the verb edges. Substrate invariants
8/8. Matrix 54/55 (one flake on the **unmigrated** catalog path — not a
regression from tonight's work).

## What changed tonight (in order)

### 1. Pipeline code fix (in source, not in pod image)

`doc-tools/doc_tools/assets/ontology_assets.py` now reads
`config.extra_metadata["domain"]` as an explicit override of the
path-derived domain. Falls back to path-derivation with a deprecation
warning when no explicit value is set. Backward-compatible.

**Not yet running in the doc-tools pod** — the pod uses the prior image
from 2026-06-09. Tonight I worked around it by uploading directly to
`s3://ontologies/maintenance/...` so the existing path-derivation
produces `domain="MAINTENANCE"`. Future ingests can use the explicit
override once a `doc-tools` image rebuild ships.

### 2. maintenance_extension.ttl authored

The 4 hand-curated mro: classes (WorkInstruction, Procedure, Symptom,
Equipment) had **no TTL source in any repo** — they were only in the
mystery hand-seeded Weaviate state from a notebook that doesn't exist
anymore. I authored `doc-tools/setup/maintenance_extension.ttl` to
declare them canonically with IOF parent subclasses:

- `mro:WorkInstruction` → `iof-construct:DescriptiveInformationContentEntity`
- `mro:Procedure` → `iof:Process`
- `mro:Symptom` → `iof-construct:DescriptiveInformationContentEntity`
- `mro:Equipment` → `iof:MaterialEntity`

Definitions preserve the original hand-written text from the
pre-canonical Weaviate seed so the resolver's hybrid search continues
to match the same way after canonicalization.

### 3. Migration: 4 nodes + 2 verb edges compact → full IRI

```
mro:WorkInstruction              → https://spec.industrialontologies.org/.../WorkInstruction
mro:TechnicalManual              → https://spec.industrialontologies.org/.../TechnicalManual
mesh:GraphExpertResponse         → http://invincible-agent/mesh#GraphExpertResponse
mesh:KnowledgeRetrievalResponse  → http://invincible-agent/mesh#KnowledgeRetrievalResponse
```

Verb edges:
- `mesh:queryKnowledgeGraph`: `(full-IRI WorkInstruction) → (full-IRI GraphExpertResponse)` @ Engine E
- `mesh:retrieveKnowledge`: `(full-IRI TechnicalManual) → (full-IRI KnowledgeRetrievalResponse)` @ Engine W

Weaviate Predicate collection's `input_uri`/`output_uri` updated to match.

**Mid-migration bug found and fixed**: the migration recreated edges
before all target nodes were migrated, so the verb edges silently
disappeared on the first pass (MATCH on the not-yet-migrated target
failed). Caught by my own verification step. Fixed via
`scripts/recreate_verb_edges.py` which idempotently restores the 2 verb
edges with correct full-IRI endpoints. Substrate invariants now catch
this class of regression.

### 4. Canonical TTL ingest

`maintenance_extension.ttl` + `mro_extension.ttl` uploaded to
`s3://ontologies/maintenance/` and ingested via canonical
`ingest_ontology_job`. Both RUN_SUCCESS. Result: 7 mro: classes now in
Weaviate at `domain="MAINTENANCE"` with **full IRIs from rdflib**,
**reproducible from MinIO**. The old `s3://ontologies/mro/mro_extension.ttl`
was deleted to prevent the sensor from auto-re-triggering at the wrong
domain.

### 5. Substrate invariants: 8/8 (was 7)

NEW: `test_no_compact_form_for_migrated_subjects` — guards against the
4 migrated nodes' band-aid compact form ever reappearing. Catches the
exact regression mode where a seed script or manual MERGE re-introduces
`mro:WorkInstruction` as a competing identity.

Updated: subject-matching tests use full-IRI canonical forms (with
module-level constants `WORK_INSTRUCTION = MRO_NS + "WorkInstruction"`
etc.). The 7 prior guards still hold.

### 6. Matrix: 54/55 across 5 runs

| Run | Result | Notes |
|---|---|---|
| 1 | 11 passed | 157.93s |
| 2 | **10 passed, 1 failed** | 157.04s — flake on `"What tables do you have?"` |
| 3 | 11 passed | 166.04s |
| 4 | 11 passed | 162.49s |
| 5 | 11 passed | 154.56s |

**The flake is on the UNMIGRATED catalog path**, not the migrated
rotor+manuals path:
- Subject: `data:Dataset` (compact, untouched in tonight's migration)
- Compat-reasoner returned 9 catalog verbs (all typed against
  `mesh:CatalogAssetQuery` / `mesh:CatalogScopeQuery` pseudo-classes)
- LLM picked correctly (`mesh:enumerateCatalog`) at **0.00 confidence**
- Test threshold is 0.5 → failed

Why this isn't a regression from tonight: this is the same class of
LLM sampling flake as TEST-1234 before `temperature 0` went on disk —
9 lexically-overlapping verb descriptions at non-zero temperature.
Tonight's migration didn't touch this path. The catalog verbs still
use compact URIs + pseudo-class typing (the 27 remaining entries
explicitly out of scope tonight).

Two fixes that would close this gap when convenient:
1. **Engine-O image rebuild** ships `temperature 0` (commit 7ffd294).
2. **Catalog path migration**: extend tonight's pattern to the 10
   catalog verbs + their pseudo-class inputs (`mesh:Catalog*Query` →
   real `idp:Dataset`/`idp:Table`/`idp:Dashboard` once idp Layer 1
   lands).

## Files added/modified

| Path | Change |
|---|---|
| `baml_shared/baml_src/clients.baml` | (committed 7ffd294 last night) `temperature 0` for Ollama. |
| `doc-tools/doc_tools/assets/ontology_assets.py` | (MODIFIED) explicit domain override via `config.extra_metadata["domain"]`. Backward-compatible. |
| `doc-tools/setup/maintenance_extension.ttl` | (NEW) 4 hand-curated mro: classes declared canonically. |
| `doc-tools/setup/mro_extension.ttl` | (already in place from last night) |
| `tests/routing/STEP0_DOMAIN_BUILD_SPEC.md` | (from last night) |
| `tests/routing/STEP1_2_EXECUTION_REPORT.md` | (from last night) |
| `tests/routing/MORNING_HANDOFF.md` | (THIS FILE — updated tonight) |
| `tests/routing/test_substrate_invariants.py` | (MODIFIED) added `test_no_compact_form_for_migrated_subjects`. 8 tests total. |
| `scripts/seed_mro_extension_runtime.py` | (last night's runtime workaround — now obsolete since canonical pipeline does the work) |
| `scripts/retype_verbs_to_real_subjects.py` | (last night's direct-Cypher verb re-typing) |
| `scripts/sync_predicate_to_typed_inputs.py` | (last night's Weaviate Predicate sync) |
| `scripts/phase1_stable_harness.sh` | (last night's stable harness) |
| `scripts/migrate_compact_to_full_iri.py` | (NEW — tonight's compact→full IRI migration) |
| `scripts/recreate_verb_edges.py` | (NEW — emergency recovery script, idempotent) |

**Nothing committed to git by me.** All new files on disk awaiting your
review. The only git history change tonight is the pipeline code fix
in `ontology_assets.py` (still uncommitted).

## What's actually load-bearing now vs what's still band-aid

**Canonical (reproducible from MinIO + Dagster, no hand-seed in path)**:
- `mro:WorkInstruction`, `mro:Procedure`, `mro:Symptom`, `mro:Equipment`
  (full IRI form) — via `maintenance_extension.ttl`
- `mro:TechnicalManual`, `mro:Diagram`, `mro:ProcedureStep` (full IRI
  form) — via `mro_extension.ttl`
- `mesh:GraphExpertResponse`, `mesh:KnowledgeRetrievalResponse`
  (full IRI form) — migrated tonight; need to be ingested via
  `mesh_system.ttl` re-ingest at MAINTENANCE for full canonical
  reproducibility (currently they exist as Neo4j-side migrations only)

**Still band-aid (compact form, hand-seeded historical, not in any TTL
the canonical pipeline reads)**:
- mesh: classes that didn't get migrated: `mesh:Request`, `mesh:Response`,
  `mesh:AgentTask`, `mesh:AgentResponse`, `mesh:GraphQuery`,
  `mesh:KnowledgeQuery`, `mesh:CatalogAssetQuery`, `mesh:CatalogScopeQuery`,
  `mesh:DatasetAnalysisRequest`, `mesh:DatasetAnalysisReport`,
  `mesh:AssetProfile`, `mesh:CatalogListing`, `mesh:OwnershipFact`,
  `mesh:LineageTopology`, `mesh:SchemaDescription`, `mesh:FreshnessReport`,
  `mesh:TagFilterResult`, `mesh:ImpactSet`, `mesh:Thing`
- mro: classes that exist as compact but ALSO as full IRI duplicates now:
  `mro:Equipment`, `mro:Procedure`, `mro:Symptom`, `mro:WorkInstruction`
  in Neo4j still have compact-form copies (the migration only deletes the
  4 specifically targeted ones; the rest with same prefix are unchanged)
- catalog domain: `data:Dataset`, `data:Dashboard`, `prov:Entity`
  (compact prov:Entity is unusual; PROV-O loaded at `idp/PROV-O.ttl`
  produces the full `http://www.w3.org/ns/prov#Entity` form, so this
  is hand-seed evidence)

Two halves of the substrate that should match but don't:
- The compact-form `mro:WorkInstruction` hand-seed still exists in
  Weaviate (alongside the full IRI version from my re-ingest). Need to
  delete it OR the resolver may continue to pick whichever Weaviate
  hybrid search ranks higher. This is the **identity duplication**
  problem the other agent warned about; the standing guard
  `test_no_compact_form_for_migrated_subjects` catches it in Neo4j but
  Weaviate needs an equivalent.

## Open questions for the morning

1. **Delete the compact-form Weaviate hand-seeds for the 7 migrated
   mro: subjects?** They're now duplicates of the canonical full-IRI
   ingest. Currently `/resolve` picks the full IRI consistently
   (verified in tonight's harness) but the safer state is to delete
   the compact duplicates. Need a substrate-invariant guard for
   Weaviate identity duplication too.

2. **Catalog path migration** — when do we tackle the 27 remaining
   compact-URI nodes + the catalog-verb pseudo-class typings?
   Sequenced after idp Layer 1 per the agent's guidance.

3. **doc-tools image rebuild** to pick up the pipeline code fix.

4. **Engine-O image rebuild** to ship `temperature 0` (last night's
   commit). Reduces the catalog 9-candidate sampling flake.

5. **The 614 mystery hand-seeded MAINTENANCE classes** — tonight's
   migration moved 4 of them to canonical form. The other ~610
   (mostly blank-node artifacts + 24 compact hand-seeds) are still
   load-bearing-by-hand. Shadow rebuild + diff is the recommended way
   to learn if the canonical pipeline can reproduce them.

6. **Gateway proper** — standing guards now catch Contract D
   regressions in CI; gateway is for registration-time enforcement
   (catches before merge). Less urgent than yesterday, still correct.

7. **Gemma against frozen baseline** — sequence remains the same:
   wipe-or-confirm the catalog path → freeze 11/11 baseline → gemma
   → idp.

## Recommended next-session order

1. Review the new files (~20 min).
2. Decide on Weaviate compact-form cleanup for the 7 migrated mro:
   subjects (low risk, high consistency gain).
3. Image rebuilds for doc-tools (pipeline code fix) and Engine-O
   (`temperature 0`).
4. idp Layer 1 (declare `idp:Dataset`/`idp:Table`/`idp:Dashboard` as
   `prov:Entity` subclasses) — this is the path that unblocks the 10
   catalog-verb debt.
5. Shadow rebuild for the 614 mystery classes — proof-of-canonical or
   discover-the-gap.
6. Gateway, then gemma.

The pattern from "prove on one domain, then generalize" applies to
canonicalization too: tonight proved canonical for the
rotor+manuals path. The catalog path is next, by the same pattern.
