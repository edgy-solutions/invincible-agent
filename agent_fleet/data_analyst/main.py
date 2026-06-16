import asyncio
import json
import os
from contextlib import asynccontextmanager

import duckdb
import restate
from fastapi import FastAPI
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

@app.get("/health")
async def health():
    return {"status": "ok"}

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

    @tool
    def query_datahub_asset(urn: str, sql_query: str) -> str:
        """
        Fetches a dataset from DataHub and executes a SQL query on it.

        Args:
            urn: The DataHub URN of the dataset.
            sql_query: The SQL query to execute against the dataset. The table name in the query should be 'dataset'.
        """
        broker_url = os.getenv("CENTRAL_GATEWAY_URL", "http://localhost:8000")
        client = CortexDataClient(
            broker_url=broker_url,
            jwt_token=user_jwt,
            originator_sub=originator_sub,
        )

        lazy_df = client.get_dataframe(urn)
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
        return result_df.write_json()

    model = get_smolagent_model()
    agent = CodeAgent(
        tools=[query_datahub_asset],
        model=model,
        additional_authorized_imports=["duckdb", "polars", "json"]
    )
    
    try:
        # agent.run() is synchronous and blocks for the LLM round-trips
        # (often 30s+ on slow Ollama backends). Hypercorn is single-event-loop,
        # so running it inline starves the readiness probe and any concurrent
        # invocations. Offload to a worker thread so the event loop stays
        # responsive.
        agent_result = await asyncio.to_thread(agent.run, augmented_prompt)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
    return {
        "status": "success",
        "data": agent_result
    }

# Mount Restate service to FastAPI
app.mount("/restate", restate.app(services=[data_analyst_service]))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8089"))
    uvicorn.run(app, host="0.0.0.0", port=port)
