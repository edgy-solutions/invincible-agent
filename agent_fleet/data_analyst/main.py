import json
import os
from contextlib import asynccontextmanager

import duckdb
import restate
from fastapi import FastAPI
from restate import Context, Service
from smolagents import CodeAgent, tool, LiteLLMModel

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
@require_topaz_auth_decorator(resource_type="global", action="analyze")
async def analyze_data(ctx: Context, request: dict, user_jwt: str = None) -> dict:
    """
    Translates user intent into SQL queries, executes them securely via DuckDB/Polars,
    and formats the output into UI widgets.
    """
    user_query = request.get("query", "Analyze the data")
    
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
        
        # Fetch the data
        lazy_df = client.get_dataframe(urn)
        dataset = lazy_df.collect()
        
        # DuckDB queries the 'dataset' variable in local scope
        result_df = duckdb.query(sql_query).pl()
        return result_df.write_json()

    model = LiteLLMModel(model_id="gpt-4o-mini")
    agent = CodeAgent(
        tools=[query_datahub_asset],
        model=model,
        additional_authorized_imports=["duckdb", "polars", "json"]
    )
    
    try:
        agent_result = agent.run(user_query)
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
