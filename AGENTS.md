# AGENTS.md — AI Agent Workflow & Safety Guide

## Governing Architecture
This project implements the **Master Architect Recipe V3 (Polyglot Mesh
Edition)** — a strictly decoupled, Polyglot Microservice architecture:
- **Dagster Control Plane:** Ephemeral, lightweight pods. Uses `requests` to
  trigger agents. Does NOT use `PipesK8sClient`. Acts as central router.
- **Agent Fleet:** Multiple independent, permanent pods (or Knative-scaled)
  running FastAPI web servers. Each framework gets its own isolated codebase,
  OCI image, and K8s Service.
- **Tech stack constraints:** Dagster (orchestration), FastAPI (API layer),
  BAML (interface), Restate+Smolagents (Engine A), LangGraph (Engine B),
  Swarms.ai (Engine C), dbt+DataHub (data layer, implemented),
  dlthub+Neo4j+Weaviate (data layer, planned).

## Project Overview
**Invincible Agent (iagent)** is a Dagster-orchestrated control plane that
dispatches work to ephemeral Kubernetes agent pods via HTTP. This repo contains
the orchestrator and the agent fleet as co-located but isolated services.

## Repository Map
```
src/iagent/
  definitions.py          # Dagster entry point (auto-loads defs/)
  defs/
    agent_routers.py      # @asset functions that POST to agent pods
    data_layer.py         # @asset: dbt ↔ ontology ↔ DataHub sync
    dynamic_factory.py    # Dynamic BPMN Factory: reads bpmn_catalog, generates jobs/ops
agent_fleet/
  ontology_service/
    main.py               # Engine O: FastAPI ontology reasoner (port 8084)
    iof_mro.ttl           # Dummy IOF/MIMOSA MRO ontology
    Procfile              # CNB: uvicorn on port 8084
    project.toml          # CNB: Python 3.12, PORT=8084
  restate_analyst/
    main.py               # Engine A: Restate + Smolagents analyst (port 8081)
    Procfile              # CNB: uvicorn on port 8081
    project.toml          # CNB: Python 3.12, PORT=8081
  langgraph_support/
    main.py               # Engine B: LangGraph support agent (port 8082)
    Procfile              # CNB: uvicorn on port 8082
    project.toml          # CNB: Python 3.12, PORT=8082
  swarms_scraper/
    main.py               # Engine C: Swarms.ai scraper/extraction (port 8083)
    Procfile              # CNB: uvicorn on port 8083
    project.toml          # CNB: Python 3.12, PORT=8083
  datahub_wrapper/
    main.py               # Engine D: DataHub metadata wrapper (port 8085)
    Procfile              # CNB: uvicorn on port 8085
    project.toml          # CNB: Python 3.12, PORT=8085
  models.py               # SQLAlchemy ORM model for bpmn_catalog table
sql/
  create_bpmn_catalog.sql # Raw SQL: CREATE TABLE + trigger + index
baml_shared/
  baml_src/
    contracts.baml        # Shared data contracts (source of truth)
    generators.baml       # BAML codegen configuration
  baml_client/            # Auto-generated — DO NOT EDIT
tests/                    # Test suite
pyproject.toml            # Project config
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
2. Run `baml generate` to regenerate the Python client.
3. Never hand-edit anything in `baml_shared/baml_client/`.
4. Verify downstream agents still conform to the updated schema.

### When adding a BPMN workflow to bpmn_catalog
1. Insert a row into the `bpmn_catalog` table with a valid BPMN JSON payload.
   The payload must have `tasks`, `gateways`, and `sequence_flows` arrays.
2. Each task must have: `id`, `name`, `type` (service_task|user_task), `agent_endpoint`.
3. Set `is_active = TRUE` so `dynamic_factory.py` picks it up on next load.
4. Restart Dagster (or reload definitions) — `build_dynamic_jobs()` runs at
   module-load time and generates jobs/ops from the catalog.
5. The generated job appears in the Dagster UI Jobs tab, named by `workflow_id`.

### When modifying dynamic_factory.py
1. Dynamic ops use `requests.post()` only — same rules as orchestrator assets.
2. Every op must `yield AssetMaterialization` for data lineage.
3. Every op must `yield Output` so downstream ops can receive the result.
4. Gateways are collapsed transparently — `_resolve_task_to_task_flows()` traces
   through gateway nodes to find task-to-task edges.
5. Test changes by inserting a sample BPMN payload and verifying the job graph.

### When adding dependencies
1. Add to `[project.dependencies]` in `pyproject.toml`.
2. Dev-only deps go in `[dependency-groups] dev`.
3. Run `uv sync` to update the lockfile.

## Safety & Boundaries

### DO NOT
- Use `PipesK8sClient` for any agents — Dagster uses only `requests`.
- Use Dockerfiles — all images are built with Cloud Native Buildpacks (`pack`).
- Import ML frameworks (torch, transformers, etc.) in the orchestrator.
- Import Restate SDK or LangGraph SDK in the orchestrator.
- Mix framework imports across engines (e.g. no Restate in Engine B).
- Import Dagster, ML frameworks, or agent SDKs in the ontology service.
- Import Restate, Dagster, or smolagents in Engine B (LangGraph support).
- Import Restate, LangGraph, Dagster, or checkpointers in Engine C (Swarms scraper).
- Add compute or orchestration logic to Engine O — it is pure semantic resolution.
- Hardcode secrets, API keys, or credentials anywhere.
- Edit auto-generated files in `baml_shared/baml_client/`.
- Run `dagster dev` or `dg dev` in CI — it starts a web server.
- Commit `.env` files or anything containing secrets.

### DO
- Keep the orchestrator lightweight — it only dispatches HTTP calls.
- Use BAML contracts as the single source of truth for schemas.
- Add `response.raise_for_status()` before parsing any HTTP response.
- Set explicit timeouts on all outbound HTTP requests.
- Write tests for new assets in `tests/`.
- Use `ruff` for linting before committing.

## Agent Pod Endpoints
These are the Kubernetes services the orchestrator communicates with:

- **Ontology reasoner (Engine O)**: `POST http://ontology-svc.default.svc.cluster.local:8084/resolve` and `POST /plan`
  Accepts `{"query": "..."}`, returns `SemanticResolution` JSON (`/resolve`) or `SupervisorTaskPlan` (`/plan`).
