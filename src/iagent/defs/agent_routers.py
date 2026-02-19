"""Agent router assets — lightweight HTTP dispatchers for the agent fleet.

These Dagster assets trigger agent pods via plain HTTP POST using only the
``requests`` library. No agent SDKs or ML frameworks are imported here.
Dagster acts as the central router (Polyglot Agentic Data Mesh V3 spec).
"""

import requests
from dagster import asset


@asset
def trigger_restate_analyst() -> dict:
    """Trigger Engine A (Restate + Smolagents) analyst agent pod."""
    response = requests.post(
        "http://restate-agent-svc.default.svc.cluster.local:8081/analyze",
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


@asset
def trigger_langgraph_support() -> dict:
    """Trigger Engine B (LangGraph) support agent pod."""
    response = requests.post(
        "http://langgraph-agent-svc.default.svc.cluster.local:8082/support",
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


@asset
def trigger_swarms_scraper() -> dict:
    """Trigger Engine C (Swarms.ai) scraper/extraction agent pod."""
    response = requests.post(
        "http://swarms-agent-svc.default.svc.cluster.local:8083/scrape",
        timeout=120,
    )
    response.raise_for_status()
    return response.json()
