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
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="DataHub Metadata Wrapper",
    description="Engine D — queries DataHub GMS for dbt dataset metadata",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "service": "datahub_wrapper", "port": 8085}


@app.get("/tables")
async def get_tables() -> dict:
    """Query DataHub for all dbt datasets and return as LLM context.

    Returns:
        {"available_tables": "stg_flight_logs, stg_maintenance_records, ..."}

    Raises:
        HTTPException 503 if DataHub is unreachable.
    """
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
        raise HTTPException(
            status_code=503,
            detail=(
                f"DataHub unreachable at {DATAHUB_GMS_URL}. "
                f"Caller should fall back to mock data. Error: {exc}"
            ),
        ) from exc

    data = resp.json()

    # Extract table names from the GraphQL response
    search_results = (
        data.get("data", {}).get("search", {}).get("searchResults", [])
    )

    table_names: list[str] = []
    for result in search_results:
        entity = result.get("entity", {})
        urn = entity.get("urn", "")

        # Prefer the properties.name if available, otherwise parse the URN
        props = entity.get("properties") or {}
        name = props.get("name") or _parse_table_name(urn)
        table_names.append(name)

    # Deduplicate and sort for deterministic output
    table_names = sorted(set(table_names))

    return {"available_tables": ", ".join(table_names) if table_names else ""}
