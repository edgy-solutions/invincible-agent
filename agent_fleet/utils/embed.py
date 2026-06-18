"""Shared embedding helper for all iagent-side Weaviate vector reads/writes.

Single source of truth for "what embedding model do we use" AND "what task
prefix do we send." Same function shape (and identical constants) exists
in doc-tools/doc_tools/utils/embed.py. A grep across both repos for
``DEFAULT_EMBED_MODEL`` / ``EXPECTED_EMBED_DIM`` / ``DOCUMENT_PREFIX`` /
``QUERY_PREFIX`` shows every call site — that IS the contract, by design.

Why this exists (and why we DON'T use Weaviate's server-side text2vec module):

  - Server-side `text2vec-ollama` puts the contract in Weaviate config.
    Writer and reader agree only if Weaviate is deployed correctly in every
    cluster. Schema change (new model) is silent — vectors become
    incompatible without any code failing CI.

  - Code-side embed (the goat-yard-archive pattern) puts the contract in
    code: one model name + one dim + one prefix scheme, one helper function
    per intent, one grep to verify alignment. Schema change forces both
    source touches; the guard test asserts only one model-name string and
    one prefix declaration exists.

Why the task prefix split (embed_document vs embed_query):

  nomic-embed-text-v1.5 (and v1) was trained with task-specific prefixes
  baked into the input. Skipping them OR mixing prefixed-vs-unprefixed
  between writer and reader silently splits the embedding space and
  retrieval quality collapses — exactly the silent-fragility class this
  module exists to eliminate. Per nomic-ai's docs:

    - ``search_document: <text>`` for corpus / chunks at write time
    - ``search_query: <text>`` for user queries at read time
    - ``clustering: <text>`` and ``classification: <text>`` for other tasks
      (not used today; add helpers when those tasks land)

  Backends behave differently on prefixes:

    - Ollama: passes ``input`` through verbatim. NO auto-prefix.
    - vLLM / sentence-transformers: MAY auto-prefix depending on config.
    - Real OpenAI / OpenRouter: no prefix concept; just a different model.

  By prefixing in OUR code we get one consistent wire payload regardless of
  backend. When deploying behind vLLM/sentence-transformers, DISABLE that
  server's auto-prefix (otherwise you double-prefix — still consistent
  within itself, but different from Ollama-routed vectors).

Both writers and readers in iagent + doc-tools call THIS module. Weaviate
collections are created WITHOUT a `vectorizer_config`; we always pass
`vector=...` explicitly to Weaviate write/query APIs.
"""
from __future__ import annotations

import os
import httpx


# Default model name. Changing this requires a Weaviate collection rebuild
# (vectors stored under the old model are not numerically compatible with
# vectors from a new model, even if the dimensions match). Keep the default
# stable; override per cluster via LLM_EMBED_MODEL when migrating.
DEFAULT_EMBED_MODEL = "nomic-embed-text"

# Expected embedding dimensionality for the default model. nomic-embed-text
# is nomic-bert-v1.5, which outputs 768-dim vectors. Used by:
#
#   - probe_embedding_dim() — call from engine startup to assert the
#     configured endpoint actually returns the expected dim; surfaces a
#     model-swap mistake immediately rather than at first query.
#   - cross-repo agreement enforcement: doc-tools/doc_tools/utils/embed.py
#     declares the SAME EXPECTED_EMBED_DIM constant. Code review on either
#     constant catches drift.
#
# Weaviate v4 collections WITHOUT a vectorizer_config (our pattern) lock
# the dimension on the FIRST write. Subsequent writes of a different dim
# are rejected loudly with "vector lengths don't match" — that's the
# cross-repo safety net on top of this constant.
#
# Migration to a different-dim model:
#   1. Wipe (or rename + recreate) the affected Weaviate collections.
#   2. Update EXPECTED_EMBED_DIM in BOTH embed.py files.
#   3. Update DEFAULT_EMBED_MODEL in both files.
#   4. Backfill writes to repopulate vectors.
EXPECTED_EMBED_DIM = 768

