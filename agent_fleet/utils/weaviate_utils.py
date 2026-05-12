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
