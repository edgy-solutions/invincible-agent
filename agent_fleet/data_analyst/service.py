import json
import duckdb
from restate import Context
from smolagents import CodeAgent, tool, LiteLLMModel
from agent_fleet.core.authz import require_topaz_auth_decorator
from dag_tools.cortex_data.client import CortexDataClient

@require_topaz_auth_decorator(resource_type="global", action="analyze")
async def analyze_data(ctx: Context, request: dict, user_jwt: str = None) -> dict:
    """
    Translates user intent into SQL queries, executes them securely via DuckDB/Polars,
    and formats the output into UI widgets.
    """
    user_query = request.get("query", "Analyze the data")
    
    # The Closure Pattern: Define the tool inside the handler so user_jwt is captured
    # from the outer scope and NOT exposed in the tool signature.
    @tool
    def query_datahub_asset(urn: str, sql_query: str) -> str:
        """
        Fetches a dataset from DataHub and executes a SQL query on it.
        
        Args:
            urn: The DataHub URN of the dataset.
            sql_query: The SQL query to execute against the dataset. The table name in the query should be 'dataset'.
        """
        # Instantiate the CortexDataClient using the securely captured user_jwt
        import os
        broker_url = os.getenv("CENTRAL_GATEWAY_URL", "http://localhost:8000")
        client = CortexDataClient(broker_url=broker_url, jwt_token=user_jwt)
        
        # Fetch the data
        lazy_df = client.get_dataframe(urn)
        
        # Execute the LLM's SQL
        dataset = lazy_df.collect()
        
        # DuckDB can directly query the 'dataset' Polars DataFrame variable in the local scope
        result_df = duckdb.query(sql_query).pl()
        
        # Return as JSON
        return result_df.write_json()

    # Initialize the CodeAgent with this tool
    # We configure a default model here; in production, this would be injected or configured via env vars
    model = LiteLLMModel(model_id="gpt-4o-mini")
    
    agent = CodeAgent(
        tools=[query_datahub_asset],
        model=model,
        additional_authorized_imports=["duckdb", "polars", "json"]
    )
    
    # Run it against the user query
    try:
        agent_result = agent.run(user_query)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
    # In a full implementation, format the output via BAML
    # from baml_client.sync_client import b
    # formatted_result = b.FormatAnalysis(agent_result)
    
    return {
        "status": "success",
        "data": agent_result
    }
