<p align="center">
  <img src="assets/icon.jpg" alt="Invincible Agent" width="280"/>
</p>

<h1 align="center">Invincible Agent</h1>

<p align="center">
  <strong>Polyglot Agentic Data Mesh on Kubernetes</strong><br/>
  Built to the Master Architect Recipe V3 (Polyglot Mesh Edition)
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Dagster-1.12.x-4F43DD?style=flat-square" alt="Dagster"/>
  <img src="https://img.shields.io/badge/BAML-0.219.x-FF6B6B?style=flat-square" alt="BAML"/>
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square" alt="Python"/>
  <img src="https://img.shields.io/badge/K8s-CNB%20Buildpacks-326CE5?style=flat-square" alt="Kubernetes"/>
</p>

---

## Architecture

<p align="center">
  <img src="assets/arch.jpg" alt="Invincible Agent Architecture" width="900"/>
</p>

A strictly decoupled, polyglot microservice architecture where a **Dagster control plane** orchestrates an **agent fleet** of independent FastAPI pods on Kubernetes. Each agent engine has its own isolated codebase, OCI image, and K8s Service.

### Dagster Control Plane
Ephemeral, lightweight pods. Uses only the `requests` library to trigger agents via internal K8s URLs. Does **not** use `PipesK8sClient`. Dagster acts as the central router, determining which framework to call.

### Agent Fleet

| Engine | Framework | Port | Endpoint | Role |
|--------|-----------|------|----------|------|
| **O** | rdflib + BAML | 8084 | `/resolve`, `/plan` | Ontology reasoner — translates NL → IOF/MIMOSA URIs, dynamic decomposer |
| **A** | Restate + Smolagents | 8081 | `/analyze`, `/workflow/start`, `/workflow/{wf}/task/{tid}/approve` | Durable analyst + BPMN workflow runner |
| **B** | LangGraph + PostgreSQL | 8082 | `/support` | Stateful support — conversational memory via checkpointer |
| **C** | Swarms.ai | 8083 | `/scrape` | Stateless heavy compute — high-concurrency extraction |
| **D** | httpx + DataHub GMS | 8085 | `/tables` | Metadata wrapper — queries DataHub for dbt dataset list |
| **E** | Restate + smolagents + mem0 | 8086 | `/query_graph` | Neo4j Graph Expert — queries military technical manual DB w/ memory |
| **F** | FastAPI + BAML | 8087 | `/render_ui` | Presentation Agent — Router separating model/view by persona |

### Data Flow

```
User Query
    │
    ▼
┌──────────┐     ┌────────────┐     ┌─────────────────────┐
│  Dagster  │────▶│  Engine O  │────▶│  Engine A / B / C   │
│  Control  │     │  Ontology  │     │  (Agent Fleet)      │
│  Plane    │     │  Reasoner  │     │                     │
└──────────┘     └────────────┘     └─────────────────────┘
    │                                         │
    ▼                                         ▼
┌──────────┐                          ┌──────────────┐
│   dbt    │◀─── mapping.ttl ────────▶│   DataHub    │
│ manifest │                          │   Glossary   │
└──────────┘                          └──────────────┘
```

---

## Tech Stack (V3 Strict Constraints)

| Layer | Technology | Purpose |
|-------|-----------|--------|
| **Orchestration** | Dagster 1.12.x | Triggers, routing, asset catalog |
| **API Layer** | FastAPI + uvicorn | Universal wrapper for all agent frameworks |
| **Interface** | BAML 0.219.x | Type-safe LLM parsing & prompting, shared across agents |
| **Engine A** | Restate SDK + smolagents | Durable, serverless, code-centric agents |
| **Engine B** | LangGraph + AsyncPostgresSaver | Stateful DAGs with async checkpointers |
| **Engine C** | Swarms.ai | High-concurrency topologies |
| **Data (implemented)** | dbt, DataHub | Transformation & catalog/glossary sync |
| **Data (planned)** | dlthub, Neo4j, Weaviate | Ingestion, knowledge graph, vector search |
| **Infra** | CNB Buildpacks, Kubernetes | No Dockerfiles — OCI images via `pack` CLI |

---

## Project Structure

