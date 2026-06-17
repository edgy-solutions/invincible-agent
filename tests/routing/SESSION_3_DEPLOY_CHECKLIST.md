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

- [ ] **`meshRegistrar.enabled: true` MUST be set in the work-cluster
      values file** (rehearsal finding 2026-06-16). The chart's
      `helm/invincible-agent/values.yaml` default is `false`, with a
      stale comment from before the SDK migration to the gateway path.
      The sandbox rehearsal's `helm upgrade` reconciled cluster-to-chart
      and removed the manually-deployed mesh-registrar, blocking all
      engine registration. Without this override, a fresh work-cluster
      bootstrap deploys engines that can't register; the routing layer
      sees no verbs and every query falls to the generalist. **This is
      a deploy-blocker.** Sandbox fix already committed in
      `helm/invincible-agent/values-sandbox.yaml`; the work-cluster
      values file (deployment time, not in this repo) needs the same
      flip. Acceptance: after `helm upgrade`, `kubectl get pod -n <ns>`
      shows `iagent-mesh-registrar-*` Running; engine pods' first-startup
      logs contain `Registered engine ... via mesh-registrar v0.2`.

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

- **Tier-3 fix landed (2026-06-16) — fabrication structurally eliminated
  via four-layer path (a); live e2e gate pending image deploy.**
  Source committed; unit tests pin the contract (8/8 GREEN); structural
  correctness gate (DA can't fabricate when URN is absent) enforced at
  the prompt-shape layer. Live URN-equality and absent-URN-honest-not-found
  acceptance assertions require the dagster-user-code image to rebuild
  with the new supervisor + DA source and the pod to roll over. After
  deploy: trace one happy-path query through `/orchestrate` → cortex_bff
  → dagster supervisor_query_job → Engine DA, confirm DA's
  `query_datahub_asset` call uses `provenance.instance_id` verbatim;
  then run one absent-URN query and confirm DA returns honest not-found.

  See the long-form banked entry below for the four-layer trace, the
  bug's mechanism, and the Step-2 general-gap finding (Engine A also
  needs the URN; not fixed in this scope).

