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
            "Data analyst agent. smolagents CodeAgent writes SQL against "
            "DataHub-backed datasets (CortexDataClient + DuckDB) with Topaz "
            "RLS/CLS enforcement and Restate-durable execution."
        ),
        verb="mesh:analyzeDataset",
        input_uri="mesh:DatasetAnalysisRequest",
        output_uri="mesh:DatasetAnalysisReport",
        verb_synonyms=[
            "analyze data", "run SQL", "query dataset",
            "data analysis", "sql analysis",
        ],
        endpoint_url=os.getenv(
            "ENGINE_DA_PUBLIC_URL",
            "http://data-analyst-svc.default.svc.cluster.local:8089/analyze_data",
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

    # Sandbox fallback: when DataHub is in mock mode, the schema_map is
    # just a fallback string with no URNs. Inject the known sandbox URNs
    # so the smolagent can find a dataset to query without hallucinating.
    sandbox_urn_hints = (
        "\n\nKnown URNs in this sandbox you can pass to query_datahub_asset:\n"
        "- urn:li:dataset:(urn:li:dataPlatform:postgres,sales_customers,PROD) "
        "  — customer_id, name, revenue (analytics).\n"
        "- urn:li:dataset:(urn:li:dataPlatform:postgres,instance_state,PROD) "
        "  — instance_id, ts, pressure, temperature, vibration_rms, flow_rate, status (telemetry).\n"
    )

    augmented_prompt = (
        f"{user_query}\n\n"
        f"### DataHub schema map\n{dynamic_schema_map or '(empty)'}"
        f"{sandbox_urn_hints}"
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
        client = CortexDataClient(broker_url=broker_url, jwt_token=user_jwt)

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
