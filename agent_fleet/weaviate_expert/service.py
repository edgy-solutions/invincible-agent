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

try:
    from ..utils.weaviate_utils import create_weaviate_client
except ImportError:
    try:
        from utils.weaviate_utils import create_weaviate_client
    except ImportError:
        from agent_fleet.utils.weaviate_utils import create_weaviate_client

from baml_client import b

# Initialize runtime BAML configuration
b = init_baml_client(b)

service = Service("WeaviateExpertService")

# ---------------------------------------------------------------------------
# GLOBAL SINGLETON: Persistent Weaviate Client
# ---------------------------------------------------------------------------
_GLOBAL_WEAVIATE_CLIENT = None

def get_weaviate_client():
    """Lazy-loads a persistent, global Weaviate connection pool."""
    global _GLOBAL_WEAVIATE_CLIENT
    
    # Return existing client if it's already connected
    if _GLOBAL_WEAVIATE_CLIENT is not None and _GLOBAL_WEAVIATE_CLIENT.is_connected():
        return _GLOBAL_WEAVIATE_CLIENT

    _GLOBAL_WEAVIATE_CLIENT = create_weaviate_client()
    return _GLOBAL_WEAVIATE_CLIENT

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
async def query_knowledge(ctx: Context, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Durable entrypoint for the Weaviate Semantic Expert (Engine W).
    Handles pure KNOWLEDGE_RETRIEVAL intents.
    """
    user_query = request.get("user_query")
    domain = request.get("domain", "MAINTENANCE").upper()
    domain_label = domain.replace(" ", "_").replace("-", "_")
    doc_collection_name = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")

    # Safely fetch the persistent client without blocking the async loop
    weaviate_client = await asyncio.to_thread(get_weaviate_client)

    # Fetch Weaviate schema dynamically via Restate
    async def fetch_weaviate_schema_task() -> str:
        return await asyncio.to_thread(fetch_weaviate_schema, weaviate_client, doc_collection_name)
        
    weaviate_schema_string = await ctx.run("fetch-weaviate-schema", fetch_weaviate_schema_task)

    # --------------------------------------------------------------------------
    # The Semantic Tool
    # --------------------------------------------------------------------------
    @tool
    def search_knowledge_base(semantic_query: str, metadata_filters: dict = None) -> str:
        """
        Searches the text of the technical manuals for policies, definitions, summaries, and general knowledge.
        
        Args:
            semantic_query: The natural language search phrase.
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
            
            # STRICT DOMAIN SEGREGATION FILTER
            response = collection.query.near_text(
                query=semantic_query,
                limit=5,
                filters=final_filter
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
        
        When using the search_knowledge_base tool, you may only filter using the following metadata properties:
{weaviate_schema_string}
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