- **Restate analyst (Engine A)**: `POST http://restate-agent-svc.default.svc.cluster.local:8081/analyze`
  Accepts `AgentTask` JSON. Internally calls Engine O `/resolve` for semantic
  context, then runs smolagents CodeAgent. Returns `AgentResponse` JSON.
- **LangGraph support (Engine B)**: `POST http://langgraph-agent-svc.default.svc.cluster.local:8082/support`
  Accepts `{thread_id, user_query, dagster_context?, task_description?, dataset_id?}` JSON. Uses `thread_id`
  for PostgreSQL-backed conversational memory and injects `dagster_context` as a SystemMessage. Returns `AgentResponse` JSON.
- **Swarms scraper (Engine C)**: `POST http://swarms-agent-svc.default.svc.cluster.local:8083/scrape`
  Accepts `{task_description, dataset_id, semantic_context?}` JSON. Stateless
  heavy compute node. Returns `AgentResponse` JSON.
- **DataHub wrapper (Engine D)**: `POST http://datahub-wrapper-svc.default.svc.cluster.local:8085/query_metadata`
  Accepts a natural language query, dynamically applies platform filters, and executes 
  a multi-entity GraphQL search. Returns `ExpertResponse` with matched asset context. 503 if DataHub unreachable.
- **Neo4j Graph Expert (Engine E)**: `POST http://neo4j-expert-svc.default.svc.cluster.local:8086/query_graph`
  Queries a Neo4j military graph database. Uses Restate for durable execution,
  smolagents `CodeAgent`, and `mem0` backed by Weaviate for long-term memory. Returns rigidly typed BAML `GraphExpertResponse`.
- **Presentation Agent (Engine F)**: `POST http://presentation-agent-svc.default.svc.cluster.local:8087/render_ui`
  Stateless UI router separating Model from View. Translates raw JSON arrays into abstract `SemanticUIContainer` objects (Intent-Based UI) tailored to the active persona via UX LLM routing. Natively supports the `PROCESS_TOPOLOGY` archetype for the `PROCESS_ENGINEER` persona.
- **Orchestration Gateway**: `POST /orchestrate`
  Top-level FastAPI gateway (Engine G). Acts as a decoupled GraphQL client to the Dagster 
  Webserver. Submits `supervisor_query_job`, polls for completion, and fetches the final 
  UI instruction from step metadata. Provides full observability and run history.
