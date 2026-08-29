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

# The ONE authenticated registration transport (SDK v0.3.0). Carries the retry semantics
# that used to live in this file — see the note at the call site for why the move went this
# direction and not the other.
from iagent_mesh.registration_transport import register_with_mesh
from typing import Iterable, Optional

# NOT a bare getLogger. uvicorn replaces the root handler at startup, so a logger
# that relies on propagation is silently DROPPED — and this module is the one that
# announces whether a registration reached the gateway or fell back to audit-only
# emit. On 2026-08-21 engine-f registered ten presentations through the gateway and
# printed nothing at all: the three-way fallback classification, built so an
# operator could tell "ship the image" from "fix the registration" from "check the
# network", discriminated perfectly into a log nobody could read.
#
# The engines had each hand-rolled this repair on their OWN named logger and
# neither reached here, the shared module they both delegate to.
try:
    from agent_fleet.utils.uvicorn_safe_logging import ensure_stdout_logger
except ImportError:  # flattened image layout (/app/utils/...)
    from utils.uvicorn_safe_logging import ensure_stdout_logger  # type: ignore

logger = ensure_stdout_logger("mesh_registration")

#: Scope stamp for capabilities that are the SYSTEM DEFAULTS rather than any one
#: surface's menu. Shared with capability_registry.menu_for(), which refuses it
#: as a caller identity — a provider is not a frontend.
SYSTEM_DEFAULT_FRONTEND_ID = "__system_default__"

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



def engine_mint(*, client_id: str, secret_env: str):
    """Return a mint callable for ONE engine's registration identity.

    IDENTITY IS AN ARGUMENT. Both the client id and the env var holding its secret are named
    BY THE CALLER, at the caller's own site. A shared helper that resolved the identity itself —
    from the component name, or from a conventional env var — would be a general name over
    specific behaviour, which is exactly how `mint_service_token()` came to read
    REVIEW_STARTER_CLIENT_ID and made the supervisor dispatch as the review starter.

    Returned lazily, not minted here: the token is obtained per registration ATTEMPT, so a
    Keycloak blip at boot is retried by the transport rather than baked into a dead closure.
    """
    def _mint() -> str:
        from iagent_mesh.service_identity import mint_token
        return mint_token(client_id=client_id, client_secret=os.environ[secret_env])
    return _mint


