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

# ---------------------------------------------------------------------------
# mem0 None-score guard — installed BEFORE ``from mem0 import Memory`` so the
# patched function is what ``mem0.memory.main`` picks up via its
# ``from mem0.utils.scoring import score_and_rank`` line.
# ---------------------------------------------------------------------------
# mem0 0.1.x's ``score_and_rank`` does:
#
#     semantic_score = result.get("score", 0.0)
#     if semantic_score < threshold:
#
# But ``dict.get(key, default)`` returns the *stored value* when the key
# exists -- so a stored ``None`` becomes ``None``, NOT ``0.0``. The default
# never fires, and the subsequent ``<`` raises TypeError every search.
#
# Our ``Mem0CompatibleWeaviate`` already guarantees a real float score on
# the way OUT of the Weaviate adapter. But mem0's own internal result
# pipeline (entity boost, BM25 fusion, score normalization) has multiple
# code paths that can produce a None ``score`` field by the time
# ``score_and_rank`` consumes it -- we saw "Entity boost computation failed"
# and "Batch entity linking failed" both with the same NoneType complaint in
# the live trace. Patching the Weaviate adapter alone is not sufficient;
# the canonical fix point is ``score_and_rank`` itself.
#
# The patch normalizes ``None`` scores to ``0.0`` in the input list before
# delegating to the original implementation. Idempotent; safe to import
# multiple times.
def _install_mem0_none_guards() -> None:
    import sys
    import mem0.utils.scoring as _scoring

    if getattr(_scoring, "_NONE_GUARD_INSTALLED", False):
        return

    _original = _scoring.score_and_rank

    def _safe_score_and_rank(semantic_results, *args, **kwargs):
        for r in semantic_results or []:
            if isinstance(r, dict) and r.get("score") is None:
                r["score"] = 0.0
        return _original(semantic_results, *args, **kwargs)

    # Patch the canonical definition site.
    _scoring.score_and_rank = _safe_score_and_rank

    # Also rebind in every module that already did
    # ``from mem0.utils.scoring import score_and_rank`` before we got here.
    # ``mem0.memory.main`` is the known caller; sweep sys.modules in case
    # any other module also imported the name directly.
    for mod in list(sys.modules.values()):
        if mod is None or mod is _scoring:
            continue
        if getattr(mod, "score_and_rank", None) is _original:
            try:
                setattr(mod, "score_and_rank", _safe_score_and_rank)
            except Exception:
                # Some module objects don't allow attribute assignment; skip.
                pass

    _scoring._NONE_GUARD_INSTALLED = True


_install_mem0_none_guards()


# ---------------------------------------------------------------------------
# mem0 score-propagation fix — also installed before ``from mem0 import Memory``.
# ---------------------------------------------------------------------------
# mem0 0.1.x's Langchain vector store provider (mem0/vector_stores/langchain.py
# :: Langchain._parse_output) literally hardcodes ``score=None`` when wrapping
# LangChain ``Document`` objects, with a comment claiming "Document objects
# typically don't include scores". That assumption is false for our adapter:
# ``Mem0CompatibleWeaviate.similarity_search_by_vector`` explicitly writes a
# real similarity score into ``doc.metadata["score"]``. mem0 throws it away.
#
# Downstream, every result lands with ``score=None`` -> our score_and_rank
# guard normalizes it to 0.0 -> mem0's default threshold (~0.5) filters out
# every result. Searches return empty even though Weaviate returned matches.
#
# Patch _parse_output to read score from doc.metadata when present, falling
# back to None only when there genuinely isn't one. Method-level patch, so
# any Langchain instance mem0 builds picks it up automatically.
def _install_mem0_score_propagation_patch() -> None:
    from mem0.vector_stores import langchain as _lc

    if getattr(_lc, "_SCORE_PROPAGATION_PATCHED", False):
        return

    _original = _lc.Langchain._parse_output

    def _patched_parse_output(self, data):
        if isinstance(data, list) and all(
            hasattr(doc, "metadata") for doc in data if hasattr(doc, "__dict__")
        ):
            result = []
            for doc in data:
                metadata = getattr(doc, "metadata", {}) or {}
                entry = _lc.OutputData(
                    id=getattr(doc, "id", None),
                    score=metadata.get("score"),  # read instead of hardcode None
                    payload=metadata,
                )
                result.append(entry)
            return result
        return _original(self, data)

    _lc.Langchain._parse_output = _patched_parse_output
    _lc._SCORE_PROPAGATION_PATCHED = True


