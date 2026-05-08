"""DataHub Metadata Wrapper — Engine D.

A lightweight FastAPI microservice that acts as a dynamic, intelligent proxy 
for DataHub's GraphQL Search API. Discovers available datasets, dashboards, 
and charts to provide LLM-friendly context for the DATA_STEWARD persona.

Port 8085 · POST /query_metadata · GET /health

Environment variables:
    DATAHUB_GMS_URL  — DataHub GraphQL endpoint (default: http://localhost:8080/api/graphql)
    DATAHUB_TOKEN    — Optional DataHub personal access token for authentication
"""

from __future__ import annotations

import os
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATAHUB_GMS_URL = os.getenv(
    "DATAHUB_GMS_URL", "http://localhost:8080/api/graphql"
)
DATAHUB_TOKEN = os.getenv("DATAHUB_TOKEN", "")

# Platform Mapping Dictionary for deterministic URN resolution
PLATFORM_MAP = {
    "SUPERSET": "urn:li:dataPlatform:superset",
    "DBT": "urn:li:dataPlatform:dbt",
    "POSTGRES": "urn:li:dataPlatform:postgres",
    "SNOWFLAKE": "urn:li:dataPlatform:snowflake",
    "KAFKA": "urn:li:dataPlatform:kafka"
}

# ---------------------------------------------------------------------------
# Generic GraphQL query — search across ALL entities
# ---------------------------------------------------------------------------
_GENERIC_SEARCH_QUERY = """
query SearchDataHub($input: SearchInput!) {
  search(input: $input) {
    searchResults {
      entity {
        urn
        type
        ... on Dataset {
          properties {
            name
            description
          }
        }
        ... on Dashboard {
          info {
            name
            description
          }
        }
        ... on Chart {
          info {
            name
            description
          }
        }
      }
    }
  }
}
"""

# Query for finding tools based on ontology_uri in customProperties
_FIND_TOOLS_QUERY = """
query SearchDataHub($input: SearchInput!) {
  search(input: $input) {
    searchResults {
      entity {
        urn
        type
        ... on Dataset {
          properties {
            name
            description
          }
          customProperties {
            key
            value
          }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------
class MetadataQueryRequest(BaseModel):
    user_query: str
    persona: str = "DATA_STEWARD"
    domain: str = "DATA_ENGINEERING"
    entity_type: Optional[str] = None


class DataStewardResponse(BaseModel):
    tool_list: List[str] = []
    safety_warnings: List[str] = []
    short_answer: str


class ExpertResponse(BaseModel):
    confidence_score: float
    referenced_uris: List[str]
    data: DataStewardResponse


from contextlib import asynccontextmanager

# Global cache for our minified schema
_DYNAMIC_SCHEMA_CACHE = "DataHub Schema Map: Not loaded."

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot-time introspection to cache the DataHub schema."""
    global _DYNAMIC_SCHEMA_CACHE
    
    introspection_query = """
    query IntrospectEntityTypes {
      __type(name: "EntityType") {
        enumValues {
          name
        }
      }
    }
    """
    
    try:
        async with httpx.AsyncClient() as client:
            headers = {}
            if DATAHUB_TOKEN:
                headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"
                
            response = await client.post(
                DATAHUB_GMS_URL,
                json={"query": introspection_query},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            enum_values = data.get("data", {}).get("__type", {}).get("enumValues", [])
            valid_types = [val["name"] for val in enum_values if val and "name" in val]
            
            if valid_types:
                _DYNAMIC_SCHEMA_CACHE = (
                    "### Valid DataHub Entity Types\n"
                    "When searching DataHub, you MUST use one of the following exact strings for the entity_type:\n"
                    f"{', '.join(valid_types)}\n"
                )
                print("[Engine D] Successfully cached dynamic DataHub schema map.")
            else:
                raise ValueError("No enum values found in response")
            
    except Exception as e:
        print(f"[Engine D] Failed to introspect DataHub schema at startup: {e}")
        _DYNAMIC_SCHEMA_CACHE = "### Valid DataHub Entity Types\nFallback: DATASET, DASHBOARD, CHART, DATA_FLOW, DATA_JOB"

    yield

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="DataHub Metadata Wrapper",
    description="Engine D — Dynamic proxy for DataHub GraphQL Search API",
    version="0.2.0",
    lifespan=lifespan,
)

@app.get("/dynamic_context")
async def get_dynamic_context():
    """Returns the minified, token-efficient DataHub schema map."""
    return {"schema_map": _DYNAMIC_SCHEMA_CACHE}


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "service": "datahub_wrapper", "port": 8085}


@app.get("/tables")
async def get_tables() -> dict:
    """Legacy endpoint — now deprecated in favor of /query_metadata."""
    return {"available_tables": "Dynamic search enabled via /query_metadata"}


