import asyncio
import json
import os
from contextlib import asynccontextmanager

import duckdb
import restate
from fastapi import FastAPI, Request
from restate import Context, Service
from smolagents import CodeAgent, tool

# Engine self-registration for the predicate-graph routing layer
# (iagent ADR-0004 Step D.1). Opt-in via MESH_REGISTER_ON_STARTUP.
try:
    from utils.mesh_registration import register_engine_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh
# Fallback routing for Topaz Authz and Dag Tools
try:
    from agent_fleet.core.authz import require_topaz_auth_decorator
except ImportError:
    from core.authz import require_topaz_auth_decorator
# Shared smolagents model factory — honors SMOLAGENTS_PROVIDER/SMOLAGENTS_MODEL/OLLAMA_BASE_URL.
# Avoids the hardcoded gpt-4o-mini that this engine had before.
try:
    from agent_fleet.llm_utils import get_smolagent_model
except ImportError:
    from llm_utils import get_smolagent_model

# Telemetry (ADR-0038): join Engine D's work to the caller's trace via observed_trace
# (create_trace_id(seed=X-Trace-Id)). telemetry.py is at /app in the fleet image; guarded so
# the engine runs identically when the shim/leaf is absent (no-op).
try:
    from telemetry import observed_trace, MAPPING, build_trace_values  # type: ignore[no-redef]
except Exception:  # pragma: no cover — telemetry never load-bearing
    from contextlib import contextmanager as _cm

    @_cm
    def observed_trace(*_a, **_k):  # type: ignore[misc]
        yield

    def build_trace_values(**_k):  # type: ignore[misc]
        return {}

    MAPPING = None

try:
    from dag_tools.cortex_data.client import CortexDataClient
except ImportError:
    # Fallback for some container layouts
    try:
        from cortex_data.client import CortexDataClient
    except ImportError:
        # Fallback for package-based install
        try:
            import dag_tools.cortex_data.client as cortex_client
            CortexDataClient = cortex_client.CortexDataClient
        except ImportError:
            raise

# Engine DA's lifespan registers it as a predicate in the mesh routing graph.
# Engine DA generates and executes SQL via smolagents over DataHub assets;
# returns a structured dataset analysis report.
@asynccontextmanager
async def lifespan(app: FastAPI):
    register_engine_to_mesh(
        name="engine_da_data_analyst",
        description=(
            "Data analysis engine. Executes SQL or Polars expressions over "
            "the actual ROWS of a SPECIFIC dataset whose URN is already "
            "known. Reads via CortexDataClient with Topaz row/column "
            "policies enforced. REQUIRES the caller to supply a URN — does "
            "NOT discover or search the catalog. For catalog Q&A "
            "(ownership, lineage, freshness, schema) use the metadata "
            "analysis engine instead. See ADR-0014."
        ),
        verb="mesh:analyzeDataset",
        input_uri="http://invincible-agent/idp#Dataset",
        output_uri="http://invincible-agent/mesh#DatasetAnalysisReport",
        verb_synonyms=[
            "execute SQL on", "run SQL against urn",
            "aggregate rows", "sum revenue from",
            "top customers by", "filter rows where",
            "calculate from data", "row-level analytics",
            "compute over dataset",
        ],
        endpoint_url=os.getenv(
            "ENGINE_DA_PUBLIC_URL",
            "http://iagent-data-analyst:8089/analyze_data",
        ),
        owner_persona="DATA_STEWARD",
        # Per ADR-0009: DA is no longer a special case routed by an
        # `if domain == "DATA_ENGINEERING"` switch — it's a normal
        # domain citizen that registers the domains it serves.
        domains=["DATA_ENGINEERING"],
        cost_class="slow",
    )
    yield


# Initialize FastAPI
app = FastAPI(lifespan=lifespan)

# Define the Restate Service
data_analyst_service = Service("DataAnalystService")

