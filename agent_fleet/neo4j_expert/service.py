import os
import sys
import asyncio
from typing import Dict, Any
from pathlib import Path

# Add baml_shared to Python path so we can import telemetry
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BAML_SHARED_PATH = _REPO_ROOT / "baml_shared"
if str(_BAML_SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_SHARED_PATH))

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
from mem0 import Memory
import weaviate
from weaviate.connect import ConnectionParams
from langchain_weaviate import WeaviateVectorStore
from langchain_community.embeddings import FakeEmbeddings

try:
    # Workspace root (Container)
    from llm_utils import get_smolagent_model
except ImportError:
    try:
        # Module-relative (Local dev)
        from .llm_utils import get_smolagent_model
    except ImportError:
        # Parent-relative (Local dev)
        from ..llm_utils import get_smolagent_model

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
            from ..llm_utils import init_baml_client
            b = init_baml_client(b)
        except ImportError:
            pass

try:
    from tools import execute_cypher, get_graph_schema
    from prompts import PERSONA_PROMPTS
except ImportError:
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
    # 2. Extract the persona directly as an uppercase string
    persona_str = request.get("persona", "MECHANIC").upper()
    user_id = request.get("user_id")
    
    # 3. Retrieve the prompt using the string key
    system_prompt = PERSONA_PROMPTS.get(persona_str, PERSONA_PROMPTS["MECHANIC"])
    
    # 🔗 DOMAIN-SPECIFIC NODE LABEL CONSTRAINTS (Strict Data Segregation)
    domain = request.get("domain", "MAINTENANCE").upper()
    
    # Sanitize the domain string for safe Neo4j label usage
    domain_label = domain.replace(" ", "_").replace("-", "_")

    domain_constraints = f"""
    STRICT DATA SEGREGATION: You are operating strictly within the {domain} domain.
    
    CRITICAL RULE: Every single node you query MUST explicitly include the `:{domain_label}` label.
    Example of a correct query: MATCH (n:Procedure:{domain_label})
    Example of an INCORRECT query: MATCH (n:Procedure)
    
    Do not guess which node types exist. Use your `get_graph_schema` tool to discover available labels, but ALWAYS append `:{domain_label}` to your queries.
    """
    
    system_prompt_with_segregation = system_prompt + "\n" + domain_constraints

    # --------------------------------------------------------------------------
    # Initialize long-term memory via mem0 using Weaviate vector DB 
    # (Survives K8s ephemeral pod restarts)
    # 🔗 Split-Service Configuration for Kubernetes (HTTP vs gRPC)
    # Defensively strip protocols and ports! 
    # 🔗 Split-Service Configuration for Kubernetes (HTTP vs gRPC)
    # Defensively strip protocols and parse host/port! 
    raw_http_env = os.getenv("WEAVIATE_HTTP_HOST", "weaviate")
    raw_grpc_env = os.getenv("WEAVIATE_GRPC_HOST", "weaviate-grpc")

    def parse_host_port(env_val: str, default_port: int):
        clean = env_val.replace("http://", "").replace("https://", "").replace("grpc://", "")
        if ":" in clean:
            h, p = clean.split(":", 1)
            try:
                return h, int(p)
            except ValueError:
                return h, default_port
        return clean, default_port

    weaviate_http_host, weaviate_http_port = parse_host_port(raw_http_env, 8080)
    weaviate_grpc_host, weaviate_grpc_port = parse_host_port(raw_grpc_env, 50051)

    # Connect to Weaviate explicitly using v4 ConnectionParams
    connection_params = ConnectionParams.from_params(
        http_host=weaviate_http_host,
        http_port=weaviate_http_port,
        http_secure=False,
        grpc_host=weaviate_grpc_host,
        grpc_port=weaviate_grpc_port,
        grpc_secure=False,
    )
    
    weaviate_client = weaviate.WeaviateClient(connection_params=connection_params)
    try:
        weaviate_client.connect()

        from smolagents import tool
        import weaviate.classes as wvc

        # The collection name where doc-tools ingests manual chunks
        doc_collection_name = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")

        @tool
        def search_manual_text(semantic_query: str) -> str:
            """
            Searches the actual text of the technical manuals for conceptual, symptom, or troubleshooting information.
            Use this when the user asks a "how-to", "why", or describes a symptom that isn't a simple part lookup.
            
            Args:
                semantic_query: The natural language search phrase (e.g., "troubleshoot whining noise on corroded rotor").
            """
            try:
                collection = weaviate_client.collections.get(doc_collection_name)
                
                # 🔗 STRICT DOMAIN SEGREGATION APPLIED TO VECTOR SEARCH
                response = collection.query.near_text(
                    query=semantic_query,
                    limit=3,
                    filters=wvc.query.Filter.by_property("domain").equal(domain_label)
                )
                
                if not response.objects:
                    return "No relevant manual text found for this query in the current domain."
                    
                results = []
                for obj in response.objects:
                    results.append(obj.properties.get("text", ""))
                    
                return "\n\n---\n\n".join(results)
            except Exception as e:
                return f"Error executing semantic search: {str(e)}"

        # 🔗 LangChain Bridge (Bypasses mem0's rigid Weaviate config)
        # WeaviateVectorStore requires an embedding model, so we provide a fake one 
        # since mem0 handles embeddings internally before passing them to the store.
        vector_store = WeaviateVectorStore(
            client=weaviate_client,
            index_name="Mem0migrations",
            text_key="text",
            embedding=FakeEmbeddings(size=1536) # Default size for text-embedding-3-small
        )

        # Initialize mem0 using the 'langchain' provider to inject our custom store
        m = Memory.from_config({
            "vector_store": {
                "provider": "langchain",
                "config": {
                    "client": vector_store,
                    "collection_name": "Mem0migrations"
                }
            }
        })

        @safe_observe(as_type="retrieval", name="mem0_context_retrieval")
        def fetch_user_memory(query: str, user_id: str):
            results = m.search(query=query, user_id=user_id)
            # Log the exact memories pulled from the vector DB to Langfuse
            safe_update_observation(input_data=query, output_data=results)
            return results

        # --------------------------------------------------------------------------
        # Run 1: The Smolagents Graph Query Loop
        # --------------------------------------------------------------------------
        @safe_observe(name="smolagents_neo4j_execution")
        async def run_smolagent() -> tuple[str, str]:
            # Retrieve past successful memories to inject into the system prompt
            if user_id:
                past_memories = fetch_user_memory(query=user_query, user_id=user_id)
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
                tools=[execute_cypher, get_graph_schema, search_manual_text],
                model=model,
                add_base_tools=False
            )
            
            # 🚨 FIX: Add the syntax reminder back in!
            syntax_reminder = """
            CRITICAL SYNTAX REQUIREMENT:
            You MUST wrap ALL of your Python code, including the final_answer() function, strictly inside <code> and </code> tags. 
            Do NOT use Markdown triple backticks. 
            
            Example of a correct final answer:
            Thoughts: I have found the work instructions.
            <code>
            final_answer("- **IID** - AII_2265525-X.pdf")
            </code>
            """

            # 🔗 HYBRID REASONING PROTOCOL
            hybrid_instructions = """
            HYBRID REASONING PROTOCOL:
            You now have access to both Graph (Neo4j) and Text (Weaviate) databases.
            - If the user describes a symptom or asks a conceptual question, use `search_manual_text` FIRST to read the manual and find the Procedure ID or required actions.
            - Once you have the Procedure ID or Part Number from the text, use `execute_cypher` to traverse the graph and find related tools, hazards, or components.

            FETCHING FIGURES: When querying for Procedures, ManufacturingSteps, MaintenanceSteps, or DataModules, ALWAYS use an OPTIONAL MATCH to check for linked Figures.
            Because data comes from multiple ingestion pipelines, you MUST check for BOTH relationship types: [:REFERENCES_FIGURE|HAS_FIGURE].
            Because properties vary by ingestion source, you MUST coalesce the URL: COALESCE(f.url, f.hasURL) AS figure_url.
            Example Cypher: OPTIONAL MATCH (step)-[:REFERENCES_FIGURE|HAS_FIGURE]->(f:Figure) RETURN step, f.title, COALESCE(f.url, f.hasURL) AS figure_url.
            You must return the figure URL and title in your Cypher results so the formatting agent can display the diagrams.
            """
            
            # Combine the system prompt, logic, and user query into a single instruction
            full_query = f"{system_prompt_with_memory}\n{hybrid_instructions}\n{syntax_reminder}\n\nUser Query: {user_query}"
            
            # Offload the blocking agent run to a background thread!
            result = str(await asyncio.to_thread(agent.run, full_query))
            
            # Extract smolagents internal logs (trajectory)
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
                        elif hasattr(log_entry, 'action') and getattr(log_entry, 'action'):
                            formatted_trace += f"Action: {getattr(log_entry, 'action')}\n"
                        if hasattr(log_entry, 'tool_result') and getattr(log_entry, 'tool_result'):
                            formatted_trace += f"Result: {getattr(log_entry, 'tool_result')}\n"
                        elif hasattr(log_entry, 'observation') and getattr(log_entry, 'observation'):
                            formatted_trace += f"Result: {getattr(log_entry, 'observation')}\n"
                    formatted_trace += "-" * 30 + "\n"
            
            return result, formatted_trace
            
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
    finally:
        weaviate_client.close()
