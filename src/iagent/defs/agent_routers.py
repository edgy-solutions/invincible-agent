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
