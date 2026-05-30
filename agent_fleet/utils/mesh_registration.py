"""Engine self-registration for the predicate-graph routing layer
(iagent ADR-0004 Step D.1).

The iagent-mesh-sdk ``MeshTool`` registers SDK-built tools to DataHub on
startup so doc-tools' AITool binding plane can materialize them as
predicate edges in Neo4j. Hardcoded fleet engines (Engine A, E, DA, W,
etc.) don't use ``MeshTool`` -- they're FastAPI apps with their own
business logic -- but they're equally valid peers in the predicate
graph. This helper gives them the same registration contract without
forcing them through the SDK.

The wire shape matches ``MeshTool`` byte-for-byte (same URN scheme, same
``customProperties`` keys). doc-tools' ``aitool_registration_sensor``
picks both up indiscriminately.

Per ADR-0006: DataHub is the inbox; runtime serving is independent.
Registration failure logs a warning and returns; the engine keeps
serving requests regardless.

Per ADR-0005: the ``verb`` URI's prefix determines ``namespace_authority``
on the emitted aspect.

Usage from an engine's FastAPI lifespan::

    from utils.mesh_registration import register_engine_to_mesh

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        register_engine_to_mesh(
            name="engine_a_restate_analyst",
            description="Durable analyst engine ...",
            verb="mesh:analyzeWithCodeAgent",
            input_uri="mesh:AgentTask",
            output_uri="mesh:AgentResponse",
            endpoint_url=os.getenv("ENGINE_A_PUBLIC_URL", "..."),
            owner_persona="DATA_STEWARD",
            cost_class="slow",
        )
        yield
"""

from __future__ import annotations

import json
import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger("mesh_registration")

#: Same opt-in env var semantics as the SDK. Set to one of these (case
#: insensitive) to actually emit; anything else and the helper logs that
#: it's skipping and returns.
_TRUTHY = {"true", "1", "yes", "on"}

#: Engines that go through this helper are tagged with this kind on the
#: registration aspect, distinguishing them from SDK-tools at the consume
#: side. Currently informational only; doc-tools doesn't branch on it.
_TOOL_KIND_ENGINE = "Engine"


def register_engine_to_mesh(
    *,
    name: str,
    description: str,
    verb: str,
    input_uri: str,
    output_uri: str,
    endpoint_url: str,
    verb_synonyms: Optional[Iterable[str]] = None,
    owner_persona: Optional[str] = None,
    domains: Optional[Iterable[str]] = None,
    cost_class: str = "medium",
    requires_human_approval: bool = False,
    version: str = "0.1.0",
    openapi_schema: Optional[dict] = None,
) -> None:
    """Emit a DataHub MCP describing this engine as a predicate edge.

    All registration emits are opt-in via ``MESH_REGISTER_ON_STARTUP``.
    The helper performs three checks in order; any failure leaves a
    clear log line and returns without raising:

    1. Is registration enabled?
    2. Is ``DATAHUB_GMS_URL`` configured?
    3. Is ``acryl-datahub`` installed in this image?

    Engines that pass all three checks emit one ``mlModel`` aspect with
    the full predicate-graph payload in ``customProperties``. Engines
    that fail any check keep serving requests; routing for them just
    won't be discoverable by ``/find_tool`` until the next startup.
    """
    if os.getenv("MESH_REGISTER_ON_STARTUP", "false").lower() not in _TRUTHY:
        logger.info(
            "Skipping DataHub registration for engine %s "
            "(set MESH_REGISTER_ON_STARTUP=true to enable)",
            name,
        )
        return

    gms_url = os.getenv("DATAHUB_GMS_URL")
    token = os.getenv("DATAHUB_TOKEN", "")

    if not gms_url:
        logger.warning(
            "MESH_REGISTER_ON_STARTUP=true but DATAHUB_GMS_URL not set; "
            "skipping registration for engine %s. The engine will keep "
            "serving but won't be reachable via /find_tool.",
            name,
        )
        return

    try:
        from datahub.emitter.mcp import MetadataChangeProposalWrapper
        from datahub.emitter.rest_emitter import DatahubRestEmitter
        from datahub.metadata.schema_classes import MLModelPropertiesClass
    except ImportError:
        logger.warning(
            "acryl-datahub is not installed; skipping registration for "
            "engine %s. Install acryl-datahub in the image to enable.",
            name,
        )
        return

    # URN scheme matches iagent-mesh-sdk MeshTool exactly; doc-tools'
    # aitool_registration_sensor treats them identically.
    urn = f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{name},PROD)"

    # Per ADR-0005: mesh: prefix -> platform authority; anything else -> domain.
    namespace_authority = "platform" if verb.startswith("mesh:") else "domain"

    custom_props = {
        # Marker for doc-tools' filter
        "mesh_is_registration":         "true",
        "mesh_tool_kind":               _TOOL_KIND_ENGINE,
        # Predicate identity + typing
        "mesh_verb_iri":                verb,
        "mesh_verb_synonyms":           json.dumps(list(verb_synonyms or [])),
        "mesh_input_uri":               input_uri,
        "mesh_output_uri":              output_uri,
        "mesh_namespace_authority":     namespace_authority,
        # Routing / policy metadata
        "mesh_owner_persona":           owner_persona or "",
        # Per ADR-0009: domains are a scope filter, not a routing key.
        # JSON-encoded list of domain scopes this engine serves; empty list
        # means domain-agnostic.
        "mesh_domains":                 json.dumps(list(domains or [])),
        "mesh_cost_class":              cost_class,
        "mesh_requires_human_approval": "true" if requires_human_approval else "false",
        # Runtime
        "mesh_endpoint_url":            endpoint_url,
        "mesh_openapi_schema":          json.dumps(openapi_schema or {}),
        # Versioning; sdk_version=0.0.0 distinguishes engine-helper emits
        # from SDK MeshTool emits at the consume side if anyone wants to
        # branch on it later.
        "mesh_sdk_version":             "0.0.0",
        "mesh_tool_version":            version,
    }

    props = MLModelPropertiesClass(
        description=description,
        customProperties=custom_props,
    )

    try:
        emitter = DatahubRestEmitter(gms_server=gms_url, token=token)
        mcp = MetadataChangeProposalWrapper(entityUrn=urn, aspect=props)
        emitter.emit(mcp)
        logger.info(
            "✅ Registered engine %s as %s -> (%s -> %s)",
            urn,
            verb,
            input_uri,
            output_uri,
        )
    except Exception as e:  # noqa: BLE001  -- ADR-0006: do not crash the engine
        logger.warning(
            "⚠️ Failed to register engine %s to DataHub: %s. "
            "Engine will keep serving; routing will resume after the next "
            "successful registration cycle.",
            urn,
            e,
        )
