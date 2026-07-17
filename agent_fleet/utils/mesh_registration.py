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
            input_uri="http://invincible-agent/mesh#AgentTask",
            output_uri="http://invincible-agent/mesh#AgentResponse",
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

def _gms_server_base(url: str) -> str:
    """Normalize DATAHUB_GMS_URL for the REST emitter.

    The env var is OVERLOADED across consumers: the GraphQL readers
    (datahub_wrapper, policy/sync/datahub_topaz_sync) use it VERBATIM as
    the GraphQL endpoint (``…/api/graphql``), while DatahubRestEmitter
    wants the bare GMS server base and appends its own paths
    (``/aspects``). Feeding the graphql-shaped value to the emitter
    404s at ``/api/graphql/aspects`` — seen live at work-deploy, where
    the shared agentFleet.env value is (correctly, for the readers) the
    graphql form, and where MESH_REGISTRAR_URL wasn't set so this
    direct-emit fallback actually ran (sandbox always took the
    registrar path, which is why the collision stayed invisible).
    Normalizing here lets ONE env value serve both consumers."""
    return url.rstrip("/").removesuffix("/api/graphql").rstrip("/")


#: Engines that go through this helper are tagged with this kind on the
#: registration aspect, distinguishing them from SDK-tools at the consume
#: side. Currently informational only; doc-tools doesn't branch on it.
_TOOL_KIND_ENGINE = "Engine"

#: Presentation capabilities (per ADR-0017) use the same registration
#: pipeline as engines but advertise an SPO triple instead of a verb
#: edge. The kind lets the consume side distinguish without changing
#: the URN scheme.
_TOOL_KIND_PRESENTATION = "Presentation"

#: The predicate IRI for every presentation registration. Per ADR-0017,
#: presentation capabilities are SPO triples of shape
#: ``(output_shape, mesh:rendersAs, archetype)``.
_PREDICATE_RENDERS_AS = "mesh:rendersAs"


