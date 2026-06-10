# Step 1 & Step 2 execution report — 2026-06-10 (overnight)

Companion to [STEP0_DOMAIN_BUILD_SPEC.md](STEP0_DOMAIN_BUILD_SPEC.md). This
documents what shipped, what surfaced, and what's open.

## Status

| Step | Status | Predict | Actual |
|---|---|---|---|
| 1 (mro extension) | DONE | manuals subject → `mro:TechnicalManual` | resolves @ 0.98, durable across pod restart |
| 1 intermediate gate | PASS | subject moves off `mesh:GraphQuery` | confirmed |
| 2 (verb re-typing) | DONE | both pseudo-class violations gone | Neo4j substrate clean, Predicate collection synced |
| 3 (verification) | IN PROGRESS | 11/11 stable harness, phantom scan 0, abstention green | abstention 13/13 green; harness running; phantom scan 0 |

Substrate invariants test (`test_substrate_invariants.py`) — **6/6 PASS**.

## What surfaced (deviations from the spec)

### 1. Canonical ingest pipeline domain-mapping gap

`ingest_ontology_to_jena` (`doc-tools/doc_tools/assets/ontology_assets.py:87`)
derives the Weaviate `domain` property from the s3 path's first segment:

```python
domain = parts[0]  # s3://ontologies/{domain}/{file}
```

This means `s3://ontologies/mro/mro_extension.ttl` lands with `domain="MRO"`.
But the Engine-O resolver queries with `domain="MAINTENANCE"`. So classes
ingested via the canonical path are invisible to the resolver — the gate
failed on the first attempt for this reason.