- **Tier-3 demo row 8 — sharpened from "bigger than 5 min" to a
  *four-layer* path (a) plus a confirmed fabrication finding**
  (sharpened 2026-06-16 by direct code reading of the supervisor's
  dispatch path).

  **Engine D's catalog is correct** — `/query_metadata` returns the
  demo URNs cleanly at score 1.0 with full lineage.

  **The URN-passing wiring is not implemented end-to-end.** Tracing
  every layer:

  1. `/resolve` returns `resolved_uri` (the class, e.g.
     `idp:Table`) AND `provenance.instance_id` (the actual URN, e.g.
     `urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)`).
  2. **Supervisor `_resolve_subject`** at
     `src/iagent/defs/dynamic_supervisor.py:227-231` extracts only
     `resolved_uri`. The `provenance.instance_id` URN is **discarded
     at the supervisor layer.**
  3. **Supervisor dispatch payload** at
     `src/iagent/defs/dynamic_supervisor.py:670-690` constructs the
     POST body with `user_query`, `user_persona`, `answerer_persona`,
     `persona`, `domain`, `dynamic_schema_map`, `user_id`,
     `predicate_verb_iri`, `routed_verb_iri` — **no URN field.**
  4. **Engine DA handler** at
     `agent_fleet/data_analyst/main.py:108-113` extracts `user_query`,
     `dynamic_schema_map`, `user_id`. Even if the supervisor passed a
     URN, the handler would silently drop it.
  5. **Engine DA augmented_prompt** says "if you don't already have a
     URN from upstream context, call `search_datahub`" — but
     `search_datahub` is not in DA's tool roster (it lives in
     Engine A). Agent has no source for the URN except fabrication.

  **The architect's question — "receiving and dropping, or
  fabricating?" — answered: fabricating.** Live evidence: Engine DA's
  recent log shows the smolagent produced URN
  `urn:li:dataset:(urn:li:dataPlatform:postgres,prod.sales.orders_raw,PROD)`
  for a "revenue_summary" query, and returned "not found in catalog."
  The URN didn't come from the supervisor (which doesn't pass it); it
  came from `dynamic_schema_map` context (the DataHub schema-map
  injection at line 668), training data, or model hallucination.
  **This is the confidently-wrong pattern showing up one layer down in
  the execution path** — exactly the failure mode the demo's
  failure-row celebrates the system *not* doing elsewhere.

  **Architectural observation worth more than the one-line bank**
  (elevated 2026-06-16): the dispatch payload drops the resolved
  `instance_id` GENERALLY. Engine A reads `dataset_id` analogously
  and the supervisor doesn't pass it either; Engine A papers over
  by calling `search_datahub`. **Both engines are in the same
  architectural shape: the supervisor resolves an identifier and
  drops it on the dispatch boundary; engines compensate by
  re-discovering it.** Engine A re-discovers (wasted work; risk of
  landing on a different asset than resolution picked); DA
  re-discovered as fabrication (because DA had no search fallback).
  The general fix is to propagate the resolved identifier to all
  instance-consuming engines and stop the re-discovery pattern.
  The Tier-3 fix shipped in this arc is **the first instance of
  that class-fix** — same shape as the first legacy-DNS source
  default fix that the writer-hunt sweep eventually closed as a
  class. A future-session class-fix would: (1) extend
  `resolved_instance_id` consumption to Engine A; (2) retire or
  downgrade `search_datahub` from Engine A's smolagent the same
  way it was removed from DA's prompt; (3) add a CI guard that
  flags engines whose handlers read identifier-shaped fields the
  supervisor's dispatch payload doesn't pass. Banked separately
  for a future session; the Tier-3 fix's scope was DA-only.

  **Two paths to fix, with the four-layer characterization in hand:**

    (a) **Wire URN passing end-to-end.** Touches four layers:
        - Supervisor `_resolve_subject` returns `instance_id` from
          `provenance`.
        - Supervisor dispatch payload includes the URN.
        - Engine DA handler extracts it from the request.
        - Engine DA prompt presents it to the smolagent and drops the
          `search_datahub` instruction.
        Architecturally clean; gives DA the *real* URN. Multi-layer
        change but each layer's change is small.
    (b) **Add `search_datahub` to Engine DA's tool roster.** Single-
        engine change. Gives DA a way to *discover* the URN itself.
        Duplicates a capability already in Engine A's smolagent
        (the "every engine gets every tool" sprawl concern).

  Row 8 stays at ⚙ READY-PENDING-INVESTIGATION. Recommendation:
  (a) is the right structural fix — it kills the fabrication pattern
  (which (b) only papers over by letting the agent re-search after
  fabricating). Demo-day fallback: show routing step live (Engine DA
  dispatch is real and latency-evident); present URN/SQL execution
  as a screenshot if path (a) hasn't shipped.

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

---

## §6. Deploy session execution playbook (work-cluster pre-flight)

**Date added:** 2026-06-16. **Status:** ready to execute when the
work-cluster deploy is scheduled.

### §6.0 Mode change — read this first

Every prior session has been in the **cheap venue** (sandbox), where the
discipline (predict, snapshot, matrix-before-after, halt-on-surprise)
made mistakes recoverable in minutes. The work-cluster deploy is the
**first time the venue isn't cheap.** The operation isn't riskier — it's
a re-run of a bootstrap that just passed 36/36 clean in the rehearsal —
but the *recovery properties* differ. The discipline that's been
reflexive needs to be **more deliberate, not less**, precisely because
the safety net is thinner.

The fresh-bootstrap rehearsal made the deploy defensible by proving the
chart works against a clean cluster. But "proven in the cheap venue" and
"executed in the expensive venue" are different acts — the gap is where
the three loaded regressions lived in the sandbox arc (chart-vs-cluster
drift that only showed when the chart was run against a clean cluster).
**The work cluster is *another* clean cluster the chart hasn't been run
against**, which means it can have its own accretion gaps: work-cluster-
specific out-of-band state, work-values that differ from sandbox in
unrecorded ways, a work DataHub catalog that's structurally different.

The pre-flight's job is to predict the work-cluster-specific deltas
explicitly so the new venue's surprises happen here, not in front of
the audience.

### §6.1 Pre-flight predictions — what's the same, what's different

**Same as sandbox (the proven-portable layer):**

| Layer | Why it stays the same |
|---|---|
| Helm chart templates | Sandbox + work both render through the same templates; chart proven by the rehearsal |
| Source defaults (DNS class-fixed) | All `iagent-<component>:port` URLs; render correctly against `{Release.Name}-{component}` naming |
| Engine source code (Tier-3 four-layer fix included) | Image is the carrier; rebuild propagates the fix |
| Standing guards (substrate invariants, DNS class-fix, Tier-3 propagation) | CI; identical execution |
| Canonical pipeline behavior | doc-tools + Writer C blank-node filter rolled into the image |

