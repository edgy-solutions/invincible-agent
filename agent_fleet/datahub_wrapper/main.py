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

# Pure selection helpers (platform filter, dedupe, structured result,
# honest truncation). NO service imports there, so it stays unit-testable
# with no cluster. Container flattens agent_fleet/datahub_wrapper/ into
# /app, so the flat import wins in-image; the dev checkout uses the package
# path — same duality as the mesh_registration imports elsewhere.
try:
    from lineage_filter import (  # type: ignore[no-redef]
        LINEAGE_MAX_HOP_DEPTH,
        LINEAGE_SCROLL_MAX_ENTITIES,
        LINEAGE_SCROLL_PAGE_SIZE,
        build_lineage_result,
    )
except ImportError:
    from agent_fleet.datahub_wrapper.lineage_filter import (
        LINEAGE_MAX_HOP_DEPTH,
        LINEAGE_SCROLL_MAX_ENTITIES,
        LINEAGE_SCROLL_PAGE_SIZE,
        build_lineage_result,
    )

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
          # BOTH edge kinds, deliberately: BI-tool connectors (Superset
          # et al.) link dashboard→chart via Contains; Consumes covers
          # direct dashboard→dataset edges. With Consumes alone a
          # dashboard rendered lineage-less even though each contained
          # chart knew its upstream datasets — the agent couldn't walk
          # dashboard→charts→datasets and answered honest-but-empty
          # (UNAVAILABLE_IN_CATALOG) to lineage questions.
          upstream: relationships(input: {types: ["Consumes", "Contains"], direction: OUTGOING, count: 25, start: 0}) {
            relationships { entity { urn type
              ... on Dataset { properties { name } }
              ... on Chart { info { name } }
            } }
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
    # 2026-07-02 SECURITY: `persona` and `domain` were ACCEPTED BUT
    # IGNORED — query_metadata enforced no access control at all, so
    # any caller (any persona incl. garbage, any domain) got full
    # PII-tagged catalog metadata. Confirmed live: a
    # DATA_ENGINEER·DEFENSE user's routing "denial" was laundered by
    # Engine A's generalist fallback, which called this endpoint with
    # a HARDCODED `persona=DATA_STEWARD`. See ADR-0025 "Catalog is an
    # enforcement surface" amendment + `[[project_adr0026_topaz_authz]]`.
    #
    # `entitled_domains` is the caller's REAL domain scope (threaded
    # from auth → supervisor → Engine A). The whole DataHub catalog is
    # the DATA_ENGINEERING domain (Engine D registers
    # domains=["DATA_ENGINEERING"]), so the coarse honest gate is: the
    # caller must be entitled to this engine's served domain.
    #
    # INTERIM POSTURE (explicitly): this is domain-granularity access.
    # The successor is per-asset Topaz `can_view` (ADR-0025 enforcement
    # session). Domain-gate stops the live PII leak today; can_view is
    # the durable model.
    #
    # Default is EMPTY, which the gate treats as DENY (least-privileged
    # per `[[optimistic-defaults-are-dishonest]]`) — a request with no
    # asserted entitlement gets nothing, never everything.
    persona: str = "DATA_STEWARD"
    domain: str = "DATA_ENGINEERING"
    entitled_domains: List[str] = []
    # ADR-0025 hop 2: the caller's ENTITLEMENT KEY (email), threaded from
    # auth → supervisor → Engine A. The SUBJECT of the Topaz can_view ask
    # that supersedes the in-code entitled_domains gate. Empty → the ask
    # denies (Topaz has no `user:` object for ""), matching the least-
    # privileged posture of an empty entitled_domains.
    caller_email: str = ""
    entity_type: Optional[str] = None
    # EXPLICIT platform scope, threaded from the router as structured data —
    # NOT inferred by scanning user_query for platform words. Slug
    # ('warehouse') or full 'urn:li:dataPlatform:<slug>'; empty = all
    # platforms (no filter). Replaces a substring heuristic that was
    # fragile both ways: a dashboard named after a platform triggered a
    # spurious filter, a paraphrase triggered none, and the caller passed
    # the narrowed entity name rather than the question so it could not fire
    # even in principle.
    platforms: List[str] = []


# The domain this DataHub catalog serves. Engine D registers
# domains=["DATA_ENGINEERING"]; the coarse access gate checks the
# caller's entitled_domains against this. Env-overridable for
# deployments that scope the catalog differently.
_ENGINE_D_SERVED_DOMAIN = os.getenv("ENGINE_D_SERVED_DOMAIN", "DATA_ENGINEERING")

# ── ADR-0025 hop 2: the ASK that supersedes the in-code domain gate ──────
# When ENABLE_AGENTIC_AUTH is ON, query_metadata ASKS Topaz can_view instead
# of evaluating entitled_domains in-code. Single-decider: the predicate lives
# in catalog_domain_view.rego (package invincible_agent.catalog.can_view),
# NOT here. The flag stays OFF until every enforcement point is migrated + the
# directory is seeded (hop 1) — it flips LAST. OFF → the in-code gate holds,
# behavior unchanged (dark launch).
# Posture ANNOUNCED at import, naming its SOURCE (2026-08-07): a dark-launched gate that says
# nothing is indistinguishable from an absent one. After the ADR-0025 flip, "DISABLED (DEFAULT)"
# must be impossible — a line that cannot tell "nobody configured this" from "someone chose
# this" cannot show that. Same wording in core/authz.py and weaviate_expert/service.py.
_AGENTIC_AUTH_RAW = os.getenv("ENABLE_AGENTIC_AUTH")
ENABLE_AGENTIC_AUTH = (_AGENTIC_AUTH_RAW or "false").lower() in ("true", "1", "yes")
print(
    f"agentic auth: {'ENFORCING' if ENABLE_AGENTIC_AUTH else 'DISABLED'} "
    f"({'explicit config' if _AGENTIC_AUTH_RAW is not None else 'DEFAULT'}, "
    f"dark-launch ADR-0025) [datahub_wrapper: query_metadata can_view]",
    flush=True,
)
TOPAZ_AUTHORIZER_URL = os.getenv("TOPAZ_AUTHORIZER_URL", "http://topaz-svc:8383")
_CATALOG_VIEW_POLICY_PATH = "invincible_agent.catalog.can_view"


async def _topaz_can_view(caller_email: str, domain: str) -> bool:
    """Ask Topaz whether ``caller_email`` may view the ``domain`` catalog.

    The single-decider ASK: Topaz DERIVES readership from the caller's own
    seeded cells (catalog_domain_view.rego walks persona×domain grants) —
    query_metadata does not evaluate any policy predicate. The subject is
    passed in resourceContext (this Topaz has no identity→user resolution
    objects; identityContext is present only to satisfy request validation).

    Fail-CLOSED: any error, timeout, or unreachable authorizer returns False.
    An auth-service problem must DENY the PII catalog, never open it — the
    inverse of the fail-open bug the ADR-0025 amendment names.
    """
    payload = {
        "identityContext": {
            "identity": caller_email or "anonymous",
            "type": "IDENTITY_TYPE_MANUAL",
        },
        "resourceContext": {"user_id": caller_email, "domain": domain},
        "policyContext": {
            "path": _CATALOG_VIEW_POLICY_PATH,
            "decisions": ["allowed"],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{TOPAZ_AUTHORIZER_URL}/api/v2/authz/is", json=payload
            )
            r.raise_for_status()
            for d in r.json().get("decisions", []):
                if d.get("decision") == "allowed":
                    return bool(d.get("is", False))
        return False
    except Exception as e:  # noqa: BLE001 — fail-closed on ANY failure
        logging.error(
            "QUERY_METADATA: Topaz can_view ask FAILED for %r/%s "
            "(fail-closed DENY): %r",
            caller_email,
            domain,
            e,
        )
        return False


async def _domain_view_gate(
    caller_email: str, entitled_domains: Optional[List[str]]
) -> tuple[bool, str]:
    """THE single catalog-metadata `can_view` gate for Engine D.

    Every metadata-plane reader — /query_metadata, /lineage_edges, and the
    platform-scoped /lineage_by_platform below — calls THIS, so "the new
    endpoint inherits the gate by construction" is the same function call,
    not similar code copied to a new site (which is exactly how the DA-read
    gate went broken-closed for months: helper present, call site threading
    the wrong identity). Returns ``(allowed, gate_basis)``; the caller
    renders an honest-empty / access_denied response on deny.

    Two branches, per the ADR-0025 dark launch:
      * ENABLE_AGENTIC_AUTH → Topaz ``can_view`` ask (fail-closed on any
        error/timeout/unreachable authorizer).
      * else → in-code ``ENGINE_D_SERVED_DOMAIN in entitled_domains``.

    SEAL STATE (2026-07-20): the IN-CODE branch is sealed on sandbox with a
    three-caller probe — entitled-to-served-domain allowed; empty denied;
    and, load-bearingly, entitled-to-the-WRONG-domain (MAINTENANCE) denied,
    which proves the check is on the SPECIFIC served domain rather than the
    mere presence of an entitlement list. The TOPAZ branch is a COLD PATH:
    unexercised in any armed environment, so it must be sealed with the
    same three-caller shape at the terminal flip before it is trusted.
    """
    entitled = [d.upper() for d in (entitled_domains or [])]
    if ENABLE_AGENTIC_AUTH:
        allowed = await _topaz_can_view(caller_email, _ENGINE_D_SERVED_DOMAIN)
        return allowed, "topaz_can_view"
    return (_ENGINE_D_SERVED_DOMAIN.upper() in entitled), "in_code_entitled_domains"


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


class MatchedAsset(BaseModel):
    """Structured per-asset record returned alongside the formatted
    short_answer. Carries the same fields the formatter renders into
    text, but as named fields so downstream consumers (cortex-ui
    SourcesTrail via Engine A's Phase 3 source attribution) can pull
    per-asset descriptions and external URLs without parsing the
    formatted string. The original ``referenced_uris`` flat-URN list
    stays for backwards compatibility — this is additive.
    """
    urn: str
    type: str                       # idp-style: "dataset" | "dashboard" | "chart"
    label: str                      # friendly name (e.g. gold.sales.revenue_summary)
    owner: Optional[str] = None
    last_updated: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = []
    upstream: List[str] = []
    downstream: List[str] = []
    columns: Optional[str] = None   # comma-separated "name:type" list, capped
    open_url: Optional[str] = None  # external DataHub UI link, when configured


class ExpertResponse(BaseModel):
    confidence_score: float
    referenced_uris: List[str]
    # Phase 3 follow-up (2026-06-24): structured per-asset list so
    # consumers can build rich Source records (snippet, link) without
    # re-parsing short_answer. Empty when no assets matched.
    matched_assets: List[MatchedAsset] = []
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


# ── ADR-0028 canvas lineage edges (deterministic, non-agentic, GATED) ─────────
# Direct 1-hop DataHub lineage among the caller's ANSWERED subjects, so the
# canvas GRAPH mode can draw DIRECTED lineage edges. This is a STRUCTURAL query
# (no LLM in the path — we know exactly what we want), but it stays behind Engine
# D's metadata gate: lineage is CATALOG METADATA, so it inherits the SAME domain
# can_view gate as query_metadata (NOT the data-plane can_read — that gates
# reading dataset CONTENTS). DataHub access stays in ONE gated boundary (Engine
# D); the gateway proxies here, never calls GMS itself.
#
# Enforcement properties: (1) denied → honest empty (no lineage without
# entitlement). (2) edges are ONLY returned between subjects the caller already
# has answers about (both endpoints in `subjects`) — an un-answered / unreadable
# upstream is NEVER revealed. Transitive lineage (a path THROUGH an unseen
# intermediate) is deliberately NOT done here — that's the existence-oracle
# question to settle before extending past 1-hop.
class LineageSubject(BaseModel):
    answer_id: str
    urn: str


class LineageEdgesRequest(BaseModel):
    subjects: List[LineageSubject] = []
    entitled_domains: List[str] = []
    caller_email: str = ""


async def _fetch_direct_upstreams(client: httpx.AsyncClient, urn: str) -> List[str]:
    """A dataset's DIRECT (1-hop) upstream dataset URNs via GMS lineage."""
    query = """
    query Up($urn: String!) {
      dataset(urn: $urn) {
        upstream: relationships(input: {types: ["DownstreamOf"], direction: OUTGOING, count: 50, start: 0}) {
          relationships { entity { urn } }
        }
      }
    }
    """
    headers = {}
    if DATAHUB_TOKEN:
        headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"
    try:
        r = await client.post(
            DATAHUB_GMS_URL,
            json={"query": query, "variables": {"urn": urn}},
            headers=headers,
        )
        r.raise_for_status()
        rels = (
            (((r.json().get("data") or {}).get("dataset") or {}).get("upstream") or {})
            .get("relationships")
            or []
        )
        return [
            rel["entity"]["urn"]
            for rel in rels
            if isinstance(rel.get("entity"), dict) and rel["entity"].get("urn")
        ]
    except Exception as e:  # noqa: BLE001 — a lineage miss is empty, never fatal
        logging.warning("lineage_edges: upstream fetch failed for %s: %r", urn, e)
        return []


@app.post("/lineage_edges")
async def lineage_edges(req: LineageEdgesRequest) -> dict:
    # SAME gate as query_metadata (lineage = catalog metadata → domain can_view).
    entitled = [d.upper() for d in (req.entitled_domains or [])]
    if ENABLE_AGENTIC_AUTH:
        allowed = await _topaz_can_view(req.caller_email, _ENGINE_D_SERVED_DOMAIN)
    else:
        allowed = _ENGINE_D_SERVED_DOMAIN.upper() in entitled
    if not allowed:
        logging.warning(
            "LINEAGE_EDGES DENIED: caller_email=%r entitled=%s",
            req.caller_email,
            entitled,
        )
        return {"edges": []}  # honest empty — no lineage without entitlement

    by_urn: Dict[str, List[str]] = {}
    for s in req.subjects:
        if s.urn:
            by_urn.setdefault(s.urn, []).append(s.answer_id)
    urns = list(by_urn.keys())
    if len(urns) < 2:
        return {"edges": []}

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            *[_fetch_direct_upstreams(client, u) for u in urns]
        )
    upstreams = {u: set(ups) for u, ups in zip(urns, results)}

    edges: List[dict] = []
    for u_down, downstream_answers in by_urn.items():
        for u_up in upstreams.get(u_down, ()):
            if u_up == u_down or u_up not in by_urn:
                continue  # ONLY edges between answered subjects (no reveal)
            for a_up in by_urn[u_up]:
                for a_down in downstream_answers:
                    edges.append(
                        {"from": a_up, "to": a_down, "kind": "lineage", "directed": True}
                    )
    logging.info(
        "LINEAGE_EDGES: %d subjects → %d edges (caller=%r)",
        len(urns), len(edges), req.caller_email,
    )
    return {"edges": edges}


# ---------------------------------------------------------------------------
# Platform-scoped upstream lineage — the server-side, filtered walk.
# ---------------------------------------------------------------------------
_SCROLL_LINEAGE_QUERY = """
query ScrollLineage($input: ScrollAcrossLineageInput!) {
  scrollAcrossLineage(input: $input) {
    nextScrollId
    searchResults { degree entity { urn } }
  }
}
"""


def _platform_or_filters(platforms: Optional[List[str]]) -> Optional[list]:
    """DataHub orFilters selecting the given platforms, or None for all.

    Accepts bare slugs or full platform URNs; emits the URN form DataHub
    matches on. None/empty means NO filter — an absent constraint must
    never become an everything-excluded one.
    """
    wanted = [str(p).strip() for p in (platforms or []) if str(p).strip()]
    if not wanted:
        return None
    values = [
        p if p.startswith("urn:li:dataPlatform:") else f"urn:li:dataPlatform:{p}"
        for p in wanted
    ]
    return [{"and": [{"field": "platform", "values": values}]}]


async def _scroll_lineage_upstream(
    client: httpx.AsyncClient,
    start_urn: str,
    platforms: Optional[List[str]],
) -> tuple[List[Dict[str, Any]], bool]:
    """UPSTREAM lineage of ``start_urn``, platform-filtered SERVER-SIDE.

    DataHub does the traversal AND the platform filter (orFilters on the
    dataPlatform field), so we never pull the full closure to filter it
    client-side, and — critically — we never mistake NAME-SEARCH hits for
    lineage. A prior approach searched by asset name and treated the hits
    as lineage; name search returns same-named assets that aren't upstream
    of anything, so its evidence set had no defensible relationship to the
    question. This is a lineage traversal, full stop.

    Scroll-paginated via ``nextScrollId`` so a large closure is fetched
    COMPLETELY, not clipped at one page (the single-page cap on the
    /lineage_edges walk is a genuine silent-loss bug; this path does not
    repeat it). Two honest bounds:
      * ``LINEAGE_SCROLL_MAX_ENTITIES`` — total entities pulled.
      * ``LINEAGE_MAX_HOP_DEPTH`` — degree ceiling. Measured 8 and 11 on a
        real dashboard; set to 20 for headroom. Applied to the returned
        ``degree`` (the server already traversed and labelled it — this is
        a filter on results, not a client walk).

    Returns ``(rows, truncated)``. ``truncated`` is True when EITHER bound
    clips, so ``build_lineage_result`` can mark the answer a lower bound.
    """
    headers = {"Content-Type": "application/json"}
    if DATAHUB_TOKEN:
        headers["Authorization"] = f"Bearer {DATAHUB_TOKEN}"
    or_filters = _platform_or_filters(platforms)

    rows: List[Dict[str, Any]] = []
    truncated = False
    scroll_id: Optional[str] = None
    # Page ceiling: a server that returns a perpetual nextScrollId must not
    # loop us forever. Derived from the entity ceiling so it can only bind
    # after that one would have.
    max_pages = (LINEAGE_SCROLL_MAX_ENTITIES // max(1, LINEAGE_SCROLL_PAGE_SIZE)) + 2

    for _ in range(max_pages):
        inp: Dict[str, Any] = {
            "urn": start_urn,
            "direction": "UPSTREAM",
            "count": LINEAGE_SCROLL_PAGE_SIZE,
        }
        if or_filters:
            inp["orFilters"] = or_filters
        if scroll_id:
            inp["scrollId"] = scroll_id

        r = await client.post(
            DATAHUB_GMS_URL,
            json={"query": _SCROLL_LINEAGE_QUERY, "variables": {"input": inp}},
            headers=headers,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            # LOUD, per the same discipline query_metadata uses: a 200 with
            # errors[] is a real failure, not an empty result.
            raise RuntimeError(
                f"scrollAcrossLineage GraphQL error: "
                f"{json.dumps(body['errors'])[:300]}"
            )
        blk = (body.get("data") or {}).get("scrollAcrossLineage") or {}
        for res in blk.get("searchResults") or []:
            deg = res.get("degree")
            urn = ((res.get("entity") or {}).get("urn")) or ""
            if isinstance(deg, int) and deg > LINEAGE_MAX_HOP_DEPTH:
                truncated = True  # beyond the hop ceiling; excluded + marked
                continue
            if urn:
                rows.append({"urn": urn, "degree": deg})
            if len(rows) >= LINEAGE_SCROLL_MAX_ENTITIES:
                truncated = True
                break
        if truncated and len(rows) >= LINEAGE_SCROLL_MAX_ENTITIES:
            break
        scroll_id = blk.get("nextScrollId")
        if not scroll_id:
            break
    else:
        # Loop hit max_pages without a terminal null scrollId — the closure
        # is larger than we will pull. Honest lower bound.
        truncated = True

    return rows, truncated


class LineageByPlatformRequest(BaseModel):
    subject_urn: str
    platforms: List[str] = []          # empty = all platforms (no filter)
    entitled_domains: List[str] = []
    caller_email: str = ""


@app.post("/lineage_by_platform")
async def lineage_by_platform(req: LineageByPlatformRequest) -> dict:
    """Platform-scoped UPSTREAM lineage of a single asset — server-side,
    exact, in code.

    Replaces the accumulate-by-name-search-then-let-the-LLM-pick pattern
    that produced a confident wrong answer: the model read a long
    repetitive list, missed the matching rows, and reported "none" while
    the matches sat in its own evidence. Selection is done HERE
    (lineage_filter.build_lineage_result); the model only narrates the
    small result.

    GATE — metadata plane, inherited VERBATIM. Calls the same
    ``_domain_view_gate`` helper as /query_metadata, fail-closed,
    honest-empty on deny. Its safety rests on a CHECKED fact: past the
    domain gate /query_metadata is per-asset-UNFILTERED (only a platform
    orFilter, no per-asset predicate in the query or the result parsing),
    so every entity this UPSTREAM walk can surface is already reachable by
    name through /query_metadata — the walk's exposure is a SUBSET. It does
    NOT rely on /lineage_edges' "edges only between subjects already seen"
    property, which does NOT survive an 8-11-hop walk.

    IF the metadata-plane ruling ever flips to per-asset ``can_read``, THIS
    endpoint is the FIRST that must adopt per-asset filtering — its
    aperture (deep upstream traversal) is the widest in the system. That
    dependency is recorded in the substrate runbook at the point it will
    break, not just here.
    """
    allowed, gate_basis = await _domain_view_gate(req.caller_email, req.entitled_domains)
    requested = sorted({str(p).strip().lower() for p in (req.platforms or []) if str(p).strip()})
    if not allowed:
        logging.warning(
            "LINEAGE_BY_PLATFORM DENIED (%s): served_domain=%s caller_email=%r",
            gate_basis, _ENGINE_D_SERVED_DOMAIN, req.caller_email,
        )
        # Honest-empty, same discriminating shape as the other metadata-plane
        # denials: access_denied True distinguishes "gate blocked" from
        # "walk ran and found nothing".
        return {
            "match_count": 0, "matches": [], "considered_count": 0,
            "platforms_requested": requested, "platform_histogram": {},
            "truncated": False, "access_denied": True, "gate_basis": gate_basis,
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rows, truncated = await _scroll_lineage_upstream(
                client, req.subject_urn, req.platforms
            )
    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "LINEAGE_BY_PLATFORM: scroll failed for subject=%r: %r",
            req.subject_urn, exc,
        )
        # Honest error, NOT a fabricated empty — the caller must be able to
        # tell "lineage unavailable" from "no matching lineage".
        return {
            "match_count": 0, "matches": [], "considered_count": 0,
            "platforms_requested": requested, "platform_histogram": {},
            "truncated": False, "error": "lineage_unavailable",
        }

    result = build_lineage_result(rows, platforms=req.platforms, truncated=truncated)
    result["access_denied"] = False
    logging.info(
        "LINEAGE_BY_PLATFORM: subject=%r platforms=%s considered=%d matched=%d truncated=%s",
        req.subject_urn, result["platforms_requested"],
        result["considered_count"], result["match_count"], result["truncated"],
    )
    return result


@app.get("/tables")
async def get_tables() -> dict:
    """Legacy endpoint — now deprecated in favor of /query_metadata."""
    return {"available_tables": "Dynamic search enabled via /query_metadata"}


# ---------------------------------------------------------------------------
# Instance resolution — Recipe v2 Piece 2.
# ---------------------------------------------------------------------------
# resolveInstance name-matching lives in a dep-free sibling so it unit-tests
# without the httpx/fastapi/datahub import chain (same split as lineage_filter);
# flatten-aware import. _name_score keeps its underscore name so call sites and
# the /resolve_instance scoring below are unchanged.
try:
    from instance_match import (  # type: ignore[no-redef]
        name_score as _name_score,
        strip_descriptor_tokens as _strip_descriptor_tokens,
    )
except ImportError:
    from agent_fleet.datahub_wrapper.instance_match import (
        name_score as _name_score,
        strip_descriptor_tokens as _strip_descriptor_tokens,
    )


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
    # Descriptor-strip fallback: users append entity-type / BI-platform nouns
    # ("customer 360 superset dashboard"); DataHub's search on the full
    # descriptor string can return ZERO hits while the core name resolves
    # exactly. Add a reduced query with those tokens removed. The full query is
    # tried first and EVERY candidate is scored against the ORIGINAL identifier
    # (via _name_score, whose multi-word-containment rule lets the core name
    # still clear the floor), so this only ADDS a candidate source — it cannot
    # make a worse match win.
    reduced = _strip_descriptor_tokens(request.identifier)
    if reduced and reduced.lower() != request.identifier.strip().lower() and reduced not in search_queries:
        search_queries.append(reduced)

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

    # Alias telemetry (log-only, zero behavior change). When the descriptor-strip
    # fallback was applied AND a NON-exact candidate resolved, the user's
    # phrasing is an ALIAS for the asset (they said it a way that isn't its
    # catalog name). Record the pair so a future decision is driven by REAL
    # phrasings from logs rather than imagined ones: (a) whether an LLM
    # candidate-generator rung is ever worth building — see ADR-0031 — and
    # (b) raw material for a v2 alias-persistence loop (confirmation-gated).
    # Grep marker: RESOLVE_INSTANCE_ALIAS.
    if reduced and reduced.strip().lower() != request.identifier.strip().lower() and candidates:
        top = candidates[0]
        if top.score < 1.0:
            logger.info(
                "RESOLVE_INSTANCE_ALIAS identifier=%r resolved_to=%r urn=%s "
                "score=%.2f reduced_query=%r — descriptor-strip bridged a "
                "non-exact name; alias-mining / LLM-rung-need signal (ADR-0031).",
                request.identifier, top.label, top.instance_id, top.score, reduced,
            )

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
    # ── ACCESS GATE — deny BEFORE any DataHub query ─────────────────
    # Two paths, selected by ENABLE_AGENTIC_AUTH (ADR-0025 hop 2):
    #
    #   ON  → ASK Topaz can_view(caller_email, served_domain). Topaz is the
    #         single decider; the predicate lives in catalog_domain_view.rego
    #         (it derives readership from the caller's seeded cells). This is
    #         the migration of the in-code predicate to an ASK.
    #   OFF → the 2026-07-02 in-code gate: served_domain ∈ entitled_domains.
    #         Unchanged behavior; the flag flips LAST (after all enforcement
    #         points migrate + the directory is seeded). Dark launch.
    #
    # Either way: empty/denied → an HONEST "not entitled" answer (fail-CLOSED,
    # least-privileged), distinct from "no assets matched". This closes the
    # confirmed bypass where any caller got full PII-tagged metadata.
    entitled = [d.upper() for d in (request.entitled_domains or [])]
    allowed, gate_basis = await _domain_view_gate(
        request.caller_email, request.entitled_domains
    )

    if not allowed:
        logging.warning(
            "QUERY_METADATA DENIED (%s): served_domain=%s caller_email=%r "
            "entitled_domains=%s persona=%s query=%r",
            gate_basis,
            _ENGINE_D_SERVED_DOMAIN,
            request.caller_email,
            entitled,
            request.persona,
            request.user_query[:120],
        )
        return ExpertResponse(
            confidence_score=0.0,
            referenced_uris=[],
            matched_assets=[],
            data=DataStewardResponse(
                short_answer=(
                    f"Not entitled: this catalog serves the "
                    f"{_ENGINE_D_SERVED_DOMAIN} domain, and your access "
                    f"scope does not include it. "
                    f"No metadata was retrieved. Request "
                    f"{_ENGINE_D_SERVED_DOMAIN} entitlement to query it."
                ),
                safety_warnings=[
                    f"access_denied: served_domain={_ENGINE_D_SERVED_DOMAIN} "
                    f"basis={gate_basis}"
                ],
            ),
        )

    # Platform scope is an EXPLICIT parameter now (see MetadataQueryRequest.
    # platforms). The old `for term in PLATFORM_MAP if term in
    # user_query.upper()` heuristic is deleted, not layered over: two
    # mechanisms deciding the same thing, one of them silently wrong, is
    # the shape this codebase keeps getting bitten by.
    wanted_platforms = [p for p in (request.platforms or []) if str(p).strip()]
    or_filters = []
    if wanted_platforms:
        or_filters.append({"and": [{"field": "platform", "values": [
            p if str(p).startswith("urn:li:dataPlatform:")
            else f"urn:li:dataPlatform:{p}"
            for p in wanted_platforms
        ]}]})

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

    # LOUD GraphQL-error path. DataHub returns HTTP 200 with
    # ``{"errors": [...], "data": null}`` on validation failures
    # (e.g. an entity_type the deployed schema doesn't expose as an
    # enum value). The previous ``data.get("data") or {}`` pattern
    # silently collapsed that to an empty result set — the smolagent
    # saw "0 results found", broadened to another entity_type, hit
    # another validation error, broadened again, and so on, while
    # the actual error message DataHub returned (which would have
    # been actionable) was discarded. Same silent-swallow shape the
    # /resolve_instance endpoint already guards against; mirror that
    # discipline here so the smolagent's broaden-on-miss loop gets
    # honest feedback instead of looping on fabricated empties.
    data = data or {}
    gql_errors = data.get("errors") or []
    if gql_errors:
        print(
            f"ERROR: DataHub GraphQL errors for /query_metadata "
            f"user_query={request.user_query!r} "
            f"entity_type={request.entity_type!r}: "
            f"{json.dumps(gql_errors)}",
            flush=True,
        )
        # Surface the validation failure to the smolagent as a
        # short_answer it can read and react to. Without this, the
        # smolagent just sees "No results found." and retries with
        # another invalid type. With this, it sees the actual
        # rejection and (for enum validation errors specifically)
        # has a chance to pick a valid type next time.
        error_messages = [
            (e or {}).get("message") or ""
            for e in gql_errors
            if (e or {}).get("message")
        ]
        return ExpertResponse(
            confidence_score=0.0,
            referenced_uris=[],
            matched_assets=[],
            data=DataStewardResponse(
                short_answer=(
                    "DataHub rejected the query: "
                    + "; ".join(error_messages)
                    + ". Common cause: the entity_type isn't in this "
                    "DataHub deployment's EntityType enum. Valid types "
                    "for this deployment are listed in the "
                    "'Valid DataHub Entity Types' block of your system "
                    "prompt — use one of those, not a guessed value."
                ),
                tool_list=["DataHub"],
                safety_warnings=[
                    "Query validation failed at DataHub. Not the same "
                    "as 'no asset found' — the query itself was malformed."
                ],
            ),
        )

    # Parse Results Generically
    data_dict = data.get("data") or {}
    search_dict = data_dict.get("searchAcrossEntities") or data_dict.get("search") or {}
    search_results = search_dict.get("searchResults") or []
    matched_assets = []
    referenced_uris = []
    # Phase 3 follow-up: structured per-asset list built alongside
    # the formatted text. Same source data, two shapes — the smolagent
    # gets the text (short_answer), the supervisor's source-attribution
    # path gets the structured list. No double DataHub call.
    matched_assets_structured: List[MatchedAsset] = []
    # Optional external DataHub UI link prefix; empty string ⇒ no
    # open_url is emitted (UI handles missing gracefully). Configured
    # via the chart's agentFleet.env so a single switch controls the
    # whole fleet's external-link policy.
    datahub_frontend_url = (os.getenv("DATAHUB_FRONTEND_URL") or "").rstrip("/")

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

    def _platform_from_urn(urn: str) -> str:
        """Best-effort platform label from an entity URN — datasets embed
        `urn:li:dataPlatform:<p>`; chart/dashboard URNs open with `(<p>,`.
        Returns '' when unparseable. WHY THE PLATFORM MUST BE VISIBLE:
        without it, a BI-tool's virtual dataset and the physical
        warehouse table behind it render identically (`DATASET:<name>`),
        so the agent can neither tell an intermediate hop from a
        terminal one nor honestly answer "which <platform> tables…"
        questions — observed live: an agent reported a dashboard's
        immediate (BI-layer) datasets AS the warehouse tables the user
        asked about, asserting a platform the tool never returned."""
        import re
        m = re.search(r"urn:li:dataPlatform:([^,)]+)", urn)
        if m:
            return m.group(1)
        m = re.match(r"urn:li:(?:chart|dashboard):\(([^,)]+),", urn)
        return m.group(1) if m else ""

    def _lineage_names(entity_dict: Dict[str, Any], key: str) -> List[str]:
        rels = ((entity_dict.get(key) or {}).get("relationships")) or []
        out: List[str] = []
        for r in rels:
            ent = (r or {}).get("entity") or {}
            etype = ent.get("type", "")
            props = ent.get("properties") or ent.get("info") or {}
            name = props.get("name") or ent.get("urn", "")
            plat = _platform_from_urn(ent.get("urn", ""))
            if name:
                out.append(f"{etype}({plat}):{name}" if plat else f"{etype}:{name}")
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
        plat = _platform_from_urn(urn)
        if plat:
            line += f" | platform={plat}"
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
        columns_str: Optional[str] = None
        if entity_type == "DATASET":
            schema = entity.get("schemaMetadata") or {}
            fields = (schema.get("fields") or [])[:12]
            if fields:
                cols = ", ".join(
                    f"{(f or {}).get('fieldPath','?')}:{(f or {}).get('nativeDataType','?')}"
                    for f in fields
                )
                columns_str = cols
                line += f"\n    columns: {cols}"

        matched_assets.append(line)
        referenced_uris.append(urn)

        # Phase 3 follow-up: build the structured per-asset record.
        # Type is lowercased to match the idp-style consumer convention
        # (cortex-ui SourcesTrail expects "dataset" not "DATASET").
        # open_url is omitted when no DATAHUB_FRONTEND_URL is set —
        # consumer treats empty as "no link available".
        open_url: Optional[str] = None
        if datahub_frontend_url and urn:
            from urllib.parse import quote
            # DataHub UI URLs follow /<entity_type_lc>/<URN>/ — Schema
            # tab for datasets, root for charts/dashboards. Quoting
            # handles the parenthesized URN body.
            ui_segment = (
                "dataset" if entity_type == "DATASET"
                else "dashboard" if entity_type == "DASHBOARD"
                else "chart" if entity_type == "CHART"
                else entity_type.lower()
            )
            suffix = "/Schema" if entity_type == "DATASET" else ""
            open_url = f"{datahub_frontend_url}/{ui_segment}/{quote(urn, safe='')}{suffix}"

        matched_assets_structured.append(MatchedAsset(
            urn=urn,
            type=entity_type.lower(),
            label=name,
            owner=(owners[0] if owners else None),
            last_updated=last_updated,
            description=(desc or None),
            tags=tags,
            upstream=upstream,
            downstream=downstream,
            columns=columns_str,
            open_url=open_url,
        ))

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
        matched_assets=matched_assets_structured,
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