def _emit_to_registrar(
    *,
    registrar_url: str,
    name: str,
    description: str,
    verb: str,
    input_uri: str,
    output_uri: str,
    endpoint_url: str,
    verb_synonyms: Optional[Iterable[str]],
    verb_anti_synonyms: Optional[Iterable[str]],
    owner_persona: Optional[str],
    domains: Optional[Iterable[str]],
    cost_class: str,
    requires_human_approval: bool,
    version: str,
    openapi_schema: Optional[dict],
    provider: Optional[str] = None,
    timeout_s: Optional[float] = None,
) -> None:
    """POST a structured manifest to the mesh-registrar gateway.

    The gateway validates Contract D (input_uri/output_uri must resolve
    to real :OntologyClass nodes in Neo4j), emits the DataHub MCP, and
    handles idempotency by tool_urn. Engines that go through this path
    don't need ``acryl-datahub`` or DataHub protocol knowledge — that
    cost lives once in the gateway image instead of in every engine.

    Manifest shape mirrors mesh-registrar's ``RegistrationManifest``
    pydantic model (``agent_fleet/mesh_registrar/main.py``).

    On Contract D rejection (HTTP 422) or DataHub failure (HTTP 502),
    logs the gateway's reason and returns. Per ADR-0006, registration
    failure must not crash the engine — serving keeps working;
    routing for this engine resumes after the next successful
    registration cycle.
    """
    try:
        import httpx
    except ImportError:
        logger.warning(
            "httpx is not installed; falling back from mesh-registrar to "
            "direct DataHub emit for engine %s. Install httpx to use the "
            "gateway path.",
            name,
        )
        return

    urn = f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{name},PROD)"
    manifest = {
        "name": name,
        "verb_iri": verb,
        "input_uri": input_uri,
        "output_uri": output_uri,
        "endpoint_url": endpoint_url,
        "owner_persona": owner_persona or "",
        "domains": list(domains or []),
        "description": description,
        "verb_synonyms": list(verb_synonyms or []),
        "verb_anti_synonyms": list(verb_anti_synonyms or []),
        "cost_class": cost_class,
        "requires_human_approval": requires_human_approval,
        "version": version,
        "openapi_schema": json.dumps(openapi_schema) if openapi_schema else None,
        "provider": provider,
        "timeout_s": timeout_s,
    }

    # v0.2 SDK retry semantics per ADR-0006 §Addendum §SDK side:
    #   - 200 → success, return immediately.
    #   - 422 (Contract D) → permanent rejection, return without retry
    #     (the ontology has to be fixed first; retrying won't help).
    #   - 5xx (saga compensated) → retry-safe; the substrate is clean,
    #     a fresh attempt will run cleanly. Bounded retry within
    #     lifespan startup budget.
    #   - exhausted retries / unreachable → log loudly and return
    #     without re-raising. The engine keeps serving; the existing
    #     probe discipline (tests/routing/test_resolve_instance_probes.py)
    #     catches "engine up but unregistered" as a named alarm so the
    #     failure mode has a name and a runbook, not a mystery.
    sdk_max_attempts = int(os.getenv("MESH_REGISTRAR_SDK_MAX_ATTEMPTS", "4"))
    sdk_initial_backoff = float(os.getenv("MESH_REGISTRAR_SDK_INITIAL_BACKOFF_S", "0.5"))
    sdk_max_backoff = float(os.getenv("MESH_REGISTRAR_SDK_MAX_BACKOFF_S", "4.0"))

    backoff = sdk_initial_backoff
    last_exc: Optional[Exception] = None
    last_status: Optional[int] = None
    last_body: Optional[str] = None
    for attempt in range(1, sdk_max_attempts + 1):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{registrar_url}/v1/register", json=manifest)
            last_status = resp.status_code
            last_body = resp.text[:500]

            if resp.status_code == 200:
                logger.info(
                    "✅ Registered engine %s via mesh-registrar v0.2 (%s -> %s) "
                    "attempt=%d",
                    urn, input_uri, output_uri, attempt,
                )
                return
            if resp.status_code == 422:
                # Contract D rejection — permanent. No point retrying
                # against the same ontology state.
                logger.warning(
                    "⚠️ mesh-registrar rejected engine %s (Contract D): %s. "
                    "Engine will keep serving; run the canonical ontology "
                    "ingest then redeploy to retry.",
                    urn, last_body,
                )
                return
            if 500 <= resp.status_code < 600:
                # Saga compensated — retry-safe per v0.2 contract.
                if attempt < sdk_max_attempts:
                    logger.warning(
                        "⚠️ mesh-registrar returned HTTP %d for engine %s "
                        "(attempt %d/%d); retrying in %.2fs. Body: %s",
                        resp.status_code, urn, attempt, sdk_max_attempts,
                        backoff, last_body,
                    )
                    import time as _t
                    _t.sleep(backoff)
                    backoff = min(backoff * 2, sdk_max_backoff)
                    continue
                # Fall through to the post-loop "exhausted" log.
                break
            # Other status codes are unexpected (3xx?). Log and stop.
            logger.warning(
                "⚠️ mesh-registrar returned unexpected HTTP %d for engine "
                "%s: %s. Not retrying.",
                resp.status_code, urn, last_body,
            )
            return
        except Exception as e:  # noqa: BLE001 — ADR-0006: do not crash the engine
            last_exc = e
            if attempt < sdk_max_attempts:
                logger.warning(
                    "⚠️ mesh-registrar at %s unreachable for engine %s "
                    "(attempt %d/%d): %s. Retrying in %.2fs.",
                    registrar_url, urn, attempt, sdk_max_attempts, e, backoff,
                )
                import time as _t
                _t.sleep(backoff)
                backoff = min(backoff * 2, sdk_max_backoff)
                continue
            break

    # Exhausted. Per ADR-0006 §Addendum §SDK side: log loudly and let
    # the engine run unregistered. The existing probe discipline catches
    # this as "engine up but unregistered" — a named alarm with a
    # runbook, not a mystery.
    logger.error(
        "❌ mesh-registrar v0.2 retries EXHAUSTED for engine %s (%d attempts). "
        "Last status=%s, last_body=%s, last_exc=%s. Engine will keep serving "
        "but its verbs will NOT route until a successful re-registration on "
        "next deploy or manual probe. This is a named alarm — see "
        "tests/routing/test_resolve_instance_probes.py for the postcondition "
        "test that catches 'engine up but unregistered' downstream.",
        urn, sdk_max_attempts, last_status, last_body, last_exc,
    )


