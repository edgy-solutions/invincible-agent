import os
import asyncio
from typing import Dict, Any

from restate import Context, Service
from smolagents import CodeAgent, InferenceClientModel
from mem0 import Memory

# Import from standard shared schemas & the ones just generated in Step 1
from baml_client import b
from baml_client.types import PersonaTarget
from .tools import execute_cypher, get_graph_schema
from .prompts import PERSONA_PROMPTS

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

    # --------------------------------------------------------------------------
    # Initialize long-term memory via mem0 using Weaviate vector DB 
    # (Survives K8s ephemeral pod restarts)
    # --------------------------------------------------------------------------
    weaviate_url = os.getenv("WEAVIATE_URL", "http://weaviate:8080")
    memory_config = {
        "vector_store": {
            "provider": "weaviate",
            "config": {
                "cluster_url": weaviate_url,
                "auth_client_secret": os.getenv("WEAVIATE_API_KEY", "")
            }
        }
    }
    m = Memory.from_config(memory_config)

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
                system_prompt_with_memory = system_prompt + prompt_extension
            else:
                system_prompt_with_memory = system_prompt
        else:
            system_prompt_with_memory = system_prompt

        # Initialize the LLM (configurable via env var, defaults to lightweight model)
        model_id = os.getenv("SMOLAGENTS_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct")
        model = InferenceClientModel(model_id=model_id)
        
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