- **Weaviate Semantic Expert (Engine W)**: `POST http://weaviate-expert-svc.default.svc.cluster.local:8088/query_knowledge`
  Handles pure knowledge retrieval intents. Searches technical manuals via Weaviate v4
  with strict domain segregation. Returns structured Markdown summaries and citations.

## Dagster UI Configuration

Assets are configured with `kinds` and `group_name` for UI badges:
- `trigger_restate_analyst`: kinds={"restate", "smolagents"}, group="agent_fleet"
- `trigger_langgraph_support`: kinds={"langgraph", "postgres"}, group="agent_fleet"
- `trigger_swarms_scraper`: kinds={"swarms", "python"}, group="agent_fleet"
- `trigger_datahub_tables`: kinds={"datahub"}, group="data_layer"
- `trigger_neo4j_expert`: kinds={"restate", "python", "smolagents", "neo4j"}, group="agent_fleet"
- `trigger_presentation_agent`: kinds={"fastapi", "python"}, group="agent_fleet"
- `sync_dbt_to_ontology`: kinds={"dbt", "datahub"}, group="data_layer"

**Icon support:** Dagster has ~200 built-in icons (dbt, datahub, postgres, python all have icons).
Custom icons for restate/smolagents/langgraph/swarms are NOT supported as kind badges.
Do NOT attempt to monkey-patch the Dagster webserver JS bundle; it's fragile and breaks on upgrades.

**Workaround — Metadata icon cards:** Custom SVG icons in `assets/icons/` are base64-encoded
and embedded in asset definition metadata via `MetadataValue.md()`. When clicking an asset
in the Dagster UI, the detail panel shows a rich card with the framework icon, name, and
description. The `_icon_card()` helper in `agent_routers.py` builds these cards.

## Development Progress

### Phase 1 — Shared Contracts (complete)
- Defined BAML contracts: `AgentTask`, `AgentResponse`, `SemanticResolution`,
  `AgentStatus`.
- Ontology classes are dynamic (from RDF graph), not hardcoded enums.
- Added `ClassifyDomainIntent` BAML function — maps user queries to
  ontology URIs injected at runtime via `active_ontology_classes` parameter.
- Generated Python/Pydantic client via BAML codegen.

### Phase 2 — Orchestrator Control Plane (complete)
- Created `agent_routers.py` with two Dagster assets:
  - `trigger_restate_analyst` → POST to :8081/analyze
  - `trigger_langgraph_support` → POST to :8082/support
- Pure HTTP dispatch, no SDK dependencies.

### Phase 2.5 — Engine O: Ontology Reasoner (complete)
- Created `agent_fleet/ontology_service/main.py` — FastAPI on port 8084.
- Loads `iof_mro.ttl` (dummy IOF/MIMOSA MRO ontology) into rdflib on startup.
- POST `/resolve`: SPARQL-queries graph for sustainment classes → formats as
  string → calls BAML `ClassifyDomainIntent` → returns `SemanticResolution`.
- No compute or orchestration — strictly translates NL to IOF/MIMOSA terms.
- GET `/health` for liveness probes.

### Phase 3 — Engine A: Restate + Smolagents Analyst (complete)
- Created `agent_fleet/restate_analyst/main.py` — FastAPI on port 8081.
- Restate `AnalystService` with durable `analyze` handler.
- Handler flow: `ctx.run(resolve_ontology)` → `ctx.run(run_smolagent)` →
  return `AgentResponse`.
- Ontology pre-resolution injects `resolved_uri`
  into the CodeAgent prompt.
- Proxy route `POST /analyze` forwards to `/restate/AnalystService/analyze`.
- Restate `Workflow("BPMNWorkflowRunner")` for durable BPMN task execution:
  - `ServiceTask` → `ctx.run()` (durable HTTP POST).
  - `UserTask` → `ctx.promise("approval_{task_id}").value()` (zero-cost waiting).
  - `approve` handler resolves the promise, waking up the workflow.
- `POST /workflow/start` — kicks off a workflow via Restate ingress.
- `POST /workflow/{wf}/task/{tid}/approve` — resolves a paused UserTask.
- GET `/health` for liveness probes.

### Phase 4 — Engine B: LangGraph Support Agent (complete)
- Created `agent_fleet/langgraph_support/main.py` — FastAPI on port 8082.
- Two-node StateGraph: `triage` → `respond` → END.
- `AsyncPostgresSaver` checkpointer for conversational memory keyed by `thread_id`.
- POST `/support` invokes the graph with thread config and returns `AgentResponse`.
- Entirely isolated from Engine A — no Restate/Dagster/smolagents imports.
- GET `/health` for liveness probes.

