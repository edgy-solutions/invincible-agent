"""
Engine A — Restate + Smolagents Durable Analyst Microservice

A FastAPI server backed by the Restate SDK for durable execution.
Before running the smolagents CodeAgent, the handler calls Engine O
(the ontology reasoner) to resolve the user's intent into a canonical
IOF/MIMOSA URI and suggested dbt models. This semantic context is then
passed into the agent so it knows which database tables to query.

Also contains the BPMNWorkflowRunner — a Restate Workflow that processes
BPMN tasks sequentially.  ServiceTasks execute via ``ctx.run()``;
UserTasks pause durably via ``ctx.promise().value()`` until a human
resolves them through the ``POST /workflow/{wf}/task/{tid}/approve``
endpoint.  Zero-cost waiting, crash-proof, no polling loops.

Run: uvicorn agent_fleet.restate_analyst.main:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import os

import httpx
import requests
import restate

import asyncio

# Add baml_shared to Python path so we can import telemetry
_CURRENT_FILE = Path(__file__).resolve()
try:
    _REPO_ROOT = _CURRENT_FILE.parents[2]
    _BAML_SHARED_PATH = _REPO_ROOT / "baml_shared"
    if _BAML_SHARED_PATH.exists() and str(_BAML_SHARED_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_SHARED_PATH))
except IndexError:
    pass

try:
    from telemetry import safe_observe, safe_update_observation
except ImportError:
    def safe_observe(**kwargs):
        def decorator(func):
            return func
        return decorator
    def safe_update_observation(input_data=None, output_data=None):
        pass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from restate import Context, ObjectContext, Service, VirtualObject, Workflow, WorkflowContext, WorkflowSharedContext

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path for the generated BAML types.
# In CNB containers, baml_client is copied locally — this is only for dev.
# ---------------------------------------------------------------------------
try:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
    if str(_BAML_CLIENT_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_CLIENT_PATH))
except IndexError:
    pass  # Running in CNB container — baml_client is already in /workspace/

from baml_client.types import AgentResponse, AgentStatus, AgentTask, BPMNInterviewState, TopologyUI  # noqa: E402
from baml_client import b  # noqa: E402

# Initialize runtime BAML configuration logic
try:
    from llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    # Fallback for local development
    try:
        from agent_fleet.llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass

# Smolagents imports — only used inside the Restate handler.
# ---------------------------------------------------------------------------
from smolagents import CodeAgent, ToolCallingAgent
try:
    from llm_utils import get_smolagent_model
except ImportError:
    from agent_fleet.llm_utils import get_smolagent_model


# Phase 3 source attribution: parse_datahub_urn lives in
# restate_analyst/urn_utils.py so unit tests can import it without
# pulling smolagents / Restate. See tests/test_engine_a_source_attribution.py.
try:
    from urn_utils import parse_datahub_urn
except ImportError:
    from agent_fleet.restate_analyst.urn_utils import parse_datahub_urn

# ---------------------------------------------------------------------------
# Fleet-standard utilities — memoized Weaviate client + shared mem0 singleton.
# The Memory object and its Weaviate-backed adapter are built once per pod,
# lazily, on a worker thread (see utils.mem0_utils). Previously this whole
# stack was rebuilt inside the async analyze() handler on every request,
# which blocked the event loop with sync gRPC and tripped the k8s readiness
# probe.
# ---------------------------------------------------------------------------
try:
    from utils.weaviate_utils import get_weaviate_client
    from utils.mem0_utils import get_mem0_memory
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import get_weaviate_client
        from agent_fleet.utils.mem0_utils import get_mem0_memory
    except ImportError:
        # Fallback for flat layout in container
        from weaviate_utils import get_weaviate_client
        from mem0_utils import get_mem0_memory


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ONTOLOGY_RESOLVE_URL = os.getenv(
    "ONTOLOGY_RESOLVE_URL",
    "http://iagent-engine-o:8084/resolve",
)
ONTOLOGY_TIMEOUT = 30  # seconds — ontology resolution is fast
AGENT_HTTP_TIMEOUT = int(os.getenv("AGENT_HTTP_TIMEOUT", "120"))
RESTATE_INGRESS_URL = os.getenv(
    "RESTATE_INGRESS_URL",
    "http://localhost:8081/restate",
)

# ---------------------------------------------------------------------------
# Per-verb prompt blocks (ADR-0017)
# ---------------------------------------------------------------------------
# Engine A advertises one verb per question shape (see registrations in
# lifespan() below). The router picks a verb based on Weaviate hybrid
# search over the predicate edges; the picked verb's IRI is passed back
# to /analyze in the request body as ``routed_verb_iri``. This handler
# selects the matching prompt block from the dict below, which carries:
#
#   - ``task_framing``: a short paragraph telling the agent what kind of
#     question this verb handles and what shape of answer to produce.
#   - ``reasoning_patterns``: only the reasoning patterns relevant to
#     this verb. Recursive lineage lives on lineage/impact verbs;
#     cross-feature predicate composability lives on tag/impact verbs;
#     simple lookups (ownership, schema, freshness) get neither, which
#     prevents over-recursion and over-search noise on those questions.
#   - ``output_uri``: the literal IRI the agent must echo back in
#     ``final_answer()`` so Engine F's /render_ui can do a deterministic
#     predicate-graph lookup for the presentation (ADR-0017 §6).
#
# When ``routed_verb_iri`` is missing or unknown, falls back to the
# generic ``mesh:analyzeWithCodeAgent`` block which retains the
# pre-ADR-0017 behavior (both reasoning patterns active, generic
# output_uri).

_REASONING_RECURSIVE_LINEAGE = (
    "REASONING PATTERN — RECURSIVE LINEAGE TRAVERSAL.\n"
    "When tracing the SOURCE OF TRUTH, the RAW source, what FEEDS an "
    "asset, or any phrasing that implies tracing all the way back (or "
    "all the way forward), do not stop at the first hop. The "
    "search_datahub response gives upstream and downstream names for "
    "the directly-matched asset only. To trace a full chain you MUST "
    "call search_datahub recursively on each name that appears in the "
    "upstream/downstream lines, walking the graph until you reach a "
    "node whose upstream list is empty (for source-of-truth questions) "
    "or downstream list is empty (for ultimate-consumer questions). "
    "Then report the full path. If the asset has 3 layers of upstream, "
    "you make 3 follow-up search_datahub calls — not 0, not 1.\n"
    "PLATFORM-NAMED QUESTIONS ARE TRAVERSAL QUESTIONS. When the user "
    "names a specific platform, database, or warehouse ('which <platform> "
    "tables does X use'), the immediate upstream datasets are usually NOT "
    "the answer — a BI tool's own virtual datasets sit between a "
    "dashboard and the physical tables. Every result line carries "
    "`platform=` (and lineage entries render as TYPE(platform):name): "
    "keep walking upstream until the platform matches the one the user "
    "named, or the upstream list is empty. Report ONLY datasets whose "
    "platform= the tool actually showed as matching — if the walk ends "
    "without reaching that platform, say so; never label a dataset with "
    "a platform the tool did not return.\n\n"
)

_REASONING_CROSS_FEATURE = (
    "REASONING PATTERN — CROSS-FEATURE PREDICATES.\n"
    "When the user's question requires assets to satisfy TWO OR MORE "
    "conditions simultaneously (e.g. \"tagged X AND consumed by Y\", "
    "\"in domain D AND owned by alice\", \"PII AND no owner\"), do not "
    "assume the search returns nothing just because a single search "
    "term doesn't surface the joint result. The search_datahub "
    "response carries multiple fields per asset on a single entry — "
    "for each search hit, inspect ALL of the fields the user's "
    "question mentions and select only those that satisfy EVERY "
    "condition. If a question mentions a tag AND a downstream "
    "relationship, search by the broader of the two, then check each "
    "result's other field. Do not give up after one search; do not "
    "say \"none found\" when you have not actually applied the second "
    "condition to the candidates the first search returned.\n\n"
)

_VERB_PROMPT_BLOCKS = {
    "mesh:lookupOwnership": {
        "task_framing": (
            "VERB SCOPE: mesh:lookupOwnership.\n"
            "Your task is to look up the OWNER of a specific named "
            "asset. Issue a single search_datahub call on the asset "
            "name and report the owner identity (email, team) plus the "
            "ownership timestamp if available. Do NOT walk lineage; do "
            "NOT inspect schema; do NOT search broadly. Stay focused "
            "on the ownership fields of the matched asset."
        ),
        "reasoning_patterns": "",
        "output_uri": "mesh:OwnershipFact",
    },
    "mesh:traceLineage": {
        "task_framing": (
            "VERB SCOPE: mesh:traceLineage.\n"
            "Your task is to TRACE THE LINEAGE of a named asset. The "
            "user wants the upstream chain (source of truth) or "
            "downstream chain (ultimate consumers). Apply the "
            "recursive-lineage-traversal pattern below — single-hop "
            "answers are insufficient when the user asks for the "
            "source or what feeds an asset."
        ),
        "reasoning_patterns": _REASONING_RECURSIVE_LINEAGE,
        "output_uri": "mesh:LineageTopology",
    },
    "mesh:assessImpact": {
        "task_framing": (
            "VERB SCOPE: mesh:assessImpact.\n"
            "Your task is to identify the BLAST RADIUS of a change to "
            "a named asset: which downstream dashboards, charts, and "
            "datasets depend on it and would break or change if it "
            "changes schema. Walk the downstream lineage and optionally "
            "filter by additional conditions the user mentions."
        ),
        "reasoning_patterns": _REASONING_RECURSIVE_LINEAGE + _REASONING_CROSS_FEATURE,
        "output_uri": "mesh:ImpactSet",
    },
    "mesh:findSchema": {
        "task_framing": (
            "VERB SCOPE: mesh:findSchema.\n"
            "Your task is to return the COLUMN SCHEMA of a named "
            "dataset: field names, data types, and field descriptions "
            "as they appear in the catalog. Do NOT read row data; do "
            "NOT walk lineage; do NOT search broadly."
        ),
        "reasoning_patterns": "",
        "output_uri": "mesh:SchemaDescription",
    },
    "mesh:checkFreshness": {
        "task_framing": (
            "VERB SCOPE: mesh:checkFreshness.\n"
            "Your task is to report the LAST UPDATED timestamp of a "
            "named dataset, compared against any SLA or staleness "
            "threshold the user mentions. Single search_datahub call, "
            "single timestamp read."
        ),
        "reasoning_patterns": "",
        "output_uri": "mesh:FreshnessReport",
    },
    "mesh:filterByTag": {
        "task_framing": (
            "VERB SCOPE: mesh:filterByTag.\n"
            "Your task is to identify assets matching a given tag, "
            "optionally composed with a secondary condition (e.g. "
            "tagged X AND exposed to a downstream dashboard, tagged Y "
            "AND owned by team Z). PII-exposure audits are the most "
            "common shape but the verb covers any tag-conditional "
            "query. Apply the cross-feature-predicate pattern below — "
            "do NOT report 'none found' until you have applied every "
            "condition to the candidates the tag search returned."
        ),
        "reasoning_patterns": _REASONING_CROSS_FEATURE,
        "output_uri": "mesh:TagFilterResult",
    },
    "mesh:describeAsset": {
        "task_framing": (
            "VERB SCOPE: mesh:describeAsset.\n"
            "Your task is to return a structured PROFILE of a named "
            "asset: owner, tags, domain, description, last-updated, "
            "and a short summary. The user wants an overview rather "
            "than any single attribute. Do NOT walk lineage; do NOT "
            "audit compliance."
        ),
        "reasoning_patterns": "",
        "output_uri": "mesh:AssetProfile",
    },
    "mesh:enumerateCatalog": {
        "task_framing": (
            "VERB SCOPE: mesh:enumerateCatalog.\n"
            "Your task is to ENUMERATE the data assets present in the "
            "DataHub catalog. The user wants a FLAT LIST of the "
            "available tables / datasets / dashboards — possibly "
            "scoped by tier (bronze / silver / gold), domain, or "
            "platform — not lineage, schema, ownership, or any "
            "single-asset attribute. Do NOT walk lineage; do NOT "
            "inspect columns; do NOT pick one asset to describe. "
            "Issue catalog-level searches and report the set of "
            "assets you find as a flat list. The downstream renderer "
            "is KNOWLEDGE_DOCUMENT, so emit `summary_text` describing "
            "what you found and `structured_data` with a `tables` (or "
            "`assets`) field listing the asset names."
        ),
        "reasoning_patterns": "",
        "output_uri": "mesh:CatalogListing",
    },
    # Generic fallback (ADR-0017 transition window). Both reasoning
    # patterns active since we don't know the question shape.
    "mesh:analyzeWithCodeAgent": {
        "task_framing": (
            "VERB SCOPE: mesh:analyzeWithCodeAgent (generic fallback).\n"
            "Your task is a general catalog Q&A question that didn't "
            "match a specialized verb. Use the broadest applicable "
            "approach: search the catalog, inspect the returned "
            "fields, apply both reasoning patterns below as needed."
        ),
        "reasoning_patterns": _REASONING_RECURSIVE_LINEAGE + _REASONING_CROSS_FEATURE,
        "output_uri": "http://invincible-agent/mesh#AgentResponse",
    },
}


def _select_verb_prompt_block(routed_verb_iri: str | None) -> dict:
    """Return the prompt block for a routed verb, falling back to the
    generic block when ``routed_verb_iri`` is missing or unknown.
    """
    if routed_verb_iri and routed_verb_iri in _VERB_PROMPT_BLOCKS:
        return _VERB_PROMPT_BLOCKS[routed_verb_iri]
    return _VERB_PROMPT_BLOCKS["mesh:analyzeWithCodeAgent"]


# ---------------------------------------------------------------------------
# Restate Service — AnalystService
# ---------------------------------------------------------------------------
analyst_service = Service("AnalystService")


# Deterministic ontology-class → DataHub entity_type mapping lives in
# ``entity_type_mapping.py`` so pure-unit tests can pin it without
# dragging this file's heavy import chain (BAML / restate-sdk /
# smolagents). Imported under the legacy underscored name so the
# prompt-construction call site (run_smolagent) doesn't change.
#
# Three import shapes for cross-environment compatibility — the
# container Dockerfile flattens agent_fleet/restate_analyst/ into
# /app/ so the FIRST fallback is the flat module name; dev checkout
# uses the agent_fleet.* path.
try:
    from entity_type_mapping import (  # type: ignore[no-redef]
        recommended_entity_type as _recommended_entity_type,
    )
except ImportError:
    from agent_fleet.restate_analyst.entity_type_mapping import (
        recommended_entity_type as _recommended_entity_type,
    )

# The deterministic traceLineage assembler (ADR-0030 / D4). PURE module —
# no network, no smolagents — so the summary is written FROM the selected
# structure and cannot contradict it. Same flatten-aware import shape.
try:
    from lineage_answer import (  # type: ignore[no-redef]
        OUTCOME_LIST,
        OUTCOME_NONE,
        build_trace_lineage_answer,
        humanize_urn_label,
        resolve_urn_outcome,
    )
except ImportError:
    from agent_fleet.restate_analyst.lineage_answer import (
        OUTCOME_LIST,
        OUTCOME_NONE,
        build_trace_lineage_answer,
        humanize_urn_label,
        resolve_urn_outcome,
    )


# The hint set the ExtractPlatformScope extractor uses to tell a recognized
# data platform from a typo'd/unknown one. These are GENERIC VENDOR SLUGS
# (DataHub dataPlatform names) — not catalog assets — so they are safe to
# name in code. Ops can extend the set for a deployment without a code change
# via KNOWN_PLATFORMS (comma-separated); the authoritative recognition still
# happens at Engine D (an unrecognized slug yields no filter match). The list
# only steers the extractor's recognized-vs-unrecognized branch.
_KNOWN_PLATFORMS_DEFAULT = [
    "snowflake", "postgres", "mysql", "mssql", "oracle", "redshift",
    "bigquery", "databricks", "dbt", "s3", "hive", "kafka", "superset",
    "looker", "tableau", "presto", "trino", "clickhouse", "mongodb",
]


def _known_platforms_str() -> str:
    """Comma-separated known-platform hint for the extractor (env-overridable)."""
    override = (os.getenv("KNOWN_PLATFORMS") or "").strip()
    if override:
        slugs = [s.strip().lower() for s in override.split(",") if s.strip()]
    else:
        slugs = list(_KNOWN_PLATFORMS_DEFAULT)
    return ", ".join(slugs)


def _is_trace_lineage(verb_iri: str) -> bool:
    """True when the router matched the traceLineage verb, tolerant of the IRI
    form (``mesh:traceLineage`` or a fully-qualified ``…#traceLineage``)."""
    if not verb_iri:
        return False
    local = verb_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return local.strip().lower() == "tracelineage"


async def _TEMPORARY_urn_resolution_belongs_on_engine_d(
    *,
    asset_label: str,
    resolved_class_uri: str,
    wrapper_url: str,
    caller_persona: str,
    task_domain: str,
    caller_entitled_domains: List[str],
    caller_email: str,
) -> Dict[str, Any]:
    """MISPLACED — DataHub entity-model knowledge that belongs on Engine D.

    This resolves a subject NAME → a single URN: a DataHub search, an
    entity_type derived from the ontology class (Dashboard → DASHBOARD), and
    the top hit under the three-outcome ambiguity floor. That is DataHub
    entity-model reasoning, and it is running on the WRONG engine — Engine A
    should be a thin consumer, Engine D owns the DataHub client.

    CORRECT HOME: Engine D already has ``resolve_instance`` — this operation
    IS that operation. Engine A should call an Engine D endpoint
    (e.g. ``/resolve_subject_urn``), not reach into the entity model itself.
    The correct layering is ALREADY in place for the walk (Engine A calls
    Engine D's ``/lineage_by_platform`` over HTTP); only THIS sub-step leaked.

    WHY IT'S HERE ANYWAY: Engine D's ``resolve_instance`` registration is
    REJECTED at load time because ``mesh#InstanceIdentifier`` /
    ``mesh#InstanceResolution`` do not resolve in Neo4j — the partial
    mesh-ontology load gap, a [[bootstrap-state-debt]] thread. D4 routes
    around the broken endpoint by doing the resolution here. The function
    name is deliberately wrong-on-sight so the misplacement cannot calcify
    into "it works, leave it" — the fix-one-instance-of-a-class failure mode.

    TRIGGER TO MOVE (do NOT leave this past it): when Engine D's
    ``resolve_instance`` registers cleanly (the ``mesh#Instance*`` classes
    load), DELETE this function and call that endpoint. Tracked as an
    enumerated owed item in ADR-0030 ("Owed items").
    """
    import requests as _requests

    entity_type = _recommended_entity_type(resolved_class_uri) or None
    candidates: List[Dict[str, Any]] = []
    try:
        payload = {
            "user_query": asset_label,
            "persona": caller_persona,
            "domain": task_domain,
            "entitled_domains": caller_entitled_domains,
            "caller_email": caller_email,
        }
        if entity_type:
            payload["entity_type"] = entity_type
        r = await asyncio.to_thread(
            lambda: _requests.post(f"{wrapper_url}/query_metadata", json=payload, timeout=15.0)
        )
        r.raise_for_status()
        for a in (r.json().get("matched_assets") or []):
            if isinstance(a, dict) and a.get("urn"):
                candidates.append({"name": a.get("label") or a.get("urn"), "urn": a["urn"]})
    except Exception as exc:  # noqa: BLE001
        logger.warning("traceLineage: subject resolution search failed (%s)", exc)
    return resolve_urn_outcome(asset_label, candidates)


def _resolve_ontology(task_description: str, user_email: str = "") -> dict:
    """Call Engine O to resolve the task description into semantic context.

    This function is executed inside ``ctx.run()`` for durable execution —
    if the pod crashes mid-flight, Restate will replay and skip this step
    if it already completed successfully.

    ADR-0025 ontology-IRI namespace: thread the caller's entitlement key
    (email) so Engine O's ``can_view`` candidate-filter discriminates on THIS
    subject here too — this is the SECOND call to O's ``/resolve`` gate (the
    supervisor's ``_resolve_subject`` is the first). The composed-path seal
    caught this path dropping identity (``caller=''``) when the supervisor's
    resolution returned UNKNOWN and Engine A re-resolved: the multi-path
    corollary of [[identity-reaches-enforcement-point]] — every call to an
    enforcement point must carry the subject, not just the primary one. Empty
    is honest-absent → deny-by-default on compartmented classes (fail-closed).
    """
    payload: dict = {"query": task_description}
    if user_email:
        payload["user_email"] = user_email
    resp = requests.post(
        ONTOLOGY_RESOLVE_URL,
        json=payload,
        timeout=ONTOLOGY_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


from orchestrator.auth import current_user_token, current_trace_id

@analyst_service.handler()
async def analyze(ctx: Context, request: dict) -> dict:
    """Durable handler: resolve ontology → run smolagent → return AgentResponse.

    Every side-effectful operation is wrapped in ``ctx.run()`` so Restate
    can guarantee exactly-once execution even across pod restarts.
    """
    # The supervisor sends `user_query` (and no `dataset_id` for analyst
    # tasks that aren't tied to a specific asset). AgentTask requires
    # task_description and dataset_id, so map defensively. Direct callers
    # sending the canonical AgentTask shape still work unchanged.
    request.setdefault("task_description", request.get("user_query") or "Analyze")
    request.setdefault("dataset_id", request.get("dataset_id", ""))
    task = AgentTask(**request)
    dynamic_schema_map = request.get("dynamic_schema_map", "")
    user_id = request.get("user_id")

    # ADR-0008 fallback context (when the supervisor escalates to Engine A
    # because no specialist predicate matched or the top hit's confidence
    # was below threshold). All three fields are optional; absence means
    # this is a normal request, not a fallback.
    fallback_reason = request.get("fallback_reason") or ""
    fallback_score = request.get("fallback_score")
    rejected_verb_iri = request.get("rejected_verb_iri") or ""

    # ADR-0017 routing context: the router passes back the verb IRI it
    # matched (e.g. "mesh:lookupOwnership", "mesh:traceLineage"). This
    # handler selects a verb-specific prompt block — only the reasoning
    # patterns relevant to that verb make it into the agent's context —
    # and instructs the agent to echo the verb's declared output_uri in
    # final_answer(). When the router doesn't pass a verb, or passes one
    # we don't recognize, _select_verb_prompt_block returns the generic
    # fallback block (both reasoning patterns active, output_uri
    # mesh:AgentResponse).
    routed_verb_iri = request.get("routed_verb_iri") or ""
    verb_block = _select_verb_prompt_block(routed_verb_iri)

    # Extract the injected token from the proxy and set it into ContextVar
    auth_header = request.get("user_jwt")
    if auth_header:
        current_user_token.set(auth_header)

    trace_id = request.get("trace_id")
    if trace_id:
        current_trace_id.set(trace_id)

    # Step 1: Resolve semantic context. Prefer the supervisor's
    # already-resolved fields when present — the supervisor's
    # /resolve call already ran the routing chain (class recall +
    # phone-book instance preemption); calling Engine O AGAIN from
    # here is the [[resolution-discard-pattern]] failure mode the
    # supervisor's dispatch-payload comment at lines 1056-1086 of
    # dynamic_supervisor.py named as banked. Without this guard,
    # Engine A re-resolves task_description (which is just the
    # user's raw question), discards entity_refs and the phone-
    # book provenance, and routinely ends up with resolved_uri=
    # UNKNOWN even for queries the routing layer resolved at
    # score 0.9+. With UNKNOWN, the deterministic
    # class→entity_type recommendation (see _recommended_entity_type
    # below) can't fire, and the smolagent falls back to guessing
    # entity_type — which is the exact LLM-luck dependency the
    # 2026-06-26 demo investigation closed at the source.
    supplied_subject_uri = (request.get("resolved_subject_uri") or "").strip()
    supplied_instance_id = (request.get("resolved_instance_id") or "").strip()
    # ADR-0025: the caller's entitlement key (email), needed BEFORE the resolve
    # branch so the legacy re-resolve threads identity to O's /resolve gate.
    # (Also read again below at its Engine-D forwarding site; same value.)
    resolve_caller_email = request.get("user_email") or ""
    if supplied_subject_uri:
        semantic_ctx = {
            "resolved_uri": supplied_subject_uri,
            "confidence_score": 0.9,  # Trust the supervisor's resolution.
            "instance_id": supplied_instance_id,
            "from_supervisor": True,
        }
    else:
        # Legacy path: no supervisor-supplied context (older callers,
        # direct test probes, the generalist fallback launched via
        # /analyze_proxy with no routing). Re-resolve via Engine O —
        # threading the caller's email so O's can_view gate discriminates
        # on THIS subject (composed-path seal: this path was caller='').
        semantic_ctx = await ctx.run(
            "resolve_ontology",
            lambda: _resolve_ontology(task.task_description, resolve_caller_email),
        )

    # --------------------------------------------------------------------------
    # Acquire the shared mem0 Memory singleton (built once per pod, off-loop).
    # The Mem0CompatibleWeaviate adapter, the embedder selection, and the
    # Memory.from_config() call all live at module scope now — see
    # get_mem0_memory() / _build_mem0_memory() above. The first request pays
    # a ~5-30s cold-start cost on a worker thread; the event loop stays free
    # so /health remains responsive and readiness stays green.
    try:
        m = await get_mem0_memory()

        from smolagents import tool

        @safe_observe(as_type="retrieval", name="mem0_context_retrieval")
        def fetch_user_memory(query: str, user_id: str):
            # ADR-0016 r2 Open Items: agent_id partition.
            # Engine A and Engine E share the Mem0 collection. Without
            # an agent_id filter, Engine A could surface past
            # transcripts from Engine E (a different agent voice with
            # different tools and a different grounding rule), and
            # vice versa. Filter writes by engine identity so the
            # "Relevant Past Experience" block surfaces only this
            # engine's own past sessions.
            results = m.search(
                query=query,
                filters={
                    "user_id": user_id,
                    "agent_id": "engine_a_restate_analyst",
                },
            )
            safe_update_observation(input_data=query, output_data=results)
            return results

        task_domain = request.get("domain", "ALL")

        # 2026-07-02 SECURITY: the REAL caller identity, threaded from
        # auth → supervisor → here. `search_datahub` MUST forward these
        # to Engine D rather than asserting a hardcoded privileged
        # persona. Absent identity → LEAST-PRIVILEGED, never steward
        # (`[[optimistic-defaults-are-dishonest]]` with an access blast
        # radius). See ADR-0025 "catalog is an enforcement surface".
        #
        #   caller_persona: the answerer/caller persona the supervisor
        #     already propagates (config.user_persona). Falls back to
        #     "" (least-privileged), NOT DATA_STEWARD.
        #   caller_entitled_domains: the caller's domain scope. Empty
        #     means "no entitlement asserted" → Engine D's gate denies.
        caller_persona = (
            request.get("user_persona")
            or request.get("persona")
            or ""  # least-privileged on absence — never DATA_STEWARD
        )
        caller_entitled_domains = request.get("entitled_domains") or []
        # ADR-0025 hop 2: the caller's entitlement key (email), threaded
        # alongside entitled_domains. Forwarded to Engine D so query_metadata
        # asks Topaz can_view about THIS subject. "" on absence → Engine D
        # denies (least-privileged), same posture as empty entitled_domains.
        caller_email = request.get("user_email") or ""

        # Phase 3 source attribution (closing the Engine A gap from
        # commit 20ed5f9, which covered Engines W and E only). Each tool
        # that retrieves data with an attributable URN appends a Source
        # record here; sources_seen_uris dedupes across repeat hits
        # within a single agent run. After the smolagent finishes, the
        # accumulated list rides on result_dict["sources"] so the
        # supervisor's subtask_sources materialization can project it
        # into the typed `sources` SSE event the cortex-ui SourcesTrail
        # consumes. Mirrors the pattern in
        # agent_fleet/weaviate_expert/service.py and
        # agent_fleet/neo4j_expert/service.py.
        sources_collected: List[Dict[str, Any]] = []
        sources_seen_uris: set[str] = set()

        def _collect_datahub_source(
            urn: str,
            search_query: str,
            relevance: float | None = None,
            label_override: str | None = None,
            entity_type_override: str | None = None,
            snippet: str | None = None,
            open_url: str | None = None,
        ) -> None:
            """Project a DataHub URN into the cortex-ui Source shape and
            append to sources_collected. Dedupes by URN so repeat hits
            across multiple search_datahub calls don't multiply. Uses
            the module-level parse_datahub_urn helper for label/type
            fallback when the caller doesn't provide structured data.

            Phase 3 follow-up (2026-06-24): structured per-asset data
            now flows through datahub_wrapper's matched_assets list,
            so the caller can pass the authoritative
            label/type/description/open_url rather than re-parsing the
            URN. parse_datahub_urn stays as the fallback for cases
            where matched_assets isn't available (older response
            shape, error path, JIT-injected tool).
            """
            if not urn or urn in sources_seen_uris:
                return
            sources_seen_uris.add(urn)
            entity_type, label = parse_datahub_urn(urn)
            sources_collected.append({
                "type": entity_type_override or entity_type,
                "label": label_override or label or urn,
                "uri": urn,
                "snippet": snippet,
                "relevance": relevance,
                "open_url": open_url,
            })

        @tool
        def search_datahub(query: str, entity_type: str = None) -> str:
            """
            Searches the DataHub metadata catalog and returns matched assets
            with their owner, last_updated, tags, description, lineage, and
            schema as authoritative facts.

            Response shape — each matched asset starts with a header line
            of the form

                [TYPE] name | key=value | key=value | ...

            where the header keys include `owner`, `last_updated`, and
            `tags` when present. Indented continuation lines below the
            header may carry `description:`, `upstream:`, `downstream:`,
            and `columns:`. Read these fields verbatim — they are returned
            from DataHub, not inferred. To trace lineage end-to-end, you
            may issue follow-up search_datahub calls on the names that
            appear in `upstream:` or `downstream:`.

            Args:
                query: CRITICAL - You MUST extract 1-3 concise keywords (e.g. 'sales dashboard'). DO NOT pass full sentences.
                entity_type: The specific entity to search. You MUST choose a value from the 'Valid DataHub Entity Types' list provided in your system prompt. Do NOT use '*'.
            """
            import requests
            import os
            DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://iagent-engine-d:8085")
            try:
                # 2026-07-02 SECURITY: forward the REAL caller identity
                # (persona + entitled_domains), NOT a hardcoded
                # DATA_STEWARD. The prior `persona="DATA_STEWARD"` here
                # was the laundering step of a confirmed PII-metadata
                # bypass: the routing layer "denied" a non-entitled
                # caller, this fallback re-queried the catalog as the
                # most privileged persona, and Engine D enforced
                # nothing. Engine D's query_metadata now gates on
                # entitled_domains; forwarding the real (possibly empty)
                # scope makes that gate meaningful. Empty scope → Engine
                # D denies (least-privileged), which is correct.
                payload = {
                    "user_query": query,
                    "persona": caller_persona,
                    "domain": task_domain,
                    "entitled_domains": caller_entitled_domains,
                    # ADR-0025 hop 2: subject for Engine D's Topaz can_view ask.
                    "caller_email": caller_email,
                }
                if entity_type:
                    payload["entity_type"] = entity_type
                resp = requests.post(
                    f"{DATAHUB_WRAPPER_URL}/query_metadata",
                    json=payload,
                    timeout=15.0
                )
                resp.raise_for_status()
                data = resp.json()
                # Phase 3 source attribution: capture every asset this
                # call surfaced.
                #
                # Preferred path: matched_assets (Phase 3 follow-up
                # 2026-06-24) carries per-asset structured data, so
                # the Source records get authoritative label/type,
                # the description as snippet, and the external open_url
                # for click-through. This is what datahub_wrapper >=
                # 2026-06-24 returns.
                #
                # Fallback: referenced_uris (the flat-URN list) is
                # still emitted by every datahub_wrapper response.
                # If matched_assets is missing or empty for some
                # reason (older wrapper, JIT-injected tool that
                # follows the same protocol but skips the new field),
                # parse_datahub_urn derives label/type from the URN
                # alone and snippet stays None.
                conf = data.get("confidence_score")
                relevance = float(conf) if conf is not None else None
                matched = data.get("matched_assets") or []
                if matched:
                    for a in matched:
                        if not isinstance(a, dict):
                            continue
                        urn = a.get("urn") or ""
                        if not urn:
                            continue
                        _collect_datahub_source(
                            urn,
                            search_query=query,
                            relevance=relevance,
                            label_override=a.get("label") or None,
                            entity_type_override=a.get("type") or None,
                            snippet=a.get("description") or None,
                            open_url=a.get("open_url") or None,
                        )
                else:
                    refs = data.get("referenced_uris") or []
                    for u in refs:
                        if isinstance(u, str) and u:
                            _collect_datahub_source(
                                u, search_query=query, relevance=relevance,
                            )
                return data.get("data", {}).get("short_answer", "No results found.")
            except Exception as e:
                return f"Error executing DataHub search via Engine D: {str(e)}"

        @tool
        def superset_analytics_manager(
            action: str,
            sql_query: str,
            chart_title: str = "AI Generated Insights",
            viz_type: str = "dist_bar",
            database_id: int = 1
        ) -> str:
            """
            Manages headless analytics via Apache Superset. 
            Use 'preview' to run SQL and get data for a UI chart. 
            Use 'publish' to save the query as a permanent Superset Dashboard Chart.

            Args:
                action: 'preview' to get raw data, or 'publish' to save to Superset.
                sql_query: The validated SQL query to execute.
                chart_title: The name for the published chart.
                viz_type: Superset viz type (e.g., 'dist_bar', 'line', 'pie', 'area').
                database_id: The ID of the Superset database connection.
            """
            import os
            import json
            import requests
            import time

            SUPERSET_URL = os.getenv("SUPERSET_URL", "http://superset:8088")
            # In your environment, the Agent uses a pre-configured JWT or Admin creds
            headers = {
                "Authorization": f"Bearer {os.getenv('SUPERSET_ACCESS_TOKEN')}",
                "Content-Type": "application/json"
            }

            if action == "preview":
                # 1. Execute via SQL Lab API to get raw data for the Cortex UI preview
                payload = {
                    "database_id": database_id,
                    "sql": sql_query,
                    "run_async": False
                }
                resp = requests.post(f"{SUPERSET_URL}/api/v1/sqllab/execute/", json=payload, headers=headers)
                if resp.status_code != 200:
                    return f"Preview failed: {resp.text}"
                
                data = resp.json().get("data", [])
                return json.dumps(data)

            elif action == "publish":
                # 2. Register the Virtual Dataset
                ds_payload = {"database": database_id, "table_name": f"tmp_{int(time.time())}", "sql": sql_query}
                ds_resp = requests.post(f"{SUPERSET_URL}/api/v1/dataset/", json=ds_payload, headers=headers)
                if ds_resp.status_code != 201:
                    return f"Dataset creation failed: {ds_resp.text}"
                dataset_id = ds_resp.json().get("id")

                # 3. Create the Chart (Slice)
                chart_payload = {
                    "slice_name": chart_title,
                    "viz_type": viz_type,
                    "datasource_id": dataset_id,
                    "datasource_type": "table",
                    "params": json.dumps({"metrics": ["count"], "groupby": []})
                }
                chart_resp = requests.post(f"{SUPERSET_URL}/api/v1/chart/", json=chart_payload, headers=headers)
                if chart_resp.status_code != 201:
                    return f"Chart publication failed: {chart_resp.text}"
                
                chart_id = chart_resp.json().get("id")
                return f"PUBLISHED: Chart ID {chart_id}. URL: {SUPERSET_URL}/explore/?slice_id={chart_id}"

            return "Invalid action. Use 'preview' or 'publish'."

        @safe_observe(name="smolagents_restate_execution")
        @safe_observe(name="smolagents_analyst_execution")
        async def run_smolagent() -> tuple[str, str, float]:
            try:
                resolved_uri = semantic_ctx.get("resolved_uri", "unknown")
                confidence = semantic_ctx.get("confidence_score", 0.0)

                # 🚀 JIT TOOL INJECTION: Fetch tools from Engine D based on resolved_uri
                from orchestrator.discovery import fetch_tools_by_uri, DynamicMeshTool, bind_mcp_server
                raw_tools = await fetch_tools_by_uri(resolved_uri)
                
                jit_tools = []
                for t in raw_tools:
                    try:
                        if t.get("type") == "MCPServer":
                            mcp_proxies = await bind_mcp_server(t)
                            jit_tools.extend(mcp_proxies)
                        else:
                            jit_tools.append(DynamicMeshTool(t))
                    except Exception as te:
                        logger.warning(f"Failed to bind JIT tool {t.get('urn')}: {te}")

                # Base system tools
                base_tools = [search_datahub, superset_analytics_manager]
                all_tools = base_tools + jit_tools
                
                logger.info(f"JIT Execution: Bound {len(jit_tools)} dynamic tools for URI {resolved_uri}")

                # ADR-0008 fallback preamble: when this engine is acting as
                # the generalist fallback (registry coverage gap or
                # low-confidence specialist match), tell the agent that
                # explicitly so its tone calibrates to uncertainty rather
                # than presenting as authoritative.
                fallback_preamble = ""
                if fallback_reason == "no_predicate_matched":
                    fallback_preamble = (
                        "ROUTING CONTEXT: You are operating as the GENERALIST "
                        "FALLBACK. The mesh's predicate registry has no "
                        "specialized engine for this request. Do your best "
                        "with the general-purpose tools below, and where the "
                        "answer is uncertain say so explicitly. Do not "
                        "present generalist judgment as specialist authority.\n\n"
                    )
                elif fallback_reason == "low_confidence":
                    fallback_preamble = (
                        f"ROUTING CONTEXT: You are operating as the GENERALIST "
                        f"FALLBACK. A specialist predicate did match this "
                        f"request ({rejected_verb_iri or 'unknown'}) but its "
                        f"confidence score ({fallback_score}) was below the "
                        f"threshold for confident routing. Do your best with "
                        f"the general-purpose tools below; where the answer "
                        f"is uncertain say so. Do not present generalist "
                        f"judgment as specialist authority.\n\n"
                    )

                # ADR-0017: per-verb prompt assembly. Reasoning patterns are
                # no longer always-on; only the patterns relevant to the routed
                # verb are included. The verb_block also carries the
                # output_uri the agent must echo in final_answer().
                #
                # Deterministic-threading: when the router resolved the
                # subject to an idp:* class that has a known DataHub
                # entity_type, surface that as the RECOMMENDED first
                # search. The smolagent historically had to INFER
                # entity_type from resolved_uri ("idp#Dashboard means
                # I should pass DASHBOARD") and got it wrong about
                # half the time, producing honest-but-frustrating
                # empty Sources cards. The recommendation eliminates
                # the variance; the "first search" framing preserves
                # the broaden-on-miss escape hatch so a wrong class
                # guess at routing time doesn't trap the agent in
                # the wrong DataHub partition.
                recommended_entity_type = _recommended_entity_type(resolved_uri)
                entity_type_hint = ""
                if recommended_entity_type:
                    entity_type_hint = (
                        f"  RECOMMENDED entity_type for the FIRST "
                        f"search_datahub call: {recommended_entity_type!r} "
                        f"(deterministically mapped from the resolved "
                        f"{resolved_uri} class). Use this as your first "
                        f"search. If it returns 0 results, broaden to "
                        f"another entity_type — but the routing layer "
                        f"already verified the asset class, so the "
                        f"deterministic mapping is the right starting "
                        f"point.\n"
                    )
                agent_prompt = (
                    f"{fallback_preamble}"
                    f"You are an enterprise data analyst operating across all domains (Maintenance, Manufacturing, Sustainment, etc.). Your ONLY source of truth is the output of the `search_datahub` tool.\n\n"
                    f"{verb_block['task_framing']}\n\n"
                    f"Task: {task.task_description}\n"
                    f"Dataset ID: {task.dataset_id}\n\n"
                    f"Semantic Context (from IOF/MIMOSA ontology):\n"
                    f"  Resolved URI: {resolved_uri}\n"
                    f"  Confidence: {confidence}\n"
                    f"{entity_type_hint}\n"
                    f"CRITICAL GROUNDING RULE: You must NEVER invent, guess, or extrapolate facts. Use only what the tools return. If a specific field the user asked about is genuinely absent from the tool result, state it is not available — but do NOT claim a field is missing if the tool returned it. See each tool's docstring for the shape of its response.\n\n"
                    f"PAST EXPERIENCE IS A HINT, NEVER A FACT.\n"
                    f"The \"Relevant Past Experience\" block (when present below) is drawn from earlier sessions in this engine's own memory partition — raw user questions and the agent's prior summaries of how it answered them. It MAY reflect summaries of your own previous answers — and you have been wrong before. Treat past experience as a possibly-stale starting hypothesis, NEVER as ground truth. You MUST verify against the current tool output before reporting anything. If past experience says \"no X exists\" for the current question, IGNORE that claim and run the tool anyway; an empty result must come from a fresh search, not from memory. Repeating a past wrong answer because it appears in past experience is the most common cascading failure in this system. The tool is authoritative; past experience is conversational background only.\n\n"
                    f"{verb_block['reasoning_patterns']}"
                )

                if dynamic_schema_map:
                    agent_prompt += f"{dynamic_schema_map}\n\n"

                agent_prompt += (
                    f"If you see a request for a 'chart' or 'visualization', you should:\n"
                    f"First, call superset_analytics_manager with action='preview'.\n"
                    f"Include the returned JSON in your final response so the UI Router can build the ChartUI object.\n\n"
                    f"You MUST return your final answer as a Python dictionary matching this Pydantic schema:\n"
                    f"class AgentFinalResponse(BaseModel):\n"
                    f"    status: str\n"
                    f"    summary_text: str = Field(description=\"A conversational summary. STRICT RULE: You must ONLY state facts returned by the DataHub tool. DO NOT guess business purposes.\")\n"
                    f"    structured_data: Optional[Dict[str, Any]] = Field(description=\"MUST be a raw JSON object. STRICT RULE: If a dashboard description is missing, UNAVAILABLE_IN_CATALOG, or empty, you MUST write 'No description available'. Do not infer or invent descriptions. DO NOT stringify this.\")\n"
                    f"    output_uri: str = Field(description=\"MUST be the literal string '{verb_block['output_uri']}'. This is the declared output shape of the verb you were routed to handle (ADR-0017). Downstream presentation routing depends on this exact value — echo it verbatim, do not modify, do not omit.\")\n\n"
                    # The argument-vs-call distinction is load-bearing: without
                    # it, models emit the dict AS the tool call (keys
                    # status/summary_text/... where 'name' belongs), smolagents
                    # rejects it, and a full LLM round-trip is wasted on the
                    # retry — observed live at step 7 of an 8-step run.
                    f"Pass this dictionary to the final_answer() tool as its single "
                    f"argument: call final_answer(answer=<the dictionary>). The "
                    f"dictionary is the ARGUMENT of final_answer — it is never "
                    f"itself the tool call."
                )

                if user_id:
                    # Bridge to a worker thread — m.search() is sync gRPC and
                    # must not block the asyncio loop.
                    past_memories_response = await asyncio.to_thread(
                        fetch_user_memory, task.task_description, user_id
                    )

                    if isinstance(past_memories_response, dict):
                        past_memories = past_memories_response.get("results", [])
                    else:
                        past_memories = past_memories_response
                        
                    if past_memories:
                        memory_strings = "\n".join([f"- {mem.get('memory', mem.get('text', ''))}" for mem in past_memories if isinstance(mem, dict)])
                        prompt_extension = f"\n\n### Relevant Past Experience\n{memory_strings}"
                        agent_prompt += prompt_extension

                tool_reminder = """
HOW TO ANSWER: call the provided tools to gather what you need, then call
final_answer with your answer. Call one tool at a time; use each tool's result
to decide the next call. Use only what the tools return — never invent data.
"""
                agent_prompt += f"\n\n{tool_reminder}"

                model = get_smolagent_model()
                
                trace_id = current_trace_id.get()
                if trace_id:
                    os.environ["LANGFUSE_TRACE_ID"] = trace_id
                    try:
                        from langfuse.decorators import langfuse_context
                        langfuse_context.update_current_trace(id=trace_id)
                    except Exception:
                        pass
                
                # ToolCallingAgent (structured tool-calls) — NOT CodeAgent
                # (free-form Python in <code> tags). gpt-oss intermittently
                # fumbles the CodeAgent envelope (prose-glued-to-code parse
                # errors -> empty answers, the mesh-suite regression); the
                # structured tool-call format is low-load enough that it doesn't.
                # Proven on Engine E (1 step-error vs CodeAgent's 7). Requires the
                # litellm ollama_chat/ route (ollama/ dropped tool_calls).
                agent = ToolCallingAgent(tools=all_tools, model=model)
                
                result = await asyncio.to_thread(agent.run, agent_prompt)

                formatted_trace = "--- Agent Execution Trace ---\n"
                if hasattr(agent, 'logs'):
                    for log_entry in agent.logs:
                        if isinstance(log_entry, dict):
                            formatted_trace += f"Step: {log_entry.get('step', 'N/A')}\n"
                            if 'thought' in log_entry:
                                formatted_trace += f"Thought: {log_entry['thought']}\n"
                            if 'tool_call' in log_entry:
                                formatted_trace += f"Action: {log_entry['tool_call']}\n"
                            if 'tool_result' in log_entry:
                                formatted_trace += f"Result: {log_entry['tool_result']}\n"
                        else:
                            formatted_trace += f"Step: {getattr(log_entry, 'step', 'N/A')}\n"
                            if hasattr(log_entry, 'thought') and getattr(log_entry, 'thought'):
                                formatted_trace += f"Thought: {getattr(log_entry, 'thought')}\n"
                            if hasattr(log_entry, 'tool_call') and getattr(log_entry, 'tool_call'):
                                formatted_trace += f"Action: {getattr(log_entry, 'tool_call')}\n"
                            if hasattr(log_entry, 'tool_result') and getattr(log_entry, 'tool_result'):
                                formatted_trace += f"Result: {getattr(log_entry, 'tool_result')}\n"
                        formatted_trace += "-" * 40 + "\n"

                return result, formatted_trace, confidence
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"ERROR in run_smolagent: {error_trace}")
                raise e

        async def run_trace_lineage():
            """Deterministic traceLineage (ADR-0030 / D4).

            The original bug was a summary that contradicted its own evidence:
            the smolagent read a long upstream list, missed the matching rows,
            and reported "none." This branch removes the model from selection
            entirely — it resolves the subject to a single URN (three-outcome
            floor: never silently walk a guessed asset), asks Engine D to walk
            and platform-FILTER lineage server-side, and assembles the answer
            FROM that structure. Narrative cannot disagree with evidence
            because there is one source of truth. Produces the same
            (raw_agent_response, execution_trace, conf) tuple the smolagent
            path does, so all shared response assembly below runs unchanged.
            """
            import requests as _requests

            wrapper_url = os.getenv("DATAHUB_WRAPPER_URL", "http://iagent-engine-d:8085")
            raw_instance = (semantic_ctx.get("instance_id") or "").strip()
            # The supervisor's phone-book match carries the instance's DISPLAY
            # LABEL separately from its URN id (whose key can be a numeric
            # superset id). Prefer the label for prose so the card isn't titled
            # after the URN key; fall back to humanizing the URN only when no
            # label was threaded.
            resolved_instance_label = (request.get("resolved_instance_label") or "").strip()
            user_query = request.get("user_query") or task.task_description

            # 1. Platform scope (BAML). known_platforms is a hint set so the
            #    extractor distinguishes a recognized platform from a typo.
            #    A failure here degrades to "no filter" (full lineage), never
            #    to a wrong filter.
            try:
                scope = await b.ExtractPlatformScope(user_query, _known_platforms_str())
                platform_scope = {
                    "platforms": [str(p).strip().lower() for p in (scope.platforms or []) if str(p).strip()],
                    "platform_mentioned": bool(scope.platform_mentioned),
                    "unrecognized": [str(u) for u in (scope.unrecognized or []) if str(u).strip()],
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("traceLineage: ExtractPlatformScope failed (%s); no platform filter", exc)
                platform_scope = {"platforms": [], "platform_mentioned": False, "unrecognized": []}

            # 2. Resolve the subject to a single URN.
            #    The router's phone-book step usually ALREADY resolved the
            #    instance to a URN and passes it as resolved_instance_id. In that
            #    case use it DIRECTLY: re-resolving a URN by NAME search is both
            #    wasteful and wrong — the URN string doesn't name-match the
            #    display label, so the search mis-scored a clean single hit as
            #    "ambiguous" and rendered the raw URN as the asset name (the
            #    Customer 360 bug). We derive a readable label for prose.
            #    Only when the instance arrives as a NAME (direct API callers,
            #    class-level queries) do we fall back to the name-search
            #    resolution — DataHub entity-model work that belongs on Engine D,
            #    quarantined in _TEMPORARY_urn_resolution_belongs_on_engine_d
            #    until its endpoint registers (ADR-0030 owed items). Either path
            #    is safe: the /lineage_by_platform walk below enforces
            #    entitlement, so skipping the resolution search never bypasses
            #    the gate.
            if raw_instance.startswith("urn:"):
                resolve = {"outcome": "found", "urn": raw_instance, "candidate_count": 1}
                asset_label = resolved_instance_label or humanize_urn_label(raw_instance)
            elif raw_instance:
                asset_label = raw_instance
                resolve = await _TEMPORARY_urn_resolution_belongs_on_engine_d(
                    asset_label=asset_label,
                    resolved_class_uri=semantic_ctx.get("resolved_uri", ""),
                    wrapper_url=wrapper_url,
                    caller_persona=caller_persona,
                    task_domain=task_domain,
                    caller_entitled_domains=caller_entitled_domains,
                    caller_email=caller_email,
                )
            else:
                # The router did NOT resolve an instance (phone-book miss, or the
                # subject was misclassified upstream so no instance matched).
                # Do NOT fall back to searching task.task_description — that is
                # the whole user question, and searching the catalog for a
                # sentence produced the "cannot locate an asset named '<entire
                # prompt>'" answer. Fail honestly instead: the assembler emits a
                # "couldn't identify which asset" message. This is a cosmetic
                # floor over an upstream (instance-discovery) failure — it does
                # NOT fix the misclassification, only stops it reading as garbage.
                asset_label = ""
                resolve = {"outcome": "no_instance"}

            # 3. Walk lineage ONLY when the subject resolved cleanly AND (if a
            #    platform was named) it was recognized. Otherwise the assembler
            #    emits the correct say-so outcome without a pointless walk.
            unrecognized_platform = platform_scope["platform_mentioned"] and not platform_scope["platforms"]
            lineage_result = None
            if resolve["outcome"] == "found" and not unrecognized_platform:
                try:
                    lr = await asyncio.to_thread(lambda: _requests.post(
                        f"{wrapper_url}/lineage_by_platform",
                        json={
                            "subject_urn": resolve["urn"],
                            "platforms": platform_scope["platforms"],
                            "entitled_domains": caller_entitled_domains,
                            "caller_email": caller_email,
                        },
                        timeout=45.0,
                    ))
                    lr.raise_for_status()
                    lineage_result = lr.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("traceLineage: /lineage_by_platform failed (%s)", exc)
                    lineage_result = {"error": "lineage_unavailable"}

            answer = build_trace_lineage_answer(
                asset_label=asset_label,
                resolve=resolve,
                platform_scope=platform_scope,
                lineage_result=lineage_result,
            )
            sd = answer["structured_data"]
            trace = (
                "--- Deterministic traceLineage (ADR-0030) ---\n"
                f"subject={asset_label!r}\n"
                f"resolve={resolve['outcome']} candidates={resolve.get('candidate_count')}\n"
                f"platforms={platform_scope['platforms']} "
                f"mentioned={platform_scope['platform_mentioned']} "
                f"unrecognized={platform_scope['unrecognized']}\n"
                f"outcome={answer['outcome']} "
                f"considered={sd.get('considered_count')} matched={sd.get('match_count')} "
                f"truncated={sd.get('truncated')}\n"
            )
            # A clean list / genuine-none is a high-confidence deterministic
            # result; the say-so outcomes are honest low-confidence answers.
            confidence = {OUTCOME_LIST: 0.95, OUTCOME_NONE: 0.9}.get(answer["outcome"], 0.5)
            raw = {
                "summary_text": answer["summary"],
                "structured_data": sd,
                "output_uri": answer["output_uri"],
                "__sources": answer["sources"],
            }
            return raw, trace, confidence

        if _is_trace_lineage(routed_verb_iri):
            raw_agent_response, execution_trace, conf = await ctx.run(
                "deterministic-trace-lineage", run_trace_lineage
            )
            # Project the deterministically-selected upstreams into the same
            # sources_collected channel the smolagent path fills, reusing its
            # dedupe + cortex-ui Source shape. `__sources` is a transport-only
            # key; drop it before the shared assembly reads the dict.
            for s in (raw_agent_response.pop("__sources", []) or []):
                _collect_datahub_source(
                    s.get("uri", ""),
                    search_query="traceLineage",
                    relevance=s.get("relevance"),
                    label_override=s.get("label"),
                    entity_type_override=s.get("type"),
                )
        else:
            raw_agent_response, execution_trace, conf = await ctx.run("run-smolagent", run_smolagent)

        summary_text = str(raw_agent_response)
        structured_data_str = None
        # ADR-0017: the agent is instructed to echo the verb's declared
        # output_uri in final_answer(). If the agent obeyed, use what it
        # echoed (cheap drift detection — the audit table can compare
        # echoed vs declared). If it didn't, fall back to the declared
        # URI so the downstream presentation lookup still fires.
        echoed_output_uri = None

        if isinstance(raw_agent_response, dict):
            summary_text = raw_agent_response.get("summary_text", str(raw_agent_response))
            structured_data = raw_agent_response.get("structured_data")
            if structured_data is not None:
                structured_data_str = json.dumps(structured_data)
            echoed_output_uri = raw_agent_response.get("output_uri")

        output_uri = echoed_output_uri or verb_block["output_uri"]

        async def save_memory() -> str:
            if not user_id:
                return "no-user-id"

            # Bridge to a worker thread — m.add() is sync gRPC and must
            # not block the asyncio loop.
            #
            # ADR-0016 (r2) Tier 0(b): infer=False disables the Mem0
            # extractor LLM. Without it, mem0 v2.0.1's default
            # ADDITIVE_EXTRACTION_PROMPT mines the assistant message
            # (which is summary_text — the agent's own voice, an
            # inference) and reframes it as a fact attributed to the
            # user. That is the Q9 catalog-PII poisoning mechanism.
            # Setting infer=False stores the raw transcript only and
            # makes m.search a similarity lookup over user queries,
            # not over agent-derived claims about the world.
            #
            # Trailing-step semantics: the agent's answer was already
            # generated above. Persistence to long-term memory is a
            # trailing concern; a failure here MUST NOT propagate up to
            # restate as a step error, because restate would retry then
            # eventually mark the whole invocation failed — and the
            # gateway would surface "Timeout or failed to fetch UI
            # payload" to a user who in fact had a correct answer ready.
            # Catch broadly, log with the trace for diagnostics, return
            # a string that distinguishes the skipped case in restate's
            # journal. Real failures observed at work-cluster 2026-06-19
            # (vLLM tokenizer mismatch — Token id out of vocabulary)
            # were poisoning the user-facing path despite the agent
            # answering correctly; this guard breaks that chain. The
            # vLLM bug still needs its own fix to RESTORE persistence,
            # but never at the cost of the user's answer.
            try:
                await asyncio.to_thread(
                    m.add,
                    messages=[
                        {"role": "user", "content": task.task_description},
                        {"role": "assistant", "content": summary_text}
                    ],
                    user_id=user_id,
                    agent_id="engine_a_restate_analyst",
                    infer=False,
                )
            except Exception as e:
                logger.warning(
                    "save-memory mem0.add failed for user_id=%s "
                    "(non-fatal, answer already generated): %s",
                    user_id,
                    e,
                    exc_info=True,
                )
                return "skipped-error"
            return "saved"

        await ctx.run("save-memory", save_memory)

        agent_result = {
            "status": AgentStatus.SUCCESS.value,
            "summary": summary_text,
            "structured_data": structured_data_str,
            "extracted_metrics": {
                "ontology_confidence": conf,
            },
            "execution_trace": execution_trace,
        }

        response = AgentResponse(**agent_result)
        # ADR-0017 transition: output_uri rides as a top-level extra
        # field alongside the BAML-typed payload. When AgentResponse's
        # BAML source grows the field, this extra-key path becomes
        # schema-validated automatically without consumer-side change.
        result_dict = response.model_dump()
        result_dict["output_uri"] = output_uri
        result_dict["routed_verb_iri"] = routed_verb_iri
        # Phase 3 source attribution (Engine A): attach the accumulated
        # URN-attributed sources at the top of the response. The
        # supervisor's _log_subtask_sources_asset reads
        # `engine_response["sources"]` (top-level key); the gateway
        # then projects into the typed `sources` SSE event and the
        # cortex-ui SourcesTrail renders the citation list. Same field-
        # name contract Engines W and E shipped in commit 20ed5f9.
        logger.info(
            "[Phase 3 Engine A] sources_collected count=%d uris=%s",
            len(sources_collected),
            [s.get("uri") for s in sources_collected[:5]],
        )
        result_dict["sources"] = sources_collected
        return result_dict
    except Exception as e:
        print(f"[restate-analyst] Fatal error during agent execution: {e}")
        raise e
    # Note: We do NOT close the global client here


# ---------------------------------------------------------------------------
# Restate Workflow — BPMNWorkflowRunner
# ---------------------------------------------------------------------------
bpmn_workflow = Workflow("BPMNWorkflowRunner")


def _execute_service_task(task: dict) -> dict:
    """Execute a BPMN ServiceTask by POSTing to the agent endpoint.

    This function runs inside ``ctx.run()`` for durable execution — if the
    pod crashes mid-flight, Restate replays and skips this step if it
    already completed.

    SUSPEND-VS-FAIL RULING (Situation C — the DoS-safe default): a mid-workflow
    ACCESS DENIAL (401/403) is a FAILURE, not a transient error. It MUST raise a
    Restate TerminalError so the workflow FAILS and RELEASES its durable state —
    never a retryable error that Restate would RETRY FOREVER and PARK (holding the
    durable execution open = the exact DoS surface: an actor who can trigger
    workflows that hit denials could accumulate parked state). A denial is NOT the
    designed-await that legitimately suspends (that's the UserTask branch); it's a
    failure, and failures release state. Transient errors (5xx / network) stay
    RETRYABLE via raise_for_status — those SHOULD retry.
    """
    agent_endpoint = task["agent_endpoint"]
    payload = {
        "task_description": task.get("name", task["id"]),
        "task_id": task["id"],
        "task_type": "service_task",
    }
    headers = {}
    if task.get("user_jwt"):
        payload["user_jwt"] = task["user_jwt"]           # body form (engine ContextVar auth)
        headers["Authorization"] = f"Bearer {task['user_jwt']}"  # header form (cortex-bff get_current_user)
    # General body-passthrough: a ServiceTask may specify (or override) the exact
    # request body its endpoint needs — a real capability (endpoints differ in the
    # shape they expect), not a test hook. When the body drives a Topaz-gated
    # endpoint as an unentitled identity, the endpoint's OWN gate returns the real
    # 401/403 that the denial handling above turns into a terminal fail-and-release.
    if isinstance(task.get("service_payload"), dict):
        payload.update(task["service_payload"])
    resp = requests.post(agent_endpoint, json=payload, headers=headers, timeout=AGENT_HTTP_TIMEOUT)
    if resp.status_code in (401, 403):
        # TERMINAL — fail-and-release, do NOT retry-and-park. Situation C.
        raise restate.TerminalError(
            f"access denied ({resp.status_code}) on service task "
            f"{task['id']!r} -> {agent_endpoint}; failing workflow (state released)",
            status_code=403,
        )
    resp.raise_for_status()  # 5xx / network stay RETRYABLE (transient, should retry)
    return resp.json()


CORTEX_BFF_URL = os.getenv("CORTEX_BFF_URL", "http://iagent-cortex-bff:8090")


def _register_human_task(workflow_id: str, task: dict, user_jwt: str) -> dict:
    """Register a visible HumanTask for a UserTask's approval audience — the
    Situation-B designed-await made observable. cortex-bff resolves the audience's
    authorized actors from Topaz and materializes one queue row per actor; the
    workflow then suspends on the promise until one of them acts. Runs inside
    ctx.run() (durable, replay-safe). The task def MUST declare `audience`
    (e.g. 'promotion:DATA_ENGINEERING'). Payload is CLEARANCE-SAFE (reference +
    summary, never compartmented content)."""
    task_id = task["id"]
    audience = task.get("audience")
    if not audience:
        # CONFIG error, not transient — a UserTask with no audience can never be
        # approved (nobody is authorized). Fail TERMINALLY (release state), never
        # retry-and-park. Same DoS-safe discipline as an access denial.
        raise restate.TerminalError(
            f"user_task {task_id!r} has no `audience` — cannot register a HumanTask",
            status_code=400,
        )
    body = {
        "kind": "workflow_ack",
        "task_id": task_id,
        "workflow_id": workflow_id,
        "audience": audience,
        "title": task.get("title") or task.get("name") or "Approve step",
        "summary": task.get("summary") or f"Approve workflow step {task_id}",
        "requested_by": task.get("requested_by", ""),
        "subject_ref": task.get("subject_ref"),
    }
    headers = {"Authorization": f"Bearer {user_jwt}"} if user_jwt else {}
    resp = requests.post(
        f"{CORTEX_BFF_URL}/internal/human_tasks/register",
        json=body, headers=headers, timeout=AGENT_HTTP_TIMEOUT,
    )
    if resp.status_code in (401, 403):
        # SUSPEND-VS-FAIL (Situation C), same discipline as _execute_service_task: a
        # persistent auth DENIAL on the register is a FAILURE, not a transient error.
        # A 401 (the initiator's token rejected) or 403 won't heal on retry — a bare
        # raise_for_status here would make ctx.run RETRY FOREVER and PARK the durable
        # execution (the exact DoS surface a denial must release, not hold). 5xx /
        # network stay RETRYABLE below (cortex-bff momentarily down SHOULD retry).
        raise restate.TerminalError(
            f"access denied ({resp.status_code}) registering HumanTask {task_id!r} "
            f"(audience {audience!r}) -> {CORTEX_BFF_URL}; failing workflow (state released)",
            status_code=403,
        )
    resp.raise_for_status()  # 5xx / network stay RETRYABLE (transient, should retry)
    return resp.json()


async def _run_definition(
    ctx: WorkflowContext, workflow_id: str, definition: dict, request: dict
) -> dict:
    """ADR-0029 Slice 1 — execute a git-asserted SPO-native WorkflowDefinition.

    ADDITIVE path alongside the sealed inline-task loop (which is UNTOUCHED; it
    retires only after this seals). Per step kind:

      * ``human_await``  — the SEALED HITL mechanics VERBATIM: register a durable
        HumanTask (so the authorized approver sees it) THEN suspend on
        ``approval_{id}``; the ``approve`` handler resolves the SAME promise, so
        the loop is byte-identical to the sealed ``user_task`` path.
      * ``spo_operation`` — PRE-RESOLVED. Verify the DECLARED verb against the
        caller's eligibility (stage-2, Engine O ``/find_compatible_verbs``), then
        dispatch. An ineligible verb -> fail-and-release BEFORE any engine call.
      * ``direct_call``  — Topaz ``can_invoke(caller, capability)`` BEFORE the POST.

    A denial (``StepFailAndRelease``) becomes a ``restate.TerminalError`` INSIDE the
    durable step -> the workflow FAILS and RELEASES its journal (Situation C — a
    denial is a failure, never a suspend/park). A transient 5xx stays retryable
    (the executor's ``raise_for_status`` propagates un-caught).
    """
    try:
        from workflow_definition import WorkflowDefinition  # type: ignore[no-redef]
        from spo_step_executor import (  # type: ignore[no-redef]
            StepFailAndRelease, dispatch_spo_step, execute_direct_call, verify_spo_step,
        )
    except ImportError:
        from agent_fleet.restate_analyst.workflow_definition import WorkflowDefinition
        from agent_fleet.restate_analyst.spo_step_executor import (
            StepFailAndRelease, dispatch_spo_step, execute_direct_call, verify_spo_step,
        )

    wf = WorkflowDefinition.model_validate(definition)  # validate the git-asserted def
    user_jwt = request.get("user_jwt", "")
    identity = {
        "authz_id": request.get("authz_id") or request.get("caller_email") or "",
        "entitled_domains": list(request.get("entitled_domains") or []),
        "persona": request.get("user_persona"),
        "user_jwt": user_jwt,
    }
    results: list[dict] = []

    for step in wf.steps:
        if step.kind == "human_await":
            task = {
                "id": step.id,
                "audience": step.audience,
                "title": step.title,
                "summary": step.summary,
                "subject_ref": step.subject_ref,
                "requested_by": step.requested_by or identity["authz_id"],
                "user_jwt": user_jwt,
            }
            # SEALED mechanics: durable register BEFORE suspend, then the promise.
            await ctx.run(
                f"register_{step.id}",
                lambda t=task: _register_human_task(workflow_id, t, user_jwt),
            )
            approval = await ctx.promise(f"approval_{step.id}", type_hint=dict).value()
            results.append({
                "step_id": step.id, "kind": "human_await",
                "status": approval.get("status", "APPROVED"), "approval": approval,
            })

        elif step.kind == "spo_operation":
            def _do_spo(s=step, ident=identity):
                try:
                    verb = verify_spo_step(s.subject, s.verb, ident["entitled_domains"])
                    return dispatch_spo_step(
                        verb, s.subject, ident,
                        rendered_intent=f"workflow {wf.id}: {s.verb} on {s.subject}",
                    )
                except StepFailAndRelease as e:
                    # Denial -> TERMINAL (fail-and-release), never retry-and-park.
                    raise restate.TerminalError(str(e), status_code=e.status_code)
            result = await ctx.run(f"exec_{step.id}", _do_spo)
            results.append({
                "step_id": step.id, "kind": "spo_operation",
                "status": "SUCCESS", "result": result,
            })

        elif step.kind == "direct_call":
            def _do_dc(s=step, ident=identity):
                try:
                    return execute_direct_call(
                        {"id": s.id, "endpoint": s.endpoint, "capability": s.capability},
                        ident,
                    )
                except StepFailAndRelease as e:
                    raise restate.TerminalError(str(e), status_code=e.status_code)
            result = await ctx.run(f"exec_{step.id}", _do_dc)
            results.append({
                "step_id": step.id, "kind": "direct_call",
                "status": "SUCCESS", "result": result,
            })

    return {
        "workflow_id": workflow_id,
        "definition_id": wf.id,
        "status": "COMPLETED",
        "step_results": results,
    }


@bpmn_workflow.main()
async def run(ctx: WorkflowContext, request: dict) -> dict:
    """Process a list of BPMN tasks sequentially with durable execution.

    For each task in the workflow:

    - **ServiceTask**: Executes immediately via ``ctx.run()`` — the HTTP
      POST to the agent endpoint is replay-safe.
    - **UserTask**: Pauses durably via ``ctx.promise().value()``.  The
      workflow suspends at zero infrastructure cost until a human calls
      the ``approve`` handler to resolve the promise.  Crash-proof:
      if the cluster loses power, Restate reads the journal on restart
      and goes right back to waiting.

    Args:
        ctx: Restate workflow context (provides run, promise, etc.).
        request: Dict with keys:
            - ``workflow_id`` (str)
            - ``tasks`` (list[dict]): Each dict has id, name, type,
              agent_endpoint.

    Returns:
        A dict with the workflow_id, overall status, and per-task results.
    """
    workflow_id = request["workflow_id"]
    # ADR-0029 Slice 1 (ADDITIVE): a git-asserted SPO-native WorkflowDefinition
    # drives the run when `definition` is present. The sealed inline-task loop
    # below is UNTOUCHED — it retires only after the definition path seals.
    if request.get("definition"):
        return await _run_definition(ctx, workflow_id, request["definition"], request)
    tasks = request.get("tasks", [])
    user_jwt = request.get("user_jwt", "")
    results: list[dict] = []

    for task in tasks:
        task_id = task["id"]
        task_type = task.get("type", "service_task")
        task_name = task.get("name", task_id)
        # Thread the initiator JWT so a service task can authenticate to a gated
        # engine (and hit a REAL Topaz denial — Situation C), and so UserTask
        # registration can authenticate to cortex-bff.
        task = {**task, "user_jwt": user_jwt}

        if task_type == "service_task":
            # ---- Durable HTTP call — replay-safe ----
            # A mid-run ACCESS DENIAL raises TerminalError inside _execute_service_task
            # -> this ctx.run fails TERMINALLY -> the workflow fails and RELEASES
            # state (Situation C, DoS-safe). A transient error retries (correct).
            result = await ctx.run(
                f"exec_{task_id}",
                lambda t=task: _execute_service_task(t),
            )
            results.append({
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "status": result.get("status", "SUCCESS"),
                "result": result,
            })

        elif task_type == "user_task":
            # ---- Situation B: designed await on an authorized human ----
            # FIRST register the visible HumanTask (durable) so the authorized
            # approver(s) can SEE it, THEN suspend on the promise. Registration
            # is required — a UserTask with no audience is a config error (the
            # KeyError fails the workflow loudly rather than suspending invisibly).
            await ctx.run(
                f"register_{task_id}",
                lambda t=task: _register_human_task(workflow_id, t, user_jwt),
            )
            # The workflow suspends here indefinitely. No polling, no CPU, no
            # memory. Restate holds a few bytes of journal state until an
            # AUTHORIZED human resolves the promise (via /human_tasks/{id}/act ->
            # the approve handler). An UNAUTHORIZED /act is denied at cortex-bff's
            # can_act gate and never reaches here — the workflow stays suspended,
            # correctly waiting for the right approver (not torn down).
            promise_name = f"approval_{task_id}"
            approval = await ctx.promise(promise_name, type_hint=dict).value()
            results.append({
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "status": approval.get("status", "APPROVED"),
                "approval": approval,
            })

        else:
            # Unknown task type — skip with warning
            results.append({
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "status": "SKIPPED",
                "reason": f"Unknown task type: {task_type}",
            })

    return {
        "workflow_id": workflow_id,
        "status": "COMPLETED",
        "task_results": results,
    }


@bpmn_workflow.handler()
async def approve(ctx: WorkflowSharedContext, request: dict) -> dict:
    """Resolve a durable promise to wake up a paused UserTask.

    Called by the FastAPI ``/workflow/{wf}/task/{tid}/approve`` endpoint.
    This resolves the promise that the ``run`` handler is awaiting,
    causing the workflow to resume execution from exactly where it
    left off.

    Args:
        ctx: Restate shared workflow context.
        request: Dict with keys:
            - ``task_id`` (str): The BPMN task to approve.
            - ``status`` (str): e.g. "APPROVED" or "REJECTED".
            - ``comments`` (str): Optional human comments.

    Returns:
        Confirmation dict.
    """
    task_id = request["task_id"]
    promise_name = f"approval_{task_id}"

    approval_payload = {
        "status": request.get("status", "APPROVED"),
        "comments": request.get("comments", ""),
        "task_id": task_id,
    }

    await ctx.promise(promise_name, type_hint=dict).resolve(approval_payload)

    return {
        "message": f"Promise '{promise_name}' resolved — workflow will resume",
        "task_id": task_id,
        "status": approval_payload["status"],
    }


# ---------------------------------------------------------------------------
# Restate Service — ProcessInterviewer (VirtualObject for durable local state)
# ---------------------------------------------------------------------------
process_interviewer_service = VirtualObject("ProcessInterviewer")

@process_interviewer_service.handler()
async def process_message(ctx: ObjectContext, request: dict) -> dict:
    thread_id = ctx.key()  # Use the key as the thread_id since it is a VirtualObject
    user_msg = request.get("user_query", "")
    bootstrap_context = request.get("bootstrap_context", "")
    
    history_key = f"history_{thread_id}"
    graph_key = f"graph_{thread_id}"
    
    chat_history = await ctx.get(history_key) or ""
    current_graph_dict = await ctx.get(graph_key) or {"nodes": [], "edges": []}
    current_graph_json = json.dumps(current_graph_dict) if isinstance(current_graph_dict, dict) else current_graph_dict

    # 1. Initialize Bootstrap Context on the first turn
    if not chat_history and bootstrap_context:
        chat_history = f"SYSTEM: Use the following baseline data extracted from the Graph Database to help draft the initial process:\n{bootstrap_context}\n\n"
    # 2. Fetch Live Ontologies and Data Catalogs
    async def fetch_catalogs():
        import httpx
        ontologies = "- (No live ontology data available)"
        data_sources = "- (No live data sources available)"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Engine O: Ontology Service
            try:
                _ONTOLOGY_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://ontology-service:8084")
                resp = await client.get(f"{_ONTOLOGY_URL}/classes")
                if resp.status_code == 200:
                    classes = resp.json().get("classes", [])
                    ont_lines = [f"- {c.get('uri')}  ({c.get('label')})" for c in classes]
                    if ont_lines:
                        ontologies = "\n".join(ont_lines)
            except Exception:
                pass # Fallback to default
                
            # Engine D: DataHub Wrapper (Dynamic search enabled)
            data_sources = "- dbt_model: (Metadata discovered dynamically during execution via /query_metadata)"
                
        return {
            "ontologies": ontologies, 
            "data_sources": data_sources
        }
        
    catalog_data = await ctx.run("fetch_catalogs", fetch_catalogs)
    ontologies = catalog_data["ontologies"]
    data_sources = catalog_data["data_sources"]
    
    # 3. Call the Socratic BAML Compiler (Must return model_dump)
    async def call_baml_interview():
        state = await b.IterateBPMNGraph(
            chat_history=chat_history,
            user_message=user_msg,
            current_graph_json=current_graph_json,
            available_ontology_classes=ontologies,
            available_data_sources=data_sources
        )
        return state.model_dump() # 🟢 CRITICAL: Serialize Pydantic to Dict for Restate

    state_dict = await ctx.run("baml_interview", call_baml_interview)
    
    # 4. Extract variables from the dictionary safely
    is_complete = state_dict.get("is_ready_to_compile", False)
    agent_reply = state_dict.get("agent_reply", "")
    
    new_history = chat_history + f"\nUser: {user_msg}\nAgent: {agent_reply}"
    ctx.set(history_key, new_history)
    
    # 5. Format the UI Payload securely
    ui_nodes = []
    for n in state_dict.get("nodes", []):
        n_type = n["node_type"] if isinstance(n["node_type"], str) else str(n["node_type"])
        ui_nodes.append({
            "id": n["id"], 
            "name": n["name"], 
            "type": n_type, 
            "description": f"Ontology: {n.get('ontology_class')} | Data: {n.get('data_source')}"
        })
        
    ui_edges = [{"source": e["source_id"], "target": e["target_id"], "label": e.get("condition_expression", "")} for e in state_dict.get("edges", [])]
    
    new_graph_dict = {"nodes": ui_nodes, "edges": ui_edges}
    ctx.set(graph_key, new_graph_dict)
    
    return {
        "is_complete": is_complete,
        "chat_reply": agent_reply,
        "raw_bpmn_payload": {"tasks": ui_nodes, "gateways": [], "sequence_flows": ui_edges}, # Passed back for the compiler
        "ui_payload": {
            "components": [
                {
                    "archetype": "PROCESS_TOPOLOGY",
                    "subject_concept": "Live BPMN Draft",
                    "nodes": ui_nodes,
                    "edges": ui_edges
                }
            ]
        }
    }

@process_interviewer_service.handler()
async def get_status(ctx: ObjectContext, request: dict) -> dict:
    thread_id = ctx.key()
    history_key = f"history_{thread_id}"
    chat_history = await ctx.get(history_key) or []
    # An interview is active if there are messages and it hasn't concluded with the Graph payload
    is_active = len(chat_history) > 0 and chat_history[-1] != "[Process Graph Generated]"
    return {"is_active": is_active}


# ---------------------------------------------------------------------------
# Restate Service — ProcessInterviewerV2 (the SPO interview; ADR-0029 Slice 2)
# ---------------------------------------------------------------------------
# Supersedes ProcessInterviewer: re-aims the interview at the git-asserted
# WorkflowDefinition model (not a BPMN graph), adds the VERB question, and moves
# every enforcement decision SERVER-SIDE. This VirtualObject is a THIN durable
# shell over the pure, unit-tested core (spo_interview.py): it holds the
# InterviewState + chat history + focused subject across turns, computes the
# authorized sets from Engine O, calls the BAML shell for the next pick, and runs
# the pick through the enforcement funnel. The LLM only PROPOSES; the funnel
# DECIDES. Old ProcessInterviewer left in place (staged retirement).
process_interviewer_v2_service = VirtualObject("ProcessInterviewerV2")

_ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
# Audience-sourcing is a follow-up: the real set is the task_audience grants
# (policy/task_grants.yaml). Until wired, the caller supplies the audiences the
# author may route to; this default keeps the promotion workflow authorable.
_DEFAULT_AUDIENCES = [{"audience": "promotion:DATA_ENGINEERING"}]

_ISTATE_FIELDS = ("id", "name", "classification", "participants", "domain_stages",
                  "steps", "observable_state")


def _norm_set(items, key: str) -> list[dict]:
    """Accept a list of strings OR {key: value} dicts -> list of {key: value} dicts."""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(it)
        elif it:
            out.append({key: str(it)})
    return out


def _render_subjects(subjects: list[dict]) -> str:
    return "\n".join(f"- {s.get('uri')}  ({s.get('label', '')})" for s in subjects) \
        or "- (no subjects visible to you yet)"


def _render_verbs(verbs: list[dict]) -> str:
    return "\n".join(f"- {v.get('verb_iri')}  (output: {v.get('output_uri', '')})" for v in verbs) \
        or "- (focus a subject first — verbs are computed for the chosen subject)"


def _render_audiences(auds: list[dict]) -> str:
    return "\n".join(f"- {a.get('audience')}" for a in auds) or "- (no audiences available)"


@process_interviewer_v2_service.handler()
async def spo_turn(ctx: ObjectContext, request: dict) -> dict:
    """One turn of the SPO interview.

    request: {user_query, caller_email, workflow_domain?, available_audiences?,
              available_capabilities?}. Durable VO state (keyed on ctx.key()):
    the accumulating InterviewState, the chat history, and the focused subject
    (whose compatible verbs are offered next turn)."""
    # Lazy dual-path import, matching this file's container/dev import dance.
    try:
        import spo_interview as si  # type: ignore[no-redef]
    except ImportError:
        from agent_fleet.restate_analyst import spo_interview as si

    user_msg = request.get("user_query", "")
    caller_email = request.get("caller_email") or request.get("user_email") or ""
    req_domain = request.get("workflow_domain")
    audiences = _norm_set(request.get("available_audiences") or _DEFAULT_AUDIENCES, "audience")
    capabilities = request.get("available_capabilities")
    capabilities = _norm_set(capabilities, "capability") if capabilities is not None else None

    raw_state = await ctx.get("state") or {}
    chat_history = await ctx.get("history") or ""
    focused_subject = await ctx.get("focused_subject") or ""

    state = si.InterviewState(**{k: v for k, v in raw_state.items() if k in _ISTATE_FIELDS})
    scope_domain = state.classification or req_domain or "MAINTENANCE"

    # 1. Compute the authorized sets (network — Engine O). The OPERATION-subject menu
    #    is sourced from the CAPABILITY GRAPH (Decision D — design §8): only subjects the
    #    mesh can act on (>=1 verb), domain- + can_view-scoped to the AUTHOR — so every
    #    offered subject leads to a verb (no 94%-dead-end ontology-vocabulary menu). Verbs
    #    are for the focused subject only. (Nameable-role menus — human_await subject_ref /
    #    participants — would source from si.authorized_subjects/`/classes`; that role-split
    #    is a follow-up once the BAML shell distinguishes the questions.)
    async def compute_sets():
        subjects = si.authorized_operation_subjects(caller_email, engine_o_url=_ENGINE_O_URL, domain=scope_domain)
        verbs = (si.authorized_verbs(focused_subject, workflow_domain=state.classification,
                                     engine_o_url=_ENGINE_O_URL) if focused_subject else [])
        return {"subjects": subjects, "verbs": verbs}

    sets = await ctx.run("authorized_sets", compute_sets)
    subjects, verbs = sets["subjects"], sets["verbs"]

    # 2. Ask the BAML shell for the next pick (it PROPOSES; the funnel DECIDES).
    async def call_baml():
        turn = await b.InterviewSPOWorkflow(
            chat_history=chat_history,
            user_message=user_msg,
            partial_definition_json=json.dumps(state._assemble()),
            available_subjects=_render_subjects(subjects),
            available_verbs=_render_verbs(verbs),
            available_audiences=_render_audiences(audiences),
        )
        return turn.model_dump()

    turn_dict = await ctx.run("baml_turn", call_baml)
    agent_reply = turn_dict.get("agent_reply", "")
    pick = turn_dict.get("pick") or {"action": "NoPick"}
    action = str(pick.get("action") or "NoPick")

    # 3. Apply the pick through the SERVER-SIDE enforcement funnel.
    refusal = None
    applied = None
    if action == "FocusSubject":
        subj = str(pick.get("subject_uri") or "")
        try:
            si.validate_pick(subj, subjects, key="uri")  # can't focus an unseen subject
            focused_subject = subj
        except si.PickRefused as e:
            refusal = str(e)
    elif action == "AddSpoStep":
        # Recompute verbs for the EXACT proposed subject, so the verb is checked against
        # that subject's eligibility, never a stale/other set (defense-in-depth).
        subj = str(pick.get("subject_uri") or "")
        try:
            si.validate_pick(subj, subjects, key="uri")

            async def verbs_for_pick():
                return si.authorized_verbs(subj, workflow_domain=state.classification,
                                           engine_o_url=_ENGINE_O_URL)

            fresh_verbs = await ctx.run("verbs_for_pick", verbs_for_pick)
            applied = si.apply_pick(state, pick, authorized_subjects=subjects,
                                    authorized_verbs=fresh_verbs, authorized_audiences=audiences,
                                    authorized_capabilities=capabilities)
        except (si.PickRefused, ValueError) as e:
            refusal = str(e)
    else:
        try:
            applied = si.apply_pick(state, pick, authorized_subjects=subjects,
                                    authorized_verbs=verbs, authorized_audiences=audiences,
                                    authorized_capabilities=capabilities)
        except (si.PickRefused, ValueError) as e:
            refusal = str(e)

    # 4. Termination = the definition VALIDATES (server-side, not an LLM flag).
    definition, gaps = si.try_finalize(state)
    definition_yaml = si.emit_definition_yaml(definition) if definition else None

    # 5. Persist durable state for the next turn.
    reply_suffix = f" (refused: {refusal})" if refusal else ""
    ctx.set("state", state._assemble())
    ctx.set("history", f"{chat_history}\nUser: {user_msg}\nAgent: {agent_reply}{reply_suffix}")
    ctx.set("focused_subject", focused_subject)

    return {
        "agent_reply": agent_reply,
        "refusal": refusal,                       # set iff a pick was rejected out-of-set
        "applied_step": applied,                  # the step appended this turn, or null
        "focused_subject": focused_subject,
        "gaps": gaps,                             # what's still missing to validate
        "is_complete": definition is not None,    # true when the definition VALIDATES
        "definition_yaml": definition_yaml,       # the file a HUMAN commits (Decision C)
        "partial_definition": state._assemble(),
    }


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger("RestateAnalyst")

# Engine self-registration for the predicate-graph routing layer
# (iagent ADR-0004 Step D.1). Opt-in via MESH_REGISTER_ON_STARTUP; the helper
# logs a clear "skipping" message when disabled or when DataHub creds are
# missing, and never crashes the engine. Engine A is the first hardcoded
# engine to register; the others (E, DA, W, etc.) follow the same call
# pattern when D.1 propagates.
try:
    from utils.mesh_registration import register_engine_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Boot Sequence
    logger.info("Initializing Engine A: Late Binding enabled (JIT Tool Injection).")

    # Register as typed predicate edges in the mesh routing graph.
    #
    # Per ADR-0017, Engine A advertises one registration per question
    # shape it handles, each with a specific output_uri. Same pod, same
    # endpoint URL, six distinct verb edges in the predicate graph. The
    # inbound mesh task envelope carries the routed verb so this engine's
    # handler can select the per-verb prompt block and echo the matching
    # output_uri in the response.
    #
    # The pre-existing `mesh:analyzeWithCodeAgent` registration (with
    # output_uri `mesh:AgentResponse`) is retained at the end of this
    # block as a fallback for queries that don't match any specific verb's
    # synonyms. It is scheduled for removal once the audit table shows
    # the specific verbs cover the observed query distribution (ADR-0017
    # §1 open item).
    _engine_a_endpoint = os.getenv(
        "ENGINE_A_PUBLIC_URL",
        "http://iagent-engine-a:8081/analyze",
    )
    _engine_a_domains = ["MAINTENANCE", "MANUFACTURING", "SUSTAINMENT", "DATA_ENGINEERING"]

    register_engine_to_mesh(
        name="engine_a_lookup_ownership",
        description=(
            "Answers who owns a specific dataset, dashboard, or chart in "
            "the DataHub catalog. Returns the owner identity (email, team) "
            "and the ownership timestamp. Does NOT walk lineage or inspect "
            "schema — use mesh:traceLineage or mesh:findSchema for those."
        ),
        verb="mesh:lookupOwnership",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#OwnershipFact",
        verb_synonyms=[
            "who owns", "owner of", "ownership of",
            "list assets owned by", "who is responsible for",
            "owning team for", "who maintains",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_trace_lineage",
        description=(
            "Walks the upstream/downstream lineage graph from a named "
            "asset in DataHub. Returns the full lineage chain or topology, "
            "recursively traversing until the upstream-empty source-of-"
            "truth node is reached. Use this for 'what feeds X' or 'what "
            "is the source of truth for X' questions."
        ),
        verb="mesh:traceLineage",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#LineageTopology",
        verb_synonyms=[
            "what is the lineage", "lineage of",
            "source of truth", "raw source of",
            "what feeds", "upstream of", "trace lineage",
            "underlying source systems", "raw tables behind",
        ],
        # ADR-0008 follow-up: explicitly repel catalog-enumeration phrasings.
        # The 5fee663d run scored this verb at 0.71 for "what tables do
        # you have" against the BM25 lexical match on "what" and "tables"
        # in the synonyms / description. Adding anti-synonyms drops the
        # BM25 score via Engine O's _anti_synonym_overlap re-rank so
        # mesh:enumerateCatalog (the right verb) wins the ranking.
        verb_anti_synonyms=[
            "what tables do you have", "what datasets do you have",
            "list tables", "list datasets", "list dashboards",
            "show me the catalog", "show all tables",
            "what's in the warehouse", "what's in the catalog",
            "enumerate catalog", "browse catalog",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_assess_impact",
        description=(
            "Identifies the set of downstream assets impacted by a change "
            "to a named asset. Walks the downstream lineage graph and "
            "returns the blast-radius set: which dashboards, datasets, "
            "and charts depend on this asset and would be affected if it "
            "changed schema or broke."
        ),
        verb="mesh:assessImpact",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#ImpactSet",
        verb_synonyms=[
            "downstream impact", "what breaks if",
            "what is impacted by", "blast radius",
            "consumers of", "what depends on",
            "downstream of", "if X changes what breaks",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_find_schema",
        description=(
            "Returns the column schema of a named dataset in DataHub: "
            "field names, data types, and field descriptions. Use this "
            "for 'what columns does X have' or 'what is the schema of X' "
            "questions. Does NOT return row data — that's Engine DA's job."
        ),
        verb="mesh:findSchema",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#SchemaDescription",
        verb_synonyms=[
            "what columns", "schema of", "data types",
            "fields of", "column descriptions",
            "what fields does", "describe schema",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_check_freshness",
        description=(
            "Reports the last-updated timestamp of a named dataset and "
            "compares it against an SLA or staleness threshold if "
            "provided. Use this for 'when was X last updated', 'is X "
            "stale', or freshness-SLA questions."
        ),
        verb="mesh:checkFreshness",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#FreshnessReport",
        verb_synonyms=[
            "when was last updated", "last updated",
            "freshness", "is it stale", "data freshness",
            "how recent is", "is the data current",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_filter_by_tag",
        description=(
            "Returns datasets, dashboards, or charts matching a given tag "
            "in the DataHub catalog, optionally composed with a secondary "
            "condition (e.g. tagged X AND exposed to a downstream "
            "dashboard, tagged Y AND owned by team Z). Handles PII-"
            "exposure audits, sensitive-data compliance checks, and any "
            "other tag-conditional asset query. Composes the cross-"
            "feature predicate: tag-match AND optional-condition-check."
        ),
        verb="mesh:filterByTag",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#TagFilterResult",
        verb_synonyms=[
            "tagged", "datasets tagged", "assets tagged",
            "filter by tag", "find assets with tag",
            "tagged pii", "pii datasets", "pii exposure",
            "compliance audit", "pii audit", "sensitive data exposed",
            "what pii is exposed", "pii datasets in dashboards",
            "datasets tagged X exposed to", "assets tagged X owned by",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_describe_asset",
        description=(
            "Returns a structured profile of a named asset in the DataHub "
            "catalog: owner, tags, domain, description, last-updated "
            "timestamp, and a high-level summary. Use this for general "
            "'tell me about X' or 'describe X' questions where the user "
            "wants an overview rather than a specific attribute. For "
            "single-attribute lookups (owner only, schema only, freshness "
            "only), the more specific verbs rank higher."
        ),
        verb="mesh:describeAsset",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#AssetProfile",
        verb_synonyms=[
            "describe", "describe dataset", "describe dashboard",
            "tell me about", "profile of", "summarize",
            "what is", "overview of", "asset profile",
            "give me the rundown on", "summary of",
        ],
        # ADR-0008 follow-up: repel multi-asset / catalog-listing phrasings.
        # describeAsset is single-asset by contract; questions framed as
        # "list / show all / what tables" are asking for the enumeration
        # verb, not a single-asset profile.
        verb_anti_synonyms=[
            "list all", "show all", "what tables do you have",
            "what datasets do you have", "enumerate", "catalog listing",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    register_engine_to_mesh(
        name="engine_a_enumerate_catalog",
        description=(
            "Returns a flat list of data assets (tables, datasets, "
            "dashboards) in the DataHub catalog, optionally scoped by "
            "tier (bronze/silver/gold), domain, or platform. Use this "
            "for catalog-enumeration questions where the user has no "
            "specific asset in mind and wants to see what is available: "
            "'what tables do you have', 'list datasets', 'show me the "
            "catalog', 'what's in the warehouse'. Does NOT walk lineage, "
            "inspect schema, or describe any single asset — use the "
            "asset-specific verbs for those. Outputs CatalogListing "
            "which renders as a flat KNOWLEDGE_DOCUMENT panel, NOT a "
            "lineage topology graph."
        ),
        verb="mesh:enumerateCatalog",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#CatalogListing",
        verb_synonyms=[
            "what tables do you have",
            "what datasets do you have",
            "what data do you have",
            "list tables", "list datasets", "list dashboards",
            "list all tables", "list all datasets",
            "show all tables", "show all datasets",
            "show me the catalog", "show me what's available",
            "show me what's in datahub",
            "what's in the warehouse", "what's in the catalog",
            "what assets are available", "what data is available",
            "enumerate catalog", "catalog listing",
            "all tables in", "all datasets in",
            "browse catalog", "browse datasets",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",
    )

    # --- Fallback: generic catalog-Q&A verb (ADR-0017 transition window). ---
    # Retained for queries that don't match any specific verb's synonyms.
    # The router scores the specific verbs higher when their synonyms hit;
    # everything else falls through to this entry. Scheduled for removal
    # per ADR-0017 §1 open item.
    register_engine_to_mesh(
        name="engine_a_restate_analyst",
        description=(
            "Metadata analysis engine. Answers questions ABOUT datasets, "
            "dashboards, and charts in the DataHub catalog: who owns what, "
            "what feeds what (lineage), when was X last updated, what "
            "columns does Y have, which assets are tagged PII, what breaks "
            "if Z's schema changes. Searches the catalog via DataHub, "
            "follows lineage by chaining queries. Does NOT read the "
            "underlying rows of any dataset — that's a separate engine."
        ),
        verb="mesh:analyzeWithCodeAgent",
        input_uri="http://invincible-agent/mesh#AgentTask",
        output_uri="http://invincible-agent/mesh#AgentResponse",
        verb_synonyms=[
            "catalog question", "metadata question",
            "who owns", "list assets owned by",
            "what is the lineage", "source of truth",
            "downstream impact", "what breaks if",
            "when was last updated", "freshness", "is it stale",
            "what columns", "schema of", "data types",
            "tagged pii", "compliance audit", "ownership audit",
            "describe dataset", "investigate metadata",
        ],
        endpoint_url=_engine_a_endpoint,
        owner_persona="DATA_STEWARD",
        domains=_engine_a_domains,
        cost_class="slow",  # smolagents loops are not cheap
    )

    yield

    # Teardown Sequence
    logger.info("Shutting down Engine A...")

app = FastAPI(
    title="Engine A — Restate Analyst",
    description=(
        "Durable analyst agent powered by Restate + HuggingFace Smolagents. "
        "Resolves ontology context via Engine O before analysis."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Restate Virtual Object — DagsterRunTracker
# ---------------------------------------------------------------------------
# Lives in a sibling module so its handler logic can be unit-tested without
# importing the rest of this file (which pulls in smolagents / baml_client).
# Try/except needed because the container Dockerfile flattens this directory
# into /app/ (so the sibling is at /app/dagster_run_tracker.py without the
# `agent_fleet.restate_analyst.` prefix), while dev runs import via the
# full package path.
try:
    from dagster_run_tracker import run_tracker  # noqa: E402  — container path
except ImportError:
    from agent_fleet.restate_analyst.dagster_run_tracker import (  # noqa: E402
        run_tracker,
    )

# Mount the Restate SDK so it handles /restate/* routes
app.mount("/restate", restate.app(services=[analyst_service, bpmn_workflow, process_interviewer_service, process_interviewer_v2_service, run_tracker]))


# ---------------------------------------------------------------------------
# Request model for the proxy endpoint
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    """Proxy request model — mirrors AgentTask."""
    task_description: str
    dataset_id: str
    semantic_context: dict | None = None


# ---------------------------------------------------------------------------
# POST /analyze — proxy route for Dagster
# ---------------------------------------------------------------------------
@app.post("/analyze")
async def analyze_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate AnalystService.

    Dagster (and other external callers) POST to ``/analyze`` with an
    ``AgentTask`` JSON body. This route forwards the payload to the Restate Ingress
    at /{ServiceName}/{MethodName} for durable execution.
    """
    try:
        payload = await request.json()
        
        # Inject the incoming request Authorization into the Restate payload
        auth_header = request.headers.get("Authorization")
        if auth_header:
            payload["user_jwt"] = auth_header
            
        import uuid
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        payload["trace_id"] = trace_id
            
        target_url = f"{RESTATE_INGRESS_URL}/AnalystService/analyze"

        # Match the supervisor's per-engine call timeout (1800s post-
        # ADR-0017). The Engine A smolagent loop can take many minutes
        # per multi-step reasoning task on slow Ollama backends; 300s
        # reliably timed out mid-loop, 900s started failing when
        # per-verb prompts narrowed the agent into deeper recursive
        # lineage walks (Q3 lineage_src, Q8 catalog_superset).
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(
                target_url,
                json=payload,
            )
            # Bubble up the exact response and status code from Restate
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.text else {}
            )
    except Exception as exc:
        print(f"DEBUG: Restate proxy call failed for AnalystService: {exc}")
        return JSONResponse(
            content={
                "status": AgentStatus.FAILED.value,
                "summary": f"Restate proxy call failed: {exc}",
                "extracted_metrics": {},
            },
            status_code=502,
        )


# ---------------------------------------------------------------------------
# BPMN Workflow request models
# ---------------------------------------------------------------------------
class WorkflowStartRequest(BaseModel):
    """Request to start a BPMN workflow run."""
    workflow_id: str
    tasks: list[dict]
    # Initiator JWT — threaded into the run so service tasks can authenticate to
    # gated engines (and hit real Topaz denials) and UserTasks can register their
    # HumanTask against cortex-bff. Optional (empty = unauthenticated internal run).
    user_jwt: str = ""


class ApprovalRequest(BaseModel):
    """Request to approve (or reject) a paused UserTask."""
    status: str = "APPROVED"
    comments: str = ""


# ---------------------------------------------------------------------------
# POST /workflow/start — kick off a BPMN workflow
# ---------------------------------------------------------------------------
@app.post("/workflow/start")
async def start_workflow(req: WorkflowStartRequest) -> JSONResponse:
    """Start a new BPMN workflow execution via Restate.

    Sends the task list to the BPMNWorkflowRunner's ``run`` handler.
    The workflow_id is used as the Restate workflow key.
    """
    try:
        resp = requests.post(
            f"{RESTATE_INGRESS_URL}/BPMNWorkflowRunner/{req.workflow_id}/run",
            json={"workflow_id": req.workflow_id, "tasks": req.tasks,
                  "user_jwt": req.user_jwt},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return JSONResponse(
            content={"message": f"Workflow '{req.workflow_id}' started", "workflow_id": req.workflow_id},
            status_code=202,
        )
    except requests.RequestException as exc:
        return JSONResponse(
            content={"error": f"Failed to start workflow: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# POST /workflow/{workflow_id}/task/{task_id}/approve — resolve a UserTask
# ---------------------------------------------------------------------------
@app.post("/workflow/{workflow_id}/task/{task_id}/approve")
async def approve_task(
    workflow_id: str,
    task_id: str,
    req: ApprovalRequest,
) -> JSONResponse:
    """Approve (or reject) a paused BPMN UserTask.

    This endpoint calls the BPMNWorkflowRunner's ``approve`` handler
    via the Restate HTTP ingress.  The handler resolves the durable
    promise that the ``run`` handler is awaiting, causing the workflow
    to resume execution from exactly where it left off.

    Zero-cost waiting: the workflow consumes no compute while paused.
    Crash-proof: Restate replays from its journal on restart.
    """
    try:
        resp = requests.post(
            f"{RESTATE_INGRESS_URL}/BPMNWorkflowRunner/{workflow_id}/approve",
            json={
                "task_id": task_id,
                "status": req.status,
                "comments": req.comments,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return JSONResponse(
            content={
                "message": f"Task '{task_id}' in workflow '{workflow_id}' approved",
                "workflow_id": workflow_id,
                "task_id": task_id,
                "status": req.status,
            },
            status_code=200,
        )
    except requests.RequestException as exc:
        return JSONResponse(
            content={"error": f"Failed to approve task: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Simple liveness probe."""
    return {"status": "ok", "engine": "restate_analyst"}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
