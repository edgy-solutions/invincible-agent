"""
Fleet-shared mem0 / Weaviate adapter and singleton.

Centralizes the long-term-memory plumbing previously duplicated between
Engine A (restate_analyst) and Engine E (neo4j_expert). The two design
goals are:

1. Build the mem0 ``Memory`` object exactly once per pod, lazily, on a
   worker thread — never on the asyncio loop. ``Memory.from_config()`` makes
   blocking gRPC calls to verify the Weaviate collection schema; running
   that on the loop starves coroutines (including ``/health``) and trips
   the k8s readiness probe within ~60s, killing the pod.

2. Preserve the hard-won ``Mem0CompatibleWeaviate`` adapter intact. It
   bridges mem0's dictionary filters into Weaviate v4 ``Filter`` objects,
   sanitizes Weaviate's native ``datetime`` / ``UUID`` payloads into
   strings mem0 expects, injects a default ``score`` so mem0 doesn't
   crash on ``None`` comparisons, and tolerates the v4 auto-schema
   cold-start where filter properties don't exist until the first insert.

Usage::

    from utils.mem0_utils import get_mem0_memory

    m = await get_mem0_memory()
    results = await asyncio.to_thread(
        m.search, query=query, filters={"user_id": user_id}
    )
"""

import asyncio
import datetime
import os
import uuid

from langchain_weaviate import WeaviateVectorStore
from mem0 import Memory
from weaviate.classes.query import Filter

try:
    from utils.weaviate_utils import get_weaviate_client
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import get_weaviate_client
    except ImportError:
        # Container flat-layout fallback
        from weaviate_utils import get_weaviate_client


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class Mem0CompatibleWeaviate(WeaviateVectorStore):
    """
    Safely bridges mem0's vector search requirement with Weaviate's
    implementation, and translates mem0's dictionary filters into
    Weaviate v4 ``Filter`` objects.
    """

    def similarity_search_by_vector(self, embedding, k=4, filter=None, **kwargs):
        weaviate_filter = None

        # Intercept and translate mem0's dictionary filter
        if isinstance(filter, dict) and filter:
            filters_list = []
            for key, value in filter.items():
                filters_list.append(Filter.by_property(key).equal(value))

            # Combine multiple filters, or just use the single one
            if len(filters_list) == 1:
                weaviate_filter = filters_list[0]
            elif len(filters_list) > 1:
                weaviate_filter = Filter.all_of(filters_list)
        else:
            # If it's already None or somehow a proper Weaviate Filter, let it through
            weaviate_filter = filter

        # Route to the supported method with the translated filter.
        # Wrapped in try/except to handle Weaviate's auto-schema trap:
        # on first run, properties like 'user_id' don't exist until data is inserted.
        try:
            results = self.similarity_search(
                query=None,
                k=k,
                vector=embedding,
                filters=weaviate_filter,
                **kwargs,
            )

            # 🚨 BULLETPROOF SANITIZATION:
            # Convert Weaviate's native Datetimes and UUIDs into strings for mem0
            for doc in results:
                # 1. Fix missing 'id' (mem0 requires a string ID)
                if doc.metadata.get("id") is None:
                    # Use stringified hash if available, otherwise generate a safe UUID string
                    doc.metadata["id"] = str(doc.metadata.get("hash", uuid.uuid4()))
                else:
                    doc.metadata["id"] = str(doc.metadata["id"])

                # +++ Fix the top-level LangChain Document ID +++
                if hasattr(doc, "id"):
                    doc.id = doc.metadata["id"]

                # 🚨 Guarantee a non-None float score. mem0's score_and_rank does
                # ``if semantic_score < threshold:`` against whatever
                # ``doc.metadata.get("score", 1.0)`` returns — and ``dict.get`` returns
                # the stored value when the key exists (even if it's None), NOT the
                # default. WeaviateVectorStore v4 puts ``score: None`` in metadata on
                # some query paths, so the previous ``if "score" not in metadata``
                # guard wasn't catching it. Derive from v4 distance/certainty when
                # available, otherwise fall back to 1.0.
                if doc.metadata.get("score") is None:
                    certainty = doc.metadata.get("certainty")
                    distance = doc.metadata.get("distance")
                    if certainty is not None:
                        doc.metadata["score"] = float(certainty)
                    elif distance is not None:
                        # Weaviate cosine distance is in [0, 2]; convert to a
                        # similarity-style score in [-1, 1] clamped to [0, 1].
                        doc.metadata["score"] = max(0.0, 1.0 - float(distance))
                    else:
                        doc.metadata["score"] = 1.0

                # 2. Loop through all metadata and sanitize types
                for key, val in list(doc.metadata.items()):
                    if isinstance(val, datetime.datetime):
                        doc.metadata[key] = val.isoformat()
                    elif isinstance(val, uuid.UUID):
                        doc.metadata[key] = str(val)

            return results
        except ValueError as e:
            # LangChain wraps Weaviate gRPC schema errors in ValueError
            if "no such prop" in str(e):
                print(
                    f"[Mem0Bridge] Skipping memory search: schema property "
                    f"not yet created. This is expected on first run. Detail: {e}"
                )
                return []
            raise
        except Exception as e:
            # Catch raw WeaviateQueryError in case it leaks unwrapped
            if "no such prop" in str(e):
                print(
                    f"[Mem0Bridge] Skipping memory search: schema property "
                    f"not yet created. This is expected on first run. Detail: {e}"
                )
                return []
            raise


