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
| **O** | rdflib + BAML | 8084 | `/resolve` | Ontology reasoner — translates NL → IOF/MIMOSA URIs |
| **A** | Restate + Smolagents | 8081 | `/analyze` | Durable analyst — semantic pre-resolution → CodeAgent |
| **B** | LangGraph + PostgreSQL | 8082 | `/support` | Stateful support — conversational memory via checkpointer |
| **C** | Swarms.ai | 8083 | `/scrape` | Stateless heavy compute — high-concurrency extraction |

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
    agent_routers.py          # @asset: HTTP dispatchers for Engines A, B, C
    data_layer.py             # @asset: dbt ↔ ontology ↔ DataHub sync

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
```

---

## Building Container Images (CNB)

No Dockerfiles. All OCI images are built with Cloud Native Buildpacks:

```bash
pack build myregistry/ontology-service  --path ./agent_fleet/ontology_service  --builder paketobuildpacks/builder-jammy-base
pack build myregistry/restate-analyst   --path ./agent_fleet/restate_analyst   --builder paketobuildpacks/builder-jammy-base
pack build myregistry/langgraph-support --path ./agent_fleet/langgraph_support --builder paketobuildpacks/builder-jammy-base
pack build myregistry/swarms-scraper    --path ./agent_fleet/swarms_scraper    --builder paketobuildpacks/builder-jammy-base
```

---

## Kubernetes Services

| Service | Internal URL |
|---------|-------------|
| Engine O | `http://ontology-svc.default.svc.cluster.local:8084/resolve` |
| Engine A | `http://restate-agent-svc.default.svc.cluster.local:8081/analyze` |
| Engine B | `http://langgraph-agent-svc.default.svc.cluster.local:8082/support` |
| Engine C | `http://swarms-agent-svc.default.svc.cluster.local:8083/scrape` |

All services expose `GET /health` for liveness probes.

---

## Environment Variables

| Variable | Service | Default | Description |
|----------|---------|---------|-------------|
| `LANGGRAPH_POSTGRES_URI` | Engine B | `postgresql://langgraph:langgraph@localhost:5432/langgraph` | PostgreSQL for checkpointer |
| `SWARMS_MODEL` | Engine C | `gpt-4o-mini` | LLM model for Swarms agents |
| `OPENAI_API_KEY` | Engine O, C | — | Required for LLM calls |
| `HF_TOKEN` | Engine A | — | HuggingFace API token for smolagents |

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