@app.get("/find_tools")
async def find_tools(ontology_uri: str):
    """
    Search for AITool or MCPServer entities tagged with a specific ontology_uri.
    Returns metadata for JIT tool injection in Engine A.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if DATAHUB_TOKEN:
        headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"

    # Search for tools across likely entity types
    search_variables = {
        "input": {
            "query": "*",
            "start": 0,
            "count": 50,
            "filters": [
                {
                    "field": "customProperties.ontology_uri",
                    "value": ontology_uri
                }
            ]
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DATAHUB_GMS_URL,
                json={"query": _FIND_TOOLS_QUERY, "variables": search_variables},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"ERROR in find_tools: {exc}")
        return {"tools": [], "error": str(exc)}

    # Safely navigate the nested GraphQL response
    data_dict = data.get("data") or {}
    search_dict = data_dict.get("search") or {}
    search_results = search_dict.get("searchResults") or []
    tools = []

    for result in search_results:
        entity = result.get("entity", {})
        if not entity:
            continue
            
        props = entity.get("properties") or {}
        # Guard against customProperties being null/None
        cp_list = entity.get("customProperties") or []
        custom_props = {cp.get("key"): cp.get("value") for cp in cp_list if cp and "key" in cp}
        
        # Tools can be 'AITool' (standard OpenAPI) or 'MCPServer' (SSE protocol)
        # We handle both via the custom_props metadata
        tools.append({
            "name": props.get("name") or entity.get("urn"),
            "description": props.get("description") or "Dynamic tool discovered from DataHub.",
            "type": custom_props.get("type", "AITool"),
            "openapi_schema": custom_props.get("openapi_schema", ""),
            "endpoint_url": custom_props.get("endpoint_url", ""),
            "urn": entity.get("urn")
        })

    return {"tools": tools, "ontology_uri": ontology_uri}


@app.post("/query_metadata", response_model=ExpertResponse)
async def query_metadata(request: MetadataQueryRequest):
    """
    Active agent endpoint for the DATA_STEWARD persona.
    Takes a natural language query, dynamically applies platform filters, 
    searches DataHub, and returns formatted metadata context.
    """
    query_upper = request.user_query.upper()
    or_filters = []
    
    # Intelligently apply platform filters if mentioned in the query
    for term, urn in PLATFORM_MAP.items():
        if term in query_upper:
            or_filters.append({
                "and": [{"field": "platform", "values": [urn]}]
            })

    # Construct the dynamic DataHub SearchInput
    search_variables = {
        "input": {
            "query": request.user_query,
            "start": 0,
            "count": 10,
        }
    }
    
    if request.entity_type:
        search_variables["input"]["type"] = request.entity_type.upper()
    
    if or_filters:
        search_variables["input"]["orFilters"] = or_filters

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if DATAHUB_TOKEN:
        headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"

    # Execute GraphQL Request
    import json
    try:
        payload = {"query": _GENERIC_SEARCH_QUERY, "variables": search_variables}
        print(f"DEBUG: Sending request to DataHub GMS ({DATAHUB_GMS_URL})")
        print(f"DEBUG: Payload: {json.dumps(payload, indent=2)}")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DATAHUB_GMS_URL,
                json=payload,
                headers=headers,
            )
            print(f"DEBUG: DataHub response status: {resp.status_code}")
            print(f"DEBUG: DataHub raw response: {resp.text}")
            
            resp.raise_for_status()
            data = resp.json()
    except httpx.RequestError as exc:
        print(f"ERROR: DataHub connection failed (RequestError): {exc}")
        return ExpertResponse(
            confidence_score=0.0,
            referenced_uris=[],
            data=DataStewardResponse(
                short_answer="The DataHub API is currently unreachable.",
                tool_list=["DataHub"],
                safety_warnings=["System offline: Cannot verify current data definitions."]
            )
        )
    except httpx.HTTPStatusError as exc:
        print(f"ERROR: DataHub returned HTTP error (HTTPStatusError): {exc.response.status_code} - {exc.response.text}")
        return ExpertResponse(
            confidence_score=0.0,
            referenced_uris=[],
            data=DataStewardResponse(
                short_answer="The DataHub API returned an error.",
                tool_list=["DataHub"],
                safety_warnings=["System error: Cannot verify current data definitions."]
            )
        )
    except Exception as exc:
        print(f"ERROR: Unexpected error during DataHub search: {exc}")
        return ExpertResponse(
            confidence_score=0.0,
            referenced_uris=[],
            data=DataStewardResponse(
                short_answer="The DataHub API is currently unreachable.",
                tool_list=["DataHub"],
                safety_warnings=["System offline: Cannot verify current data definitions."]
            )
        )

    # Parse Results Generically
    data = data or {}
    data_dict = data.get("data") or {}
    search_dict = data_dict.get("search") or {}
    search_results = search_dict.get("searchResults") or []
    matched_assets = []
    referenced_uris = []
    
    for result in search_results:
        entity = result.get("entity", {})
        urn = entity.get("urn", "")
        entity_type = entity.get("type", "UNKNOWN")
        
        # Extract name and description based on entity type and specific aspects
        name = urn
        desc = "No description provided."
        
        if entity_type == "DATASET":
            # Datasets store these in the 'properties' aspect
            props = entity.get("properties") or {}
            name = props.get("name") or urn
            desc = props.get("description", "")
            if isinstance(desc, str):
                desc = desc.strip()
        elif entity_type in ["DASHBOARD", "CHART"]:
            # Dashboards and Charts store these in the 'info' aspect
            info = entity.get("info") or {}
            name = info.get("name") or urn
            desc = info.get("description", "")
            if isinstance(desc, str):
                desc = desc.strip()
            
        if not desc:
            desc = "UNAVAILABLE_IN_CATALOG"
            
        matched_assets.append(f"[{entity_type}] {name}: {desc}")
        referenced_uris.append(urn)

    # Construct the final ExpertResponse
    if matched_assets:
        asset_list_str = "\n".join([f"- {a}" for a in matched_assets])
        answer = f"I searched the data catalog and found the following relevant assets:\n{asset_list_str}"
        confidence = 0.90
    else:
        answer = f"I could not find any data assets matching your request in the catalog."
        confidence = 0.10

    return ExpertResponse(
        confidence_score=confidence,
        referenced_uris=referenced_uris,
        data=DataStewardResponse(
            short_answer=answer,
            tool_list=["DataHub GraphQL Search"],
            safety_warnings=["Verify access controls before querying underlying data sources."]
        )
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8085))
    uvicorn.run(app, host="0.0.0.0", port=port)
