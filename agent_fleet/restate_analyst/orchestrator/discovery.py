import os
import httpx
import logging
import asyncio
import threading
import contextvars
from smolagents import Tool
from mcp import ClientSession
from mcp.client.sse import sse_client
from orchestrator.auth import current_user_token, current_trace_id

logger = logging.getLogger("RestateAnalyst")

DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://iagent-engine-d:8085")

async def fetch_tools_from_wrapper() -> list[dict]:
    """Legacy: Fetch all active tools."""
    endpoint = f"{DATAHUB_WRAPPER_URL}/api/v1/tools/active"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(endpoint)
        return response.json() if response.status_code == 200 else []

async def fetch_tools_by_uri(ontology_uri: str) -> list[dict]:
    """JIT: Fetch tools tagged with a specific ontology URI from Engine D."""
    endpoint = f"{DATAHUB_WRAPPER_URL}/find_tools"
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(endpoint, params={"ontology_uri": ontology_uri})
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])
        except Exception as e:
            logger.error(f"Failed to fetch tools for URI {ontology_uri}: {e}")
            return []

class DynamicMeshTool(Tool):
    def __init__(self, tool_data: dict):
        super().__init__()
        
        # 1. Clean the URN to make it a valid Python identifier for the LLM
        # e.g., "urn:li:tool:scaffold" -> "scaffold"
        urn = tool_data.get("urn", "unknown_tool")
        self.name = urn.split(":")[-1].replace("-", "_")
        
        self.description = tool_data.get("description", f"Dynamic tool: {self.name}")
        self.endpoint_url = tool_data.get("endpoint_url")
        if not self.endpoint_url:
            raise ValueError(f"Tool {self.name} missing endpoint_url")
            
        # 2. Map OpenAPI Schema to smolagents 'inputs' dictionary
        self.inputs = self._parse_openapi(tool_data.get("openapi_schema", {}))
        
        # 3. Default output type
        self.output_type = "string" 

    def _parse_openapi(self, schema: dict) -> dict:
        """Translates OpenAPI JSON schema into smolagents input format."""
        smol_inputs = {}
        try:
            schemas = schema.get("components", {}).get("schemas", {})
            properties = {}
            for schema_name, schema_def in schemas.items():
                if "properties" in schema_def:
                    properties = schema_def["properties"]
                    break
                    
            for key, val in properties.items():
                smol_inputs[key] = {
                    "type": val.get("type", "string"),
                    "description": val.get("description", f"Parameter {key}")
                }
        except Exception as e:
            logger.warning(f"Failed to parse OpenAPI schema for {self.name}: {e}")
            
        return smol_inputs

    def forward(self, **kwargs) -> str:
        """The actual execution block triggered by the LLM."""
        auth_header = current_user_token.get()
        headers = {"Authorization": auth_header} if auth_header else {}
        
        trace_id = current_trace_id.get()
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        
        # smolagents Tool.forward is synchronous by default.
        with httpx.Client() as client:
            response = client.post(
                self.endpoint_url, 
                json=kwargs,
                headers=headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.text

class DynamicMCPTool(Tool):
    def __init__(self, mcp_tool_info, endpoint_url: str):
        super().__init__()
        # mcp_tool_info is an mcp.types.Tool object with name, description, inputSchema
        self.name = mcp_tool_info.name.replace("-", "_")
        self.description = mcp_tool_info.description or f"MCP tool: {self.name}"
        self.endpoint_url = endpoint_url
        self.original_name = mcp_tool_info.name
        
        # Translate JSON schema 'properties' directly into smolagents dict
        self.inputs = self._parse_json_schema(mcp_tool_info.inputSchema)
        self.output_type = "string"

    def _parse_json_schema(self, schema: dict) -> dict:
        smol_inputs = {}
        try:
            properties = schema.get("properties", {})
            for key, val in properties.items():
                smol_inputs[key] = {
                    "type": val.get("type", "string"),
                    "description": val.get("description", f"Parameter {key}")
                }
        except Exception as e:
            logger.warning(f"Failed to parse MCP schema for {self.name}: {e}")
        return smol_inputs

    async def _async_execute(self, kwargs: dict) -> str:
        auth_header = current_user_token.get()
        headers = {"Authorization": auth_header} if auth_header else {}
        
        trace_id = current_trace_id.get()
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        
        async with sse_client(self.endpoint_url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(self.original_name, arguments=kwargs)
                
                text_outputs = []
                for content in result.content:
                    if content.type == "text":
                        text_outputs.append(content.text)
                return "\n".join(text_outputs)

    def forward(self, **kwargs) -> str:
        """The actual execution block triggered by the LLM."""
        result = None
        exception = None
        
        # 1. Snapshot the current context (which contains the JWT)
        ctx = contextvars.copy_context()

        def _thread_worker():
            nonlocal result, exception
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # The token is safely accessible inside this execution block!
                result = loop.run_until_complete(self._async_execute(kwargs))
            except Exception as e:
                exception = e
            finally:
                loop.close()

        # 2. Run the target worker INSIDE the copied context
        thread = threading.Thread(target=ctx.run, args=(_thread_worker,))
        thread.start()
        thread.join()

        if exception:
            raise exception
        return result

async def bind_mcp_server(server_data: dict) -> list[DynamicMCPTool]:
    """Connect to an MCP server via SSE, list tools, and generate proxies."""
    endpoint_url = server_data.get("endpoint_url")
    if not endpoint_url:
        logger.warning(f"MCP server {server_data.get('urn')} missing endpoint_url.")
        return []
        
    tools = []
    try:
        async with sse_client(endpoint_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_resp = await session.list_tools()
                
                for tool_info in tools_resp.tools:
                    proxy = DynamicMCPTool(tool_info, endpoint_url)
                    tools.append(proxy)
                    logger.info(f"Successfully bound MCP tool: {proxy.name}")
    except Exception as e:
        logger.error(f"Failed to bind MCP server at {endpoint_url}: {e}")
        
    return tools