```
src/iagent/
  definitions.py              # Dagster entry point (auto-loads defs/)
  defs/
    agent_routers.py          # @asset: HTTP dispatchers for Engines A, B, C, D
    data_layer.py             # @asset: dbt ↔ ontology ↔ DataHub sync
    dynamic_factory.py        # Dynamic BPMN Factory: reads bpmn_catalog, generates jobs/ops
    dynamic_supervisor.py     # Phase 2 Dynamic Fan-Out/Fan-In job for multi-domain queries

agent_fleet/
  ontology_service/
    main.py                   # Engine O: FastAPI ontology reasoner (port 8084)
    iof_mro.ttl               # IOF/MIMOSA MRO ontology
    Procfile / project.toml   # CNB buildpack config
  restate_analyst/
    main.py                   # Engine A: Restate + Smolagents (port 8081)
    Procfile / project.toml
  langgraph_support/
    main.py                   # Engine B: LangGraph + PostgreSQL (port 8082)
    Procfile / project.toml
  swarms_scraper/
    main.py                   # Engine C: Swarms.ai (port 8083)
    Procfile / project.toml
  datahub_wrapper/
    main.py                   # Engine D: DataHub metadata wrapper (port 8085)
    Procfile / project.toml
  neo4j_expert/
    main.py                   # Engine E: Neo4j Graph Expert (port 8086)
    Procfile / project.toml
  presentation_agent/
    main.py                   # Engine F: Presentation Agent (port 8087)
    Procfile / project.toml
  models.py                   # SQLAlchemy ORM model for bpmn_catalog table

sql/
  create_bpmn_catalog.sql     # Raw SQL: CREATE TABLE + auto-update trigger

baml_shared/
  baml_src/
    contracts.baml            # Shared data contracts (source of truth)
    generators.baml           # BAML codegen → Python/Pydantic
  baml_client/                # Auto-generated — DO NOT EDIT
```

---

## Shared Data Contracts (BAML)

All inter-service communication uses schemas defined in `contracts.baml`:

| Schema | Description |
|--------|-------------|
| `AgentTask` | Universal input payload (task_description, dataset_id, semantic_context?) |
| `AgentResponse` | Universal output (status, summary, extracted_metrics) |
| `SemanticResolution` | Ontology resolution result (resolved_uri, confidence_score, suggested_dbt_models) |
| `AgentStatus` | Enum: `SUCCESS` · `FAILED` · `HUMAN_REQUIRED` |
| `ClassifySustainmentIntent` | BAML function — maps queries to dynamic ontology URIs from the RDF graph |

Ontology classes are **never hardcoded** — they are dynamically injected at runtime from the RDF graph via the `active_ontology_classes` parameter.

---

## Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [pack CLI](https://buildpacks.io/docs/tools/pack/) (for container builds)

### Install Dependencies

```bash
uv sync
```

Activate the virtual environment:

| OS | Command |
| --- | --- |
| macOS / Linux | `source .venv/bin/activate` |
| Windows | `.venv\Scripts\activate` |

### Regenerate BAML Client

After modifying `baml_shared/baml_src/contracts.baml`:

```bash
baml-cli generate --from baml_shared/baml_src
```

### Run Dagster (Control Plane)

```bash
dg dev
```

