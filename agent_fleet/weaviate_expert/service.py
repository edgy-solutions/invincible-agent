import os
import asyncio
from typing import Dict, Any

from restate import Context, Service
from smolagents import CodeAgent, tool
import weaviate
from weaviate.connect import ConnectionParams
import weaviate.classes as wvc

try:
    from llm_utils import get_smolagent_model, init_baml_client
except ImportError:
    try:
        from .llm_utils import get_smolagent_model, init_baml_client
    except ImportError:
        from ..llm_utils import get_smolagent_model, init_baml_client

from baml_client import b

# Initialize runtime BAML configuration
b = init_baml_client(b)

service = Service("WeaviateExpertService")

@service.handler()
async def query_knowledge(ctx: Context, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Durable entrypoint for the Weaviate Semantic Expert (Engine W).
    Handles pure KNOWLEDGE_RETRIEVAL intents.
    """
    user_query = request.get("user_query")
    
    # 🔗 DOMAIN SEGREGATION (Sanitized for Weaviate Filtering)
    domain = request.get("domain", "MAINTENANCE").upper()
    domain_label = domain.replace(" ", "_").replace("-", "_")

    # 🔗 Weaviate Connection Logic (K8s Split-Service)
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
        doc_collection_name = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")

        # --------------------------------------------------------------------------
        # The Semantic Tool
        # --------------------------------------------------------------------------
        @tool
        def search_knowledge_base(semantic_query: str) -> str:
            """
            Searches the text of the technical manuals for policies, definitions, summaries, and general knowledge.
            
            Args:
                semantic_query: The natural language search phrase.
            """
            try:
                collection = weaviate_client.collections.get(doc_collection_name)
                
                # STRICT DOMAIN SEGREGATION FILTER
                response = collection.query.near_text(
                    query=semantic_query,
                    limit=5,
                    filters=wvc.query.Filter.by_property("domain").equal(domain_label)
                )
                
                if not response.objects:
                    return f"No relevant information found for '{semantic_query}' in the {domain} domain."
                    
                results = []
                for idx, obj in enumerate(response.objects):
                    text = obj.properties.get("text", "")
                    doc_id = obj.properties.get("doc_id", "Unknown Document")
                    results.append(f"--- Excerpt {idx + 1} (Source: {doc_id}) ---\n{text}")
                    
                return "\n\n".join(results)
            except Exception as e:
                return f"Error executing semantic search: {str(e)}"

        # --------------------------------------------------------------------------
        # The Agent Execution Loop
        # --------------------------------------------------------------------------
        async def run_smolagent() -> str:
            model = get_smolagent_model()
            
            agent = CodeAgent(
                tools=[search_knowledge_base],
                model=model,
                add_base_tools=False
            )
            
            system_prompt = f"""
            You are a Technical Librarian and Policy Expert for the {domain} domain.
            Your sole job is to answer the user's query by searching the knowledge base and summarizing the findings accurately.
            Never invent information. If the search tool returns no results, state clearly that the information is unavailable.
            ALWAYS include the Source Document IDs in your final answer so the user knows where the information came from.
            """
            
            syntax_reminder = """
CRITICAL SYNTAX REQUIREMENT:
You are a Code Agent. You MUST wrap ALL of your Python code strictly inside <code> and </code> tags.
DO NOT put your thoughts, explanations, or Markdown text inside the <code> tags. Only valid Python code belongs inside the tags.

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
            
            full_query = f"{system_prompt}\n{syntax_reminder}\n\nUser Query: {user_query}"
            return str(await asyncio.to_thread(agent.run, full_query))
            
        raw_agent_response = await ctx.run("run-smolagent", run_smolagent)

        # --------------------------------------------------------------------------
        # BAML Strict Formatting
        # --------------------------------------------------------------------------
        async def format_baml() -> Dict[str, Any]:
            # Use our new dedicated Knowledge format contract
            baml_response = await b.FormatKnowledgeResponse(raw_agent_response, domain)
            return baml_response.model_dump()
            
        final_structured_dict = await ctx.run("format-baml", format_baml)
        
        return final_structured_dict
        
    finally:
        weaviate_client.close()