The 614 existing MAINTENANCE-domain `OntologyClass` records in Weaviate were
NOT seeded by the canonical pipeline — they came from a path that isn't in
the `invincible-agent` or `doc-tools` repos (likely an interactive notebook
or external repo). The hand-written `definition` text (e.g., *"A formal
documented procedure for performing maintenance or assembly work, including
steps, tools, hazards, and personnel roles..."*) is not what rdflib would
extract from a TTL.

**Tonight's workaround**: mirrored the historical hand-seeded path with
`c:/tmp/seed_mro_extension_runtime.py` — direct writes to Weaviate
(`domain="MAINTENANCE"`, compact URIs) and Neo4j (`OntologyClass` MERGE) for
the 3 new classes. The TTL did successfully land in Jena
(`http://internal/mro` named graph, 18 triples) as the canonical source of
truth — that's the spec-conformant record. The Jena→runtime substrates path
is the broken segment.

**Follow-up — pick one (or both)**:
- (a) Fix the ingest job to either accept a `domain` config field or compute
  it from a path-to-domain mapping (`mro` → `MAINTENANCE`, `idp` →
  `DATA_ENGINEERING`, etc.) declared in a config map.
- (b) Make the resolver query multiple domains (e.g.,
  `domain IN ['MAINTENANCE','MRO']`), so the s3-path naming convention
  matches the substrate categories the resolver looks under.
- (c) Recommended: (a). The s3 path is the ontology's *source*, not its
  semantic *domain*. Conflating them breaks future scenarios where one
  domain has multiple source TTLs from different upstream ontology stewards.

### 2. Verb re-typing via direct Cypher, not via the mesh-registrar gateway

The spec assumed Step 2 would happen through the gateway (option C from
`c:/tmp/plans/mesh_registrar_gateway.md`). The gateway is a multi-night
build (new microservice, SDK changes across all engines, DataHub
re-registration). For tonight, the verb re-typing happened via direct
Cypher (`c:/tmp/retype_verbs.py`) — the same mechanism the existing
`seed_sandbox_predicates.py` uses, so this is consistent with the current
substrate-seeding pattern, not a new band-aid.

**The gateway is still the right architecture** — Contract D
enforcement at registration time, single source of truth for the registry,
the only sound place to catch a regression before it lands. Tonight's
direct-Cypher path achieves the same end-state but doesn't prevent the
*next* registration from re-introducing a pseudo-class.

**Standing guard added** to compensate: `test_substrate_invariants.py`
asserts no verb's `_input_uri`/`_output_uri` references a pseudo-class or
phantom OntologyClass. This catches a regression at CI time even without
the gateway in place. It's the registration-time check moved to test time
— second-best, but enforces the same invariant.

**Follow-up**: build the gateway proper. Spec is in
`c:/tmp/plans/mesh_registrar_gateway.md`. With the standing guards in
place, the urgency is lower than before tonight — a regression now fails
loudly in CI rather than silently in production.

### 3. Orphan subClassOf bridges to pseudo-classes remain

After re-typing, the OntologyClass nodes `mesh:GraphQuery` and
`mesh:KnowledgeQuery` still exist, with subClassOf edges from:

- `mesh:GraphQuery` ← `mro:Procedure`, `mro:Symptom`, `mro:Equipment`,
  `mro:WorkInstruction`, `mesh:Request`
- `mesh:KnowledgeQuery` ← `mesh:Request`

These were the legacy verb-binding bridges (before the verbs were typed
directly against the real subjects). They're now functionally inert — no
verb is typed against the pseudo-class, so the compat-walk from
`mro:Procedure` walking up subClassOf to `mesh:GraphQuery` finds nothing.

**Not dropping tonight** because the matrix has not yet shown a regression
attributable to these. The `mro:Procedure`/`mro:Symptom`/`mro:Equipment`
subjects don't currently appear in the routing matrix — the queries that
would use them aren't in the test suite. Dropping the subClassOf bridges
*and* leaving these subjects with no verb coverage would silently degrade
their routing without any test catching it.

**Follow-up**: when the matrix adds coverage for procedure/symptom/equipment
queries, either (a) drop the bridges and add real verbs typed against those
subjects, or (b) keep the bridges and add the verbs at `mesh:GraphQuery`
level (but Contract D will reject that, which is correct).

### 5. Wider Contract D debt: 10 more catalog verbs typed against pseudo-classes

While scanning the substrate to confirm tonight's two fixes didn't create
collateral damage, I queried *all* registered verbs and their `_input_uri`
typings. The result revealed a pre-existing debt that the spec didn't surface
because the matrix hasn't exercised it yet:

| Pseudo-class input | Verbs typed against it |
|---|---|
| `mesh:CatalogAssetQuery` | `mesh:assessImpact`, `mesh:checkFreshness`, `mesh:describeAsset`, `mesh:filterByTag`, `mesh:findSchema`, `mesh:lookupOwnership`, `mesh:traceLineage` |
| `mesh:CatalogScopeQuery` | `mesh:enumerateCatalog` |
| `mesh:DatasetAnalysisRequest` | `mesh:analyzeDataset` |
| `mesh:AgentTask` | `mesh:analyzeWithCodeAgent` |

Tonight fixed 2 of 12 total Contract D pseudo-class violations. The other 10
are catalog / data-mesh verbs whose proper subjects don't exist yet —
`idp:Dataset`, `idp:Table`, `idp:Dashboard` (Layer 1 work, GMS-blocked on the
verb side). When the `idp` extension lands tomorrow / next session, these
10 should move to real `idp:*` subjects.

**Standing guard for this**: `test_pseudo_class_debt_matches_known_set`
asserts the *exact* set of debt verbs. Two failure modes both alert:
1. A new verb gets added against an existing pseudo-class → debt expansion
2. An existing debt verb gets fixed → reminder to move it from
   `PSEUDO_KNOWN_DEBT` to `PSEUDO_FIXED`

This is the "list the problems" pattern — failure as visibility, not just
as deny-list.

### 4. Engine-O image rebuild not done tonight

The `temperature 0` BAML edit was committed (7ffd294) but takes effect only
after BAML re-compile + Engine-O image rebuild + redeploy. That's the same
build cycle as the gateway, deferred together.

**Impact for tonight's 11/11 prediction**: the TEST-1234 boundary case is
likely to still flake 1-in-5 on sampling. Predict 10/11 deterministic +
1/11 with the known TEST-1234 sampling flake (8/11 on flake-runs, 11/11 on
clean runs). NOT a regression — this is the same state as the last
post-temperature-0-commit stable run.

**Follow-up**: rebuild Engine-O image with the new BAML compile so
`temperature 0` actually ships.

## Open: ADR-0011 internal-tool composition (follow-up, not tonight)

Engine E's `search_manual_text` (`agent_fleet/neo4j_expert/service.py:250`)
is an internal smolagent tool that reaches into Engine W's domain
(Weaviate `DocumentChunks` collection). Per ADR-0011 §1, intra-domain
composition should be invisible to routing — which the current
implementation IS — but architecturally cleaner is for Engine E to compose
via `/find_path` and route the chunk-fetch through Engine W rather than
holding W's capability inline. Not tonight's work; recorded so the option
isn't forgotten.

## Files added/modified

| Path | Purpose |
|---|---|
| `baml_shared/baml_src/clients.baml` | (committed 7ffd294) `temperature 0` for Ollama |
| `tests/routing/STEP0_DOMAIN_BUILD_SPEC.md` | requirements + verified substrate state |
| `tests/routing/STEP1_2_EXECUTION_REPORT.md` | this file |
| `tests/routing/test_substrate_invariants.py` | 6 standing guards (Contract D enforcement at CI) |
| `c:/tmp/mro_extension.ttl` | canonical TTL (uploaded to `s3://ontologies/mro/`) |
| `c:/tmp/seed_mro_extension_runtime.py` | runtime seed for the canonical-pipeline gap workaround |
| `c:/tmp/retype_verbs.py` | direct Cypher verb re-typing |
| `c:/tmp/update_predicate_weaviate.py` | Weaviate Predicate collection sync |
| `c:/tmp/phase1_stable.sh` | stable harness without rollout churn |

The TTL `c:/tmp/mro_extension.ttl` should be moved into the repo as
`doc-tools/setup/mro_extension.ttl` (next to `sustainment_extension.ttl`)
once the user reviews — it's currently committed only to MinIO via the
upload, not to git.