# ---------------------------------------------------------------------------
# REPLAY-SEAL SCAFFOLDING (env-gated, default 0 = no-op; never fires in normal operation)
# ---------------------------------------------------------------------------
# Same shape as ``dispatch_driver``'s ``PCN_SEAL_PAUSE_AFTER_*``: durable-execution behaviour is
# only observable across a REPLAY, and a replay has to be manufactured on purpose or the seal will
# never run.
#
# WHY A DELIBERATE FAILURE AND NOT A POD KILL — measured, not assumed (2026-08-05). The obvious
# manufacture is to delete the pod mid-handler. Restate does retry (witnessed: a handler killed at
# t=5s returned 200 after 30.6s total), but the FIRST attempt's evidence dies with it: the OTel
# batch exporter had not flushed, so the killed execution's boundary span never reached Langfuse
# and the trace showed ONE span for TWO executions. **The instrument shared a fate with the thing
# being killed** — it undercounts in exactly the scenario it exists to measure.
#
# Failing after the work instead keeps the process alive, so every counter (stdout, the exporter,
# the journal) survives and reports honestly. It is also deterministic: no timing race against a
# variable-length LLM round-trip.
#
# The failure is a PLAIN exception, deliberately NOT a TerminalError — Restate must RETRY it, which
# is the whole point. The budget is per-process, so attempt 1 fails and attempt 2 completes; a
# fresh pod resets it, which bounds the blast radius to one extra execution per pod.
_SEAL_FAIL_AFTER_WORK = int(os.getenv("DA_SEAL_FAIL_AFTER_WORK", "0") or 0)
_seal_failures_used = 0

@app.get("/health")
async def health():
    return {"status": "ok"}


def _is_access_denied(exc: Exception) -> bool:
    """True iff `exc` is a data-plane ACCESS DENIAL (central-gateway can_read
    403) — as opposed to an empty result, a URN-not-found, a data-plane
    outage, or a code fumble. Keyed on the gate's SPECIFIC 403 so the UI
    surfaces 'request access' ONLY for real authorization denials, never for
    fumbles/empties (a fumble isn't fixed by requesting access)."""
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 403:
        return True
    s = str(exc).lower()
    return "403" in s and ("forbidden" in s or "not authorized" in s or "/authorize" in s)


def _access_denied_response(assets: list, subject: str, sources: list) -> dict:
    """The STRUCTURED access-denied engine response (Bug 2). Distinct
    `status` so the pipeline/UI can offer the HITL request-access flow
    (/access_requests) rather than rendering an empty chart that hides the
    denial. Carries the denied asset + the subject the request is filed for."""
    asset = assets[0] if assets else ""
    msg = (
        "Access denied: you are not authorized to read this dataset"
        + (f" ({asset})" if asset else "")
        + ". You can request access."
    )
    return {
        "status": "access_denied",
        "denied_assets": assets,
        "subject": subject or "",
        "message": msg,
        # `data` too, so the existing pipeline (which reads engine_response
        # data) degrades gracefully to the denial text even before the
        # access_denied signal is projected to the UI (Bug 2B/2C).
        "data": msg,
        "sources": sources,
    }