_install_mem0_score_propagation_patch()

from mem0 import Memory  # noqa: E402 — must come after the guards installed above
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

    # Properties mem0 may write that the collection schema does not define.
    # Weaviate rejects unknown properties strictly. `id` is the worst case
    # because it is *reserved* — Weaviate uses it for the object UUID, so
    # nothing can be inserted with it as a regular property. mem0 v2.0.1
    # writes `id`, `score`, and `linked_memory_ids` as properties; the
    # collection schema only declares the properties listed below.
    # We drop everything outside that allow-list before delegating to the
    # parent insert.
    #
    # `agent_id` was added per ADR-0016 r2 Open Items so Engine A and
    # Engine E can partition their memory streams within the shared
    # collection. The Weaviate collection schema must carry an `agent_id`
    # TEXT property — recreate the collection (or add the property
    # in-place) if it predates this change.
    _MEM0_ALLOWED_PROPS = {
        "text", "data", "attributed_to", "created_at",
        "user_id", "agent_id", "text_lemmatized", "updated_at", "hash",
    }

    def _sanitize_metadatas(self, metadatas):
        """Strip mem0-only fields the Weaviate schema does not accept."""
        if not metadatas:
            return metadatas
        cleaned = []
        for m in metadatas:
            if not isinstance(m, dict):
                cleaned.append(m)
                continue
            cleaned.append({
                k: v for k, v in m.items()
                if k in self._MEM0_ALLOWED_PROPS
            })
        return cleaned

    def add_texts(self, texts, metadatas=None, **kwargs):
        # Mem0 v2.0.1 writes `id`, `score`, `linked_memory_ids` as
        # properties — Weaviate rejects `id` (reserved) and the others
        # (not in schema). Sanitize before insert. Memory persistence
        # then works as best-effort: the next insert with the same
        # `hash` will be a no-op via Weaviate's UUIDv5-on-hash assignment
        # (langchain_weaviate generates uuid.uuid5(NAMESPACE_DNS, hash))
        # so we don't need to round-trip mem0's `id` value.
        return super().add_texts(
            texts,
            metadatas=self._sanitize_metadatas(metadatas),
            **kwargs,
        )

    def add_documents(self, documents, **kwargs):
        # langchain_weaviate's add_documents() unwraps Document.metadata
        # into metadatas before calling add_texts(). Override here too in
        # case mem0 calls add_documents directly.
        if documents:
            for doc in documents:
                if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
                    doc.metadata = {
                        k: v for k, v in doc.metadata.items()
                        if k in self._MEM0_ALLOWED_PROPS
                    }
        return super().add_documents(documents, **kwargs)

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

    LLM selection: mem0's internal LLM does fact extraction (structured
    JSON output from short messages) — a fundamentally different task
    from agent reasoning. We honor ``MEM0_LLM_MODEL`` if set so deployments
    can point mem0 at a smaller, faster, more JSON-stable model
    (e.g. ``gemma4:31b``, ``qwen2.5:7b``) while keeping ``SMOLAGENTS_MODEL``
    pointed at the big reasoning model for agent loops. Falls back to
    ``SMOLAGENTS_MODEL`` for backward compatibility, then to a sane default.
    """
    weaviate_client = get_weaviate_client()

    # Provider resolution: prefer the mem0-specific knob, then fall back
    # to the shared smolagents knob, then default to ollama. This lets
    # deployments target one backend for agent reasoning and a different
    # backend for mem0's structured-output prompts (the ADR-0001 split)
    # OR run both against the same backend by leaving MEM0_LLM_PROVIDER
    # unset.
    provider = (
        os.getenv("MEM0_LLM_PROVIDER")
        or os.getenv("SMOLAGENTS_PROVIDER", "ollama")
    ).lower()

    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        # Prefer MEM0_OLLAMA_BASE_URL so Mem0's embedder can be pointed at a
        # separate ollama instance from the main agent LLM. Falls back to the
        # shared OLLAMA_BASE_URL for backward compatibility. Allows physically
        # splitting Mem0 (sidecar concern) onto a different GPU from the main
        # reasoning model — avoids GPU memory contention.
        ollama_url = os.getenv(
            "MEM0_OLLAMA_BASE_URL",
            os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        ).replace("/v1", "")
        embedder_model = os.getenv("MEM0_EMBEDDER_MODEL", "nomic-embed-text")
        langchain_embedder = OllamaEmbeddings(
            model=embedder_model, base_url=ollama_url
        )
        index_name = "Mem0migrationsOllama"
    elif provider == "openai":
        # OpenAI-compatible endpoint — covers LiteLLM, vLLM, OpenRouter,
        # and real OpenAI. The protocol matters; the implementation label
        # is incidental. Engine talks OpenAI Chat Completions + OpenAI
        # Embeddings to whatever URL OPENAI_BASE_URL points at.
        #
        # Env var resolution (per knob, with sensible fallbacks):
        #   base URL:  MEM0_OPENAI_BASE_URL -> OPENAI_BASE_URL
        #   API key:   MEM0_OPENAI_API_KEY  -> OPENAI_API_KEY -> "any"
        #              (vLLM and most LiteLLM gateways accept any non-empty
        #              string; real OpenAI requires a valid key)
        #   embedder:  MEM0_EMBEDDER_MODEL  (required; no sane default
        #              because embedding model availability is
        #              backend-specific)
        from langchain_openai import OpenAIEmbeddings

        openai_url = (
            os.getenv("MEM0_OPENAI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )
        if not openai_url:
            raise RuntimeError(
                "MEM0_LLM_PROVIDER=openai requires MEM0_OPENAI_BASE_URL "
                "or OPENAI_BASE_URL to be set (e.g. http://litellm:4000/v1)."
            )
        openai_api_key = (
            os.getenv("MEM0_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or "any"
        )
        embedder_model = os.getenv("MEM0_EMBEDDER_MODEL")
        if not embedder_model:
            raise RuntimeError(
                "MEM0_LLM_PROVIDER=openai requires MEM0_EMBEDDER_MODEL "
                "(e.g. BAAI/bge-large-en-v1.5 via vLLM, or "
                "text-embedding-3-small via OpenAI, or nomic-embed-text "
                "via Ollama-behind-LiteLLM)."
            )
        langchain_embedder = OpenAIEmbeddings(
            model=embedder_model,
            base_url=openai_url,
            api_key=openai_api_key,
        )
        # Share the existing Mem0migrationsOpenAI index — schema is
        # identical (same embedding-dimensionality assumption is on the
        # operator; if they swap embedder models, they need to wipe the
        # collection or use a different index name via Weaviate-side).
        index_name = "Mem0migrationsOpenAI"
    else:
        from langchain_openai import OpenAIEmbeddings

        # Default real-OpenAI path (uses OpenAI's default endpoint when
        # no base_url is set). Kept for the SMOLAGENTS_PROVIDER=openrouter
        # case where the LLM is OpenRouter but mem0 has no explicit
        # provider knob set — falls through here and uses real OpenAI
        # embeddings.
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

    # mem0's internal LLM — fact extraction, NOT agent reasoning. See
    # docstring above. MEM0_LLM_MODEL wins; falls back to SMOLAGENTS_MODEL.
    mem0_llm_model = (
        os.getenv("MEM0_LLM_MODEL")
        or os.getenv("SMOLAGENTS_MODEL")
        or ("llama3.2" if provider == "ollama" else "anthropic/claude-3.5-sonnet")
    )

    if provider == "ollama":
        mem0_config["llm"] = {
            "provider": "ollama",
            "config": {
                "model": mem0_llm_model,
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
    elif provider == "openai":
        # mem0 talks OpenAI Chat Completions + Embeddings to the
        # configured base_url. Works against LiteLLM, vLLM, OpenRouter,
        # or real OpenAI — the protocol is the same, only the URL
        # changes. The same env vars feed the embedder branch above so
        # mem0 and langchain agree on which endpoint to call.
        mem0_config["llm"] = {
            "provider": "openai",
            "config": {
                "model": mem0_llm_model,
                "api_key": openai_api_key,
                "openai_base_url": openai_url,
            },
        }
        mem0_config["embedder"] = {
            "provider": "openai",
            "config": {
                "model": embedder_model,
                "api_key": openai_api_key,
                "openai_base_url": openai_url,
            },
        }
    elif provider == "openrouter":
        mem0_config["llm"] = {
            "provider": "openai",
            "config": {
                "model": mem0_llm_model,
                "api_key": os.getenv("OPENROUTER_API_KEY", ""),
                "base_url": "https://openrouter.ai/api/v1",
            },
        }

    return Memory.from_config(mem0_config)
