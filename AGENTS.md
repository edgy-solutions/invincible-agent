# AGENTS.md — AI Agent Workflow & Safety Guide

## Governing Architecture

A strictly decoupled, **Polyglot Microservice** architecture:

- **Cortex BFF (`iagent-cortex-bff`, port 8090)** — Synchronous gateway.
  Accepts user queries via `POST /orchestrate`, calls Engine O for intent
  routing, launches Dagster supervisor jobs, streams SSE back to the
  frontend.
- **Dagster Control Plane** — Ephemeral, lightweight pods. Uses
  `requests` (no `PipesK8sClient`). Per-query dynamic supervisor jobs
  fan out to engines selected by the predicate graph (ADR-0004).
- **Agent Fleet** — Multiple independent FastAPI pods, one per engine,
  each with its own isolated codebase and OCI image. Inter-service
  contracts are BAML-typed.

**Routing is predicate-graph driven (ADR-0004).** Engines self-register
their verbs into Weaviate at startup. The supervisor calls Engine O
`/search_predicates` per subtask to look up which engine handles which
verb, scoped to the caller's `entitled_domains` claim. The RDF ontology
is the *vocabulary layer* (subjects, concepts, verbs); Weaviate's
Predicate collection is the *router*.

**Tech stack constraints:** Dagster (orchestration), FastAPI (API
layer), BAML (contracts), Restate + smolagents (Engine A / DA / E / W),
LangGraph (Engine B), Swarms.ai (Engine C), dbt + DataHub (catalog),
Polars + CortexDataClient (data plane), Neo4j + Weaviate (graph +
semantic), Keycloak + Topaz (authn + authz).

## Project Overview

**Invincible Agent (iagent)** is a Dagster-orchestrated mesh that
dispatches work to Kubernetes agent pods via HTTP. Each engine
specializes: catalog search (D), knowledge retrieval (W), graph
queries (E), code-agent analysis (A), data-plane reads (DA),
synthesis (B), UI mapping (F).

## Repository Map

```
src/iagent/
  definitions.py            # Dagster entry point (auto-loads defs/)
  gateway.py                # Cortex BFF FastAPI app (port 8090)
  auth.py                   # Keycloak JWT verification + persona/domain claims
  defs/
    agent_routers.py        # Dagster @asset HTTP dispatchers
    data_layer.py           # @asset: dbt ↔ ontology ↔ DataHub sync
    dynamic_factory.py      # Dynamic BPMN factory (reads bpmn_catalog)
    dynamic_supervisor.py   # Per-query dynamic supervisor
agent_fleet/
  ontology_service/         # Engine O — port 8084
    main.py                 # FastAPI app
    iof_mro.ttl             # IOF/MIMOSA MRO ontology
  restate_analyst/          # Engine A — port 8081
    main.py                 # Restate + smolagents analyst
    orchestrator/discovery.py  # JIT tool binding via DataHub
  langgraph_support/        # Engine B — port 8082 (synthesis + memory)
  swarms_scraper/           # Engine C — port 8083
  datahub_wrapper/          # Engine D — port 8085
  data_analyst/             # Engine DA — port 8089
    service.py              # Restate handler
    main.py                 # FastAPI app
  neo4j_expert/             # Engine E — port 8086
  presentation_agent/       # Engine F — port 8087
  weaviate_expert/          # Engine W — port 8088
  utils/                    # mesh_registration, weaviate_utils
  core/                     # authz dependency, topaz client
  llm_utils.py              # Shared get_smolagent_model() + init_baml_client()
  models.py                 # SQLAlchemy ORM for bpmn_catalog
sql/
  create_bpmn_catalog.sql   # Schema + auto-update trigger
baml_shared/
  baml_src/contracts.baml   # SOURCE OF TRUTH for inter-service schemas
  baml_client/              # Auto-generated — DO NOT EDIT
baml_client_ts/             # Generated TypeScript client (frontend)
docs/
  adr/                      # Architecture decision records (0001..0013)
helm/invincible-agent/      # Helm chart deploying the full stack
scripts/
  seed_sandbox_predicates.py   # Seed Weaviate Predicate collection
  seed_weaviate_manuals.py     # Seed Engine W's DocumentChunk collection
  seed_datahub_catalog.py      # Seed DataHub catalog
tests/
  sandbox_e2e/              # End-to-end through cortex-bff /orchestrate
  test_*.py                 # Unit/mock pytest tests
pyproject.toml              # Orchestrator project config
```