@data_analyst_service.handler()
async def analyze_data(ctx: Context, request: dict) -> dict:
    # NB: require_topaz_auth_decorator was removed from this handler. It
    # was written for FastAPI (looks for a Request in args/kwargs) and
    # its `*args, **kwargs` wrapper signature blinds Restate's inspect-
    # based handler-arg detection — Restate then calls `func(ctx)` and
    # the handler errors with "missing required positional argument:
    # request". The central-gateway already enforces authz on the data
    # path; engine-side authz can be re-added once the decorator is
    # rewritten to be Restate-compatible.
    user_jwt = None
    # Translates user intent into SQL queries, executes them securely via DuckDB/Polars,
    # and formats the output into UI widgets.
    # Supervisor sends `user_query`; legacy/direct callers send `query`.
    user_query = request.get("user_query") or request.get("query") or "Analyze the data"
    dynamic_schema_map = request.get("dynamic_schema_map", "")
    # The end user's Keycloak sub. The data client carries it through to
    # central-gateway so user-level deny lists / row-level filters apply
    # even though we're using a service-account JWT for the actual call.
    originator_sub = request.get("user_id") or None
    # The end user's authz_id / entitlement key (email in sandbox). The
    # supervisor already sends this as `user_email` (= current_user.authz_id
    # post-consolidation); DA previously DROPPED it. It's the key the
    # email-keyed central-gateway can_read gate needs — threaded to the
    # CortexDataClient below as originator_email → X-Originator-Email.
    originator_email = request.get("user_email") or None

    # Tier-3 fix (2026-06-16): the supervisor now threads the resolved
    # instance URN through to this handler so DA queries the SAME URN
    # that /resolve produced rather than fabricating one from training
    # data or schema-map context.
    #
    # The fabrication bug this closes: previously the supervisor's
    # dispatch payload OMITTED the URN, DA's handler had no field to
    # extract it from, and the prompt told the agent to "call
    # search_datahub" — a tool not in DA's roster. The agent fell back
    # to inventing a URN from training-data plausibility, then queried
    # it, then returned "not found" for a fabricated identifier that
    # never had a chance of matching.
    #
    # The new contract: the supervisor passes the real URN as
    # `resolved_instance_id`. DA presents it explicitly to the agent
    # and instructs query_datahub_asset to use exactly that URN. When
    # no URN was resolved upstream (provenance.instance_resolved=false
    # or /resolve unreachable), DA tells the agent to return honest
    # not-found — NOT to invent one.
    resolved_instance_id = request.get("resolved_instance_id", "")

    # Engine DA's prompt deliberately does NOT inject hardcoded URN hints.
    # Earlier versions had a `sandbox_urn_hints` block enumerating 6 specific
    # URNs (postgres / clickhouse / s3 sales_customers variants) so the
    # smolagent had something to point query_datahub_asset at without
    # hallucinating. That hint set was added during overnight backend-
    # coverage testing — see ADR-0014 for why it has to leave.
    #
    # Once Engine DA was reachable through the predicate router, the
    # hardcoded hints became a context poison: the supervisor routed
    # catalog-Q&A queries to Engine DA on the `mesh:analyzeDataset`
    # verb, and the agent answered "list datasets owned by alice@..."
    # with the hardcoded fixture URNs (which weren't in DataHub at all,
    # and weren't owned by alice). The agent had no way to know the
    # hint block was sandbox scaffolding rather than ground truth.
    #
    # New contract (Tier-3 fix, 2026-06-16): present the resolved URN
    # to the agent and instruct it to use that exact URN, OR — when no
    # URN was resolved upstream — instruct it to return honest
    # not-found. The agent has no path that requires inventing a URN
    # because it has no tool to discover-or-invent identifiers (the
    # search_datahub tool was deliberately not added; see ADR-0014 and
    # the deploy checklist §4 Tier-3 entry).
    if resolved_instance_id:
        asset_discovery_block = (
            f"### Resolved DataHub URN\n"
            f"The DataHub URN for this query has been resolved upstream:\n"
            f"    {resolved_instance_id}\n"
            f"\n"
            f"Call `query_datahub_asset` with this EXACT URN. Do NOT modify, "
            f"substitute, abbreviate, or invent any URN. If this URN is "
            f"unreachable or returns no data, return an honest message "
            f"explaining that — do not try a different URN.\n"
        )
    else:
        asset_discovery_block = (
            f"### No DataHub URN resolved\n"
            f"No DataHub URN was resolved upstream for this query. The "
            f"catalog either does not contain this asset, or the query "
            f"was too ambiguous to ground to a single asset. Return an "
            f"honest message explaining that you cannot ground this "
            f"query to a specific dataset. Do NOT invent or guess a URN. "
            f"Do NOT call `query_datahub_asset` with a fabricated "
            f"identifier.\n"
        )

    augmented_prompt = (
        f"{user_query}\n\n"
        f"### DataHub schema map\n{dynamic_schema_map or '(empty)'}\n\n"
        f"{asset_discovery_block}"
    )

    # Phase 3 source attribution (Engine DA, 2026-06-24). Same closure
    # pattern Engines A / W / E ship. Engine DA's tool surface is a
    # single tool (query_datahub_asset) and the URN is literally a
    # tool argument, so the source-emit is simpler than A's
    # multi-asset matched_assets case — one Source per successful
    # query, dedup by URN.
    sources_collected: list[dict] = []
    sources_seen_uris: set[str] = set()

    def _label_from_dataset_urn(urn: str) -> str:
        """Pull the friendly dataset name out of a DataHub dataset URN.
        Same convention as the restate_analyst/urn_utils helper
        (the second-to-last comma-separated segment for the
        `urn:li:dataset:(platform,name,env)` shape). Falls back to the
        raw URN when the shape doesn't match.
        """
        if not urn or not urn.startswith("urn:li:dataset:"):
            return urn or ""
        body = urn[len("urn:li:dataset:"):]
        if body.startswith("(") and body.endswith(")"):
            parts = [p.strip() for p in body[1:-1].split(",")]
            if len(parts) >= 2:
                return parts[-2]
        return urn

    def _record_query_attempt(urn: str, sql_query: str) -> None:
        """Record that the agent ATTEMPTED to query this URN. Called
        before the data fetch so the SourcesTrail surfaces what was
        attempted even when CortexDataClient can't reach the
        underlying data (sandbox data plane unavailable, ACL denial,
        URN-but-no-data) — the user sees "we tried this", not silent
        absence.
        """
        if not urn or urn in sources_seen_uris:
            return
        sources_seen_uris.add(urn)
        snippet = sql_query or ""
        if len(snippet) > 240:
            snippet = snippet[:240].rstrip() + "…"
        sources_collected.append({
            "type": "dataset",
            "label": _label_from_dataset_urn(urn),
            "uri": urn,
            "snippet": snippet,
            "relevance": None,
            "open_url": None,
        })

    def _annotate_query_success(urn: str, row_count: int | None) -> None:
        """Update an existing Source record's snippet with the row
        count after a successful query. No-op if the URN was never
        recorded as an attempt (defensive — shouldn't happen with
        the current call order, but keeps the helper idempotent).
        """
        if not urn or row_count is None:
            return
        for s in sources_collected:
            if s.get("uri") == urn:
                snippet = s.get("snippet") or ""
                if "row(s) returned" not in snippet:
                    s["snippet"] = (
                        f"{snippet}\n— {row_count} row(s) returned"
                        if snippet else f"{row_count} row(s) returned"
                    )
                return

    # Bug 2: structured access-denial capture. The tool appends the denied
    # URN here on a gate 403; the handler surfaces it as status="access_denied"
    # (distinct from success/error/empty) so the UI can offer request-access.
    access_denials: list = []

    @tool
    def query_datahub_asset(urn: str, sql_query: str) -> str:
        """
        Fetches a dataset from DataHub and executes a SQL query on it.

        Args:
            urn: The DataHub URN of the dataset.
            sql_query: The SQL query to execute against the dataset. The table name in the query should be 'dataset'.
        """
        # Phase 3 source attribution: record the attempt UP FRONT so
        # the SourcesTrail surfaces what we tried to query even when
        # the data fetch below fails (data plane unreachable, ACL
        # deny, URN-registered-but-no-data). After a successful
        # query the source's snippet is annotated with the row count.
        _record_query_attempt(urn, sql_query=sql_query)

        broker_url = os.getenv("CENTRAL_GATEWAY_URL", "http://localhost:8000")
        client = CortexDataClient(
            broker_url=broker_url,
            jwt_token=user_jwt,
            originator_sub=originator_sub,
            # The end user's authz_id / entitlement key (email in sandbox).
            # The central-gateway's can_read topaz check is email-keyed, so
            # it MUST see the ORIGINATING USER's email — not the M2M service
            # token's (empty) email. Without this the DA-read gate denied
            # everyone (broken-closed: allow-path never worked). Threaded
            # via X-Originator-Email. See originator_email below.
            originator_email=originator_email,
        )

        try:
            lazy_df = client.get_dataframe(urn)
        except Exception as e:
            # Distinguish a data-plane ACCESS DENIAL (gate 403) from every
            # other failure. Record it STRUCTURALLY so the handler surfaces
            # `status="access_denied"` (→ UI request-access flow), and tell
            # the agent NOT to retry (an authz deny won't yield to retries).
            if _is_access_denied(e):
                if urn not in access_denials:
                    access_denials.append(urn)
                raise PermissionError(
                    f"ACCESS_DENIED reading {urn}: you are not authorized. "
                    f"This is an authorization denial, not a data error — do "
                    f"NOT retry; report that access is denied."
                ) from e
            raise
        dataset = lazy_df.collect()

        # DuckDB sees `dataset` because it picks up registered Python
        # variables from the calling frame at query() time. The previous
        # code relied on this but the scope wasn't right — the agent ran
        # SQL in a different frame than this tool. Register explicitly
        # on a dedicated connection so the query sees the table.
        con = duckdb.connect()
        con.register("dataset", dataset)
        try:
            result_df = con.execute(sql_query).pl()
        finally:
            con.close()
        try:
            row_count = result_df.height if result_df is not None else None
        except Exception:
            row_count = None
        _annotate_query_success(urn, row_count=row_count)
        return result_df.write_json()

    model = get_smolagent_model()
    # A/B TOGGLE (DA_STRUCTURED_OUTPUTS, default OFF, DA-only, reversible):
    # smolagents 1.24 native structured generation. Moves the agent's action
    # CODE into a JSON field so gpt-oss isn't juggling markdown-envelope +
    # Python-syntax + logic simultaneously (the "structure tax" behind the
    # CodeAgent <code>-envelope fumble). This is a MODEL-PATH change — gated so
    # it flips back with zero blast radius. The open question the live A/B
    # settles: does gpt-oss HONOR json-schema constraining through our
    # litellm->ollama chain? An INERT flag (provider silently ignores it) shows
    # up as NO change in the fumble rate, not an error. If inert, BAML is the
    # fallback for this same class-2 (CodeAgent-by-necessity) slot.
    _use_structured = os.getenv("DA_STRUCTURED_OUTPUTS", "").strip().lower() in (
        "1", "true", "yes", "on"
    )
    agent = CodeAgent(
        tools=[query_datahub_asset],
        model=model,
        additional_authorized_imports=["duckdb", "polars", "json"],
        use_structured_outputs_internally=_use_structured,
    )
    print(f"DA_AGENT_CONFIG use_structured_outputs_internally={_use_structured}",
          flush=True)
    
    def _emit_fumble_metric(outcome: str) -> None:
        # A/B FUMBLE METRIC: count smolagents step ERRORS (parse/exec failures
        # — the <code>-envelope fumble) from the agent's memory. The fumble
        # usually RECOVERS (retries), so a successful run still carries the
        # fumble count in its step errors — this is the rate we A/B on
        # (flag-on vs a FRESHLY-measured flag-off baseline, over MANY runs
        # because it's stochastic). One clean grep-able line per run.
        try:
            _steps = getattr(getattr(agent, "memory", None), "steps", []) or []
            _errs = sum(1 for s in _steps if getattr(s, "error", None))
            print(
                f"DA_FUMBLE_METRIC structured={_use_structured} outcome={outcome} "
                f"steps={len(_steps)} step_errors={_errs}",
                flush=True,
            )
        except Exception as _me:  # never let instrumentation break the handler
            print(f"DA_FUMBLE_METRIC compute_failed structured={_use_structured} "
                  f"outcome={outcome} err={_me}", flush=True)

    try:
        # agent.run() is synchronous and blocks for the LLM round-trips
        # (often 30s+ on slow Ollama backends). Hypercorn is single-event-loop,
        # so running it inline starves the readiness probe and any concurrent
        # invocations. Offload to a worker thread so the event loop stays
        # responsive.
        # Telemetry (ADR-0038): join Engine D's generation(s) to the caller's trace —
        # observed_trace seeds create_trace_id on the forwarded X-Trace-Id, so these spans
        # nest under the analyst trace that called this engine. Fail-soft; no-op if disabled.
        with observed_trace(MAPPING, build_trace_values(
            trace_id=request.get("trace_id"),
            engine="data_analyst",
            authz_id=request.get("user_id") or request.get("authz_id"),
            domain=request.get("domain"),
        ), name="data analyst"):
            agent_result = await asyncio.to_thread(agent.run, augmented_prompt)
        _emit_fumble_metric("ok")
    except Exception as e:
        # Count the fumble even on a TOTAL failure (agent.run raised) — the
        # memory still holds the errored steps; a run that never recovered is
        # the worst fumble and must not be invisible to the A/B.
        _emit_fumble_metric("raised")
        # A gate access-denial surfaces STRUCTURALLY even if the agent's
        # error path fired — check it before the generic error so the UI
        # offers request-access, not a generic "something went wrong".
        if access_denials:
            return _access_denied_response(access_denials, originator_email, sources_collected)
        # Even on error, return any sources we did manage to capture —
        # the agent may have queried successfully before something else
        # blew up downstream (e.g. SQL syntax issue on a follow-up call).
        return {"status": "error", "message": str(e), "sources": sources_collected}

    # REPLAY-SEAL INJECTION POINT (env-gated, default no-op). Placed AFTER the work and OUTSIDE the
    # try/except above ON PURPOSE: inside it, the broad `except Exception` would swallow this and
    # return an error dict, and Restate would never see a failure to retry. Here it propagates, the
    # invocation is retried, and the handler re-enters from the top — which is the replay this seal
    # exists to observe.
    global _seal_failures_used
    if _seal_failures_used < _SEAL_FAIL_AFTER_WORK:
        _seal_failures_used += 1
        raise RuntimeError(
            f"DA_SEAL: deliberate post-work failure #{_seal_failures_used} to manufacture a "
            f"Restate replay (DA_SEAL_FAIL_AFTER_WORK={_SEAL_FAIL_AFTER_WORK}). "
            f"The agent work above ALREADY RAN — count it."
        )

    # Phase 3 source attribution: attach the accumulated sources at
    # the top of the response. The supervisor's
    # _log_subtask_sources_asset reads engine_response["sources"];
    # gateway projects into the typed `sources` SSE event; cortex-ui
    # SourcesTrail renders. Same field-name contract Engines A/W/E
    # ship.

    # If the data access was DENIED (gate 403), surface it STRUCTURALLY
    # regardless of the agent's prose ("I'm unable to access…") — the UI
    # needs the typed access_denied signal to offer request-access, not an
    # empty chart that hides the denial.
    if access_denials:
        return _access_denied_response(access_denials, originator_email, sources_collected)

    return {
        "status": "success",
        "data": agent_result,
        "sources": sources_collected,
    }

