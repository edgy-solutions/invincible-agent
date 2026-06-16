# Session 3 — Deployability Checklist + Work-Cluster Adjustments

**Status:** Draft. Use as the pre-deploy punch-list when the work-cluster
deploy is scheduled. Sessions 1+2 made everything in §"Portable today"
true; this document captures what's left.

---

## §0. What Sessions 1+2 made portable

The runtime architecture is fully reproducible from source. None of this
needs work-cluster-specific adjustment:

| Layer | Reproduced by |
|---|---|
| Routing logic (resolve → compat → classify, Contract A/B, conjunctive invariant) | engine_o image + canonical TTL ingest |
| Gateway saga + Contract D + read-back probe | mesh-registrar image (ADR-0006 §Addendum) |
| v0.2.1 Restate VirtualObject wiring | mesh-registrar image (Session 1 A1) |
| Engine source declarations (canonical full-IRI) | engine_a / engine_d / engine_e / engine_w / engine_o (data_analyst) images |
| Substrate canonical pipeline (TTL → Jena+Weaviate+Neo4j via one observable seam) | doc-tools image (Session 2 keystone — Option 3 asset) |
| Helm charts (env knobs in source) | helm/invincible-agent/ |
| Standing guards (substrate invariants + coverage + B2 G1/G2/G3) | tests/routing/ |
| Frozen baseline (correctness + abstention + extraction-recall) | tests/routing/test_classify_route.py |

The portability proof: the fresh-bootstrap rehearsal materialized 1406
OntologyClass nodes across 5 domains from source TTLs in 11 dagster runs,
and the matrix passed 18/18 against the result.

---

## §1. Pre-deploy checklist (do these before the work-cluster Helm install)

### §1.0 Source-side fixes that ride into every fresh canonical ingest

These are bug fixes already merged that must be in the deployed image
because the canonical pipeline runs on first bootstrap and reproduces
the bug's residue on the work cluster otherwise.

- [ ] **Legacy-DNS class-fix (2026-06-16 consolidation).** The B4
      durability check surfaced that source defaults across multiple
      engines pointed to a stale K8s service-naming convention
      (`*-svc.default.svc.cluster.local`) that doesn't resolve in the
      current cluster. Engine W's `TechnicalManual` registration and
      Engine E's `WorkInstruction` / `ProcedureStep` registrations had
      already drifted onto this legacy DNS in the sandbox substrate;
      next pod restart with the unfixed image would have *regressed*
      the working B4 edges (FaultIsolation, IPD, DDM, ProcedureDataModule)
      onto the same broken DNS. The class-fix updates source defaults
      in **every engine** to the current `iagent-<component>:<port>`
      naming the helm chart's `{{ .Release.Name }}-{{ .component }}`
      template renders. Files touched in the sweep:
      `agent_fleet/{data_analyst,restate_analyst,ontology_service,
      neo4j_expert,weaviate_expert}/main.py`,
      `agent_fleet/restate_analyst/orchestrator/discovery.py`,
      `src/iagent/defs/{agent_routers,dynamic_supervisor}.py`,
      `scripts/recreate_verb_edges.py`. CI guard added:
      `tests/routing/test_no_legacy_dns_references.py` — catches any
      new file defaulting to the legacy pattern at CI before it can
      reach a fresh cluster. **This is a deploy-blocker-class fix**:
      fresh-bootstrap on the work cluster would have failed silently
      without it, the same way the sandbox would have on pod restart.
      Acceptance: `test_no_live_legacy_dns_references` passes; substrate
      matrix passes after engine pod restart on the work cluster
      (source-driven re-registration reconciles all edges to current DNS).