def register_engine_to_mesh(
    *,
    name: str,
    description: str,
    verb: str,
    input_uri: str,
    output_uri: str,
    endpoint_url: str,
    verb_synonyms: Optional[Iterable[str]] = None,
    verb_anti_synonyms: Optional[Iterable[str]] = None,
    owner_persona: Optional[str] = None,
    domains: Optional[Iterable[str]] = None,
    cost_class: str = "medium",
    requires_human_approval: bool = False,
    version: str = "0.1.0",
    openapi_schema: Optional[dict] = None,
    provider: Optional[str] = None,
    timeout_s: Optional[float] = None,
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

    # mesh-registrar gateway dispatch — opt-in via MESH_REGISTRAR_URL.
    # When set, the engine POSTs a small manifest to the gateway and the
    # gateway handles Contract D validation + DataHub emit + idempotency
    # centrally. Engine doesn't need acryl-datahub or DataHub protocol
    # knowledge. Returns early on success — the legacy DataHub path
    # below is only used when the gateway isn't configured.
    registrar_url = os.getenv("MESH_REGISTRAR_URL", "").rstrip("/")
    if registrar_url:
        _emit_to_registrar(
            registrar_url=registrar_url,
            name=name, description=description,
            verb=verb, input_uri=input_uri, output_uri=output_uri,
            endpoint_url=endpoint_url,
            verb_synonyms=verb_synonyms, verb_anti_synonyms=verb_anti_synonyms,
            owner_persona=owner_persona, domains=domains,
            cost_class=cost_class,
            requires_human_approval=requires_human_approval,
            version=version, openapi_schema=openapi_schema,
            provider=provider, timeout_s=timeout_s,
        )
        return

    gms_url = os.getenv("DATAHUB_GMS_URL")
    token = os.getenv("DATAHUB_TOKEN", "")

    if not gms_url:
        logger.warning(
            "MESH_REGISTER_ON_STARTUP=true but neither MESH_REGISTRAR_URL "
            "nor DATAHUB_GMS_URL set; skipping registration for engine %s. "
            "The engine will keep serving but won't be reachable via "
            "/find_tool.",
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
        # Anti-synonyms: NL phrases that should REPEL this verb in the
        # /search_predicates re-rank. See ADR-0008 follow-up — addresses
        # the confidently-wrong routing pattern where verb_synonyms alone
        # can't disambiguate semantically-adjacent intents (e.g.
        # traceLineage scoring 0.71 for "what tables do you have").
        "mesh_verb_anti_synonyms":      json.dumps(list(verb_anti_synonyms or [])),
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
        emitter = DatahubRestEmitter(gms_server=_gms_server_base(gms_url), token=token)
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


def register_presentation_to_mesh(
    *,
    name: str,
    description: str,
    subject_uri: str,
    object_uri: str,
    archetype: str,
    expected_fields: Optional[Iterable[str]] = None,
    persona_fit: Optional[Iterable[str]] = None,
    domain_fit: Optional[Iterable[str]] = None,
    version: str = "0.1.0",
) -> None:
    """Emit a DataHub MCP describing a presentation capability as a
    ``(subject_uri, mesh:rendersAs, object_uri)`` triple.

    Per ADR-0017, Engine F (and any other component that knows how to
    render a shape) advertises its capabilities through this helper.
    The triple flows into the same Weaviate Predicate collection as
    engine verbs (ADR-0004) and is found by ``/search_predicates``
    when ``cortex-bff`` calls ``/render_ui`` with an ``output_uri``.

    The wire shape matches ``register_engine_to_mesh`` byte-for-byte
    except:

    - ``mesh_tool_kind`` is ``"Presentation"`` instead of ``"Engine"``.
    - The semantic fields name an SPO triple, not a verb edge:
      ``mesh_subject_uri``, ``mesh_predicate_iri`` (always
      ``mesh:rendersAs``), ``mesh_object_uri``.
    - ``mesh_archetype`` carries the BAML archetype enum string the
      renderer expects (e.g. ``"KNOWLEDGE_DOCUMENT"``).
    - ``mesh_expected_fields`` is a JSON-encoded list of fields the
      archetype expects to find in ``structured_data``.
    - There is no ``endpoint_url`` — the presentation isn't a callable
      peer, it's a capability advertised by Engine F.

    Same opt-in env var (``MESH_REGISTER_ON_STARTUP``) and same
    no-crash failure mode as the engine helper. If registration is
    skipped, Engine F's ``/render_ui`` falls back to the legacy
    BAML ``DesignUI`` path automatically (per ADR-0017 §6) and the
    presentation is simply not discoverable via the predicate graph
    until the next successful emit.

    Parameters
    ----------
    name : str
        Unique slug for the URN. Convention:
        ``presentation_<archetype_lower>_for_<subject_slug>``.
    description : str
        Free-form, written to the DataHub aspect ``description`` field.
    subject_uri : str
        The output-shape IRI this presentation can render
        (e.g. ``mesh:OwnershipFact``). Must be one of the IRIs declared
        by an engine's ``output_uri`` for the lookup to fire.
    object_uri : str
        The archetype IRI (e.g. ``mesh:KnowledgeDocument``). See
        :class:`iagent_mesh.shapes.Archetypes`.
    archetype : str
        The BAML archetype enum string Engine F's renderer uses
        (e.g. ``"KNOWLEDGE_DOCUMENT"``). Resolves ``object_uri`` back
        to the BAML-side identifier.
    expected_fields : Iterable[str], optional
        Field names the archetype expects to find in
        ``structured_data``. Used by Engine F's strict-validation mode
        (ADR-0017 open item) and by future schema validators.
    persona_fit : Iterable[str], optional
        User personas this presentation is well-suited for. Ranks higher
        when ``/search_predicates`` is called with a matching
        ``persona_hint``.
    domain_fit : Iterable[str], optional
        Domains this presentation is well-suited for. Ranks higher when
        ``/search_predicates`` is called with a matching ``domain_hint``.
    version : str
        Tool-version stamp; same field as engine registrations.
    """
    if os.getenv("MESH_REGISTER_ON_STARTUP", "false").lower() not in _TRUTHY:
        logger.info(
            "Skipping DataHub registration for presentation %s "
            "(set MESH_REGISTER_ON_STARTUP=true to enable)",
            name,
        )
        return

    # Presentations don't currently go through the mesh-registrar
    # gateway — the gateway's RegistrationManifest only models verb
    # edges (input_uri/output_uri pair); the (subject, mesh:rendersAs,
    # archetype) triple shape isn't supported yet. When the gateway
    # adds presentation support, mirror the dispatch above.
    if os.getenv("MESH_REGISTRAR_URL"):
        logger.info(
            "MESH_REGISTRAR_URL set but presentation %s won't go through "
            "the gateway (presentation triples aren't yet supported by "
            "RegistrationManifest); using direct DataHub emit.",
            name,
        )

    gms_url = os.getenv("DATAHUB_GMS_URL")
    token = os.getenv("DATAHUB_TOKEN", "")

    if not gms_url:
        logger.warning(
            "MESH_REGISTER_ON_STARTUP=true but DATAHUB_GMS_URL not set; "
            "skipping registration for presentation %s. /render_ui will "
            "fall back to legacy BAML DesignUI until the next successful "
            "registration cycle.",
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
            "presentation %s. Install acryl-datahub in the image to "
            "enable.",
            name,
        )
        return

    urn = f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{name},PROD)"
    namespace_authority = "platform" if subject_uri.startswith("mesh:") else "domain"

    custom_props = {
        # Marker for doc-tools' filter — same key as engine registrations.
        "mesh_is_registration":         "true",
        "mesh_tool_kind":               _TOOL_KIND_PRESENTATION,
        # SPO triple identity. Per ADR-0017 the predicate is constant.
        "mesh_subject_uri":             subject_uri,
        "mesh_predicate_iri":           _PREDICATE_RENDERS_AS,
        "mesh_object_uri":              object_uri,
        # Renderer-side metadata.
        "mesh_archetype":               archetype,
        "mesh_expected_fields":         json.dumps(list(expected_fields or [])),
        "mesh_namespace_authority":     namespace_authority,
        # Scoping. Same JSON-encoded list convention as engine
        # registrations so /search_predicates handles both uniformly.
        "mesh_persona_fit":             json.dumps(list(persona_fit or [])),
        "mesh_domain_fit":              json.dumps(list(domain_fit or [])),
        # Versioning.
        "mesh_sdk_version":             "0.0.0",
        "mesh_tool_version":            version,
    }

    props = MLModelPropertiesClass(
        description=description,
        customProperties=custom_props,
    )

    try:
        emitter = DatahubRestEmitter(gms_server=_gms_server_base(gms_url), token=token)
        mcp = MetadataChangeProposalWrapper(entityUrn=urn, aspect=props)
        emitter.emit(mcp)
        logger.info(
            "✅ Registered presentation %s as (%s -> %s -> %s)",
            urn,
            subject_uri,
            _PREDICATE_RENDERS_AS,
            object_uri,
        )
    except Exception as e:  # noqa: BLE001  -- ADR-0006: do not crash the engine
        logger.warning(
            "⚠️ Failed to register presentation %s to DataHub: %s. "
            "Engine F /render_ui will fall back to legacy BAML DesignUI "
            "for this shape until the next successful registration cycle.",
            urn,
            e,
        )