### Phase 5 — Engine C: Swarms.ai Scraper (complete)
- Created `agent_fleet/swarms_scraper/main.py` — FastAPI on port 8083.
- Swarms.ai `SequentialWorkflow` with a `DataExtractor` agent.
- POST `/scrape` runs the workflow and returns `AgentResponse`.
- Completely isolated — no Restate, LangGraph, Dagster, or checkpointers.
- Model configurable via `SWARMS_MODEL` env var (default: gpt-4o-mini).
- GET `/health` for liveness probes.

### Phase 6 — Cloud Native Buildpacks Containerization (complete)
- No Dockerfiles. All OCI images built with `pack` CLI + `paketobuildpacks/builder-jammy-base`.
- Each service in `agent_fleet/` now has a `Procfile` (uvicorn start command)
  and `project.toml` (Python 3.12, PORT env var).
- CI/CD build commands:
  - `pack build myregistry/ontology-service --path ./agent_fleet/ontology_service --builder paketobuildpacks/builder-jammy-base`
  - `pack build myregistry/restate-analyst --path ./agent_fleet/restate_analyst --builder paketobuildpacks/builder-jammy-base`
  - `pack build myregistry/langgraph-support --path ./agent_fleet/langgraph_support --builder paketobuildpacks/builder-jammy-base`
  - `pack build myregistry/swarms-scraper --path ./agent_fleet/swarms_scraper --builder paketobuildpacks/builder-jammy-base`
  - `pack build myregistry/weaviate-expert --path ./agent_fleet/weaviate_expert --builder paketobuildpacks/builder-jammy-base`

### Phase 7 — Data Mesh Bindings: dbt + DataHub (complete)
- Created `src/iagent/defs/data_layer.py` with `sync_dbt_to_ontology` asset.
- Reads dbt `manifest.json`, extracts `ontology_uri` meta tags from models.
- POSTs glossary term updates to DataHub GMS (gracefully handles offline).
- Writes `mapping.ttl` linking dbt models to ontology URIs.
- Proves Dagster keeps physical data (dbt) and semantic brain (ontology) in sync.

### Phase 8 — Engine D: DataHub Metadata Wrapper (complete)
- Created `agent_fleet/datahub_wrapper/main.py` — FastAPI on port 8085.
- `POST /query_metadata` executes a generic GraphQL search for metadata discovery.
- (Deleted) Legacy asset `trigger_datahub_tables`.
- CNB configs: Procfile + project.toml for port 8085.
- GET `/health` for liveness probes.

### Phase 9 — Dynamic BPMN Interpreter (in progress)
- Implementing the Imperative-Declarative Hybrid Pattern in Dagster.
- Created `src/iagent/defs/dynamic_factory.py` with three sub-phases:
  - **9.1 Database Fetcher**: `fetch_active_bpmn_models()` queries `bpmn_catalog`
    table via psycopg2. Gracefully returns `[]` on connection failure.
  - **9.2 Dynamic Op Factory**: `create_agent_op(task_node, input_names, gateway_branches)`
    generates `@op` at runtime — POSTs to agent endpoint, yields `AssetMaterialization`,
    yields `Output` for downstream chaining. Tasks preceding exclusive gateways get
    `Out(is_required=False)` per branch; `_evaluate_condition()` evaluates the
    `condition_expression` against the HTTP response and yields only the first match.
  - **9.3 Graph Builder**: `build_gateway_routing()` maps tasks to their gateway
    branches. `_resolve_direct_flows()` handles non-gateway edges. `build_dynamic_jobs()`
    wires both direct (`"result"`) and gateway (`"branch_{target_id}"`) outputs via
    `GraphDefinition` + `DependencyDefinition`, converts to `JobDefinition`.
- Supporting files:
  - `agent_fleet/models.py` — SQLAlchemy ORM for `bpmn_catalog` table.
  - `sql/create_bpmn_catalog.sql` — Raw SQL with auto-update trigger + partial index.
- Env vars: `BPMN_POSTGRES_HOST`, `BPMN_POSTGRES_PORT`, `BPMN_POSTGRES_DB`,
  `BPMN_POSTGRES_USER`, `BPMN_POSTGRES_PASSWORD`, `AGENT_HTTP_TIMEOUT` (default: 300).

