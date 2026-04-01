import os
import asyncio
from typing import Dict, Any

from restate import Context, Service
from smolagents import CodeAgent
from mem0 import Memory

try:
    from ..llm_utils import get_smolagent_model
except ImportError:
    from llm_utils import get_smolagent_model

# Import from standard shared schemas & the ones just generated in Step 1
from baml_client import b

# Initialize runtime BAML configuration logic
try:
    from ..llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        from llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass
from baml_client.types import PersonaTarget
try:
    from .tools import execute_cypher, get_graph_schema
    from .prompts import PERSONA_PROMPTS
except ImportError:
    from tools import execute_cypher, get_graph_schema
    from prompts import PERSONA_PROMPTS

service = Service("Neo4jExpertService")

@service.handler()
async def query_graph(ctx: Context, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Durable entrypoint for the Neo4j Graph Expert.
    Runs the smolagent CodeAgent, then formats the result via BAML.
    
    Expected Request Dict:
    {
      "user_query": "What tools are needed to remove the main rotor?",
      "persona": "MECHANIC",
      "user_id": "mechanic_bob123"
    }
    """
    user_query = request.get("user_query")
    persona_str = request.get("persona", "MECHANIC").upper()
    user_id = request.get("user_id")
    
    # Map raw string to BAML enum
    try:
        persona_target = PersonaTarget(persona_str)
    except ValueError:
        persona_target = PersonaTarget.MECHANIC
        
    system_prompt = PERSONA_PROMPTS.get(persona_target, PERSONA_PROMPTS[PersonaTarget.MECHANIC])
    
    # 🔗 DOMAIN-SPECIFIC NODE LABEL CONSTRAINTS (Strict Data Segregation)
    domain = request.get("domain", "MAINTENANCE").upper()
    domain_constraints = ""
    if domain == "DATA_ENGINEERING":
        domain_constraints = """
        STRICT DATA SEGREGATION: You are in the DATA_ENGINEERING domain.
        Use ONLY these labels in your Cypher queries:
        (:DataAsset), (:SystemComponent), (:DataPipeline)
        Do NOT query maintenance or sustainment nodes.
        """
    elif domain == "SUSTAINMENT":
        domain_constraints = """
        STRICT DATA SEGREGATION: You are in the SUSTAINMENT domain.
        Use ONLY these labels in your Cypher queries:
        (:InventoryItem), (:Supplier), (:ProcurementContract)
        Do NOT query maintenance or data engineering nodes.
        """
    else:
        # Default to MAINTENANCE
        domain_constraints = """
        STRICT DATA SEGREGATION: You are in the MAINTENANCE domain.
        Use ONLY these labels in your Cypher queries:
        (:PhysicalAsset), (:MaintenanceEvent), (:Hazard)
        Do NOT query sustainment or data engineering nodes.
        """
    
    system_prompt_with_segregation = system_prompt + "\n" + domain_constraints

    # --------------------------------------------------------------------------
    # Initialize long-term memory via mem0 using Weaviate vector DB 
    # (Survives K8s ephemeral pod restarts)
    # 🔗 Split-Service Configuration for Kubernetes (HTTP vs gRPC)
    # --------------------------------------------------------------------------
    import weaviate
    from weaviate.connect import ConnectionParams

    weaviate_http_host = os.getenv("WEAVIATE_HTTP_HOST", "weaviate")
    weaviate_grpc_host = os.getenv("WEAVIATE_GRPC_HOST", "weaviate-grpc")

    # Connect to Weaviate explicitly using v4 ConnectionParams
    connection_params = ConnectionParams.from_params(
        http_host=weaviate_http_host,
        http_port=8080,
        http_secure=False,
        grpc_host=weaviate_grpc_host,
        grpc_port=50051,
        grpc_secure=False,
    )
    
    weaviate_client = weaviate.WeaviateClient(connection_params=connection_params)
    weaviate_client.connect()

    m = Memory.from_config({
        "vector_store": {
            "provider": "weaviate",
            "config": {
                "client": weaviate_client,
                "collection_name": "Mem0migrations"
            }
        }
    })

    # --------------------------------------------------------------------------
    # Run 1: The Smolagents Graph Query Loop
    # --------------------------------------------------------------------------
    async def run_smolagent() -> str:
        # Retrieve past successful memories to inject into the system prompt
        if user_id:
            past_memories = m.search(query=user_query, user_id=user_id)
            if past_memories:
                memory_strings = "\n".join([f"- {mem['text']}" for mem in past_memories])
                prompt_extension = f"\n\n### Relevant Past Experience\n{memory_strings}"
                system_prompt_with_memory = system_prompt_with_segregation + prompt_extension
            else:
                system_prompt_with_memory = system_prompt_with_segregation
        else:
            system_prompt_with_memory = system_prompt_with_segregation

        # Initialize the LLM (configurable via env var, defaults to lightweight model)
        model = get_smolagent_model()
        
        # Instantiate the agent giving it ONLY the Neo4j tools and persona
        agent = CodeAgent(
            tools=[execute_cypher, get_graph_schema],
            model=model,
            add_base_tools=False
        )
        
        # Combine the system prompt and user query into a single instruction
        full_query = f"{system_prompt_with_memory}\n\nUser Query: {user_query}"
        
        # Offload the blocking agent run to a background thread!
        return str(await asyncio.to_thread(agent.run, full_query))
        
    # Standard 120s timeout from the orchestrator allows for extended searching
    raw_agent_response = await ctx.run("run-smolagent", run_smolagent)

    # --------------------------------------------------------------------------
    # Run 2: BAML Strict Formatting
    # --------------------------------------------------------------------------
    async def format_baml() -> Dict[str, Any]:
        # Uses the Async BAML client to format the raw unstructured string
        # into the union GraphExpertResponse based on the requested persona
        baml_response = await b.FormatGraphResponse(raw_agent_response, persona_target)
        
        # Returns the Pydantic .model_dump() dict which Restate will serialize to JSON
        return baml_response.model_dump()
        
    final_structured_dict = await ctx.run("format-baml", format_baml)
    
    # --------------------------------------------------------------------------
    # Run 3: Save Successful Event to Memory
    # --------------------------------------------------------------------------
    async def save_memory() -> str:
        if user_id:
            m.add(
                messages=[
                    {"role": "user", "content": user_query},
                    {"role": "assistant", "content": raw_agent_response}
                ],
                user_id=user_id
            )
        return "saved"
    
    await ctx.run("save-memory", save_memory)
    
    return final_structured_dict
