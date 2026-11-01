"""Seal the `mcp` tag surface: the tagged operations are exactly MCP_ROUTES, the committed
docs/api/mcp.openapi.json is the generator's output, and /interview/stream (the second decorator on
the /orchestrate handler) is not in the set.

Run: uv run pytest tests/test_the_mcp_surface_is_stable.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent import gateway  # noqa: E402
from src.iagent.ingest_api import MCP_ROUTES, MCP_TAG  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_gen_mcp_openapi", ROOT / "scripts" / "generate_mcp_openapi.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def full():
    return gateway.app.openapi()


def _tagged(full):
    return {
        (m.upper(), p)
        for p, item in full["paths"].items()
        for m, op in item.items()
        if isinstance(op, dict) and MCP_TAG in (op.get("tags") or [])
    }


def test_tagged_operations_are_exactly_mcp_routes(full):
    assert _tagged(full) == set(MCP_ROUTES), _tagged(full) ^ set(MCP_ROUTES)
    assert len(MCP_ROUTES) == 13


def test_committed_document_matches_generator(full):
    committed = gen._read(gen.DOC_PATH)
    assert committed == gen.serialise(gen.filter_mcp(full, MCP_TAG)), (
        "docs/api/mcp.openapi.json is stale: run scripts/generate_mcp_openapi.py")


def test_interview_stream_is_not_in_the_set(full):
    assert ("POST", "/interview/stream") not in _tagged(full)
    assert "/interview/stream" not in gen.filter_mcp(full, MCP_TAG)["paths"]
    assert ("POST", "/orchestrate") in _tagged(full)
