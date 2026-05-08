import json
import os
import duckdb
import restate
from fastapi import FastAPI
from restate import Context, Service
from smolagents import CodeAgent, tool, LiteLLMModel
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

# Initialize FastAPI
app = FastAPI()

# Define the Restate Service
data_analyst_service = Service("DataAnalystService")

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
