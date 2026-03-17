import os
import asyncio
from typing import Dict, Any

from restate import Context, Service
from smolagents import CodeAgent, HfApiModel

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
      "persona": "MECHANIC"
    }
    """
    user_query = request.get("user_query")
    persona_str = request.get("persona", "MECHANIC").upper()
    
    # Map raw string to BAML enum
    try:
        persona_target = PersonaTarget(persona_str)
    except ValueError:
        persona_target = PersonaTarget.MECHANIC
        
    system_prompt = PERSONA_PROMPTS.get(persona_target, PERSONA_PROMPTS[PersonaTarget.MECHANIC])

    # --------------------------------------------------------------------------
    # Run 1: The Smolagents Graph Query Loop
    # --------------------------------------------------------------------------
    async def run_smolagent() -> str:
        # Initialize the LLM (configurable via env var, defaults to lightweight model)
        model_id = os.getenv("SMOLAGENTS_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct")
        model = HfApiModel(model_id=model_id)
        
        # Instantiate the agent giving it ONLY the Neo4j tools and persona
        agent = CodeAgent(
            tools=[execute_cypher, get_graph_schema],
            model=model,
            system_prompt=system_prompt,
            add_base_tools=False
        )
        
        # Offload the blocking agent run to a background thread!
        return str(await asyncio.to_thread(agent.run, user_query))
        
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
    
    return final_structured_dict