Open [http://localhost:3000](http://localhost:3000) to see the asset graph.

### Run Agent Services (Local Dev)

Each engine runs independently:

```bash
# Engine O — Ontology Reasoner
uvicorn agent_fleet.ontology_service.main:app --port 8084

# Engine A — Restate Analyst
uvicorn agent_fleet.restate_analyst.main:app --port 8081

# Engine B — LangGraph Support
uvicorn agent_fleet.langgraph_support.main:app --port 8082

# Engine C — Swarms Scraper
uvicorn agent_fleet.swarms_scraper.main:app --port 8083

# Engine D — DataHub Wrapper
uvicorn agent_fleet.datahub_wrapper.main:app --port 8085

# Engine E — Neo4j Graph Expert
uvicorn agent_fleet.neo4j_expert.main:app --port 8086

# Engine F — Presentation Agent
uvicorn agent_fleet.presentation_agent.main:app --port 8087
```

---

## Building Container Images (CNB)

No Dockerfiles. All OCI images are built with Cloud Native Buildpacks:

```bash
pack build myregistry/ontology-service  --path ./agent_fleet/ontology_service  --builder paketobuildpacks/builder-jammy-base
pack build myregistry/restate-analyst   --path ./agent_fleet/restate_analyst   --builder paketobuildpacks/builder-jammy-base
pack build myregistry/langgraph-support --path ./agent_fleet/langgraph_support --builder paketobuildpacks/builder-jammy-base
pack build myregistry/swarms-scraper    --path ./agent_fleet/swarms_scraper    --builder paketobuildpacks/builder-jammy-base
pack build myregistry/datahub-wrapper   --path ./agent_fleet/datahub_wrapper   --builder paketobuildpacks/builder-jammy-base
pack build myregistry/neo4j-expert      --path ./agent_fleet/neo4j_expert      --builder paketobuildpacks/builder-jammy-base
pack build myregistry/presentation-agent --path ./agent_fleet/presentation_agent --builder paketobuildpacks/builder-jammy-base
```

---

## Kubernetes Services

| Service | Internal URL |
|---------|-------------|
| Engine O | `http://ontology-svc.default.svc.cluster.local:8084/resolve` |
| Engine A | `http://restate-agent-svc.default.svc.cluster.local:8081/analyze` |
| Engine B | `http://langgraph-agent-svc.default.svc.cluster.local:8082/support` |
| Engine C | `http://swarms-agent-svc.default.svc.cluster.local:8083/scrape` |
| Engine D | `http://datahub-wrapper-svc.default.svc.cluster.local:8085/tables` |
| Engine E | `http://neo4j-expert-svc.default.svc.cluster.local:8086/query_graph` |
| Engine F | `http://presentation-agent-svc.default.svc.cluster.local:8087/render_ui` |

All services expose `GET /health` for liveness probes.

---

## Environment Variables

| Variable | Service | Default | Description |
|----------|---------|---------|-------------|
| `BPMN_POSTGRES_HOST` | Dagster | `localhost` | PostgreSQL host for bpmn_catalog |
| `BPMN_POSTGRES_PORT` | Dagster | `5432` | PostgreSQL port for bpmn_catalog |
| `BPMN_POSTGRES_DB` | Dagster | `iagent` | PostgreSQL database name |
| `BPMN_POSTGRES_USER` | Dagster | `iagent` | PostgreSQL user |
| `BPMN_POSTGRES_PASSWORD` | Dagster | `iagent` | PostgreSQL password |
| `AGENT_HTTP_TIMEOUT` | Dagster | `120` | HTTP timeout (seconds) for agent calls from dynamic ops |
| `LANGGRAPH_POSTGRES_URI` | Engine B | `postgresql://langgraph:langgraph@localhost:5432/langgraph` | PostgreSQL for checkpointer |
| `SWARMS_MODEL` | Engine C | `gpt-4o-mini` | LLM model for Swarms agents |
| `OPENAI_API_KEY` | Engine O, C | — | Required for LLM calls |
| `HF_TOKEN` | Engine A | — | HuggingFace API token for smolagents |
| `DATAHUB_GMS_URL` | Engine D | `http://localhost:8080/api/graphql` | DataHub GraphQL endpoint |
| `DATAHUB_TOKEN` | Engine D | — | Optional DataHub personal access token |

---

## Design Principles

1. **Strict Decoupling** — Each engine is an isolated pod. No cross-engine imports. Dagster never imports agent SDKs.
2. **FastAPI Everywhere** — Universal API wrapper for all agent frameworks.
3. **BAML as Interface** — Type-safe contracts shared across the entire mesh.
4. **Ontology-First** — All agents resolve intent through the RDF knowledge graph before executing.
5. **Durable by Default** — Engine A wraps all side effects in Restate `ctx.run()` for exactly-once execution.
6. **Stateful When Needed** — Engine B uses PostgreSQL-backed checkpointers for conversational memory.
7. **No Dockerfiles** — Cloud Native Buildpacks produce OCI-compliant images.
8. **Dagster as Router** — Pure HTTP dispatch via `requests`. No `PipesK8sClient`.
9. **Imperative-Declarative Hybrid** — BPMN workflows use ops for control flow and `AssetMaterialization` for data lineage.

---

## Dynamic BPMN Interpreter

The project includes a **Dynamic BPMN Factory** (`src/iagent/defs/dynamic_factory.py`) that reads simplified BPMN JSON definitions from a PostgreSQL `bpmn_catalog` table and generates Dagster jobs at module-load time.

### How It Works

```
bpmn_catalog (Postgres)
    │
    ▼
fetch_active_bpmn_models()   ← Phase 9.1
    │
    ▼
create_agent_op() × N        ← Phase 9.2 (one @op per BPMN task)
    │
    ▼
_resolve_task_to_task_flows() ← Collapses gateways into task→task edges
    │
    ▼
GraphDefinition + DependencyDefinition
    │
    ▼
.to_job(name=workflow_id)    ← Phase 9.3
    │
    ▼
Definitions(jobs=[...])      ← Exposed to Dagster UI
```

### Database Setup

Run the SQL script to create the `bpmn_catalog` table:

```bash
psql -h localhost -U iagent -d iagent -f sql/create_bpmn_catalog.sql
```

The table stores BPMN payloads as JSONB with tasks, gateways, and sequence flows. Each generated op POSTs to the agent endpoint defined in the BPMN task, yields an `AssetMaterialization` for lineage, and passes the result downstream via `Output`.

---

## Additional Documentation

| File | Purpose |
|------|--------|
| [`llms.txt`](llms.txt) | AI-readable project index and development log |
| [`.cursorrules`](.cursorrules) | Coding style enforcement and tech stack constraints |
| [`AGENTS.md`](AGENTS.md) | AI agent workflow rules, safety boundaries, and progress |
| [`contracts.baml`](baml_shared/baml_src/contracts.baml) | Shared data contracts (source of truth) |

---

## Learn More

- [Dagster Documentation](https://docs.dagster.io/)
- [BAML Documentation](https://docs.boundaryml.com/)
- [Restate Documentation](https://docs.restate.dev/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Swarms.ai Documentation](https://docs.swarms.world/)
- [Cloud Native Buildpacks](https://buildpacks.io/)
- [DataHub Documentation](https://datahubproject.io/docs/)
