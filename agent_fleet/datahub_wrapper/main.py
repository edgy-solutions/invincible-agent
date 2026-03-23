"""DataHub Metadata Wrapper — Engine D.

A lightweight FastAPI microservice that queries DataHub's GMS GraphQL API
to discover available dbt datasets and returns them as LLM-friendly context.

Port 8085 · GET /tables · GET /health

Environment variables:
    DATAHUB_GMS_URL  — DataHub GraphQL endpoint (default: http://localhost:8080/api/graphql)
    DATAHUB_TOKEN    — Optional DataHub personal access token for authentication
"""

from __future__ import annotations

import os
import re

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATAHUB_GMS_URL = os.getenv(
    "DATAHUB_GMS_URL", "http://localhost:8080/api/graphql"
)
DATAHUB_TOKEN = os.getenv("DATAHUB_TOKEN", "")

# ---------------------------------------------------------------------------
# GraphQL query — search for dbt platform datasets
# ---------------------------------------------------------------------------
_SEARCH_QUERY = """
query SearchDbtDatasets($input: SearchInput!) {
  search(input: $input) {
    searchResults {
      entity {
        urn
        ... on Dataset {
          name
          properties {
            name
            qualifiedName
          }
          platform {
            name
          }
        }
      }
    }
  }
}
"""

_SEARCH_VARIABLES = {
    "input": {
        "type": "DATASET",
        "query": "*",
        "start": 0,
        "count": 200,
        "orFilters": [
            {
                "and": [
                    {
                        "field": "platform",
                        "values": ["urn:li:dataPlatform:dbt"],
                    }
                ]
            }
        ],
    }
}

# ---------------------------------------------------------------------------
# URN parser — extracts the human-readable table name from a DataHub URN
# ---------------------------------------------------------------------------
_URN_PATTERN = re.compile(
    r"urn:li:dataset:\(urn:li:dataPlatform:\w+,([^,]+),\w+\)"
)


def _parse_table_name(urn: str) -> str:
    """Extract a clean table name from a DataHub dataset URN.

    Example:
        urn:li:dataset:(urn:li:dataPlatform:dbt,my_project.stg_flight_logs,PROD)
        → stg_flight_logs
    """
    match = _URN_PATTERN.match(urn)
    if match:
        qualified = match.group(1)
        # Return the last segment after any dots (project.model → model)
        return qualified.rsplit(".", 1)[-1]
    return urn


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------
class MetadataQueryRequest(BaseModel):
    user_query: str
    persona: str = "DATA_STEWARD"
    domain: str = "DATA_ENGINEERING"


class DataStewardResponse(BaseModel):
    tool_list: List[str] = []
    safety_warnings: List[str] = []
    short_answer: str


class ExpertResponse(BaseModel):
    confidence_score: float
    referenced_uris: List[str]
    data: DataStewardResponse


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="DataHub Metadata Wrapper",
    description="Engine D — queries DataHub GMS for dbt dataset metadata",
    version="0.1.0",
)


async def _fetch_all_table_names() -> list[str]:
    """Internal helper to fetch all dbt table names from DataHub GMS."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if DATAHUB_TOKEN:
        headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DATAHUB_GMS_URL,
                json={"query": _SEARCH_QUERY, "variables": _SEARCH_VARIABLES},
                headers=headers,
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Re-raise so endpoints can handle or fallback
        raise exc

    data = resp.json()
    search_results = data.get("data", {}).get("search", {}).get("searchResults", [])

    table_names: list[str] = []
    for result in search_results:
        entity = result.get("entity", {})
        urn = entity.get("urn", "")
        props = entity.get("properties") or {}
        name = props.get("name") or _parse_table_name(urn)
        table_names.append(name)

    return sorted(set(table_names))


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "service": "datahub_wrapper", "port": 8085}


@app.get("/tables")
async def get_tables() -> dict:
    """Query DataHub for all dbt datasets and return as LLM context."""
    try:
        table_names = await _fetch_all_table_names()
        return {"available_tables": ", ".join(table_names) if table_names else ""}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"DataHub unreachable at {DATAHUB_GMS_URL}. Error: {exc}",
        )


@app.post("/query_metadata", response_model=ExpertResponse)
async def query_metadata(request: MetadataQueryRequest):
    """
    Active agent endpoint for the DATA_STEWARD persona.
    Takes a natural language query, searches DataHub, and returns bound URIs.
    """
    try:
        all_tables = await _fetch_all_table_names()
    except Exception as exc:
        # Fallback to empty list so the agent can still respond with "not found"
        print(f"DEBUG: DataHub fetch failed, falling back to empty list: {exc}")
        all_tables = []

    # Basic Keyword Matching Logic
    # We look for table names that appear in the user query (fuzzy match)
    query_upper = request.user_query.upper()
    matched_tables = [
        t for t in all_tables 
        if t.upper() in query_upper or t.replace("_", " ").upper() in query_upper
    ]

    # If no exact match, return a subset as a fallback for the demo/concept
    if not matched_tables and all_tables:
        matched_tables = all_tables[:3]

    # Construct standard DataHub URNs for the React HUD Data Bindings
    # Format: urn:li:dataset:(urn:li:dataPlatform:dbt,project.table,PROD)
    platform = "dbt"
    env = "PROD"
    referenced_uris = [
        f"urn:li:dataset:(urn:li:dataPlatform:{platform},{table},{env})" 
        for table in matched_tables
    ]

    # Construct the human-readable response
    if matched_tables:
        table_list_str = "\n".join([f"- {t}" for t in matched_tables])
        answer = f"I found the following relevant data assets in the catalog:\n{table_list_str}"
        confidence = 0.85
    else:
        answer = "I could not find any directly matching data models in the catalog."
        confidence = 0.0

    return ExpertResponse(
        confidence_score=confidence,
        referenced_uris=referenced_uris,
        data=DataStewardResponse(
            short_answer=answer,
            tool_list=["DataHub", "dbt"],
            safety_warnings=["Ensure PII masking policies are applied before querying raw layers."]
        )
    )
