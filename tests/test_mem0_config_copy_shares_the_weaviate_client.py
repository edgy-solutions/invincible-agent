"""mem0 copies its vector-store config; the copy shares our adapter and fails nothing.

mem0 2.x deep-copies the vector-store config (for telemetry at init, and for the entity store on
first use). That config holds `Mem0CompatibleWeaviate`, which holds the live Weaviate client, and
the client cannot be copied. mem0 caught the failure and fell back to a clone holding the same
adapter, but the half-built connection logged, on every engine that uses mem0:

    AttributeError: 'ConnectionSync' object has no attribute '_client'

The adapter's `__deepcopy__` returns itself, which is what mem0's fallback produced anyway.

Run: uv run pytest tests/test_mem0_config_copy_shares_the_weaviate_client.py -q
"""
from __future__ import annotations

import copy
import gc
import sys

import pytest

pytest.importorskip("mem0")
pytest.importorskip("weaviate")

import weaviate  # noqa: E402
from mem0.configs.vector_stores.langchain import LangchainConfig  # noqa: E402
from mem0.memory.main import _safe_deepcopy_config  # noqa: E402
from weaviate.connect import ConnectionParams  # noqa: E402

from agent_fleet.utils.mem0_utils import Mem0CompatibleWeaviate  # noqa: E402


@pytest.fixture
def adapter():
    """The adapter around a real (never connected) v4 client. Nothing here reaches a server."""
    client = weaviate.WeaviateClient(
        connection_params=ConnectionParams.from_params(
            http_host="localhost", http_port=1, http_secure=False,
            grpc_host="localhost", grpc_port=2, grpc_secure=False),
        skip_init_checks=True)
    ad = Mem0CompatibleWeaviate.__new__(Mem0CompatibleWeaviate)
    ad._client = client
    return ad


@pytest.fixture
def unraisable(monkeypatch):
    """What `__del__` raised during collection: the 'Exception ignored in' lines in the pod log."""
    seen: list = []
    gc.collect()
    monkeypatch.setattr(sys, "unraisablehook", lambda u: seen.append(u))
    yield seen


def test_A_DEEP_COPY_OF_MEM0S_CONFIG_SUCCEEDS_AND_SHARES_THE_ADAPTER(adapter, unraisable):
    cfg = LangchainConfig(client=adapter, collection_name="mem0")
    out = copy.deepcopy(cfg)
    assert out.client is adapter
    assert out.collection_name == "mem0"
    gc.collect()
    assert [f"{u.exc_type.__name__}: {u.exc_value}" for u in unraisable] == []


def test_MEM0S_OWN_COPY_GIVES_WHAT_ITS_FALLBACK_GAVE_WITHOUT_THE_FAILURE(adapter, unraisable, monkeypatch):
    """The consumer: mem0's `_safe_deepcopy_config` takes its deepcopy branch, never the fallback,
    and the result holds the same adapter (which is what the fallback returned before)."""
    import mem0.memory.main as mm

    fell_back: list = []
    monkeypatch.setattr(mm.logger, "debug", lambda msg, *a, **k: fell_back.append(str(msg)))
    cfg = LangchainConfig(client=adapter, collection_name="mem0")
    out = _safe_deepcopy_config(cfg)
    assert out.client is adapter
    assert not [m for m in fell_back if "Deepcopy failed" in m], fell_back
    gc.collect()
    assert [f"{u.exc_type.__name__}: {u.exc_value}" for u in unraisable] == []


def test_CONTROL_THE_CLIENT_ITSELF_STILL_CANNOT_BE_COPIED(adapter, unraisable):
    """Shares the subject's client and differs only in what is copied: without the adapter's own
    `__deepcopy__`, copying the client fails, so the seals above are not passing by accident."""
    with pytest.raises(TypeError):
        copy.deepcopy(adapter._client)