### Phase 10 — Engine E: Neo4j Graph Expert (complete)
- Created `agent_fleet/neo4j_expert/main.py` — FastAPI on port 8086.
- Integrates Restate SDK with smolagents `CodeAgent` and BAML typing.
- Evaluates queries against a military technical manual graph database (S1000D, IADS).
- Defines explicit `@tool` for `execute_cypher` and `get_graph_schema` to allow the agent to self-correct.
- Wraps execution in `ctx.run("run-smolagent")` and `ctx.run("format-baml")` for durable reliability.
- Added `trigger_neo4j_expert` remote asset to Dagster control plane.

### Phase 11 — Dynamic Supervisor & Synthesis Recipes (complete)
- **Phase 2 (Dynamic Fan-Out):** Upgraded Engine O with a `/plan` endpoint that scales multi-domain queries into lists using BAML `DecomposeQuery`. Written `dynamic_supervisor.py` for Dagster to asynchronously fan-out HTTP requests to Engine E for each persona-specific sub-task.
- **Recipe 1 (Path A - Stateless Dagster Synthesis):** Configured Dagster to synthesize Engine E's JSON array into a cohesive Markdown report using `b.SynthesizeReports` entirely within the Dagster op (`synthesize_stateless`).
- **Recipe 2 (Path B - Stateful LangGraph Synthesis):** Updated Dagster fan-in to pipe `dagster_context` json into Engine B (LangGraph Support) via `/support` payload, retaining `thread_id` to allow follow-up questions using memory.
- **Recipe 3 (Phase 3 - Long-Term Episodic Memory):** Augmented Neo4j Graph Expert with long-term episodic memory via `mem0` paired with `weaviate-client`. Retrieves and saves past successful Cypher queries across ephemeral K8s pods into persistent Vector Storage.

### Phase 12 — Engine F: Presentation Agent (complete)
- Created `agent_fleet/presentation_agent/main.py` — FastAPI on port 8087.
- Defined `ui_contracts.baml` introducing `MoodType`, `UIComponentType`, and the `DesignUI` routing function map.
- Added `PROCESS_ENGINEER` to `PersonaTarget` in main contracts.
- Integrated Engine F directly into the Dynamic Supervisor to map output aggregates into Server-Driven UI instructions.
- **Backend Capstone:** Finalized the Dagster loop in `dynamic_supervisor.py` and implemented `src/iagent/gateway.py` to expose the entire multi-agent workflow via a single synchronous HTTP endpoint.

### Phase 13 — Composite Dashboard & Persona Loading State (complete)
- **DashboardUI Contract:** Added `DashboardUI` class to `contracts.baml` wrapping a `components` array of UI unions (`TopologyUI | HazardUI | MetricUI | DocumentUI`). `DesignUI` now returns `DashboardUI` instead of a single component, enabling multi-panel composite dashboards from a single query.
- **Persona Icon Broadcasting:** `create_task_plan` in `dynamic_supervisor.py` now yields an `AssetMaterialization(asset_key=["active_agent_roster"])` with a `personas` metadata entry. The BFF polls for this via GraphQL `eventConnection` and emits an SSE `action: "plan"` event carrying the persona list. The frontend renders animated persona icons ("Agents Assembling") during the fan-out phase.
- **GraphQL `__typename` Fix:** Fixed `_get_run_events()` in the BFF to include `__typename` on the `runOrError` query so the guard `run_data.get("__typename") != "Run"` no longer silently drops all materializations.
- **RadarReveal Animation:** New frontend component renders each dashboard section with a 3-phase reveal: horizontal neon scan line → vertical expand → content fade-in, staggered per component.
- **Markdown Rendering:** Replaced raw text dump with `react-markdown` for `KNOWLEDGE_DOCUMENT` archetype.
- **Metrics Table Fix:** Updated `SupplyTable` to map BAML `UIEntity` fields (`name`, `type`, `description`) instead of nonexistent `value`/`metric` fields.

### Phase 14 — Comprehensive Helm Charting (complete)
- Expanded Helm chart in `helm/invincible-agent` to cover the full service stack.
- Added `engineF`, `cortexUi`, and `cortexBff` definitions.
- Integrated infrastructure templates for Neo4j, Weaviate, and Fuseki with optional `enabled` flags.
- Implemented `post-install` and `post-upgrade` Helm hooks for `restate-init` and `db-init` jobs.
- Added `InitContainers` to all jobs for robust dependency polling (waiting for agents and DBs to be healthy).
- Unified fleet-wide service discovery via a central ConfigMap and helper templates.

