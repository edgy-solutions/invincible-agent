"""Agent router assets — lightweight HTTP dispatchers for the agent fleet.

These Dagster assets trigger agent pods via plain HTTP POST using only the
``requests`` library. No agent SDKs or ML frameworks are imported here.
Dagster acts as the central router (Polyglot Agentic Data Mesh V3 spec).
"""

import base64
from pathlib import Path

import logging
import requests
import os
from dagster import MetadataValue, asset

# svc:supervisor's outbound credential. GUARDED IMPORT, deliberately: this module is loaded at
# Dagster CODE-LOCATION load time, so a hard ImportError here takes the whole location down rather
# than failing one asset. The fallback restores exactly today's behaviour (no credential) and SAYS
# SO — a silent fallback here would be the same defect this change is fixing.
try:  # pragma: no cover - import path differs by runtime
    from agent_fleet.utils.service_identity import outbound_auth_headers
except ImportError:  # pragma: no cover
    def outbound_auth_headers(**_kw):
        logging.getLogger(__name__).warning(
            "agent_fleet.utils.service_identity unavailable — Dagster engine calls proceed "
            "UNAUTHENTICATED (engines record caller:none)"
        )
        return {}

# ---------------------------------------------------------------------------
# Icon helper — reads SVGs from assets/icons/ and encodes as base64 markdown
# ---------------------------------------------------------------------------
_ICONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"


def _icon_card(icon_name: str, title: str, description: str) -> MetadataValue:
    """Build a Markdown metadata card with an embedded base64 SVG icon."""
    svg_path = _ICONS_DIR / f"{icon_name}.svg"
    if svg_path.exists():
        b64 = base64.b64encode(svg_path.read_bytes()).decode()
        img = f"![{title}](data:image/svg+xml;base64,{b64})"
    else:
        img = ""
    return MetadataValue.md(f"{img}\n\n**{title}**\n\n{description}")


# ---------------------------------------------------------------------------
# Service Discovery — defaults to K8s internal DNS, overridden via env
# ---------------------------------------------------------------------------
RESTATE_ANALYST_URL = os.getenv("RESTATE_ANALYST_URL", "http://iagent-engine-a:8081")
LANGGRAPH_SUPPORT_SVC_URL = os.getenv("LANGGRAPH_SUPPORT_SVC_URL", "http://iagent-langgraph-support:8082")
SWARMS_SCRAPER_URL = os.getenv("SWARMS_SCRAPER_URL", "http://iagent-swarms-scraper:8083")
DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://iagent-engine-d:8085")
NEO4J_EXPERT_SVC_URL = os.getenv("NEO4J_EXPERT_SVC_URL", "http://iagent-engine-e:8086")
PRESENTATION_AGENT_SVC_URL = os.getenv("PRESENTATION_AGENT_SVC_URL", "http://iagent-engine-f:8087")
ONTOLOGY_SERVICE_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
DATA_ANALYST_URL = os.getenv("DATA_ANALYST_URL", "http://iagent-data-analyst:8089")

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@asset(
    kinds={"restate", "smolagents"},
    group_name="agent_fleet",
    metadata={
        "Engine A": _icon_card(
            "restate",
            "Restate + Smolagents",
            "Durable analyst engine. Calls Engine O for semantic resolution, "
            "then runs a smolagents CodeAgent with `ctx.run()` for exactly-once "
            "execution.\n\n"
            "**Endpoint:** `POST :8081/analyze`",
        ),
    },
)
def trigger_restate_analyst() -> dict:
    """Trigger Engine A (Restate + Smolagents) analyst agent pod."""
    # svc:supervisor — the Dagster plane's process identity, named HERE. Not `_telemetry_headers`:
    # that helper lives in dynamic_supervisor and takes a `config` this asset does not have. Same
    # identity, same mint, one shared helper — reaching across for a private function would be the
    # worse coupling.
    response = requests.post(
        f"{RESTATE_ANALYST_URL}/analyze",
        # BODY REQUIRED. `/analyze` forwards to Restate's AnalystService, which reads AgentTask
        # fields off the payload; posting nothing made `await request.json()` raise inside the
        # proxy's bare except and come back as a 502 NAMING RESTATE. Fields mirror AnalyzeRequest
        # (restate_analyst/main.py) — smoke payload, same standing as Engines E/F/DA's.
        json={
            "task_description": "Smoke: summarise this dataset's lineage and freshness.",
            "dataset_id": "default",
        },
        timeout=300,
        headers=outbound_auth_headers(
            client_id=os.getenv("SUPERVISOR_CLIENT_ID", "iagent-supervisor"),
            secret_env="SUPERVISOR_CLIENT_SECRET",
        ),
    )
    response.raise_for_status()
    return response.json()