## Workflow Rules

### When adding a new Dagster asset
1. Create or edit a file in `src/iagent/defs/`.
2. Use the `@asset` decorator from `dagster`.
3. If the asset calls an agent pod, use only `requests.post()` with
   `timeout=120`. Do NOT import any agent SDK or ML library.
4. Return `dict` (parsed JSON from the agent response).
5. Add a docstring explaining what the asset does.

### When modifying data contracts
1. Edit `baml_shared/baml_src/contracts.baml`.
2. Regenerate clients:
   ```bash
   cd baml_shared
   uv run --no-project --with baml-py==0.219.0 baml-cli generate --from baml_src
   ```
3. **Never hand-edit anything in `baml_shared/baml_client/` or
   `baml_client_ts/baml_client/`** — they are regenerated.
4. Commit BOTH the `.baml` change AND the regenerated client files in
   the same commit. CI does not regenerate on its own.
5. Verify downstream agents still conform to the updated schema —
   BAML's structured-output enforcement will catch mismatches at
   runtime.

### When modifying a tool docstring on a smolagent engine
1. Tool docstrings (the body of the `@tool def some_tool(...)` function)
   are **part of the BAML grounding contract**, not just documentation.
   The smolagent's tool-selection step reads them at runtime.
2. If the upstream service the tool wraps changes its response shape,
   update the docstring in the same PR. See ADR-0013 for context.
3. Do NOT hard-code wire-format details into the engine's system
   prompt. Wire-format documentation lives on the tool, not the prompt.

### When adding a new engine
1. Create `agent_fleet/<engine_name>/`.
2. Add `pyproject.toml`, `uv.lock`, `Procfile`, `main.py`.
3. Register the engine's verbs at startup via
   `utils.mesh_registration.register_engine_to_mesh(...)` — this is
   what makes ADR-0004's predicate routing actually find it.
4. Engine declares its `domains=[...]`, `owner_persona=...`,
   `cost_class=...` so the routing graph can filter by entitled
   domains and cost.
5. Add the engine to the CI build matrix in
   `.github/workflows/build-containers.yml`.
6. Add a deployment block in `helm/invincible-agent/templates/`
   (most are auto-generated from `engines.yaml`).
7. Add an end-to-end test in `tests/sandbox_e2e/` exercising the new
   engine through `cortex-bff /orchestrate`.

### When adding a BPMN workflow to bpmn_catalog
1. Insert a row into the `bpmn_catalog` table with a valid BPMN JSON
   payload. The payload must have `tasks`, `gateways`, and
   `sequence_flows` arrays.
2. Each task must have: `id`, `name`, `type`
   (service_task | user_task), `agent_endpoint`.
3. Set `is_active = TRUE` so `dynamic_factory.py` picks it up on next
   load.
4. Restart Dagster (or reload definitions) — `build_dynamic_jobs()`
   runs at module-load time and generates jobs/ops from the catalog.

### When adding dependencies to an engine
1. Add to `[project.dependencies]` in that engine's `pyproject.toml`.
2. Regenerate the engine's lock: `cd agent_fleet/<engine> && uv lock`.
3. Commit BOTH `pyproject.toml` and `uv.lock`.
4. CI builds the engine image from its own lockfile, so the lock is
   load-bearing.

## Safety & Boundaries

### DO NOT
- Use `PipesK8sClient` for any agents — Dagster uses only `requests`.
- Mix framework imports across engines (e.g. no Restate in Engine B,
  no LangGraph in Engine A).