def _emit_to_registrar(
    *,
    mint=None,
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
    slots: Optional[list] = None,
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
        # WHAT THE VERB TAKES. Sent as a typed LIST, not a JSON string: this is an API
        # boundary and the gateway should be able to validate what it is handed. The
        # string form is a NEO4J storage constraint (a property may hold primitives or
        # arrays of primitives, never maps) and belongs at the Neo4j write, not smeared
        # up into every engine that registers. `openapi_schema` above stringifies at the
        # client, which is the older habit and the reason nothing can validate it.
        "slots": list(slots or []),
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
    # ONE AUTHENTICATED TRANSPORT (2026-08-10, SDK v0.3.0).
    #
    # The retry machinery that stood here — 422 permanent (Contract D), 5xx bounded
    # exponential backoff, env-tunable — was NOT deleted. It MOVED to
    # `iagent_mesh.registration_transport` and this call consumes it.
    #
    # THE DIRECTION WAS NEARLY REVERSED, and the enumeration is what caught it: the SDK's own
    # registration had NO retry at all (one POST, raise on any non-200), so the natural-sounding
    # "platform binds the SDK" would have DELETED ADR-0006's ruled semantics in the name of
    # having one implementation. The richer implementation moved; the poorer one retired.
    #
    # ONE SEAM FOR AUTH, N BODIES FOR CONTENT. The manifest above is this module's own; the
    # SDK lifespan builds a different one. Only the POST — where the credential attaches and a
    # divergence would be invisible — is shared.
    #
    # IDENTITY IS AN ARGUMENT: `mint` comes from the caller and is never read from ambient env
    # here. A helper with a general name reading one service's credentials is exactly how the
    # supervisor came to dispatch as the review starter.
    result = register_with_mesh(
        registrar_url, manifest, component=(urn or name), mint=mint, timeout=30.0,
    )
    if result.registered:
        logger.info("✅ %s", result.announcement(urn or name))
        return

    # LOUD UNREGISTERED, WITH THE CAUSE NAMED. "mint failed" and "registrar refused" produce
    # ONE symptom — the engine's verbs absent from routing — so the message is the only thing
    # that can separate them, and an operator who cannot spends an incident's first hour
    # learning which side of the call broke.
    #
    # Running unregistered is safe by a ROUTING-LAYER FACT, not optimism: routing is
    # conjunctive, so a verb that never registered simply never routes. The engine is degraded
    # and VISIBLE, never corrupt.
    logger.error(
        "❌ %s — engine keeps serving but its verbs will NOT route until a successful "
        "re-registration. This is a named alarm; see "
        "tests/routing/test_resolve_instance_probes.py for the postcondition test.",
        result.announcement(urn or name),
    )


def register_engine_to_mesh(
    *,
    mint=None,
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
    slots: Optional[list] = None,
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
            mint=mint,
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
            # THE GATEWAY IS THE LIVE PATH. Omitting this here while setting `mesh_slots`
            # in the DataHub fallback below is precisely the defect this repo already
            # measured once: presentations emitted direct-to-DataHub while the
            # DataHub->substrate materialiser was RETIRED, so 11 URNs reached 0 rows.
            slots=slots,
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
        # ORPHAN FIELD — projected as a string and read by NOTHING. engine-p, the largest
        # registrant, passes it ZERO times, so its registrations carry "{}". It is not a
        # derived artifact of a per-verb Pydantic model either: MeshTool declares only
        # semantics (verb, input_uri, output_uri, synonyms) and carries no input model, and
        # engine-p's MeasureRequest types the ENVELOPE (`state_ref`, `params: dict`) rather
        # than any verb's arguments. Left in place rather than deleted — removing it is a
        # doc-tools projection change that should not ride the slots work.
        # DO NOT PUT ROUTING SEMANTICS HERE. See `mesh_slots` below: a passthrough nobody
        # consumes is the worst possible host for the declaration everything downstream will.
        "mesh_openapi_schema":          json.dumps(openapi_schema or {}),
        # WHAT THE VERB TAKES — the third thing a registration must say, beside what it is
        # ABOUT (input_uri) and what it PRODUCES (output_uri). Its absence is why the router
        # cannot know a slot is missing (it only knows nothing cleared threshold) and why a
        # spoken parameter is dropped in silence on every verb that has a default for it.
        #
        # Each record: {name, kind, type, required, values?, default?}, kind being one of
        # spoken-mandatory | spoken-optional | handle | ceremony. The KIND is the one fact no
        # type system carries — `baseline_state: str` and `site_id: str` are the same shape
        # with opposite provenance.
        #
        # ADDITIVE, per the local idiom: absent means [] and means today's behaviour, exactly
        # as `mesh_domains` absent means domain-agnostic.
        #
        # NOT YET PROJECTED. doc-tools' aitool_linker.py builds the Neo4j edge from an
        # explicit ALLOWLIST, so this key is silently dropped there until that repo adds a row
        # for it — no error, no warning. Declarations therefore sit dark rather than half-lit,
        # which is the intended landing order.
        "mesh_slots":                   json.dumps(slots or []),
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


#: Namespaces the compact `prefix:Local` forms expand against. Kept beside the registration
#: helpers because THIS is where the wire form is decided; the read side folds both forms via
#: `capabilities.canonical_iri_for_lookup`, but a producer must pick one and it must be the
#: one the graph stores.
_IRI_PREFIXES = {
    "mesh:": "http://invincible-agent/mesh#",
    "idp:": "http://invincible-agent/idp#",
}


def _expand_mesh_iri(iri: str) -> str:
    """`mesh:ChartWidget` -> `http://invincible-agent/mesh#ChartWidget`.

    Idempotent: an already-full IRI is returned unchanged, so a caller that already passes
    full form (every engine registration does) is unaffected. An unknown prefix is left
    alone rather than guessed at — inventing a namespace would fabricate the same phantom
    class Contract D exists to refuse.
    """
    s = (iri or "").strip()
    for pfx, ns in _IRI_PREFIXES.items():
        if s.startswith(pfx):
            return ns + s[len(pfx):]
    return s



# Field names an OLD registrar (one that predates the Presentation species) will
# report as missing: it ignores the unknown presentation fields, then refuses
# because the verb-shaped fields it still requires are absent. This is the
# SIGNATURE that separates "ship the image" from "fix the registration" — the
# two 422 futures whose repairs are opposite.
_STALE_REGISTRAR_FIELDS = ("verb_iri", "input_uri", "output_uri", "endpoint_url")


def _classify_gateway_refusal(status_code, reason: str):
    """Name the reason CLASS for a failed gateway registration.

    Returns ``(reason_class, detail)``. One symptom — rendersAs stays 0 — with
    three different repairs, so the class is the only thing that tells an
    operator which one they are in.
    """
    text = (reason or "").lower()
    if status_code == 422:
        # THE SIGNATURE IS "REQUIRED", NOT "MENTIONED". A Contract D refusal
        # naming output_uri ("output_uri not found as :OntologyClass") contains a
        # stale-image field name while being the OPPOSITE diagnosis -- matching on
        # the name alone sends an operator to ship an image when the registration
        # is malformed. Caught by this classifier's own test before it shipped.
        _missing_marker = ("required" in text or "missing" in text)
        if _missing_marker and any(f in text for f in _STALE_REGISTRAR_FIELDS):
            return ("gateway-rejected-STALE-IMAGE",
                    f"the deployed registrar asked for verb-shaped fields "
                    f"({', '.join(_STALE_REGISTRAR_FIELDS)}), so it predates the "
                    f"Presentation species. REPAIR: ship the registrar image — "
                    f"direct emit will not produce a rendersAs row. Gateway said: {reason}")
        return ("gateway-rejected-REFUSED",
                f"a current gateway REFUSED this manifest (Contract D, or a malformed "
                f"presentation). REPAIR: fix the registration — direct emit only records "
                f"the same bad claim as audit. Gateway said: {reason}")
    return ("gateway-unreachable",
            f"transport or credential failure (status={status_code}). REPAIR: network or "
            f"mint. Direct emit is a real stopgap here. Detail: {reason}")


def _emit_presentation_to_registrar(
    *,
    registrar_url: str,
    name: str,
    description: str,
    subject_uri: str,
    object_uri: str,
    archetype: str,
    expected_fields: list,
    persona_fit: list,
    domain_fit: list,
    version: str,
    mint=None,
    frontend_id: Optional[str] = None,
    recomputes: Optional[bool] = None,
):
    """POST a Presentation manifest to the mesh-registrar gateway.

    Returns ``True`` on success, else ``(reason_class, detail)``.

    Mirrors ``_emit_to_registrar`` and shares the SAME transport seam
    (``register_with_mesh``) so the credential attaches in exactly one place.
    The manifest carries the SPO triple; the gateway normalises it onto the
    verb-edge shape and Contract-D-checks both ends.

    NOTE the IRI positions, which are inherited and not invented: the predicate
    stays COMPACT and subject/object stay FULL, matching every existing row.
    """
    try:
        from iagent_mesh.registration_transport import register_with_mesh  # noqa: PLC0415
    except ImportError as exc:
        return ("gateway-unreachable",
                f"iagent_mesh transport not importable: {exc}")

    manifest = {
        "name": name,
        "tool_kind": "Presentation",
        "subject_uri": _expand_mesh_iri(subject_uri),
        "predicate_iri": _PREDICATE_RENDERS_AS,
        "object_uri": _expand_mesh_iri(object_uri),
        "archetype": archetype,
        "expected_fields": list(expected_fields),
        # THE SYSTEM DEFAULTS ARE NOT A FRONTEND'S MENU. Engine F advertises the
        # UNIVERSAL FALLBACK -- the population `default-menu` provenance refers to
        # -- not one surface's private capabilities. Stamping these "engine-f"
        # made a PROVIDER look like a registered SURFACE, and left a small
        # honesty hole: a caller sending frontend_id="engine-f" would get
        # `presentation_source: "registered"` against defaults it never
        # registered, upgrading its own provenance by naming a provider.
        #
        # The sentinel is deliberately un-typeable as a real frontend id and is
        # REFUSED by menu_for(), so these rows reach callers only through the
        # union, labelled `default-menu`, which is what they are.
        # IDENTITY IS AN ARGUMENT. A caller that HAS a declared identity passes it;
        # only the system-default provider falls through to the sentinel. Reading
        # this from ambient env for every caller is how a provider's name ended up
        # in a frontend's field, and how cortex-bff would have stamped its own
        # process identity onto every UI behind it.
        "frontend_id": (frontend_id or "").strip()
                       or os.getenv("MESH_FRONTEND_ID", SYSTEM_DEFAULT_FRONTEND_ID),
        "owner_persona": (persona_fit[0] if persona_fit else "ANY"),
        "domains": list(domain_fit),
        "description": description,
        "version": version,
    }
    # TRI-STATE, END TO END. Only a DECLARED value travels; None never becomes
    # False on the wire, or the manifest would assert "not a live view" about a
    # component that never said (ADR-0042 Ruling 9's honest default).
    if recomputes is not None:
        manifest["recomputes"] = bool(recomputes)
    try:
        result = register_with_mesh(
            registrar_url, manifest, component=name, mint=mint, timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        return ("gateway-unreachable", f"{type(exc).__name__}: {exc}")

    if getattr(result, "registered", False):
        return True
    return _classify_gateway_refusal(
        getattr(result, "status_code", None), getattr(result, "reason", "")
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
    mint=None,
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

    # ── THE GATEWAY IS THE WRITER. Direct emit is the FALLBACK. ──────────────
    #
    # RegistrationManifest learned the Presentation species (tool_kind
    # discriminant, SPO triple normalised onto the verb-edge shape), so this
    # mirrors the engine dispatch above. Per ADR-0006 §Addendum the gateway is
    # SOLE WRITER of predicate edges into Neo4j + Weaviate: a presentation that
    # goes through it lands a rendersAs row, and one that does not lands an
    # audit record in DataHub and nothing else.
    #
    # The fallback exists ONLY so deploy ordering does not matter — an engine-f
    # that boots before the registrar image ships still registers SOMETHING
    # rather than failing. It is not a second writer, and it must never be
    # mistaken for one.
    #
    # ═══ RETIREMENT TRIGGER — this branch is scheduled for DELETION ═══
    # Condition: every deployed mesh-registrar advertises "Presentation" in
    # `manifest_species` on /health. Check:
    #     kubectl -n <ns> exec deploy/iagent-mesh-registrar --     #         python -c "import urllib.request,json;     #         print(json.load(urllib.request.urlopen('http://localhost:8090/health'))['manifest_species'])"
    # When that lists 'Presentation' fleet-wide, delete this fallback branch and
    # the `mesh_registration_via` property with it.
    #
    # THIS TRIGGER USED TO KEY ON A LOG LINE ("VIA GATEWAY") and was DEAD ON
    # ARRIVAL: this module's logger propagated to a root that uvicorn had
    # replaced, so engine-f registered ten presentations through the gateway and
    # printed nothing — the condition could not be observed even when it was
    # true. A condition that cannot be observed is not a condition. It now reads
    # a fact the server states about itself, which cannot go silent the same way
    # and whose ABSENCE is as meaningful as its content.
    #
    # WHY A TRIGGER AND NOT A TODO: ADR-0006 preserved doc-tools' linker as a
    # manual fallback, its DataHub token went stale, and it spent months
    # returning SUCCESS while writing nothing — a dead path dressed as a working
    # one. A fallback with no removal condition becomes that.
    registrar_url = os.getenv("MESH_REGISTRAR_URL")
    if registrar_url:
        outcome = _emit_presentation_to_registrar(
            registrar_url=registrar_url,
            name=name,
            description=description,
            subject_uri=subject_uri,
            object_uri=object_uri,
            archetype=archetype,
            expected_fields=list(expected_fields or []),
            persona_fit=list(persona_fit or []),
            domain_fit=list(domain_fit or []),
            version=version,
            mint=mint,
        )
        if outcome is True:
            logger.info(
                "✅ presentation %s registered VIA GATEWAY — rendersAs row is the "
                "gateway's to write.", name,
            )
            return
        # FALLING BACK. Loud, and with the REASON CLASS named, because the two
        # classes have OPPOSITE repairs and one symptom (rendersAs stays 0):
        #
        #   gateway-rejected-STALE-IMAGE : the deployed registrar predates the
        #       Presentation species and is asking for verb-shaped fields.
        #       REPAIR: ship the registrar image. Direct emit will NOT help.
        #   gateway-rejected-REFUSED     : a current gateway refused this
        #       manifest — Contract D, or a genuinely malformed presentation.
        #       REPAIR: fix the registration. Direct emit will NOT help either;
        #       it only records the same bad claim as audit.
        #   gateway-unreachable          : transport/mint failure. REPAIR: the
        #       network or the credential. Direct emit is a real stopgap here.
        logger.warning(
            "⚠️  presentation %s FELL BACK to direct DataHub emit — reason class: %s. "
            "The fallback writes an AUDIT RECORD ONLY: no rendersAs row reaches "
            "Weaviate, so this presentation stays undiscoverable via /search_predicates "
            "until the gateway accepts it. Detail: %s",
            name, outcome[0], outcome[1],
        )
        _fallback_reason = outcome[0]
    else:
        _fallback_reason = "no-registrar-url"

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

    # ── THE WIRE CARRIES FULL IRIs (2026-08-21) ───────────────────────────────────────
    # doc-tools' linker materializes a registration by MATCHing both triple endpoints as
    # :OntologyClass nodes, and those nodes hold FULL IRIs. Engine registrations already
    # satisfy that because their callers pass full form
    # (`http://invincible-agent/idp#Dataset`); PRESENTATION_CAPABILITIES uses COMPACT form
    # (`mesh:OwnershipFact`), so a presentation's MATCH missed on BOTH ends and the row was
    # never created. Measured against the live substrate 2026-08-21.
    #
    # Expanded HERE, at the emit boundary, rather than by rewriting the table: the compact
    # form is the in-repo vocabulary and `canonical_iri_for_lookup` exists to fold both, but
    # THE WIRE HAS ONE CONVENTION and it is the one the linker reads. Fixing it at the
    # boundary keeps presentations byte-comparable with engine registrations instead of
    # asking the linker to compensate for a producer that speaks differently.
    subject_uri = _expand_mesh_iri(subject_uri)
    object_uri = _expand_mesh_iri(object_uri)

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
        # THE RECORD ADMITS WHAT IT IS. Reaching this emit means the gateway did
        # not accept the registration, so this row is an AUDIT RECORD and not a
        # materialised capability: no rendersAs row exists in Weaviate for it and
        # /search_predicates cannot find it. Stamped so a reader of DataHub can
        # tell a presentation that ROUTES from one that merely happened, without
        # cross-referencing Weaviate to find out.
        "mesh_registration_via":        f"direct-fallback({_fallback_reason})",
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