@asset(
    kinds={"langgraph", "postgres"},
    group_name="agent_fleet",
    metadata={
        "Engine B": _icon_card(
            "langgraph",
            "LangGraph + PostgreSQL",
            "Stateful support agent. Two-node StateGraph (triage → respond) "
            "with AsyncPostgresSaver checkpointer for conversational memory "
            "keyed by `thread_id`.\n\n"
            "**Endpoint:** `POST :8082/support`",
        ),
    },
)
def trigger_langgraph_support(context) -> dict:
    """Trigger Engine B (LangGraph) support agent pod."""
    # BODY REQUIRED. `SupportRequest.thread_id` (langgraph_support/main.py) has no default, so a
    # bodyless POST was a 422 before the graph was ever reached — the asset advertised an endpoint
    # it could not call. `thread_id` is the AsyncPostgresSaver CHECKPOINT KEY, so it is run-scoped
    # deliberately: a constant would accumulate every Dagster run into one conversation forever,
    # and that is a memory-shape decision, not a placeholder.
    response = requests.post(
        f"{LANGGRAPH_SUPPORT_SVC_URL}/support",
        json={
            "thread_id": f"dagster-{context.run_id}",
            "task_description": "Smoke: triage and respond for the default dataset.",
            "dataset_id": "default",
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


@asset(
    kinds={"swarms", "python"},
    group_name="agent_fleet",
    metadata={
        "Engine C": _icon_card(
            "swarms",
            "Swarms.ai",
            "Stateless heavy-compute scraper. SequentialWorkflow with a "
            "DataExtractor agent for high-concurrency extraction.\n\n"
            "**Endpoint:** `POST :8083/scrape`",
        ),
    },
)
def trigger_swarms_scraper() -> dict:
    """Trigger Engine C (Swarms.ai) scraper/extraction agent pod."""
    # BODY REQUIRED. `ScrapeRequest` (swarms_scraper/main.py) requires BOTH `task_description` and
    # `dataset_id` with no defaults — a bodyless POST was a 422. Same defect class as Engine A and
    # Engine B above; ADR-0046 filed only Engine B's, and the class was three.
    response = requests.post(
        f"{SWARMS_SCRAPER_URL}/scrape",
        json={
            "task_description": "Smoke: extract structured records for the default dataset.",
            "dataset_id": "default",
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()




@asset(
    kinds={"restate", "python", "smolagents", "neo4j"},
    group_name="agent_fleet",
    metadata={
        "Engine E": _icon_card(
            "restate",  # Neo4j uses Restate for durable execution
            "Engine E: Neo4j Graph Expert",
            "Queries the military technical manual Neo4j graph using a smolagents "
            "CodeAgent with standard Cypher and Schema tools. Execution is made "
            "durable via Restate SDK.\n\n"
            "**Endpoint:** `POST :8086/query_graph`",
        ),
    },
)
def trigger_neo4j_expert(context) -> dict:
    """Trigger Engine E (Neo4j Graph Expert) agent pod."""
    response = requests.post(
        f"{NEO4J_EXPERT_SVC_URL}/query_graph",
        json={"user_query": "What are the common tools?", "persona": "MECHANIC"}, # Dummy payload for now as it wasn't specified
        timeout=300,
    )
    response.raise_for_status()
    
    data = response.json()
    
    # Write the agent's internal monologue to the Dagster UI!
    trace = data.get("execution_trace")
    if trace:
        context.log.info(f"🧠 Agent Reasoning Trajectory:\n{trace}")
        
    return data


@asset(
    kinds={"fastapi", "python"},
    group_name="agent_fleet",
    metadata={
        "Engine F": _icon_card(
            "python",  # DAGSTER BUG: we can't easily add completely custom icons outside of their 200, but python works well
            "Engine F: Presentation Agent",
            "Stateless UI Router. Converts raw domain JSON into Server-Driven UI instructions "
            "(Component + Props) based on the user Persona.\n\n"
            "**Endpoint:** `POST :8087/render_ui`",
        ),
    },
)
def trigger_presentation_agent() -> dict:
    """Trigger Engine F (Presentation Agent) UI Router pod."""
    response = requests.post(
        f"{PRESENTATION_AGENT_SVC_URL}/render_ui",
        json={"raw_data": {"demo": True}, "persona": "MECHANIC"}, # Dummy payload for UI UI
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

@asset(
    kinds={"restate", "python", "smolagents", "duckdb"},
    group_name="agent_fleet",
    metadata={
        "Engine DA": _icon_card(
            "restate",
            "Engine DA: Data Analyst Agent",
            "Data Analyst Agent built with smolagents and restate that writes SQL to analyze data. "
            "Securely executes SQL over DataHub assets.\n\n"
            "**Endpoint:** `POST :8089/analyze_data`",
        ),
    },
)
def trigger_data_analyst(context) -> dict:
    """Trigger Engine DA (Data Analyst Agent) pod."""
    # svc:supervisor — the Dagster plane's process identity, named HERE. TRANSPORT only: DA's read
    # gate keys on the END USER (`user_id` in the body, X-Originator-* at the data gateway), so this
    # credential must never be read as the entitlement subject.
    response = requests.post(
        f"{DATA_ANALYST_URL}/analyze_data",
        json={"user_query": "Show me the top 5 tables by size", "persona": "DATA_STEWARD", "domain": "DATA_ENGINEERING", "user_id": "test_user"}, # Dummy payload
        timeout=300,
        headers=outbound_auth_headers(
            client_id=os.getenv("SUPERVISOR_CLIENT_ID", "iagent-supervisor"),
            secret_env="SUPERVISOR_CLIENT_SECRET",
        ),
    )
    response.raise_for_status()
    
    data = response.json()
    
    trace = data.get("execution_trace")
    if trace:
        context.log.info(f"🧠 Agent Reasoning Trajectory:\n{trace}")
        
    return data