- Import Dagster, ML frameworks, or agent SDKs in the ontology service.
- Import Restate, LangGraph, Dagster, or smolagents in Engine B.
- Import Restate, LangGraph, Dagster, or checkpointers in Engine C.
- Add compute or orchestration logic to Engine O — it is pure
  semantic resolution + predicate routing.
- Hardcode wire-format details of one engine in another engine's
  system prompt. Format goes on the tool docstring (see ADR-0013).
- Hardcode secrets, API keys, or credentials anywhere.
- Edit auto-generated files in `baml_shared/baml_client/` or
  `baml_client_ts/baml_client/`.
- Commit `.env` files or anything containing secrets.
- Use the floating Restate image tag `1.1` — pin to a specific version
  (sandbox uses `1.6.2`). The floating tag has drifted on Docker Hub
  and broken the cluster in the past.

### DO
- Keep the orchestrator lightweight — it only dispatches HTTP calls.
- Use BAML contracts as the single source of truth for schemas.
- Add `response.raise_for_status()` before parsing any HTTP response.
- Set explicit timeouts on all outbound HTTP requests. Smolagent
  loops can take many minutes — engine proxy timeouts should be 600s
  or longer when calling Restate ingress.
- Self-register every new engine via `register_engine_to_mesh` at
  startup, with accurate `domains` and `owner_persona`.
- Write tests in `tests/sandbox_e2e/` for new mesh paths.
- Cite the ADR when introducing a load-bearing architectural change.

## Agent Pod Endpoints

These are the in-cluster URLs the orchestrator and the BFF talk to.

- **Cortex BFF**: `POST http://iagent-cortex-bff:8090/orchestrate`
  Accepts `{message, session_id}` JSON with `Authorization: Bearer
  <jwt>`. Streams SSE events including `event: final_payload` with
  the `DashboardUI` payload.
- **Ontology reasoner (Engine O)**:
  - `POST http://iagent-engine-o:8084/route_intent` — BAML
    `ExtractIntent`, returns `{mode, entity_refs, confidence}`.
  - `POST http://iagent-engine-o:8084/plan` — BAML `DecomposeQuery`,
    returns `SupervisorTaskPlan`.
  - `POST http://iagent-engine-o:8084/search_predicates` — Weaviate
    hybrid search over the Predicate collection. Returns the matched
    engine endpoint scoped by `entitled_domains`.
  - `POST http://iagent-engine-o:8084/resolve` — RDF ontology URI
    classification via `ClassifyDomainIntent`.
  - `POST http://iagent-engine-o:8084/find_tool` — exact lookup by
    `(subject_uri, verb_label)`.
  - `POST http://iagent-engine-o:8084/find_path` — multi-hop traversal
    through the predicate graph (planning support, ADR-0011).
- **Restate analyst (Engine A)**:
  `POST http://iagent-engine-a:8081/analyze`
  Accepts `AgentTask` JSON. Resolves semantic context, runs a
  smolagents `CodeAgent` with `search_datahub`,
  `superset_analytics_manager`, and JIT-bound tools discovered via
  DataHub. Returns `AgentResponse` JSON.
- **LangGraph support (Engine B)**:
  `POST http://iagent-engine-b:8082/support`
  Accepts synthesis context + `thread_id` for memory.
- **Swarms scraper (Engine C)**:
  `POST http://iagent-engine-c:8083/scrape`
- **DataHub wrapper (Engine D)**:
  `POST http://iagent-engine-d:8085/query_metadata` — natural-language
  search; returns matched assets with **owner, last_updated, tags,
  description, upstream / downstream lineage, and schema columns**
  (per the enrichment landed during the 2026-06-02 DataHub work).
  Also `GET /dynamic_context` and `GET /find_tools?ontology_uri=...`.
- **Data analyst (Engine DA)**:
  `POST http://iagent-data-analyst:8089/analyze`
  Restate-durable. Calls CortexDataClient to read Postgres /
  ClickHouse / S3 Parquet / Delta / Iceberg. RLS/CLS enforced by
  Topaz via the central gateway.
- **Neo4j Graph Expert (Engine E)**:
  `POST http://iagent-engine-e:8086/query_proxy`
  Restate-durable Cypher generation via smolagents. Long-term episodic
  memory via mem0 + Weaviate.
