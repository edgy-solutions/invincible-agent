import os
import sys
import asyncio
import json
from typing import Dict, Any
from pathlib import Path

# Add baml_shared to Python path so we can import telemetry
_CURRENT_FILE = Path(__file__).resolve()
try:
    _REPO_ROOT = _CURRENT_FILE.parents[2]
    _BAML_SHARED_PATH = _REPO_ROOT / "baml_shared"
    if _BAML_SHARED_PATH.exists() and str(_BAML_SHARED_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_SHARED_PATH))
except IndexError:
    pass

try:
    from telemetry import safe_observe, safe_update_observation
except ImportError:
    def safe_observe(**kwargs):
        def decorator(func):
            return func
        return decorator
    def safe_update_observation(input_data=None, output_data=None):
        pass

from restate import Context, Service
from smolagents import CodeAgent

# ---------------------------------------------------------------------------
# Fleet-standard utilities — memoized Weaviate client + shared mem0 singleton.
# Previously this engine built its own Weaviate client AND the full mem0 stack
# inside every /query_graph request, which (a) leaked one gRPC + HTTP
# connection per request and (b) blocked the async event loop with sync
# Memory.from_config() schema verification. The shared singleton in
# utils.mem0_utils builds the stack exactly once per pod on a worker thread.
# ---------------------------------------------------------------------------
try:
    from utils.weaviate_utils import get_weaviate_client
    from utils.mem0_utils import get_mem0_memory
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import get_weaviate_client
        from agent_fleet.utils.mem0_utils import get_mem0_memory
    except ImportError:
        # Fallback for flat layout in container
        from weaviate_utils import get_weaviate_client
        from mem0_utils import get_mem0_memory

try:
    # Workspace root (Container)
    from llm_utils import get_smolagent_model
except ImportError:
    try:
        # Module-relative (Local dev)
        from .llm_utils import get_smolagent_model
    except ImportError:
        # Parent-relative (Local dev)
        from agent_fleet.llm_utils import get_smolagent_model

# Import from standard shared schemas & the ones just generated in Step 1
from baml_client import b
from baml_py import baml_py

# Initialize runtime BAML configuration logic
try:
    # Workspace root (Container)
    from llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        # Module-relative
        from .llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        try:
            # Parent-relative
            from agent_fleet.llm_utils import init_baml_client
            b = init_baml_client(b)
        except ImportError:
            pass

try:
    from tools import execute_cypher, get_graph_schema, get_neo4j_driver
    from prompts import PERSONA_PROMPTS
except ImportError:
    from .tools import execute_cypher, get_graph_schema, get_neo4j_driver
    from .prompts import PERSONA_PROMPTS

service = Service("Neo4jExpertService")

def fetch_dynamic_schema_from_neo4j() -> str:
    """Fetches the live Neo4j database schema at boot-time."""
    try:
        from tools import get_neo4j_driver
        driver = get_neo4j_driver()
        with driver.session() as session:
            result = session.execute_read(lambda tx: list(tx.run("CALL apoc.meta.schema() YIELD value RETURN value")))
            if not result:
                return "Schema not available."
            return json.dumps(result[0]["value"], indent=2)
    except Exception as e:
        return f"Error fetching schema: {e}"

