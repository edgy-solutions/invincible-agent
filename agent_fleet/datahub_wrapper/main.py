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

import asyncio
import os
import logging
import difflib
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataHubWrapper")

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
# Generic GraphQL query — search ACROSS entity types.
#
# DataHub's `search` field requires a non-null `type` parameter and
# returns a Validation error otherwise — which the previous query
# silently masked by raising for_status() that never fired because
# the HTTP 200 carried `errors[]` in the body, not a 4xx. Switch to
# `searchAcrossEntities`, which has no type requirement and returns
# every kind in one round-trip (DATASETs, DASHBOARDs, CHARTs,
# DATA_FLOWs, DATA_JOBs). This is the only sensible default for the
# "tell me about <name>" shape of query; per-type narrowing stays
# available via the original SearchInput for callers that need it.
# ---------------------------------------------------------------------------
_GENERIC_SEARCH_QUERY = """
query SearchDataHub($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    searchResults {
      entity {
        urn
        type
        ... on Dataset {
          properties { name description }
          ownership { owners { owner { ... on CorpUser { username properties { displayName email } } } } }
          tags { tags { tag { urn } } }
          schemaMetadata { fields { fieldPath nativeDataType description } }
          upstream: relationships(input: {types: ["DownstreamOf"], direction: OUTGOING, count: 25, start: 0}) {
            relationships { entity { urn type ... on Dataset { properties { name } } } }
          }
          downstream: relationships(input: {types: ["DownstreamOf","Consumes"], direction: INCOMING, count: 25, start: 0}) {
            relationships { entity { urn type
              ... on Dataset { properties { name } }
              ... on Dashboard { info { name } }
              ... on Chart { info { name } }
            } }
          }
          operations(limit: 1) { timestampMillis operationType }
        }
        ... on Dashboard {
          info { name description }
          ownership { owners { owner { ... on CorpUser { username } } } }
          tags { tags { tag { urn } } }
          upstream: relationships(input: {types: ["Consumes"], direction: OUTGOING, count: 25, start: 0}) {
            relationships { entity { urn type ... on Dataset { properties { name } } } }
          }
        }
        ... on Chart {
          info { name description }
          ownership { owners { owner { ... on CorpUser { username } } } }
          tags { tags { tag { urn } } }
          upstream: relationships(input: {types: ["Consumes"], direction: OUTGOING, count: 25, start: 0}) {
            relationships { entity { urn type ... on Dataset { properties { name } } } }
          }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# DataHub schema introspection — version-skew tolerance for `customProperties`.
#
# DataHub moved `customProperties` between major versions. The two shapes
# this wrapper has to support concurrently:
#
#   Legacy / v1.1.0 shape (and most pre-1.0 builds):
#     customProperties is nested INSIDE the `properties` block of Dataset
#       ... on Dataset {
#         properties {
#           customProperties { key value }   <- here
#         }
#       }
#
#   Newer shape (the previous code targeted this):
#     customProperties is a TOP-LEVEL field of Dataset
#       ... on Dataset {
#         customProperties { key value }   <- here
#       }
#
# Querying the wrong shape returns
# `FieldUndefined@[searchAcrossEntities/searchResults/entity/customProperties]`
# from the deployed GMS and Engine D logs an error + returns an empty
# tool list (which broke JIT tool discovery on the sandbox cluster that
# was running DataHub 1.1.0).
#
# The clean fix is GraphQL introspection: ask the GMS what fields its
# Dataset type actually exposes, once, at first use, then build the
# query and parse the response based on whichever shape that GMS
# supports. Cached for the process lifetime.
#
# The user-facing contract is "version-skew tolerant" — newer DataHub
# installations still get full customProperties; older 1.1.0 installations
# stop tripping the FieldUndefined error. No code change needed when
# bumping DataHub versions in either direction; the next process start
# re-introspects.
_INTROSPECTION_QUERY = """
query ProbeDataHubSchema {
  dataset: __type(name: "Dataset") { fields { name } }
  datasetProperties: __type(name: "DatasetProperties") { fields { name } }
}
"""

_SchemaFeatures = Dict[str, bool]
_schema_cache: Optional[_SchemaFeatures] = None
_schema_cache_lock = asyncio.Lock()


async def _discover_schema_features() -> _SchemaFeatures:
    """Introspect the deployed DataHub GMS once; cache the result.

    Returns a dict with two booleans:
      - dataset_has_top_level_customProperties:
          True when GMS exposes `customProperties` as a direct field of
          the Dataset type (newer DataHub).
      - dataset_properties_has_customProperties:
          True when GMS exposes `customProperties` nested inside the
          DatasetProperties type (legacy / v1.1.0 shape).

    Both can be true on transitional GMS builds. The query builder
    prefers the top-level shape when present (richer data path in
    newer DataHub); falls back to nested when only that's available.

    On introspection failure (network error, GMS unreachable, schema
    response malformed), assumes the legacy nested shape — that's the
    safer default because the nested shape works on more DataHub
    versions historically and was what this wrapper started with
    before being updated to the new shape.
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache
    async with _schema_cache_lock:
        # Re-check after acquiring the lock (another coroutine may
        # have raced in and populated the cache while we waited).
        if _schema_cache is not None:
            return _schema_cache

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if DATAHUB_TOKEN:
            headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    DATAHUB_GMS_URL,
                    json={"query": _INTROSPECTION_QUERY},
                    headers=headers,
                )
                resp.raise_for_status()
                payload = resp.json()
            data = payload.get("data") or {}
            dataset = data.get("dataset") or {}
            dataset_properties = data.get("datasetProperties") or {}
            dataset_field_names = {
                f.get("name") for f in (dataset.get("fields") or []) if f
            }
            dataset_props_field_names = {
                f.get("name") for f in (dataset_properties.get("fields") or []) if f
            }
            features: _SchemaFeatures = {
                "dataset_has_top_level_customProperties":
                    "customProperties" in dataset_field_names,
                "dataset_properties_has_customProperties":
                    "customProperties" in dataset_props_field_names,
            }
            logger.info(
                "DataHub schema introspection complete: "
                "Dataset.customProperties=%s, "
                "DatasetProperties.customProperties=%s",
                features["dataset_has_top_level_customProperties"],
                features["dataset_properties_has_customProperties"],
            )
        except Exception as exc:
            logger.warning(
                "DataHub schema introspection failed (%s); assuming "
                "legacy nested customProperties shape "
                "(DatasetProperties.customProperties).",
                exc,
            )
            features = {
                "dataset_has_top_level_customProperties": False,
                "dataset_properties_has_customProperties": True,
            }

        _schema_cache = features
        return features