- **Presentation Agent (Engine F)**:
  `POST http://iagent-engine-f:8087/render_ui`
  Stateless. Calls BAML `DesignUI(raw_data, persona) → DashboardUI`.
  Six archetypes available (see UI Archetypes below). ADR-0012 tracks
  the planned dynamic-columns refactor.
- **Weaviate Semantic Expert (Engine W)**:
  `POST http://iagent-engine-w:8088/query_knowledge`
  Restate-durable. Weaviate v4 hybrid search (`near_text` + BM25)
  over technical manuals. Strict per-domain segregation via filter.

## Development Log

The phase log captures the architectural evolution. Each phase
references the relevant ADR where one exists.

### Phase 1 — Shared contracts (complete)
Defined BAML contracts: `AgentTask`, `AgentResponse`,
`SemanticResolution`, `AgentStatus`. Ontology classes dynamic.

### Phase 2 — Orchestrator control plane (complete)
Lightweight Dagster `@asset` HTTP dispatchers, no SDK imports.

### Phase 2.5 — Engine O: Ontology Reasoner (complete)
`agent_fleet/ontology_service/main.py` on port 8084. Loads
`iof_mro.ttl` into rdflib, SPARQL queries for classes, BAML
`ClassifyDomainIntent`.

### Phase 3 — Engine A: Restate + Smolagents Analyst (complete)
Durable `analyze` handler. Smolagents `CodeAgent`. BPMN workflow
runner for long-running workflows with `UserTask` promise suspension.

### Phase 4 — Engine B: LangGraph Support Agent (complete)
Two-node graph + `AsyncPostgresSaver` checkpointer.

### Phase 5 — Engine C: Swarms.ai Scraper (complete)
Stateless `SequentialWorkflow` for extraction.

### Phase 6 — Multi-stage Docker via uv (complete)
**Migrated from Cloud Native Buildpacks (Paketo) to dynamic
multi-stage Docker builds powered by `uv`.** Dockerfiles are
generated within the CI/CD pipeline to keep the repo root clean
while sharing modules (`baml_shared`, `llm_utils.py`) during build.

### Phase 7 — Late Binding & Mesh Discovery (complete)
Deprecated `data_layer.py`'s direct dbt/SQL mapping; migrated to
`doc-tools`. Semantic resolution uses Weaviate hybrid search + BAML
TypeBuilder for zero-hallucination routing.

### Phase 8 — Engine D: DataHub Metadata Wrapper (complete)
`/query_metadata` against DataHub's GraphQL search.

### Phase 9 — Dynamic BPMN Interpreter (complete)
Imperative-declarative hybrid in `dynamic_factory.py`. BPMN payloads
in `bpmn_catalog`, generates `@op` and `@job` at module-load time.

### Phase 10 — Engine E: Neo4j Graph Expert (complete)
Restate + smolagents Cypher generation against military technical
manual graph.

### Phase 11 — Dynamic Supervisor & Synthesis (complete)
Engine O `/plan` for multi-domain decomposition. Dagster
`dynamic_supervisor.py` for fan-out / fan-in. Recipe 1 (stateless
Dagster synth) and Recipe 2 (stateful LangGraph synth).

### Phase 12 — Engine F: Presentation Agent (complete)
`/render_ui` with BAML `DesignUI` mapping to UI archetypes.

### Phase 13 — Composite DashboardUI (complete)
`DashboardUI` wrapping `(TopologyUI | HazardUI | MetricUI |
DocumentUI)[]`. Persona icon broadcasting via `AssetMaterialization`.

### Phase 14 — Comprehensive Helm Charting (complete)
Single Helm release covers every engine + infra (Postgres, Restate,
Neo4j, Weaviate, Fuseki, Keycloak). Post-install hooks for restate-
init and db-init.

### Phase 15 — Multi-Domain Agentic Mesh (complete)
Intelligent routing via BAML `Domain` + `Intent` extraction. Strict
data segregation in SPARQL named graphs and Neo4j domain-specific
node labels. **ADR-0009** later sunsetted the classification axes
once predicate-graph routing landed.