# Mount Restate service to FastAPI
app.mount("/restate", restate.app(services=[data_analyst_service]))


# ---------------------------------------------------------------------------
# POST /analyze_data — proxy route for the supervisor
# ---------------------------------------------------------------------------
# Mirrors Engine A's /analyze proxy (restate_analyst/main.py:1500). The
# verb registry advertises this engine's endpoint as
# http://iagent-data-analyst:8089/analyze_data, but the FastAPI app
# only mounted Restate at /restate — there was no plain HTTP route
# accepting the supervisor's dispatch payload, so every analyzeDataset
# route returned 404 and the pipeline failed. Caught 2026-06-24 when
# the supervisor /resolve timeout bump unblocked routing to this
# engine for the first time.
@app.post("/analyze_data")
async def analyze_data_proxy(request: Request):
    """Forward the supervisor's POST to the Restate ingress so the
    durable handler runs and the response is returned to Dagster.
    """
    import httpx
    import uuid as _uuid
    from fastapi.responses import JSONResponse
    try:
        payload = await request.json()
        auth_header = request.headers.get("Authorization")
        if auth_header:
            payload["user_jwt"] = auth_header
        trace_id = request.headers.get("X-Trace-Id") or str(_uuid.uuid4())
        payload["trace_id"] = trace_id
        restate_ingress = os.getenv("RESTATE_INGRESS_URL", "http://iagent-restate:8080")
        target_url = f"{restate_ingress}/DataAnalystService/analyze_data"
        # Match the supervisor's per-engine 1800s ceiling so a slow
        # smolagent loop on a busy Ollama backend doesn't get truncated
        # mid-step.
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(target_url, json=payload)
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.text else {},
            )
    except Exception as exc:
        print(f"DEBUG: Restate proxy call failed for DataAnalystService: {exc}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Restate proxy call failed: {exc}",
                "sources": [],
            },
            status_code=502,
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8089"))
    uvicorn.run(app, host="0.0.0.0", port=port)