# ---------------------------------------------------------------------------
# Singleton — built once per pod, off the event loop
# ---------------------------------------------------------------------------
_MEM0_MEMORY = None
_MEM0_LOCK = asyncio.Lock()


async def get_mem0_memory() -> Memory:
    """Lazy, thread-bridged init of the mem0 ``Memory`` singleton.

    Heavy gRPC + schema work happens on first call only, off the event loop.
    Subsequent calls return the cached instance immediately. Safe under
    concurrent first requests via the asyncio.Lock + double-check.
    """
    global _MEM0_MEMORY
    if _MEM0_MEMORY is not None:
        return _MEM0_MEMORY
    async with _MEM0_LOCK:
        if _MEM0_MEMORY is not None:
            return _MEM0_MEMORY
        _MEM0_MEMORY = await asyncio.to_thread(_build_mem0_memory)
        return _MEM0_MEMORY


def _build_mem0_memory() -> Memory:
    """Synchronous mem0 stack builder. Called once via ``asyncio.to_thread``.

    Encapsulates: Weaviate client acquisition, embedder selection,
    vector_store construction, and ``Memory.from_config()``. All blocking
    I/O (collection verification, schema checks, embedder warmup) is
    contained inside this function so the async layer never sees it.
    """
    weaviate_client = get_weaviate_client()

    provider = os.getenv("SMOLAGENTS_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        ollama_url = os.getenv(
            "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
        ).replace("/v1", "")
        langchain_embedder = OllamaEmbeddings(
            model="nomic-embed-text", base_url=ollama_url
        )
        index_name = "Mem0migrationsOllama"
    else:
        from langchain_openai import OpenAIEmbeddings

        langchain_embedder = OpenAIEmbeddings(model="text-embedding-3-small")
        index_name = "Mem0migrationsOpenAI"

    vector_store = Mem0CompatibleWeaviate(
        client=weaviate_client,
        index_name=index_name,
        text_key="text",
        embedding=langchain_embedder,
    )

    mem0_config = {
        "vector_store": {
            "provider": "langchain",
            "config": {
                "client": vector_store,
                "collection_name": index_name,
            },
        }
    }

    if provider == "ollama":
        mem0_config["llm"] = {
            "provider": "ollama",
            "config": {
                "model": os.getenv("SMOLAGENTS_MODEL", "llama3.2"),
                "ollama_base_url": ollama_url,
            },
        }
        mem0_config["embedder"] = {
            "provider": "ollama",
            "config": {
                "model": "nomic-embed-text",
                "ollama_base_url": ollama_url,
            },
        }
    elif provider == "openrouter":
        mem0_config["llm"] = {
            "provider": "openai",
            "config": {
                "model": os.getenv(
                    "SMOLAGENTS_MODEL", "anthropic/claude-3.5-sonnet"
                ),
                "api_key": os.getenv("OPENROUTER_API_KEY", ""),
                "base_url": "https://openrouter.ai/api/v1",
            },
        }

    return Memory.from_config(mem0_config)