- [ ] **Writer C blank-node filter** — `sync_jena_ontologies_to_neo4j`
      in `doc-tools/doc_tools/assets/ontology_assets.py`. Pre-fix, the
      blank-node filter checked `uri.startswith("Bnode_")`/`"_:"` —
      neither matches rdflib's `BNode.__str__` output (`N[a-f0-9]{32}`),
      so every imported ontology with anonymous owl:Class restrictions
      (PROV-O, IOF_Core, S3000L, DINEN62264, IOF_MRO) leaked
      ~441 blank-node `:OntologyClass` phantoms into the sandbox
      substrate. Fixed 2026-06-15: SPARQL `FILTER(!isBlank(?uri))`
      primary, Python `isinstance(row.uri, rdflib.term.BNode)` defensive.
      Acceptance test: `doc-tools/tests/test_ontology_assets_blank_node_filter.py`.
      Substrate watchman: `tests/routing/test_substrate_invariants.py::test_no_blank_node_ontology_classes`.
      Without this fix in the deployed image, the work cluster's first
      canonical ingest reproduces the phantoms. Cosmetic (no routing
      impact — they're inert), but the deploy stops being "clean
      from source" until the fix lands.

### §1.1 Verify the work cluster has the infrastructure dependencies

The Helm chart deploys the iagent stack; these must exist already (or
be deployed via separate manifests):

- [ ] Neo4j 5.x (community OK) with APOC + n10s plugins
- [ ] Weaviate 4.4+ (no vectorizer in sandbox; configure per work-cluster
      embedding preference — but the matrix passes BM25-only)
- [ ] Apache Jena Fuseki 4.x with TDB2 persistent dataset
- [ ] MinIO (or S3-compatible object store) with an `ontologies` bucket
- [ ] Restate (for v0.2.1 VirtualObject; falls back to in-process saga
      if absent — Session 1 A1 verified this graceful degradation)
- [ ] DataHub (for catalog instance resolution — engine_d phone book
      depends on this; if absent, catalog routing rows degrade to
      LLM-fallback)
- [ ] PostgreSQL (Dagster's run + asset store)

### §1.2 Work-cluster-specific environment variables

These need to be set in the Helm values for the work cluster — sandbox
values WILL NOT work:

| Variable | Notes |
|---|---|
| `NEO4J_*` | URI, USERNAME, PASSWORD for the work-cluster's Neo4j |
| `WEAVIATE_*` | HTTP_HOST, GRPC_HOST (use the work-cluster's service names) |
| `JENA_URL` | The work-cluster's Fuseki endpoint |
| `S3_ENDPOINT_URL`, `AWS_*_KEY` | The work-cluster's MinIO endpoint + creds |
| `RESTATE_INGRESS_URL`, `RESTATE_ADMIN_URL` | If using Restate |
| `DATAHUB_GMS_URL` | Engine D's catalog backend |
| `OLLAMA_*` | LLM endpoints; the routing baseline pins gpt-oss-128k:120b on ai1 — if work cluster has a different model host, expect re-benchmarking per MODEL_COMPARISON_BENCHMARK.md |
| `SMOLAGENTS_MODEL` | Engine A's agent loop model |

### §1.3 Phone-book matrix rows need work-catalog asset names

The routing matrix exercises live DataHub queries. R1's
`gold.sales.revenue_summary` (and other catalog asset names) are SANDBOX
data. On the work cluster the catalog is different. Before running the
matrix:

- [ ] Pick 2–4 real catalog assets from the work cluster's DataHub
      (per the architect's "while Session 1 runs, your one decision is
      picking the work-cluster demo's question set")
- [ ] Update the matrix rows' query strings + `expected_subject_substring`
      / `expect_instance_provider` annotations in
      `tests/routing/test_classify_route.py`
- [ ] **Bonus:** the SAME real-asset names feed B0's §2 question
      inventory — kill two birds.

### §1.4 Phone-book provenance is the demo

When the work cluster has a populated DataHub, the natural demo is:
"who owns X / trace lineage of Y / tell me about <real asset>." The
provenance field on `/resolve` shows the routing path
("instance_match=fuzzy, instance_provider=engine_d, instance_score=0.75")
— putting that on screen is the visible product of three weeks of
substrate work. Don't gate the demo on docs phase; data engineering on
real work data IS the first demo.

---

## §2. Deploy-time procedure

### §2.1 Order of operations

```
1. Helm install — brings up infra + dagster + mesh-registrar (engines
   not yet up)
2. Run prime_databases.py (setup/) — Neo4j constraints + Jena dataset
   + MinIO TTL upload
   Decision flag: --trigger-ingest fires the dagster ingest_ontology_job
   for each partition; without it, manually fire from Dagster UI or
   wait for the sensor to auto-detect uploads.
3. Wait for the canonical pipeline to complete (typically ~5min for
   11 partitions; Sustainment is the heavy lifter).
4. Verify substrate: cypher `MATCH (c:OntologyClass) WHERE c.domain IN
   ['MAINTENANCE','MIL','MESH','DATA_ENGINEERING','SUSTAINMENT'] RETURN
   c.domain, count(c)`. Expect: MAINTENANCE~261, MIL=10, MESH=22,
   DATA_ENGINEERING=45, SUSTAINMENT~1068 (counts may vary slightly with
   upstream TTL versions).
5. Deploy engines (engine_a / engine_d / engine_e / engine_w /
   data_analyst). Each registers through the gateway saga on startup;
   verify mesh-registrar logs show 14 `Registered ...` lines.
6. Substrate verification: run substrate invariants
   (pytest test_substrate_invariants.py). Expected: 9/10 green; the
   1 red is the pre-existing mesh:GraphExpertResponse compact-spine
   debt unless that's been migrated.
7. Matrix run: pytest test_classify_route.py. Expected: 18/18 (replace
   sandbox asset names with work-cluster ones per §1.3 first).
8. Bonus: substrate-coverage guard:
   pytest test_substrate_invariants.py::test_substrate_covers_routing_via_v02_saga_edges
   — proves every matrix-successful (subject, verb) pair is backed by
   a v0.2 saga edge.
```

### §2.2 Predictable failures + their meanings

| Symptom | Most likely cause |
|---|---|
| Matrix rows return UNKNOWN for DATA_ENGINEERING | Repeat of the Session-2 rehearsal finding: prime script's manifest tagged idp:* with the wrong semantic domain. Verify CANONICAL_TTL_MANIFEST has `domain="DATA_ENGINEERING"` for idp/*. |
| Engines fail to register at startup with "ADR-0019 Contract D" | Class referenced by engine source isn't in Neo4j. Trigger the corresponding TTL ingest; check `MATCH (c:OntologyClass {uri: '<the URI>'}) RETURN c`. |
| `mesh:resolveInstance` matrix rows return UNKNOWN | The phone book providers (Engine D / Engine E) didn't register, or DataHub is unreachable. Check engine logs for `Registered ... resolveInstance`. |
| Maintenance queries fall through to generalist | MAINTENANCE domain has fewer classes than expected (~261). Likely the mro_extension or maintenance_extension TTL didn't ingest. |
| Conjunctive-read invariant test red | Substrate split — Neo4j has a verb edge but Weaviate's Predicate collection doesn't (or vice versa). Indicates a gateway saga failure mid-flight; check mesh-registrar saga logs. |

### §2.3 Rollback procedure

The substrate is rebuildable from source (Sessions 1+2's whole point).
If a deploy goes catastrophically wrong:

1. Snapshot before destroying: cypher exports + Weaviate backup.
2. `prime_databases.py --wipe --i-mean-it --namespace=<work>` (the
   guarded wipe).
3. Re-run from §2.1 step 2.

The architect's standing discipline applies: snapshot first, predict
before running, name the gap if anything moves outside prediction.

---

## §3. Demo script (the first work-cluster demonstration)

### §3.1 What works on day one

- Catalog-routing questions over real work-cluster DataHub assets
  ("who owns X," "trace lineage of Y," "what columns does Z have").
  Engine D resolves the instance, the substrate routes, the response
  includes provenance the audience can SEE on screen.
- The instance-resolution architecture: showing the
  `provenance.instance_provider=engine_d` field that distinguishes
  "the LLM guessed Table" from "the catalog said Table." This is the
  load-bearing distinction in a system that doesn't make things up.
- Hierarchy routing: `customer_silver` resolves to `idp:Table` → the
  catalog verbs route via `subClassOf` to `idp:Dataset`. The
  inheritance path is visible in the provenance.

### §3.2 What's coming (don't gate the demo on it)

- Docs phase (B-track): tech manual search, fault isolation routing,
  IPD queries, DMC instance resolution as provider #3. Lands week-over-
  week after the docs ingest pipeline ships (B2 has scaffolding +
  guards committed already; B2 implementation is the next big phase).
- Wave-3 column verbs: A6's R4 read confirmed the column entity
  resolves in DataHub (idp:Column subject). Verbs are NOT yet typed
  against it — when real questions demand column-level operations
  (extract this column, derive a feature from this column), B4's verb-
  registration pattern adds them.
- Composition (ADR-0011): chain-shaped queries get routed across
  multiple verbs. Tripwire: "what procedure covers replacing the part
  that's failing on tail 42" — held as an expected-generalist canary
  in the docs-phase matrix (B0 Q5).

### §3.3 Talking points for the demo

1. **"Three weeks ago this system's runtime couldn't be trusted."** The
   architect's perspective line. Today: routing is sound, registrations
   are atomic, the substrate is rebuildable from source.
2. **"The substrate is the architecture."** Show the OntologyClass
   count (~1406), the v0.2 saga edges (14), the matrix at 18/18.
3. **"The system corrects its operators."** The DELETE classifier story
   — when prediction-by-reasoning would have failed, a guard backed by
   a passing automated check kept the discipline.

---

## §4. Banked findings — bring up if asked

These are real cleanup items the work cluster may or may not encounter:

- **Tier-3 demo row 8 — bigger than the "5-minute catalog sync" the
  earlier framing suggested** (consolidation session 2026-06-16).
  Engine D's `/query_metadata` returns demo URNs cleanly at score 1.0
  (DataHub catalog is correct). The actual gap is *inside* Engine DA:
  the smolagent has `tools=[query_datahub_asset]` only, but the
  augmented prompt instructs the agent to "call `search_datahub`
  first" — and `search_datahub` is not in DA's tool roster (it lives
  in Engine A's smolagent). Engine DA's `analyze_data` handler does
  NOT extract `resolved_uri` from the request payload, so the URN
  Engine D's resolveInstance returns is silently dropped even if the
  supervisor passes it. Two paths reconcile this, both bigger than
  five minutes:
    (a) handler change to extract `resolved_uri` from request +
        prompt update to use the URN it was given (drop the
        `search_datahub` instruction). Predicates on supervisor
        actually passing the URN; needs to be verified.
    (b) add `search_datahub` as a registered tool on Engine DA
        (duplicates a capability that lives in Engine A's smolagent;
        watch for "every engine gets every tool" sprawl).
  Row 8 retagged from ⚙ READY-PENDING-SYNC to ⚙ READY-PENDING-
  INVESTIGATION. Demo-day fallback: show routing step live (latency-
  evident dispatch to Engine DA); present URN/SQL execution as
  screenshot if neither path has shipped.

- **The 8 historical OntologyClass nodes without canonical provenance**
  (G1 guard flagged tonight). Pre-canonical-era debt: `mro:Equipment`,
  `mro:Symptom`, `data:Dataset`, `data:Dashboard`, etc. Not load-
  bearing for routing (the canonical replacements exist alongside);
  cleanup is documented but not blocking.
- **The `mesh:GraphExpertResponse` / `mesh:KnowledgeRetrievalResponse`
  compact-spine debt** (test_no_compact_form_for_migrated_subjects).
  These OntologyClass nodes have `subClassOf` edges to compact
  `mesh:Response`. The canonical mesh:* hierarchy migration to full-IRI
  for the subClassOf spine is queued — separate from the
  verb-referenced sweep that Session 2's A3 closed.
- **The existing `sync_jena_to_neo4j` (XML pipeline) has the same wrong
  Fuseki endpoint path** (`/ds/query` instead of `/ds/sparql`) that
  Session 2's first n10s attempt hit. The XML pipeline has likely been
  failing silently for ingest paths that go through it.
- **`v0.2.2` queued: live concurrent-duplicate-registration integration
  test** against Restate. Wire-contract tests are pinned (A1); the live
  serialization test needs a Restate cluster.
- **A5 queued: compliance URI prefixed-name bug** in doc-tools
  `process_document_artifact_job`. Belongs in B2 work since it's in the
  document-ingestion path.

---

## §5. The architect's "second certification" is now live

Session 1 made #1 work: *"this running cluster works."*
Session 2 made #2 work: *"this repo + bootstrap produces a cluster that
works."* That's the architect's framing made operational.

The fresh-bootstrap rehearsal tonight proved #2 empirically on the
sandbox cluster: prime → ingest → matrix-verify, 1406 classes from
source, matrix 18/18. The work cluster is the same procedure on
different infrastructure.

Run the procedure. Don't skip §1.3 (work-cluster asset names) — the
architect's "two birds" framing made this both a deploy prerequisite
AND B0's question inventory seed.