**Different on work (the explicit delta list — predict each):**

| Delta | What to verify pre-flight | Predicted state |
|---|---|---|
| `values-work.yaml` exists and includes `meshRegistrar.enabled: true` | The §1.0 deploy-blocker from the rehearsal finding. Sandbox flipped; work needs its own flip in its own values file. | **Must be present**; halt if missing |
| `values-work.yaml` includes `ENGINE_W_PUBLIC_URL` and `ENGINE_E_PUBLIC_URL` pins | The belt-and-suspenders from the durability check. Source defaults are now correct, but the explicit pin makes the deployment's intent auditable | **Must be present**; halt if missing |
| Work-cluster release name | If `Release.Name` differs from `iagent`, every service named `{Release.Name}-{component}` differs from the source defaults | Predict: same `iagent` release name; if different, source defaults need overrides via env var per engine |
| Work-cluster namespace | Sandbox runs in `sandbox`; work runs in its own namespace | Predict: a single dedicated work namespace; `meshRegistrar.enabled` discipline still applies |
| LLM endpoints (`OLLAMA_BASE_URL`, `MEM0_OLLAMA_BASE_URL`) | sandbox hardcoded to `192.168.1.119` and `192.168.1.188`; work uses its own LLM hosts | Predict: different IPs in work-values; benchmark for parity per `MODEL_COMPARISON_BENCHMARK.md` |
| Secrets (`NEO4J_PASSWORD`, `BPMN_POSTGRES_PASSWORD`, etc.) | All `changeme-*-sandbox` markers MUST be replaced for work | **Must be replaced**; halt if any `changeme-*-sandbox` reaches work |
| Ingress hostnames (`*.edgy-solutions.com`) | sandbox-specific routing | Predict: work uses its own DNS scheme |
| DataHub catalog content | sandbox has `gold.sales.revenue_summary` etc. as test fixtures; work has its real catalog | Predict: §1.3 real-name substitution applies — re-point matrix rows to real work assets |
| Manuals content (S1000D/40051) | sandbox has SANDBOXRTX + helmet IADS fixtures; work has its real manuals (or none yet) | Predict: B4 verb-routing works (substrate test), but live retrieval depends on work-ingested content. **If manuals aren't ingested into work, predict Tier-4 rows 11–14 as known-not-yet, NOT a failure** |
| Tier-3 row 8 | source-complete fix; live behavior confirmed by image rebuild | Predict: deploy *is* the Tier-3 live confirmation — Acceptances A and B run post-rollout |

### §6.2 Work-values translation checklist

Run through `helm/invincible-agent/values-sandbox.yaml` against the
work-values file. For each top-level section overridden in sandbox,
confirm the work equivalent is set:

- [ ] `global` — pull secret + imagePullPolicy
- [ ] `engineB`, `engineC` — enabled state (sandbox disables both; work decides)
- [ ] `engineE`, `engineW`, `meshRegistrar` — **enabled: true** (the rehearsal-finding fix)
- [ ] `agentFleet.env` — LLM endpoints (work-specific IPs), `MEM0_*` settings, BAML config
- [ ] `agentFleet.secrets` — NEO4J_PASSWORD (work value), SUPERSET_ACCESS_TOKEN (work)
- [ ] Per-engine `env:` blocks — `ENGINE_W_PUBLIC_URL`, `ENGINE_E_PUBLIC_URL` belt-and-suspenders pins
- [ ] `dataAnalyst`, `engineA`, `engineO`, `engineD`, `engineF` — replicas, resources, work-specific overrides
- [ ] `postgresql`, `neo4j`, `weaviate`, `fuseki`, `keycloak`, `topaz` — admin passwords (NO `changeme-*-sandbox` allowed)
- [ ] `dagster` — image repository + ingress hostnames (work DNS)
- [ ] `centralGateway`, `cortexBff`, `cortexUi` — ingress + auth URLs (work DNS)
- [ ] `secrets` — top-level secret values (NO `changeme-*-sandbox` allowed)

**Gate:** before `helm install`, grep work-values for `changeme-`. If
ANY match, halt. The placeholder discipline exists exactly to catch this.

```bash
grep -n "changeme-" path/to/values-work.yaml && echo "HALT: placeholder secrets present"
```

### §6.3 Deploy procedure (the actual sequence)

The §2.1 order of operations still applies. The pre-flight specifically
adds:

