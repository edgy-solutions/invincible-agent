"""Agent router assets — lightweight HTTP dispatchers for the agent fleet.

These Dagster assets trigger agent pods via plain HTTP POST using only the
``requests`` library. No agent SDKs or ML frameworks are imported here.
Dagster acts as the central router (Polyglot Agentic Data Mesh V3 spec).
"""

import base64
from pathlib import Path

import requests
from dagster import MetadataValue, asset

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
    response = requests.post(
        "http://restate-agent-svc.default.svc.cluster.local:8081/analyze",
        timeout=120,
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
def trigger_langgraph_support() -> dict:
    """Trigger Engine B (LangGraph) support agent pod."""
    response = requests.post(
        "http://langgraph-agent-svc.default.svc.cluster.local:8082/support",
        timeout=120,
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
    response = requests.post(
        "http://swarms-agent-svc.default.svc.cluster.local:8083/scrape",
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


@asset(
    kinds={"datahub"},
    group_name="data_layer",
    metadata={
        "Engine D": _icon_card(
            "datahub",
            "DataHub Metadata Wrapper",
            "Queries DataHub GMS GraphQL API for dbt platform datasets. "
            "Returns a comma-separated list of table names for LLM context. "
            "Falls back to 503 if DataHub is unreachable.\n\n"
            "**Endpoint:** `GET :8085/tables`",
        ),
    },
)
def trigger_datahub_tables() -> dict:
    """Fetch available dbt tables from Engine D (DataHub wrapper)."""
    response = requests.get(
        "http://datahub-wrapper-svc.default.svc.cluster.local:8085/tables",
        timeout=30,
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
def trigger_neo4j_expert() -> dict:
    """Trigger Engine E (Neo4j Graph Expert) agent pod."""
    response = requests.post(
        "http://neo4j-expert-svc.default.svc.cluster.local:8086/query_graph",
        json={"user_query": "What are the common tools?", "persona": "MECHANIC"}, # Dummy payload for now as it wasn't specified
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


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
        "http://presentation-agent-svc.default.svc.cluster.local:8087/render_ui",
        json={"raw_data": {"demo": True}, "persona": "MECHANIC"}, # Dummy payload for UI UI
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