### Phase 16 — Engine W: Weaviate Semantic Expert (complete)
`agent_fleet/weaviate_expert/main.py` on port 8088. Weaviate v4
`near_text` + `Filters`. Optimized for `mesh:retrieveKnowledge`.

### Phase 17 — Agentic Auth Middleware (complete)
`agent_fleet/core/authz.py` with `require_topaz_auth` FastAPI
dependency. Decodes Keycloak JWT, queries Topaz REST API, injects
validated `user_jwt` into route handlers.

### Phase 18 — Zero-Trust Data Mesh & Engine DA (complete)
Three-component data plane: smolagents driver (Engine DA), policy
injector (central gateway extracts `allowed_columns` and
`row_filters` from Topaz response), enforcer (CortexDataClient
applies CLS/RLS to the Polars `LazyFrame` before LLM-generated SQL
runs). Covers Postgres / ClickHouse / S3 Parquet / Delta / Iceberg.

### Phase 19 — Predicate Graph Routing (complete, **ADR-0004**)
Replaced LLM-driven engine selection with a Weaviate `Predicate`
collection. Each engine self-registers its verbs, owner persona,
domains, and endpoint at startup via
`utils.mesh_registration.register_engine_to_mesh`. Engine O's new
`/search_predicates` does hybrid vector search to pick the right
engine per subtask, filtered by the caller's `entitled_domains`.

### Phase 20 — Verb + Concept Namespaces (complete, **ADR-0005**)
Standardized the `mesh:` verb namespace and the concept URI scheme.
Engine registrations validate against the RDF-namespace-defined
verb registry.

### Phase 21 — Routing Fallback Policy (complete, **ADR-0008**)
When `/search_predicates` returns no match for the caller's domain
scope, Engine A is invoked as the generalist fallback with an
explicit "no specialist matched" preamble so its tone calibrates to
uncertainty.

### Phase 22 — Sunset Classification Axes (complete, **ADR-0009**)
Retired the legacy `RouteAndPlan` 3-axis classifier in favor of
predicate-graph routing + a simplified `ExtractIntent` BAML function
(mode + entity_refs only). The persona split (caller-side vs
answerer-side) is also formalized here.

### Phase 23 — Distributed Tracing (complete, **ADR-0010**)
OTel-style trace propagation across BFF, Dagster, engines, and
Restate invocations. Enables end-to-end latency tracking per query.

### Phase 24 — DataHub Stack Stand-Up (complete)
Stood up the full DataHub v1.6.0 stack in the sandbox: GMS,
OpenSearch 2.18.0 (DataHub v1.6 incompatible with OpenSearch 3.x),
Redpanda (Kafka-compatible, no Zookeeper), Postgres (existing
`iagent-postgresql`). `DATAHUB_REVISION=3` mismatch between the GMS
and upgrade images required running a separate system-update job to
land the right schema marker.

### Phase 25 — Engine D Enrichment (complete)
Extended `_GENERIC_SEARCH_QUERY` to fetch `ownership`, `tags`,
`schemaMetadata`, upstream/downstream relationships, and the most
recent `operations.timestampMillis`. Response formatter emits per-
asset pipe-separated headers (`owner=`, `last_updated=`, `tags=`)
plus indented `description:`, `upstream:`, `downstream:`,
`columns:` continuation lines. **ADR-0013** scopes the planned
follow-up: replace the single fuzzy-search tool with a set of
capability tools (`get_owner`, `get_lineage`, `list_stale_assets`,
etc.) so the agent can ask specific questions rather than parse a
multi-line response.

### Phase 26 — UI Archetype Grounding Patch (complete)
BAML `DesignUI` prompt extended with explicit grounding rules
forbidding URN invention and steering catalog Q&A to
`KNOWLEDGE_DOCUMENT` (preserves owner/lineage/freshness as prose)
instead of `ASSET_STATE_METRIC` (a 4-column table widget that drops
those fields). **ADR-0012** documents the architectural tension —
the rigid `MetricUI` schema — and proposes the dynamic-columns
generalization as the long-term fix.