def fetch_weaviate_schema(weaviate_client, collection_name: str) -> str:
    """Fetches the live metadata properties available in Weaviate."""
    try:
        collection = weaviate_client.collections.get(collection_name)
        config = collection.config.get()
        
        # Extract the property names and their data types
        properties = []
        for prop in config.properties:
            properties.append(f"- {prop.name} (Type: {prop.data_type.name})")
            
        schema_str = f"Available Metadata Filters for {collection_name}:\n" + "\n".join(properties)
        return schema_str
    except Exception as e:
        return f"Could not fetch Weaviate schema: {str(e)}"

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
    # 2. Extract the persona directly as an uppercase string
    persona_str = request.get("persona", "MECHANIC").upper()
    user_id = request.get("user_id")
    
    # 3. Retrieve the prompt using the string key
    system_prompt = PERSONA_PROMPTS.get(persona_str, PERSONA_PROMPTS["MECHANIC"])
    
    # Fetch schema dynamically via Restate to ensure durability
    async def fetch_schema() -> str:
        return fetch_dynamic_schema_from_neo4j()
        
    db_schema_string = await ctx.run("fetch-schema", fetch_schema)
    
    schema_injection = f"""
CRITICAL GRAPH SCHEMA:
You must ONLY use the following Nodes, Properties, and Relationships. Do not guess.
{db_schema_string}
"""
    
    # 🔗 DOMAIN-SPECIFIC NODE LABEL CONSTRAINTS (Strict Data Segregation)
    domain = request.get("domain", "MAINTENANCE").upper()
    
    # Sanitize the domain string for safe Neo4j label usage
    domain_label = domain.replace(" ", "_").replace("-", "_")

    domain_constraints = f"""
{schema_injection}

    STRICT DATA SEGREGATION: You are operating strictly within the {domain} domain.
    
    CRITICAL RULE: Every single node you query MUST explicitly include the `:{domain_label}` label.
    Example of a correct query: MATCH (n:Procedure:{domain_label})
    Example of an INCORRECT query: MATCH (n:Procedure)
    
    Do not guess which node types exist. Use your `get_graph_schema` tool to discover available labels, but ALWAYS append `:{domain_label}` to your queries.
    
    Optimization Update: When searching for specific part numbers or gauge references, ALWAYS prioritize the `search_manual_text` tool before attempting complex Cypher traversal, as part numbers are often embedded in unstructured manual text.
    """
    
    system_prompt_with_segregation = system_prompt + "\n" + domain_constraints

    # --------------------------------------------------------------------------
    # Acquire shared Weaviate client + mem0 Memory singleton. Both are
    # process-wide (built once per pod on a worker thread, see utils.*).
    # Previously this section built a fresh Weaviate client AND the entire
    # mem0 stack inside every request — leaking gRPC connections and
    # starving the asyncio loop with sync Memory.from_config() schema work.
    # --------------------------------------------------------------------------
    weaviate_client = await asyncio.to_thread(get_weaviate_client)
    m = await get_mem0_memory()

    from smolagents import tool
    import weaviate.classes as wvc

    # The collection name where doc-tools ingests manual chunks
    doc_collection_name = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")

    # Fetch Weaviate schema dynamically via Restate (on a thread — gRPC is sync)
    async def fetch_weaviate_schema_task() -> str:
        return await asyncio.to_thread(
            fetch_weaviate_schema, weaviate_client, doc_collection_name
        )

    weaviate_schema_string = await ctx.run("fetch-weaviate-schema", fetch_weaviate_schema_task)

    weaviate_constraints = f"""
    When using the search_manual_text tool, you may only filter using the following metadata properties:
{weaviate_schema_string}
"""
    system_prompt_with_segregation += "\n" + weaviate_constraints

    try:

        @tool
        def search_manual_text(semantic_query: str, metadata_filters: dict = None) -> str:
            """
            Searches the actual text of the technical manuals for conceptual, symptom, or troubleshooting information.
            Use this when the user asks a "how-to", "why", or describes a symptom that isn't a simple part lookup.

            Args:
                semantic_query: The natural language search phrase (e.g., "troubleshoot whining noise on corroded rotor").
                metadata_filters: Optional dictionary of metadata fields and exact values to filter by (e.g., {"doc_id": "TM-123"}).
            """
            try:
                collection = weaviate_client.collections.get(doc_collection_name)

                # Base filter: strict domain segregation
                base_filter = wvc.query.Filter.by_property("domain").equal(domain_label)

                if metadata_filters and isinstance(metadata_filters, dict):
                    filter_list = [base_filter]
                    for key, value in metadata_filters.items():
                        filter_list.append(wvc.query.Filter.by_property(key).equal(value))
                    final_filter = wvc.query.Filter.all_of(filter_list)
                else:
                    final_filter = base_filter

                # 🔗 STRICT DOMAIN SEGREGATION APPLIED TO VECTOR SEARCH
                response = collection.query.near_text(
                    query=semantic_query,
                    limit=3,
                    filters=final_filter
                )

                if not response.objects:
                    return "No relevant manual text found for this query in the current domain."

                results = []
                for obj in response.objects:
                    results.append(obj.properties.get("text", ""))

                return "\n\n---\n\n".join(results)
            except Exception as e:
                return f"Error executing semantic search: {str(e)}"

        @safe_observe(as_type="retrieval", name="mem0_context_retrieval")
        def fetch_user_memory(query: str, user_id: str):
            # Wrap user_id in filters for new mem0 API
            results = m.search(query=query, filters={"user_id": user_id})
            safe_update_observation(input_data=query, output_data=results)
            return results

        # --------------------------------------------------------------------------
        # Run 1: The Smolagents Graph Query Loop
        # --------------------------------------------------------------------------
        @safe_observe(name="smolagents_neo4j_execution")
        @safe_observe(name="smolagents_neo4j_execution")
        async def run_smolagent() -> tuple[str, str]:
            try:
                # Retrieve past successful memories to inject into the system prompt.
                # Bridge to a worker thread — m.search() is sync gRPC and must
                # not block the asyncio loop.
                if user_id:
                    past_memories_response = await asyncio.to_thread(
                        fetch_user_memory, user_query, user_id
                    )

                    if isinstance(past_memories_response, dict):
                        past_memories = past_memories_response.get("results", [])
                    else:
                        past_memories = past_memories_response
                        
                    if past_memories:
                        memory_strings = "\n".join([f"- {mem.get('memory', mem.get('text', ''))}" for mem in past_memories if isinstance(mem, dict)])
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
                    tools=[execute_cypher, get_graph_schema, search_manual_text],
                    model=model,
                    add_base_tools=False
                )
                
                # 🚨 FIX: Add the syntax reminder back in!
                syntax_reminder = """
CRITICAL SYNTAX REQUIREMENT:
You are a Code Agent. You MUST wrap ALL of your Python code strictly inside <code> and </code> tags.
DO NOT put your thoughts, explanations, or Markdown text inside the <code> tags. Only valid Python code belongs inside the tags.
If your search results contain image references or file paths (e.g., `image_path`), you MUST include those exact file paths and their figure titles in your `final_answer` payload so the downstream formatter can render them.

Example of BAD formatting:
<code>
I will now search the database.
result = search("query")
</code>

Example of GOOD formatting:
I will now search the database.
<code>
result = search("query")
print(result)
</code>
"""
                
                final_prompt = f"{system_prompt_with_memory}\n\n{syntax_reminder}\n\nUser Query: {user_query}"
                
                # Run the agent in a thread pool since smolagents is synchronous
                result = await asyncio.to_thread(agent.run, final_prompt)
                
                # We also want to capture the internal reasoning steps to display in the UI!
                # Smolagents logs its steps in `agent.logs`
                formatted_trace = "--- Agent Execution Trace ---\n"
                if hasattr(agent, 'logs'):
                    for log_entry in agent.logs:
                        if isinstance(log_entry, dict):
                            formatted_trace += f"Step: {log_entry.get('step', 'N/A')}\n"
                            if 'thought' in log_entry:
                                formatted_trace += f"Thought: {log_entry['thought']}\n"
                            if 'tool_call' in log_entry:
                                formatted_trace += f"Action: {log_entry['tool_call']}\n"
                            if 'tool_result' in log_entry:
                                formatted_trace += f"Result: {log_entry['tool_result']}\n"
                        else:
                            formatted_trace += f"Step: {getattr(log_entry, 'step', 'N/A')}\n"
                            if hasattr(log_entry, 'thought') and getattr(log_entry, 'thought'):
                                formatted_trace += f"Thought: {getattr(log_entry, 'thought')}\n"
                            if hasattr(log_entry, 'tool_call') and getattr(log_entry, 'tool_call'):
                                formatted_trace += f"Action: {getattr(log_entry, 'tool_call')}\n"
                            if hasattr(log_entry, 'tool_result') and getattr(log_entry, 'tool_result'):
                                formatted_trace += f"Result: {getattr(log_entry, 'tool_result')}\n"
                        formatted_trace += "-" * 40 + "\n"
                        
                return str(result), formatted_trace
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"ERROR in run_smolagent: {error_trace}")
                raise e
        # Standard 120s timeout from the orchestrator allows for extended searching
        raw_agent_response, execution_trace = await ctx.run("run-smolagent", run_smolagent)

        # --------------------------------------------------------------------------
        # Run 2: BAML Strict Formatting
        # --------------------------------------------------------------------------
        async def format_baml() -> Dict[str, Any]:
            # Instantiate the BAML log collector
            collector = baml_py.Collector()
            
            # Uses the Async BAML client to format the raw unstructured string
            # into the union GraphExpertResponse based on the requested persona
            baml_response = await b.FormatGraphResponse(
                raw_agent_response, 
                persona_str,
                baml_options={"collector": collector}
            )
            
            # Extract the BAML logs
            baml_trace = "\n\n--- BAML Formatting Trace ---\n"
            if collector.logs and collector.logs[0].calls:
                # Get the first LLM call attempt
                call = collector.logs[0].calls[0]
                
                # Extract the rendered prompt and raw response
                # Depending on BAML version, http_request/http_response might be dicts or strings
                prompt = getattr(call, 'http_request', 'N/A')
                raw_llm_response = getattr(call, 'http_response', 'N/A')
                
                baml_trace += f"Prompt Sent:\n{prompt}\n\n"
                baml_trace += f"Raw LLM Response:\n{raw_llm_response}\n"
            
            # Combine both the smolagents trace and the BAML trace
            combined_trace = execution_trace + baml_trace
            
            # Inject execution trace
            baml_response.execution_trace = combined_trace
            
            # Returns the Pydantic .model_dump() dict which Restate will serialize to JSON
            return baml_response.model_dump()
            
        final_structured_dict = await ctx.run("format-baml", format_baml)
        
        # --------------------------------------------------------------------------
        # Run 3: Save Successful Event to Memory
        # --------------------------------------------------------------------------
        async def save_memory() -> str:
            if user_id:
                # Bridge to a worker thread — m.add() is sync gRPC and must
                # not block the asyncio loop.
                await asyncio.to_thread(
                    m.add,
                    messages=[
                        {"role": "user", "content": user_query},
                        {"role": "assistant", "content": raw_agent_response}
                    ],
                    user_id=user_id
                )
            return "saved"

        await ctx.run("save-memory", save_memory)

        return final_structured_dict
    finally:
        # NOTE: we intentionally do NOT close weaviate_client here. It is a
        # process-wide singleton from utils.weaviate_utils.get_weaviate_client
        # shared across all requests for the lifetime of the pod.
        pass