def _reset_schema_cache_for_tests() -> None:
    """Test-only helper: clear the introspection cache so the next
    `_discover_schema_features()` call re-probes the GMS. Lets unit
    tests simulate a DataHub version change without restarting the
    process.
    """
    global _schema_cache
    _schema_cache = None


def _build_find_tools_query(features: _SchemaFeatures) -> str:
    """Build the find-tools GraphQL query string based on the deployed
    DataHub's schema features. See `_discover_schema_features` for the
    two shapes this handles.
    """
    has_top_level = features.get("dataset_has_top_level_customProperties", False)
    has_nested = features.get("dataset_properties_has_customProperties", False)

    # Build the properties block. When customProperties is nested in
    # DatasetProperties, include it here.
    if has_nested:
        properties_block = (
            "          properties {\n"
            "            name\n"
            "            description\n"
            "            customProperties { key value }\n"
            "          }\n"
        )
    else:
        properties_block = (
            "          properties {\n"
            "            name\n"
            "            description\n"
            "          }\n"
        )

    # Build the top-level customProperties block. When the field exists at
    # the Dataset top level, include it too (newer DataHub builds carry
    # the same data here; some installations populate both).
    if has_top_level:
        top_level_cp_block = (
            "          customProperties { key value }\n"
        )
    else:
        top_level_cp_block = ""

    return (
        "query SearchDataHub($input: SearchAcrossEntitiesInput!) {\n"
        "  searchAcrossEntities(input: $input) {\n"
        "    searchResults {\n"
        "      entity {\n"
        "        urn\n"
        "        type\n"
        "        ... on Dataset {\n"
        f"{properties_block}"
        f"{top_level_cp_block}"
        "        }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )


def _extract_custom_properties(entity: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pull the `customProperties` list out of a Dataset search result,
    looking in BOTH locations the two DataHub shapes use. Prefers the
    top-level location when both are present and non-empty (newer
    DataHub builds carry the authoritative data there); falls back to
    the nested `properties.customProperties` location used by
    DataHub 1.1.0.

    Returns an empty list when neither location yields data, which
    callers should treat as "no metadata bag" rather than an error.
    """
    top_level = entity.get("customProperties")
    if top_level:
        return top_level
    nested = (entity.get("properties") or {}).get("customProperties")
    return nested or []

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------
class MetadataQueryRequest(BaseModel):
    user_query: str
    persona: str = "DATA_STEWARD"
    domain: str = "DATA_ENGINEERING"
    entity_type: Optional[str] = None


# Recipe v2 instance-resolution contract.
# Engine D registers (mesh:InstanceIdentifier)-[mesh:resolveInstance]->(mesh:InstanceResolution)
# at startup; the router fans an identifier here and reads the class
# from the candidate list. An EMPTY list is a first-class answer.
class ResolveInstanceRequest(BaseModel):
    identifier: str
    query: Optional[str] = None  # full user query, advisory only


class InstanceCandidate(BaseModel):
    instance_id: str    # DataHub URN
    class_uri: str      # idp:* class — what the resolver consumes
    label: str
    score: float        # provider relevance, 0.0–1.0


class ResolveInstanceResponse(BaseModel):
    candidates: List[InstanceCandidate]


# DataHub entity_type → canonical idp:* class. The mapping is intentionally
# narrow: only entity types whose canonical class already lives in
# idp_extension.ttl and has verbs typed against it (or against an ancestor
# reachable via subClassOf). Anything else is dropped — abstaining is the
# contract.
#
# Values MUST be the FULL IRI form. The idp_extension.ttl canonical ingest
# expands ``idp:Table`` → ``http://invincible-agent/idp#Table`` when it
# writes :OntologyClass nodes. Returning the compact form would set a
# subject the compat-walk Cypher cannot find — the matrix went silently
# RED on 2026-06-12 because of this; before the Contract B fix shipped
# (dcf9e22) the LLM was masking it by picking verbs from the unconstrained
# Weaviate pool. The fix is to return the canonical URI form here so
# Engine O's subClassOf walk can actually reach the typed verbs.
_DATAHUB_TO_IDP: Dict[str, str] = {
    "DATASET":   "http://invincible-agent/idp#Table",      # warehouse three-part names land here
    "DASHBOARD": "http://invincible-agent/idp#Dashboard",
    "CHART":     "http://invincible-agent/idp#Dashboard",  # charts hang off dashboards in our model
    "DATA_FLOW": "http://invincible-agent/idp#Pipeline",
    "DATA_JOB":  "http://invincible-agent/idp#Job",
}

# Identifier patterns that suggest a column (last segment after the dataset
# path) — used to prefer idp:Column over idp:Table when the DataHub-returned
# schema mentions the trailing token. The classification still comes from
# DataHub's authoritative entity type; this only chooses Column when the
# query identifier ends in `.<schema-field-name>`.
RESOLVE_INSTANCE_MIN_SCORE = float(os.getenv("RESOLVE_INSTANCE_MIN_SCORE", "0.7"))


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

    # Recipe v2: register Engine D as the v1 mesh:resolveInstance provider.
    # The router fans an identifier-shaped token here when /resolve's LLM
    # extracts one, and the candidate list returned (class + score) drives
    # the routing subject override. This is Engine D's FIRST registered
    # mesh predicate — it was a silent backend tool before.
    try:
        try:
            from utils.mesh_registration import register_engine_to_mesh
        except ImportError:
            from agent_fleet.utils.mesh_registration import register_engine_to_mesh

        _engine_d_endpoint = os.getenv(
            "DATAHUB_WRAPPER_SVC_URL",
            "http://iagent-engine-d:8085",
        ).rstrip("/") + "/resolve_instance"

        register_engine_to_mesh(
            name="engine_d_resolve_instance",
            description=(
                "Resolves a named individual (catalog asset path, dotted "
                "dataset name, dashboard title, or other identifier-shaped "
                "token) to its canonical idp:* class via authoritative "
                "DataHub search. Used by the router's instance-resolution "
                "pre-step (Recipe v2). Returns candidate instances with "
                "class URI, label, identity URN, and provider relevance "
                "score sorted descending. An empty list is a first-class "
                "answer — the provider abstains below "
                "RESOLVE_INSTANCE_MIN_SCORE rather than returning least-"
                "bad matches. The lexical SHAPE of the identifier never "
                "decides the class — only DataHub's authoritative entity "
                "type does."
            ),
            verb="mesh:resolveInstance",
            input_uri="http://invincible-agent/mesh#InstanceIdentifier",
            output_uri="http://invincible-agent/mesh#InstanceResolution",
            verb_synonyms=[
                "resolve instance", "look up named asset",
                "what kind of asset", "identify catalog path",
                "classify identifier",
            ],
            endpoint_url=_engine_d_endpoint,
            owner_persona="DATA_STEWARD",
            domains=["DATA_ENGINEERING"],
            cost_class="fast",
            requires_human_approval=False,
            provider="engine_d",
            # DataHub's searchAcrossEntities p95 in sandbox is 3-5s
            # (cold-cache), so the budget needs headroom above that.
            # 8s is the same value the router was holding as a global
            # default before per-provider budgets landed; declaring it
            # at the provider site moves the truth to where the SLO
            # actually lives.
            timeout_s=8.0,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[Engine D] mesh:resolveInstance registration failed: {e}")

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


# ---------------------------------------------------------------------------
# Instance resolution — Recipe v2 Piece 2.
# ---------------------------------------------------------------------------
def _name_score(identifier: str, candidate_name: str) -> float:
    """Provider relevance for a candidate name against the lookup token.

    1.0  exact match (case-insensitive).
    0.9  identifier is a suffix of the candidate name (resolved against a
         shorter alias) OR vice versa — a strong hit either way.
    else difflib.SequenceMatcher ratio — fuzzy / typo tolerant.

    The contract requires honest scores; do NOT inflate to win. The
    routing decision table treats anything below
    RESOLVE_INSTANCE_MIN_SCORE as absent.
    """
    a = (identifier or "").strip().lower()
    b = (candidate_name or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a.endswith(b) or b.endswith(a):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def _column_match(identifier: str, entity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """If the identifier looks like <dataset>.<field> and the trailing
    segment matches a schemaMetadata.fields[*].fieldPath on the returned
    DATASET, classify it as idp:Column rather than idp:Table.

    This is NOT a dot-counting heuristic at the router layer — Engine D
    uses its own catalog-domain knowledge (schemas, fields) to decide.
    The router consumes whatever class Engine D returns.
    """
    if entity.get("type") != "DATASET":
        return None
    if "." not in (identifier or ""):
        return None
    dataset_name = (entity.get("properties") or {}).get("name") or ""
    if not dataset_name:
        return None
    prefix = dataset_name + "."
    ident_norm = identifier.strip()
    if not ident_norm.startswith(prefix):
        return None
    field_path = ident_norm[len(prefix):]
    schema = entity.get("schemaMetadata") or {}
    fields = schema.get("fields") or []
    for f in fields:
        fp = (f or {}).get("fieldPath", "")
        if fp == field_path:
            return {
                "instance_id": f"{entity.get('urn', '')}.{fp}",
                "class_uri": "http://invincible-agent/idp#Column",
                "label": f"{dataset_name}.{fp}",
                "score": 0.95,  # exact field match
            }
    # Identifier names a dataset-prefixed segment but no matching field
    # was returned. Treat as Column with lower confidence so the router
    # still classifies as Column (the user's intent) even if the schema
    # cache is stale.
    return {
        "instance_id": f"{entity.get('urn', '')}.{field_path}",
        "class_uri": "http://invincible-agent/idp#Column",
        "label": f"{dataset_name}.{field_path}",
        "score": 0.75,
    }


@app.post("/resolve_instance", response_model=ResolveInstanceResponse)
async def resolve_instance(request: ResolveInstanceRequest) -> ResolveInstanceResponse:
    """Instance-resolution endpoint for the mesh:resolveInstance predicate.

    Given an identifier-shaped token, search DataHub and return the
    candidate instances above ``RESOLVE_INSTANCE_MIN_SCORE`` with their
    canonical idp:* class, label, identity URN, and provider relevance
    score. An empty list is a first-class answer — do NOT return
    least-bad matches when nothing meets the floor.

    Contract:
      - The score is the provider's honest relevance, not inflated.
      - Class assignment comes from DataHub's authoritative entity type
        (or a column-field match), never from the identifier's shape.
      - Both DATASET-trailing-by-field (Column) and DATASET-as-whole
        (Table) are returned when the identifier matches both — the
        router's decision table handles the mixed-class case.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if DATAHUB_TOKEN:
        headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"

    # Try the full identifier first; if it looks like <dataset>.<field>,
    # also query the dataset prefix so DataHub returns schema metadata
    # for the column-detection pass.
    search_queries = [request.identifier]
    if "." in request.identifier:
        prefix = request.identifier.rsplit(".", 1)[0]
        if prefix and prefix not in search_queries:
            search_queries.append(prefix)

    all_results: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for q in search_queries:
                payload = {
                    "query": _GENERIC_SEARCH_QUERY,
                    "variables": {"input": {"query": q, "start": 0, "count": 10}},
                }
                resp = await client.post(DATAHUB_GMS_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json() or {}
                # LOUD error path: DataHub returns HTTP 200 with
                # `errors[]` + `data=null` on GraphQL validation
                # failures. The previous code's `data.get("search")` ->
                # empty list pattern silently swallowed those, which
                # masked the missing-`type` bug for who knows how long.
                # Empty candidates must be REAL empties (no asset
                # found), never a polite shape over a malformed query.
                gql_errors = data.get("errors") or []
                if gql_errors:
                    logger.error(
                        "DataHub GraphQL errors for /resolve_instance "
                        "identifier=%r search_query=%r: %s",
                        request.identifier, q, json.dumps(gql_errors),
                    )
                data_dict = data.get("data") or {}
                # Tolerate both shapes — searchAcrossEntities (new) and
                # search (legacy) — in case the GraphQL schema is rolled
                # back during ops, the endpoint still returns candidates.
                hit = data_dict.get("searchAcrossEntities") or data_dict.get("search") or {}
                all_results.extend(hit.get("searchResults") or [])
    except Exception as exc:  # noqa: BLE001 — empty answer is a first-class result
        logger.warning(
            "resolve_instance: DataHub search failed for %r: %s",
            request.identifier, exc,
        )
        return ResolveInstanceResponse(candidates=[])

    candidates: List[InstanceCandidate] = []
    seen_ids: set[str] = set()
    for result in all_results:
        entity = (result or {}).get("entity") or {}
        urn = entity.get("urn", "")
        entity_type = entity.get("type", "")
        if not urn:
            continue

        # Column path takes priority for DATASETs whose schema fields
        # match the identifier's trailing segment.
        col = _column_match(request.identifier, entity)
        if col:
            cid = col["instance_id"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                candidates.append(InstanceCandidate(**col))
            continue
        # column_match also needs the canonical full-IRI form to land
        # downstream — patched at the call site for the same reason
        # _DATAHUB_TO_IDP was patched: Neo4j stores idp:* as full IRIs.

        class_uri = _DATAHUB_TO_IDP.get(entity_type)
        if not class_uri:
            continue

        if entity_type == "DATASET":
            name = (entity.get("properties") or {}).get("name") or urn
        elif entity_type in ("DASHBOARD", "CHART"):
            name = (entity.get("info") or {}).get("name") or urn
        else:
            name = urn

        score = _name_score(request.identifier, name)
        if score < RESOLVE_INSTANCE_MIN_SCORE:
            continue
        if urn in seen_ids:
            continue
        seen_ids.add(urn)
        candidates.append(
            InstanceCandidate(
                instance_id=urn,
                class_uri=class_uri,
                label=name,
                score=round(score, 3),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return ResolveInstanceResponse(candidates=candidates)


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
                    "values": [ontology_uri]
                }
            ]
        }
    }

    # Build the query dynamically based on which `customProperties`
    # shape the deployed DataHub supports (introspected once, cached).
    # See `_discover_schema_features` for the version-skew rationale.
    schema_features = await _discover_schema_features()
    find_tools_query = _build_find_tools_query(schema_features)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DATAHUB_GMS_URL,
                json={"query": find_tools_query, "variables": search_variables},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            # Check for GraphQL-level errors
            if "errors" in data:
                logger.error(f"DataHub GraphQL Errors for {ontology_uri}: {json.dumps(data['errors'])}")

    except Exception as exc:
        logger.error(f"HTTP Error in find_tools for {ontology_uri}: {exc}")
        return {"tools": [], "error": str(exc)}

    # Safely navigate the nested GraphQL response
    data_dict = data.get("data") or {}
    search_dict = data_dict.get("searchAcrossEntities") or data_dict.get("search") or {}
    search_results = search_dict.get("searchResults") or []
    tools = []

    for result in search_results:
        entity = result.get("entity", {})
        if not entity:
            continue

        props = entity.get("properties") or {}
        # Look in both shapes the two DataHub versions use; see
        # `_extract_custom_properties` for the lookup rules.
        cp_list = _extract_custom_properties(entity)
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
        # searchAcrossEntities takes a list of types; legacy callers pass
        # a single type string, so wrap it.
        search_variables["input"]["types"] = [request.entity_type.upper()]

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
    search_dict = data_dict.get("searchAcrossEntities") or data_dict.get("search") or {}
    search_results = search_dict.get("searchResults") or []
    matched_assets = []
    referenced_uris = []

    def _owners(entity_dict: Dict[str, Any]) -> List[str]:
        own = entity_dict.get("ownership") or {}
        out: List[str] = []
        for o in own.get("owners") or []:
            owner = (o or {}).get("owner") or {}
            uname = owner.get("username")
            if uname:
                out.append(uname)
        return out

    def _tags(entity_dict: Dict[str, Any]) -> List[str]:
        tags = (entity_dict.get("tags") or {}).get("tags") or []
        out: List[str] = []
        for t in tags:
            tag = (t or {}).get("tag") or {}
            urn = tag.get("urn") or ""
            if urn.startswith("urn:li:tag:"):
                out.append(urn[len("urn:li:tag:"):])
        return out

    def _lineage_names(entity_dict: Dict[str, Any], key: str) -> List[str]:
        rels = ((entity_dict.get(key) or {}).get("relationships")) or []
        out: List[str] = []
        for r in rels:
            ent = (r or {}).get("entity") or {}
            etype = ent.get("type", "")
            props = ent.get("properties") or ent.get("info") or {}
            name = props.get("name") or ent.get("urn", "")
            if name:
                out.append(f"{etype}:{name}")
        return out

    def _last_updated(entity_dict: Dict[str, Any]) -> Optional[str]:
        ops = entity_dict.get("operations") or []
        if not ops:
            return None
        ts = (ops[0] or {}).get("timestampMillis")
        if not ts:
            return None
        try:
            from datetime import datetime, timezone
            return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return str(ts)

    for result in search_results:
        entity = result.get("entity", {})
        urn = entity.get("urn", "")
        entity_type = entity.get("type", "UNKNOWN")

        # Extract name and description based on entity type
        name = urn
        desc = ""
        if entity_type == "DATASET":
            props = entity.get("properties") or {}
            name = props.get("name") or urn
            desc = (props.get("description") or "").strip()
        elif entity_type in ["DASHBOARD", "CHART"]:
            info = entity.get("info") or {}
            name = info.get("name") or urn
            desc = (info.get("description") or "").strip()

        owners = _owners(entity)
        tags = _tags(entity)
        upstream = _lineage_names(entity, "upstream")
        downstream = _lineage_names(entity, "downstream")
        last_updated = _last_updated(entity)

        line = f"[{entity_type}] {name}"
        if owners:
            line += f" | owner={','.join(owners)}"
        if last_updated:
            line += f" | last_updated={last_updated}"
        if tags:
            line += f" | tags={','.join(tags)}"
        if desc:
            line += f"\n    description: {desc}"
        if upstream:
            line += f"\n    upstream: {', '.join(upstream)}"
        if downstream:
            line += f"\n    downstream: {', '.join(downstream)}"

        # Per-entity schema for datasets — keep it bounded so the prompt
        # doesn't balloon under wide tables.
        if entity_type == "DATASET":
            schema = entity.get("schemaMetadata") or {}
            fields = (schema.get("fields") or [])[:12]
            if fields:
                cols = ", ".join(
                    f"{(f or {}).get('fieldPath','?')}:{(f or {}).get('nativeDataType','?')}"
                    for f in fields
                )
                line += f"\n    columns: {cols}"

        matched_assets.append(line)
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
