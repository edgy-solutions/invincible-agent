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
        from agent_fleet.llm_utils import get_smolagent_model, init_baml_client
    except ImportError:
        pass

try:
    from utils.weaviate_utils import create_weaviate_client
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import create_weaviate_client
    except ImportError:
        from weaviate_utils import create_weaviate_client

# Shared embedding helper — code owns the contract for "what model" and
# "what task prefix." Engine W is a READ path, so embed_query is the right
# helper (it adds the nomic search_query: prefix).
try:
    from utils.embed import embed_query
except ImportError:
    try:
        from agent_fleet.utils.embed import embed_query
    except ImportError:
        from embed import embed_query

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
    # Source attribution (Phase 3 of grounding panel)
    # --------------------------------------------------------------------------
    # Closure-scoped accumulator: every search_knowledge_base call that
    # returns a Weaviate hit appends one source-record dict here. After
    # the smolagent loop finishes, these records are attached to the
    # engine's response. The supervisor materializes them as a
    # `subtask_sources` Dagster asset, the gateway projects into a
    # typed `sources` SSE event, the cortex-ui SourcesTrail renders them.
    #
    # Architect's discipline (carried through to citation layer):
    # snippet = matched-chunk text VERBATIM (NOT an LLM summary). Synthesis
    # at the citation layer is the exact failure this panel exists to
    # prevent — users must be able to read the words the retriever
    # actually saw.
    #
    # Dedup-by-uri so a multi-tool-call loop that hits the same chunk
    # twice doesn't produce duplicate sources. First-seen relevance wins
    # (the agent's first call gets the most relevant ordering; later
    # exploratory calls are weaker and shouldn't override the first
    # relevance score).
    sources_collected: List[Dict[str, Any]] = []
    sources_seen_uris: set[str] = set()

    def _collect_weaviate_source(obj, search_query: str) -> None:
        """Project a Weaviate object into the Source shape the UI expects."""
        try:
            doc_id = obj.properties.get("doc_id") or "Unknown Document"
            text = obj.properties.get("text") or ""
            page_number = obj.properties.get("page_number")
            object_uri = obj.properties.get("source_url") or obj.properties.get("uri") or f"weaviate://{doc_collection_name}/{obj.uuid}"
            if object_uri in sources_seen_uris:
                return
            sources_seen_uris.add(object_uri)
            # relevance: weaviate-client v4 surfaces `score` (hybrid) or
            # `certainty` (near_*). Either is a 0..1 signal that maps
            # directly to the cortex-ui ConfidenceBar.
            relevance: float | None = None
            md = getattr(obj, "metadata", None)
            if md is not None:
                if getattr(md, "score", None) is not None:
                    relevance = float(md.score)
                elif getattr(md, "certainty", None) is not None:
                    relevance = float(md.certainty)
            label = f"{doc_id}" + (f" · p.{page_number}" if page_number else "")
            sources_collected.append({
                "type": "document",
                "label": label,
                "uri": str(object_uri),
                # First ~240 chars of matched-chunk text (snippet, not
                # summary — see discipline note above).
                "snippet": (text[:240].strip() + ("…" if len(text) > 240 else "")) if text else None,
                "relevance": relevance,
                "open_url": str(object_uri) if str(object_uri).startswith(("http://", "https://", "s3://")) else None,
                # search_query is the actual semantic_query the agent
                # passed in — useful as audit trail (which query call
                # produced this match).
                "matched_for": search_query,
            })
        except Exception as collect_err:
            # Source-collection failure must NEVER kill the search;
            # log and continue. [[trailing-steps-nonfatal]] applied
            # to the citation accumulator.
            print(f"Source-collection failed in Engine W (non-fatal): {collect_err}")

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

            # STRICT DOMAIN SEGREGATION FILTER + explicit vector.
            # We compute the query vector via embed_query() (LiteLLM
            # /embeddings, search_query: prefix) instead of letting
            # Weaviate vectorize the query via a text2vec module — code
            # owns the contract, NOT infra. See agent_fleet/utils/embed.py.
            # return_metadata=ALL surfaces score/certainty so the
            # source-attribution accumulator can populate `relevance`.
            metadata_query = wvc.query.MetadataQuery(score=True, certainty=True, distance=True)
            try:
                query_vector = embed_query(semantic_query)
                response = collection.query.near_vector(
                    near_vector=query_vector,
                    limit=5,
                    filters=final_filter,
                    return_metadata=metadata_query,
                )
            except Exception as embed_err:
                # If the embedding gateway is down, fall back to BM25 so
                # the engine still returns something instead of error.
                # Logs the failure so observability surfaces the gap.
                print(f"embed_query failed in Engine W; BM25 fallback: {embed_err}")
                response = collection.query.bm25(
                    query=semantic_query,
                    limit=5,
                    filters=final_filter,
                    return_metadata=metadata_query,
                )

            if not response.objects:
                return f"No relevant information found for '{semantic_query}' in the {domain} domain."

            results = []
            for idx, obj in enumerate(response.objects):
                text = obj.properties.get("text", "")
                doc_id = obj.properties.get("doc_id", "Unknown Document")
                results.append(f"--- Excerpt {idx + 1} (Source: {doc_id}) ---\n{text}")
                # Accumulate the source record for the engine's response.
                _collect_weaviate_source(obj, semantic_query)

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

    # Phase 3 source attribution: attach the accumulated source records
    # to the engine's response. The supervisor reads this in
    # execute_subtask and materializes a Dagster `subtask_sources` asset
    # which the gateway projects into the typed `sources` SSE event.
    # The field name `sources` is the supervisor's expected key (other
    # engines W/E/A use the same key for a uniform contract).
    #
    # Dropped silently if the BAML response already has a `sources` key
    # (defensive against a future BAML schema change that adds one).
    if "sources" not in final_structured_dict:
        final_structured_dict["sources"] = sources_collected

    return final_structured_dict