# Task prefixes. See module docstring for the rationale. Both writer and
# reader call THIS module's helpers; the prefix is on the wire payload, so
# the backend (Ollama / vLLM / OpenAI / OpenRouter) sees a consistent
# request regardless of how it was constructed.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def _resolve_endpoint() -> tuple[str, str, str]:
    """(base_url, api_key, model) tuple with the standard fallbacks.

    Standalone so callers (and tests) can introspect what we resolved
    without having to re-derive it.
    """
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "embed requires LLM_BASE_URL (or OPENAI_BASE_URL) to be set. "
            "Point it at an OpenAI-compatible endpoint that exposes "
            "/embeddings — typically the in-cluster LiteLLM proxy "
            "(http://iagent-litellm:4000/v1)."
        )
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "any"
    model = os.getenv("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    return base_url, api_key, model


def _post_embedding(input_payload, timeout: float) -> list:
    """Raw POST against the OpenAI /embeddings endpoint.

    Private — callers must use embed_document / embed_query / their batch
    variants so the task prefix is enforced. The guard test forbids direct
    /embeddings POST in any module other than this one.

    Returns the raw `data` list (list of {embedding: [...], index: ...}
    objects). Strict response validation is done by the public helpers.
    """
    base_url, api_key, model = _resolve_endpoint()
    r = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": input_payload},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or []
    if not data:
        raise RuntimeError(
            f"Embedding endpoint {base_url} returned an empty response for "
            f"model={model!r}: {payload!r}"
        )
    return data


def embed_document(text: str, timeout: float = 30.0) -> list[float]:
    """Embed ONE corpus chunk for storage in Weaviate.

    Prefixes with DOCUMENT_PREFIX so the backend sees the task-prefixed
    form nomic-embed-text was trained on. Writers MUST use this (not
    embed_query) for corpus inserts — otherwise queries (prefixed with
    QUERY_PREFIX) land in a different region of the embedding space and
    retrieval scores collapse.
    """
    data = _post_embedding(f"{DOCUMENT_PREFIX}{text}", timeout=timeout)
    if "embedding" not in data[0]:
        raise RuntimeError(f"Embedding response missing 'embedding' key: {data[0]!r}")
    return list(data[0]["embedding"])


def embed_documents(texts: list[str], timeout: float = 60.0) -> list[list[float]]:
    """Batch-embed corpus chunks. Same prefix discipline as embed_document.

    Used for ingest paths that have many chunks ready at once (e.g.
    ontology_assets sync, multi-chunk document ingest). Single round-trip
    against backends that support batch input; backends that don't fall
    back to a sequential loop internally.
    """
    prefixed = [f"{DOCUMENT_PREFIX}{t}" for t in texts]
    data = _post_embedding(prefixed, timeout=timeout)
    if len(data) != len(texts):
        raise RuntimeError(
            f"Embedding endpoint returned {len(data)} vectors for "
            f"{len(texts)} inputs"
        )
    return [list(d["embedding"]) for d in data]


def embed_query(text: str, timeout: float = 30.0) -> list[float]:
    """Embed a user query for search. Always prefixed with QUERY_PREFIX.

    Readers MUST use this (not embed_document) for query vectors. The
    asymmetric prefix encoding is what tells nomic-embed-text the task
    type; using the wrong prefix produces a vector in the wrong subspace
    of the embedding space and retrieval scores collapse silently.
    """
    data = _post_embedding(f"{QUERY_PREFIX}{text}", timeout=timeout)
    if "embedding" not in data[0]:
        raise RuntimeError(f"Embedding response missing 'embedding' key: {data[0]!r}")
    return list(data[0]["embedding"])


def probe_embedding_dim(probe_text: str = "iagent embed probe") -> int:
    """Optional startup probe — assert the configured endpoint returns
    EXPECTED_EMBED_DIM vectors. Raises with a clear message on mismatch so
    a misconfigured LLM_EMBED_MODEL is caught at boot, not on first write.

    Probes via embed_query (any helper works — they all use the same
    underlying call); EXPECTED_EMBED_DIM is independent of task prefix.
    """
    vec = embed_query(probe_text)
    dim = len(vec)
    if dim != EXPECTED_EMBED_DIM:
        _, _, model = _resolve_endpoint()
        raise RuntimeError(
            f"Embedding-model dimension mismatch: model={model!r} returned "
            f"{dim}-dim vectors but the codebase expects EXPECTED_EMBED_DIM="
            f"{EXPECTED_EMBED_DIM} (the dim for DEFAULT_EMBED_MODEL="
            f"{DEFAULT_EMBED_MODEL!r}). EITHER your LLM_EMBED_MODEL is set "
            f"to a different-dim model than the default, OR you intend "
            f"to migrate the codebase to a new embedder — in which case "
            f"update EXPECTED_EMBED_DIM in agent_fleet/utils/embed.py AND "
            f"doc-tools/doc_tools/utils/embed.py, AND wipe/rebuild every "
            f"Weaviate collection that stores vectors. See the EXPECTED_EMBED_DIM "
            f"docstring for the full migration checklist."
        )
    return dim
