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

- **Ontology reasoner (Engine O)**: `POST http://ontology-svc.default.svc.cluster.local:8084/resolve`
  Accepts `{"query": "..."}`, returns `SemanticResolution` JSON.
- **Restate analyst (Engine A)**: `POST http://restate-agent-svc.default.svc.cluster.local:8081/analyze`
  Accepts `AgentTask` JSON. Internally calls Engine O `/resolve` for semantic
  context, then runs smolagents CodeAgent. Returns `AgentResponse` JSON.
- **LangGraph support (Engine B)**: `POST http://langgraph-agent-svc.default.svc.cluster.local:8082/support`
  Accepts `{task_description, dataset_id, thread_id}` JSON. Uses `thread_id`
  for PostgreSQL-backed conversational memory. Returns `AgentResponse` JSON.
- **Swarms scraper (Engine C)**: `POST http://swarms-agent-svc.default.svc.cluster.local:8083/scrape`
  Accepts `{task_description, dataset_id, semantic_context?}` JSON. Stateless
  heavy compute node. Returns `AgentResponse` JSON.
- **DataHub wrapper (Engine D)**: `GET http://datahub-wrapper-svc.default.svc.cluster.local:8085/tables`
  Queries DataHub GMS GraphQL for dbt datasets. Returns
  `{"available_tables": "table1, table2, ..."}`. 503 if DataHub unreachable.

## Dagster UI Configuration

Assets are configured with `kinds` and `group_name` for UI badges:
- `trigger_restate_analyst`: kinds={"restate", "smolagents"}, group="agent_fleet"
- `trigger_langgraph_support`: kinds={"langgraph", "postgres"}, group="agent_fleet"
- `trigger_swarms_scraper`: kinds={"swarms", "python"}, group="agent_fleet"
- `trigger_datahub_tables`: kinds={"datahub"}, group="data_layer"
- `sync_dbt_to_ontology`: kinds={"dbt", "datahub"}, group="data_layer"

**Icon support:** Dagster has ~200 built-in icons (dbt, datahub, postgres, python all have icons).
Custom icons for restate/smolagents/langgraph/swarms are NOT supported as kind badges.
Do NOT attempt to monkey-patch the Dagster webserver JS bundle; it's fragile and breaks on upgrades.

**Workaround — Metadata icon cards:** Custom SVG icons in `assets/icons/` are base64-encoded
and embedded in asset definition metadata via `MetadataValue.md()`. When clicking an asset
in the Dagster UI, the detail panel shows a rich card with the framework icon, name, and
description. The `_icon_card()` helper in `agent_routers.py` builds these cards.

## Development Progress

### Phase 8 — Engine D: DataHub Metadata Wrapper (complete)
- Created `agent_fleet/datahub_wrapper/main.py` — FastAPI on port 8085.
- `GET /tables` queries DataHub GMS GraphQL for dbt platform datasets.
- Parses URNs to extract clean table names, returns comma-separated list.
- Returns 503 if DataHub unreachable (callers should fall back to mock data).
- Uses `httpx.AsyncClient` — no ML frameworks, no agent SDKs.
- Env vars: `DATAHUB_GMS_URL` (default: `http://localhost:8080/api/graphql`),
  `DATAHUB_TOKEN` (optional).
- Dagster asset: `trigger_datahub_tables` (GET to :8085/tables, group: data_layer).
- CNB configs: Procfile + project.toml for port 8085.
- GET `/health` for liveness probes.

### Phase 1 — Shared Contracts (complete)
- Defined BAML contracts: `AgentTask`, `AgentResponse`, `SemanticResolution`,
  `AgentStatus`.
- Ontology classes are dynamic (from RDF graph), not hardcoded enums.
- Added `ClassifySustainmentIntent` BAML function — maps user queries to
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
  string → calls BAML `ClassifySustainmentIntent` → returns `SemanticResolution`.
- No compute or orchestration — strictly translates NL to IOF/MIMOSA terms.
- GET `/health` for liveness probes.

### Phase 3 — Engine A: Restate + Smolagents Analyst (complete)
- Created `agent_fleet/restate_analyst/main.py` — FastAPI on port 8081.
- Restate `AnalystService` with durable `analyze` handler.
- Handler flow: `ctx.run(resolve_ontology)` → `ctx.run(run_smolagent)` →
  return `AgentResponse`.
- Ontology pre-resolution injects `resolved_uri` + `suggested_dbt_models`
  into the CodeAgent prompt so it knows which tables to query.
- Proxy route `POST /analyze` forwards to `/restate/AnalystService/analyze`.
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

### Phase 7 — Data Mesh Bindings: dbt + DataHub (complete)
- Created `src/iagent/defs/data_layer.py` with `sync_dbt_to_ontology` asset.
- Reads dbt `manifest.json`, extracts `ontology_uri` meta tags from models.
- POSTs glossary term updates to DataHub GMS (gracefully handles offline).
- Writes `mapping.ttl` linking dbt models to ontology URIs.
- Proves Dagster keeps physical data (dbt) and semantic brain (ontology) in sync.