### Phase 27 — Engine A Tool Docstring Refactor (complete)
Engine D's wire format moved out of Engine A's system prompt and
into the `search_datahub` tool's docstring. Engine A's prompt is
again domain-level ("analyst persona, ground in tool results");
each tool documents its own response shape via its docstring. This
keeps Engine A loosely coupled to Engine D's format. Tool
docstrings are part of the BAML grounding contract, not
documentation prose.

## Persona Reference

Five domain-expert personas (BAML `PersonaTarget`). The supervisor
assigns sub-tasks; engines execute; Engine F maps to UI archetypes.

### MECHANIC
- **Icon:** Wrench (amber)
- **Engine E Response:** `MechanicResponse` — tool_list, safety_warnings, short_answer
- **Typical UI:** `HAZARD_DECLARATION` / `ASSET_STATE_METRIC`

### TECH_WRITER
- **Icon:** BookOpen (blue)
- **Engine E Response:** `AuthoringResponse` — draft_content (Markdown), missing_info_flags
- **Typical UI:** `KNOWLEDGE_DOCUMENT`

### LOGISTICS
- **Icon:** Truck (emerald)
- **Engine E Response:** `LogisticsResponse` — impacted_platforms, blocked_procedures, risk_severity
- **Typical UI:** `ASSET_STATE_METRIC` / `HAZARD_DECLARATION`

### AUDITOR
- **Icon:** ShieldCheck (red)
- **Engine E Response:** `AuditResponse` — non_compliant_nodes, rule_violated, recommended_fix
- **Typical UI:** `HAZARD_DECLARATION` / `KNOWLEDGE_DOCUMENT`

### PROCESS_ENGINEER
- **Icon:** Network (purple)
- **Engine E Response:** Any (depends on sub-query)
- **Typical UI:** `PROCESS_TOPOLOGY`

### DATA_STEWARD
- **Engine D / Engine A Response:** `DataStewardResponse` — tool_list, safety_warnings, short_answer
- **Typical UI:** `KNOWLEDGE_DOCUMENT` (catalog Q&A) / `ASSET_STATE_METRIC` (catalog listings)

## UI Archetypes

Engine F returns `DashboardUI` with `components` array of:

- **`PROCESS_TOPOLOGY`** — Full-width React Flow graph (nodes + edges).
- **`HAZARD_DECLARATION`** — Inline 2-col card. Risk alerts with severity.
- **`ASSET_STATE_METRIC`** — Inline 2-col card. id/name/type/description.
- **`KNOWLEDGE_DOCUMENT`** — Full-width Markdown via `react-markdown`.
- **`CHART_WIDGET`** — Recharts BAR / LINE / PIE / SCATTER.
- **`DIGITAL_TWIN_3D`** — three.js scene with anomaly highlighting.

Known limitation: `MetricUI`'s 4-column schema is too rigid for
catalog Q&A. ADR-0012 proposes a dynamic-columns generalization.

## ADR Index

| ADR | Subject | Status |
|-----|---------|--------|
| 0001 | mem0 LLM decouple | Accepted |
| 0002 | mem0 monkeypatches | Accepted |
| 0003 | LLM rightsizing | Accepted |
| **0004** | **Predicate graph routing** | **Accepted (current router)** |
| 0005 | Verb + concept namespaces | Accepted |
| 0006 | Verb registry location | Accepted |
| 0007 | Survey before mint | Accepted |
| 0008 | Routing fallback policy | Accepted |
| **0009** | **Sunset classification axes** | **Accepted** |
| 0010 | Distributed tracing strategy | Accepted |
| 0011 | Multi-SPO routing | Proposed (deferred) |
| 0012 | UI archetype rigidity | Proposed (workaround in place) |
| 0013 | Engine D capability surface | Proposed (workaround in place) |

When adding a load-bearing architectural change, draft an ADR in
`docs/adr/` following the template of the most recent ones.
