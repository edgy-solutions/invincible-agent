import os
import weaviate
from weaviate.connect import ConnectionParams

def create_weaviate_client() -> weaviate.WeaviateClient:
    """
    Fleet-standard factory for creating a Weaviate v4 client.
    Handles split HTTP/gRPC routing for Kubernetes environments.

    Returns a fully connected ``WeaviateClient``. Do NOT call ``.connect()``
    on the returned client — ``connect_to_custom()`` already does this, and
    calling ``.connect()`` a second time orphans the original ConnectionSync
    and produces misleading
    ``AttributeError: 'ConnectionSync' object has no attribute '_client'``
    GC noise.
    """
    raw_http_env = os.getenv("WEAVIATE_HTTP_HOST", "weaviate:8080")
    raw_grpc_env = os.getenv("WEAVIATE_GRPC_HOST", "weaviate-grpc:50051")

    def parse_host_port(env_val: str, default_port: int):
        clean = env_val.replace("http://", "").replace("https://", "").replace("grpc://", "")
        if ":" in clean:
            h, p = clean.split(":", 1)
            try:
                return h, int(p)
            except ValueError:
                return h, default_port
        return clean, default_port

    http_h, http_p = parse_host_port(raw_http_env, 8080)
    grpc_h, grpc_p = parse_host_port(raw_grpc_env, 50051)

    client = weaviate.connect_to_custom(
        http_host=http_h,
        http_port=http_p,
        http_secure=False,
        grpc_host=grpc_h,
        grpc_port=grpc_p,
        grpc_secure=False
    )

    print(f"[Fleet Shared] Connected to Weaviate at HTTP {http_h}:{http_p} | gRPC {grpc_h}:{grpc_p}")
    return client


# ---------------------------------------------------------------------------
# Memoized process-wide client — shared by Engine A, Engine E, and any other
# fleet member that needs a persistent connection pool.
# ---------------------------------------------------------------------------
_GLOBAL_WEAVIATE_CLIENT = None


def get_weaviate_client() -> weaviate.WeaviateClient:
    """Lazy-load + memoize a process-wide Weaviate v4 client.

    Reuses the connection pool across requests. Reconnects transparently
    if the previous client was closed or lost its connection. Safe to call
    from sync code; callers in async paths should wrap in
    ``asyncio.to_thread`` since the first call performs the (sync) handshake.
    """
    global _GLOBAL_WEAVIATE_CLIENT

    if _GLOBAL_WEAVIATE_CLIENT is not None:
        try:
            if _GLOBAL_WEAVIATE_CLIENT.is_connected():
                return _GLOBAL_WEAVIATE_CLIENT
        except Exception:
            _GLOBAL_WEAVIATE_CLIENT = None

    _GLOBAL_WEAVIATE_CLIENT = create_weaviate_client()
    return _GLOBAL_WEAVIATE_CLIENT


# ---------------------------------------------------------------------------
# THE NAMED VECTOR SPACE — declared at create, addressed at write, both ends.
# ---------------------------------------------------------------------------
#: The one name every routing collection stores its vectors under.
#:
#: MEASURED 2026-09-19, on scratch collections in sandbox. A bare
#: ``collections.create(name, properties)`` on weaviate-client 4.21.0 emits a NAMED vector space
#: called ``default``; a positional ``insert(vector=[...])`` writes the LEGACY unnamed slot. The
#: named space — the only target a search can name — then stays empty, and the store answers
#:
#:     nearObject(self) -> "vectorize search vector: vector not found for target: default"
#:
#: on a row whose vector reads back as ``{'default': '768 dims'}``. **Every presence check
#: passes and every vector search returns nothing**, with no error and no log line, because the
#: hybrid's BM25 half still answers. That was live on `OntologyClass` and `Predicate` — the two
#: collections the router runs on — and it made the whole fleet lexical-only.
#:
#: THE DEFECT EXISTED BECAUSE NEITHER END NAMED THE SPACE: implicit on the create, positional on
#: the write. Naming both ends is the fix, and it also makes a future mistake LOUD — a write to a
#: space the schema does not declare is a 500 at insert, not a silent miss (measured).
VECTOR_SPACE = "default"


def named_vector_config():
    """The ``create(...)`` kwargs that declare :data:`VECTOR_SPACE` explicitly.

    TWO FORMS, AND THE FALLBACK IS REAL CODE RATHER THAN DECORATION. ``pyproject.toml`` pins
    ``weaviate-client>=4.5.4,<5.0`` — a RANGE — and ``Configure.Vectors`` is a later 4.x
    addition, so a deployment at the floor of that range has only ``Configure.NamedVectors``.
    Both forms were measured to produce ``vector_config=['default']`` and to retrieve through
    INSERT and REPLACE alike; the newer one is preferred because the older raises ``Dep024``.

    Returns kwargs to splat, not a value, because the two forms use DIFFERENT PARAMETER NAMES
    (``vector_config=`` vs ``vectorizer_config=``) — a helper returning only the value would
    push that difference back onto every call site, which is how one of them would get it wrong.
    """
    import weaviate.classes as wvc

    vectors = getattr(wvc.config.Configure, "Vectors", None)
    if vectors is not None and hasattr(vectors, "self_provided"):
        return {"vector_config": vectors.self_provided(name=VECTOR_SPACE)}
    return {
        "vectorizer_config": [
            wvc.config.Configure.NamedVectors.none(name=VECTOR_SPACE)
        ]
    }


def named_vector(vector):
    """A vector addressed to :data:`VECTOR_SPACE`, or ``None`` when there is nothing to write.

    ``insert``/``replace`` take ``vector=`` either positionally (legacy slot — the defect) or as
    a mapping (the named space). This is the mapping, built in one place so a call site cannot
    quietly pass the list form again.

    ``None`` PASSES THROUGH rather than becoming ``{"default": None}``: writing no vector is a
    legitimate state (the registrar does it when the embed gateway is down, deliberately, so a
    registration is not blocked on the LLM stack) and it must stay distinguishable from writing
    one. A row with no vector is equally unretrievable but needs a RE-EMBED, not a relocation —
    the one case the backfill cannot repair.
    """
    if vector is None:
        return None
    return {VECTOR_SPACE: list(vector)}