1. **Pre-deploy snapshot of work cluster state** — what's already there before this deploy adds anything. Snapshot the work namespace's existing resources so rollback is concrete (see §6.5 reversibility).
2. **Helm install** (or upgrade if a prior partial install exists):
   ```bash
   helm install iagent helm/invincible-agent -n <work-ns> -f path/to/values-work.yaml
   ```
3. **Watch `iagent-mesh-registrar` pod come up FIRST.** The rehearsal
   finding requires it; engines block on its DNS at registration time.
   If mesh-registrar isn't Running before engines start, registration
   warnings appear in engine logs (the named alarm from the rehearsal).
   Halt and resolve before proceeding.
4. **Run `setup/prime_databases.py`** per §2.1 with `--trigger-ingest`.
5. **Wait for the canonical pipeline** to materialize the substrate
   (~5 min for the standard 11 partitions).
6. **Substrate verification** — exact substrate counts depend on what
   TTLs the work cluster ingests; predict 1400+ OntologyClass nodes if
   the full set ingests cleanly, scaled down if work runs a subset.
7. **Engine pod rollout** triggered by mesh-registrar coming up; check
   each engine's first-startup log for
   `Registered engine ... via mesh-registrar v0.2`. **Any retry-
   exhaustion message is a named alarm — halt and diagnose** (DNS,
   service selector, network policy).
8. **Run the post-rollout verification** (§6.4 below).

### §6.4 Post-rollout verification

#### §6.4.1 Matrix + guards (the reproduce-36/36 gate)

```bash
# From this repo, against work cluster's Engine O port-forward:
export ROUTING_TEST_BASE_URL=http://localhost:8084
kubectl port-forward -n <work-ns> svc/iagent-engine-o 8084:8084 &
kubectl port-forward -n <work-ns> svc/iagent-neo4j 7687:7687 &

pytest tests/routing/test_classify_route.py \
       tests/routing/test_substrate_invariants.py \
       tests/routing/test_no_legacy_dns_references.py
```

**Predicted state after work deploy + canonical ingest + ALL B4 verbs registered:**

| Suite | Expected | Notes |
|---|---|---|
| `test_no_legacy_dns_references.py` | 1/1 (CI guard; pure source-scan) | Independent of cluster; deterministic |
| `test_substrate_invariants.py` | 13/13 | Substrate counts may differ from sandbox; the GUARDS work against logical invariants, not counts |
| `test_classify_route.py` matrix | **Conditional** — see below |

**Matrix conditional predictions** (the work-cluster-specific deltas):

- The DATA_ENGINEERING rows (1–6, 9 in the demo script) depend on work's
  real DataHub catalog content. After §1.3 real-name substitution, predict
  matched routing if substituted assets exist in work's DataHub.
- The MAINTENANCE rows (10–14) depend on what manuals content has been
  ingested into work. If no manuals ingested yet, predict: `/resolve`
  may UNKNOWN-out for B4 rows; that's expected, NOT a regression. Don't
  flip Tier-4 rows red without confirming work has manuals ingested.

**Outside-predictions findings:** if any row fails with a shape OTHER
than the predicted deltas, that's a real work-cluster-specific finding.
Characterize before pushing forward.

#### §6.4.2 Tier-3 Acceptance A — URN-equality happy path

This is the live confirmation that the four-layer URN propagation
shipped in this arc actually behaves end-to-end. The image rebuild +
pod rollout is what makes the source-complete fix live, so the deploy
IS the live test.

Procedure:

```bash
# Pick a query whose /resolve returns a non-empty provenance.instance_id.
# (Use a substituted real work asset name per §1.3.)
TEST_QUERY="Fetch a sample of rows from <WORK_REAL_TABLE>"

# Step 1 — capture what /resolve produces (the URN we expect DA to use)
curl -s -m 30 http://localhost:8084/resolve \
  -X POST -H "Content-Type: application/json" \
  -d "{\"query\":\"$TEST_QUERY\",\"domain\":\"DATA_ENGINEERING\"}" \
  > /tmp/tier3_a_resolve.json
EXPECTED_URN=$(jq -r '.provenance.instance_id' /tmp/tier3_a_resolve.json)
echo "Expected URN from /resolve: $EXPECTED_URN"

# Step 2 — dispatch the same query through cortex_bff /orchestrate
# (this is the runtime path — supervisor → dispatch → Engine DA)
kubectl port-forward -n <work-ns> svc/iagent-cortex-bff 8090:8090 &
curl -s -m 600 http://localhost:8090/orchestrate \
  -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer <real-user-jwt>" \
  -d "{\"query\":\"$TEST_QUERY\",\"...\":\"...\"}" \
  > /tmp/tier3_a_orchestrate.json

# Step 3 — inspect Engine DA pod logs for the smolagent's actual
# query_datahub_asset call
DA_POD=$(kubectl get pods -n <work-ns> -l app.kubernetes.io/component=data-analyst -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n <work-ns> "$DA_POD" --tail=200 | grep -E "query_datahub_asset|urn:li:dataset"
```

