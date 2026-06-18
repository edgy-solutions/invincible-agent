"""Shared embedding helper for all iagent-side Weaviate vector reads/writes.

Single source of truth for "what embedding model do we use." Same function
shape (and default model name) exists in doc-tools/doc_tools/utils/embed.py.
A grep across both repos for `LLM_EMBED_MODEL` and `embed_text` shows every
call site — that IS the contract, by design.

Why this exists (and why we DON'T use Weaviate's server-side text2vec module):

  - Server-side `text2vec-ollama` puts the contract in Weaviate config:
    "this collection's vectorizer is configured to use model X." Writer and
    reader agree only if Weaviate is deployed correctly in every cluster.
    Schema change (new model) is silent — vectors become incompatible without
    any code failing CI.

  - Code-side embed (the goat-yard-archive pattern, see backend/gill_search.py
    and pipeline/scripts/ingest.py in that repo) puts the contract in code:
    one `LLM_EMBED_MODEL` env var with one default, one `embed_text()` function
    both sides call, one grep to verify alignment. Schema change forces both
    source touches; the guard test asserts only one model-name string exists.

Both writers and readers in iagent + doc-tools call THIS function. Weaviate
collections are created WITHOUT a `vectorizer_config`; we always pass
`vector=...` explicitly to Weaviate write/query APIs.

Endpoint discovery:

  - `LLM_BASE_URL` — same env var the BAML chat-completion client uses
    (canonical OpenAI-compatible base, e.g. `http://iagent-litellm:4000/v1`).
    Falls back to `OPENAI_BASE_URL` for callers that haven't migrated.

  - `LLM_API_KEY` — same env var the BAML chat-completion client uses.
    Falls back to `OPENAI_API_KEY` for callers that haven't migrated.
    Empty / "any" is fine for stateless LiteLLM and direct Ollama;
    real OpenAI / OpenRouter / authenticated LiteLLM need a real key.

  - `LLM_EMBED_MODEL` — model name LiteLLM (or whatever you point
    `LLM_BASE_URL` at) routes to a real embedder. Default `nomic-embed-text`
    matches the iagent helm chart's litellm.config.model_list entry
    (`ollama/nomic-embed-text` → 192.168.1.188:11434). Override per
    deployment if you've routed a different name.

Usage::

    from agent_fleet.utils.embed import embed_text

    vec = embed_text(query)  # list[float], length 768 for nomic-embed-text
    response = collection.query.hybrid(
        query=query,                # BM25 side: literal text
        vector=vec,                 # vector side: pre-computed by us
        alpha=0.5,                  # 0.0 = pure BM25, 1.0 = pure vector
        filters=...,
    )
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
# is nomic-bert-v1, which outputs 768-dim vectors. Used by:
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
# cross-repo safety net on top of this constant. Even if someone misconfigures
# LLM_EMBED_MODEL to a different-dim model, the second writer fails fast
# instead of silently producing incompatible vectors.
#
# If you intentionally migrate to a different-dim model:
#   1. Wipe (or rename + recreate) the affected Weaviate collections.
#   2. Update EXPECTED_EMBED_DIM here AND in doc-tools/.../embed.py.
#   3. Update DEFAULT_EMBED_MODEL in both files.
#   4. Backfill writes to repopulate vectors.
EXPECTED_EMBED_DIM = 768


def _resolve_endpoint() -> tuple[str, str, str]:
    """(base_url, api_key, model) tuple with the standard fallbacks.

    Standalone so callers (and tests) can introspect what we resolved
    without having to re-derive it.
    """
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "embed_text requires LLM_BASE_URL (or OPENAI_BASE_URL) to be "
            "set. Point it at an OpenAI-compatible endpoint that exposes "
            "/embeddings — typically the in-cluster LiteLLM proxy "
            "(http://iagent-litellm:4000/v1)."
        )
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "any"
    model = os.getenv("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    return base_url, api_key, model


def embed_text(text: str, timeout: float = 30.0) -> list[float]:
    """Compute an embedding for a single string via the LLM gateway.

    Raises on transport error or empty embedding. Empty input is allowed
    (the upstream model handles it deterministically) but consider sanitizing
    upstream — empty vectors are usually not what the caller wants.
    """
    base_url, api_key, model = _resolve_endpoint()
    # OpenAI-compatible endpoints expose POST {base}/embeddings with
    # {"model": ..., "input": ...}. LiteLLM, vLLM, Ollama-via-LiteLLM,
    # real OpenAI and OpenRouter all implement this contract.
    r = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": text},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or []
    if not data or "embedding" not in data[0]:
        raise RuntimeError(
            f"Embedding endpoint {base_url} returned an empty/malformed "
            f"response for model={model!r}: {payload!r}"
        )
    return list(data[0]["embedding"])


def probe_embedding_dim(probe_text: str = "iagent embed probe") -> int:
    """Optional startup probe — assert the configured endpoint returns
    EXPECTED_EMBED_DIM vectors. Raises with a clear message on mismatch so
    a misconfigured LLM_EMBED_MODEL is caught at boot, not on first write.

    Returns the observed dim on success. Callers can compare to
    EXPECTED_EMBED_DIM themselves if they prefer a soft check (log + warn)
    over an exception.
    """
    vec = embed_text(probe_text)
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


def embed_texts(texts: list[str], timeout: float = 60.0) -> list[list[float]]:
    """Batch embed multiple strings in a single round-trip.

    OpenAI's contract allows `input` to be a list; LiteLLM passes it through
    to the backend. Backends that don't support batches (some Ollama tags)
    will fall back internally to a sequential loop — same answer, just slower.
    """
    base_url, api_key, model = _resolve_endpoint()
    r = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": texts},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or []
    if len(data) != len(texts):
        raise RuntimeError(
            f"Embedding endpoint {base_url} returned {len(data)} vectors "
            f"for {len(texts)} inputs (model={model!r})"
        )
    # data is ordered by input index per the OpenAI contract.
    return [list(d["embedding"]) for d in data]