### Phase 15 — Multi-Domain Agentic Mesh Upgrade (complete)
- **Intelligent Routing**: Updated BAML contracts to extract `Domain` (MAINTENANCE, SUSTAINMENT, DATA_ENGINEERING) and `Intent` (ONE_SHOT_QUERY, PROCESS_CREATION).
- **Strict Data Segregation (Graph)**: Implemented SPARQL Named Graph injection in Engine O to isolate domain ontologies.
- **Strict Data Segregation (Neo4j)**: Enforced domain-specific Node Label constraints in Engine E (Neo4j Expert) to prevent cross-domain data leakage.
- **Unified Orchestration**: Enhanced the BFF and Dagster supervisor to propagate domain context throughout the multi-agent fan-out.

### Phase 16 — Engine W: Weaviate Semantic Expert (complete)
- Created `agent_fleet/weaviate_expert/service.py` — FastAPI on port 8088.
- Dedicated semantic retriever using Weaviate v4 `near_text` and `Filters`.
- Optimized for `KNOWLEDGE_RETRIEVAL` intents requiring manual summaries without graph lookups.
- Integrated into Helm chart as a Deployment/Service pair.

## Persona Reference

The system supports 5 domain-expert personas defined in `PersonaTarget` (BAML enum).
Engine O decomposes user queries and assigns sub-tasks to the appropriate persona.
Engine E executes each sub-task against the Neo4j graph DB.
Engine F maps the aggregated results into UI archetypes per persona.

### MECHANIC
- **Icon:** Wrench (amber)
- **Graph Expert Response:** `MechanicResponse` — `tool_list`, `safety_warnings`, `short_answer`
- **Typical UI Archetype:** `HAZARD_DECLARATION` (safety warnings, risk alerts) or `ASSET_STATE_METRIC` (tool/part tables)
- **Use Case:** Safety hazards, tool requirements, hands-on maintenance procedures

### TECH_WRITER
- **Icon:** BookOpen (blue)
- **Graph Expert Response:** `AuthoringResponse` — `draft_content` (Markdown), `missing_info_flags`
- **Typical UI Archetype:** `KNOWLEDGE_DOCUMENT` (rendered Markdown documentation)
- **Use Case:** Technical procedure overviews, manual drafts, documentation gaps

### LOGISTICS
- **Icon:** Truck (emerald)
- **Graph Expert Response:** `LogisticsResponse` — `impacted_platforms`, `blocked_procedures`, `risk_severity`
- **Typical UI Archetype:** `ASSET_STATE_METRIC` (supply tables) or `HAZARD_DECLARATION` (blocked procedure alerts)
- **Use Case:** Platform impact analysis, supply chain risks, blocked procedures

### AUDITOR
- **Icon:** ShieldCheck (red)
- **Graph Expert Response:** `AuditResponse` — `non_compliant_nodes`, `rule_violated`, `recommended_fix`
- **Typical UI Archetype:** `HAZARD_DECLARATION` (compliance violations) or `KNOWLEDGE_DOCUMENT` (audit reports)
- **Use Case:** Compliance auditing, regulatory violations, corrective action recommendations

### PROCESS_ENGINEER
- **Icon:** Network (purple)
- **Graph Expert Response:** Any (depends on sub-query)
- **Typical UI Archetype:** `PROCESS_TOPOLOGY` (workflow graphs with nodes/edges for React Flow)
- **Use Case:** Process step mapping, workflow visualization, procedure sequencing

## Semantic UI Archetypes

Engine F outputs a `DashboardUI` containing an array of components. Each component uses one of these archetypes:

- **`PROCESS_TOPOLOGY`** — Full-width workflow graph. Nodes and edges rendered via React Flow. Triggers blueprint phase.
- **`HAZARD_DECLARATION`** — Inline card. Red/amber risk alerts with severity badges and hazard lists.
- **`ASSET_STATE_METRIC`** — Inline card. Entity/Type/Detail table for telemetry, inventory, or tool lists.
- **`KNOWLEDGE_DOCUMENT`** — Full-width Markdown document rendered via `react-markdown`.

Layout rule: `PROCESS_TOPOLOGY` and `KNOWLEDGE_DOCUMENT` span full width. `HAZARD_DECLARATION` and `ASSET_STATE_METRIC` flow inline in a 2-column grid.