**Acceptance A criterion:** the URN appearing in the
`query_datahub_asset` call in DA's pod logs MUST equal `$EXPECTED_URN`
captured in Step 1. Any deviation (modification, substitution,
abbreviation) fails Acceptance A.

#### §6.4.3 Tier-3 Acceptance B — Absent-URN honest not-found (the keystone)

This is the negative control — the test that proves fabrication is
structurally eliminated, not just bypassed on the happy path.

Procedure:

```bash
# Construct a query whose resolved URN is ABSENT from the work catalog.
# Options:
#   (a) Reference a real-shape but nonexistent asset:
#       "Fetch a sample of rows from absent_definitely_not_in_catalog_table"
#   (b) Reference an obviously absurd name that /resolve will fan out on
#       but no provider will match:
#       "Fetch rows from xyz_fake_table_for_negative_control"
ABSENT_QUERY="Fetch a sample of rows from xyz_fake_table_for_negative_control"

# Step 1 — confirm /resolve produces empty/missing instance_id
curl -s -m 30 http://localhost:8084/resolve \
  -X POST -H "Content-Type: application/json" \
  -d "{\"query\":\"$ABSENT_QUERY\",\"domain\":\"DATA_ENGINEERING\"}" \
  > /tmp/tier3_b_resolve.json
INSTANCE_RESOLVED=$(jq -r '.provenance.instance_resolved' /tmp/tier3_b_resolve.json)
ABSENT_INSTANCE_ID=$(jq -r '.provenance.instance_id // ""' /tmp/tier3_b_resolve.json)
echo "instance_resolved: $INSTANCE_RESOLVED"
echo "instance_id: $ABSENT_INSTANCE_ID"
# Expected: instance_resolved=false or instance_id=null/empty

# Step 2 — dispatch through cortex_bff
curl -s -m 600 http://localhost:8090/orchestrate \
  -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer <real-user-jwt>" \
  -d "{\"query\":\"$ABSENT_QUERY\",\"...\":\"...\"}" \
  > /tmp/tier3_b_orchestrate.json

# Step 3 — inspect Engine DA logs for honest not-found vs fabrication
DA_POD=$(kubectl get pods -n <work-ns> -l app.kubernetes.io/component=data-analyst -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n <work-ns> "$DA_POD" --tail=200
```

**Acceptance B criteria (ALL must hold):**

1. DA must NOT call `query_datahub_asset` with a fabricated URN.
   Specifically: there must be NO `urn:li:dataset:(...)` string in
   DA's pod log that wasn't passed by the supervisor.
2. DA must return a response indicating "no URN was resolved" or
   equivalent honest-not-found. The user-visible answer must NOT
   claim to have queried an asset.
3. If DA tries to call `search_datahub`, that's a fix incomplete —
   the instruction was removed but the tool removal wasn't (it
   shouldn't be in the roster at all). Confirm `search_datahub` is
   not exercised.

**If Acceptance B fails**: structural elimination didn't behave as
designed. Halt and diagnose — likely the dagster-user-code image
wasn't rebuilt with the new source, or the supervisor's payload
field name doesn't match the handler's expected name. Bank the
finding precisely; do not push forward on the failed contract.

**On Acceptance B pass:** flip demo row 8 from ⚙ READY-PENDING-IMAGE-
DEPLOY to ✅ READY in `docs/demo-script.md`.

### §6.5 Reversibility discipline (the expensive-venue gate)

**Before any work-cluster operation that isn't trivially reversible,
confirm the reversibility first.** The sandbox let you snapshot-and-
restore freely; the work cluster's properties may differ. Confirm what
the equivalent is BEFORE you need it.

Specifically:

- [ ] **Substrate wipe path** — sandbox's `prime_databases.py --wipe
      --i-mean-it --namespace=sandbox` requires all three guards.
      Confirm the same triple-guard is honored on work. If work's
      Neo4j/Weaviate/Jena store anything beyond the canonical-
      pipeline-rebuildable substrate (e.g., user-added instances,
      operational ABox state), `--wipe` is destructive-and-not-
      reversible by the canonical pipeline alone. **HALT and confirm
      before wiping work data.**
- [ ] **Namespace deletion** — never delete the work namespace as a
      rollback step unless explicitly authorized. Containing-resource
      ownership may include things the deploy didn't create.
- [ ] **Helm rollback** — `helm rollback iagent <REVISION> -n <ns>`
      restores the prior chart revision but does NOT restore substrate
      state. If a deploy fails midway and substrate is partially
      populated, the canonical pipeline can rebuild substrate from
      source; user-added state cannot.
- [ ] **DataHub URN mutations** — if the deploy triggers any URN
      writes against the work DataHub (e.g., the mesh-registrar's
      DataHub MCP emit), confirm those URNs are idempotent and
      cleanable. Sandbox treated DataHub as disposable; work may not.

**If any reversibility property is unknown, halt the destructive step
and ask before proceeding.** Push-through on unknown reversibility is
the failure mode the expensive venue exists to teach against.

### §6.6 Hard scope + halt-and-confirm criteria

**In scope** for the deploy session:

1. `helm install` (or upgrade) of the iagent chart with the work-values
   file.
2. `prime_databases.py --trigger-ingest` against work substrate.
3. Wait for canonical pipeline; verify substrate counts.
4. Confirm engines registered (mesh-registrar reachable, no retry-
   exhaustion alarms in logs).
5. Run §6.4 post-rollout verification: matrix + guards + Tier-3
   Acceptance A + Tier-3 Acceptance B.
6. §1.3 real-name substitution against work's actual DataHub catalog.
7. Flip demo-script row 8 to ✅ READY on Acceptance B pass.

**Out of scope** (banked from this arc):

- Engine A class-fix (re-discovery pattern; first-instance-of-class
  is the Tier-3 fix; class generalization is a future session).
- ADR-0020 implementation (composition-walk; non-urgent; trigger-gated).
- Manufacturing track (separate work; needs Gap-1 corpus).
- Any new substrate cleanup.

**Halt-and-confirm triggers** (do NOT push through any of these):

- mesh-registrar pod fails to come Running before engines start
  → diagnose; halt.
- Any engine's first-startup log shows "v0.2 retries EXHAUSTED"
  → DNS or network policy issue; halt.
- Substrate count drops to zero, or canonical pipeline returns errors
  → halt; do NOT proceed to matrix.
- Matrix fails on rows OUTSIDE the predicted work-cluster deltas
  → real finding; characterize before proceeding.
- Tier-3 Acceptance B fails (DA fabricates on absent-URN test)
  → structural fix didn't behave as designed; halt and diagnose.
- Reversibility of any step is unknown
  → halt and confirm before executing.
- Any work-cluster out-of-band accretion gap surfaces (analogous to the
  sandbox `meshRegistrar` finding) → characterize; possibly halt;
  do NOT silently work around.

### §6.7 What this deploy proves

If the §6.4 verification all passes:

- The chart bootstraps a working cluster on a venue it wasn't built on
  (the work cluster is a different cluster than sandbox).
- The canonical pipeline reproduces the substrate at scale.
- The DNS class-fix renders correctly against work's service names.
- The mesh-registrar gate (the rehearsal finding) is closed on work.
- The Tier-3 four-layer fix behaves as designed in live execution.
- The system holds the "stop being confidently wrong" thesis at the
  execution layer, not just at the routing layer.

That's the deploy as the thing the whole arc was building toward.

### §6.8 Closing note — why this deploy is defensible rather than hopeful

Every loaded regression that would have bitten live was caught in the
cheap venue:

1. Legacy-DNS source defaults (three drift instances on B4 edges + three
   systemic in the sweep + CI guard against the fourth).
2. `PROCEDURE_STEP` guard staleness (canonicalization missed in 2026-06-15).
3. Helm chart's `meshRegistrar.enabled=false` default (rehearsal finding —
   would have silently broken every engine registration on fresh
   bootstrap).
4. The fabrication-class bug at Tier-3 (structurally closed via four-
   layer URN propagation; live confirmation rides on the deploy).

The deploy is a re-run of a proven operation in a venue that's new but
not untested-in-kind. The only genuinely new variables are work-cluster-
specific (its values file, its rendered names, its catalog content, its
reversibility properties) — and §6.1's predictions name them explicitly
so the new venue's surprises happen in pre-flight, not in front of the
audience.

The cheap venue paid for itself three times so this venue doesn't have to.
