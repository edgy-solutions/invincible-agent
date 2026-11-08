"""The MCP surface is exactly the routes tagged `mcp`, and nothing else.

Three things are compared, none of them a typed list:

  * the LIVE registry: every `APIRoute` of `gateway.app` carrying `MCP_TAG`;
  * the LIVE schema: the operations `app.openapi()` tags `mcp`;
  * the DOCUMENT: `docs/api/mcp.openapi.json` as committed, and as the generator writes it.

They must be the same set. An untagged route cannot be in the document, and every operation in the
document must carry the tag in the live app. (`tests/test_the_mcp_surface_is_stable.py` compares
the tagged set with the hand-kept `MCP_ROUTES`; this one reads the registry the server serves.)

Run: uv run pytest tests/mcp_seals/test_no_untagged_route_is_on_the_mcp_surface.py -q
"""
from __future__ import annotations

import json

import pytest

from _mcp_surface_derived import generator, mcp_routes, ops, untagged_routes

from src.iagent import gateway
from src.iagent.ingest_api import MCP_TAG

HTTP = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _doc_ops(doc: dict) -> set[tuple[str, str]]:
    return {(m.upper(), p) for p, item in doc.get("paths", {}).items() for m in item if m in HTTP}


def _untagged_in(doc: dict) -> list[tuple[str, str]]:
    """Operations of `doc` that do not carry the tag."""
    return sorted((m.upper(), p) for p, item in doc.get("paths", {}).items()
                  for m, op in item.items()
                  if m in HTTP and MCP_TAG not in (op.get("tags") or []))


@pytest.fixture(scope="module")
def gen():
    return generator()


@pytest.fixture(scope="module")
def full():
    return gateway.app.openapi()


@pytest.fixture(scope="module")
def committed(gen):
    return json.loads(gen._read(gen.DOC_PATH))


def test_instrument_found_both_tagged_and_untagged_routes():
    assert len(mcp_routes()) >= 2 and len(untagged_routes()) >= 10, (
        len(mcp_routes()), len(untagged_routes()))


def test_the_live_schema_tags_exactly_the_registry_tagged_routes(full):
    schema_tagged = {(m.upper(), p) for p, item in full["paths"].items()
                     for m, op in item.items()
                     if m in HTTP and MCP_TAG in (op.get("tags") or [])}
    assert schema_tagged == ops(mcp_routes()), schema_tagged ^ ops(mcp_routes())


def test_the_committed_document_holds_exactly_the_tagged_routes(committed):
    assert _doc_ops(committed) == ops(mcp_routes()), _doc_ops(committed) ^ ops(mcp_routes())


def test_the_generator_writes_exactly_the_tagged_routes(gen, full):
    built = gen.filter_mcp(full, MCP_TAG)
    assert _doc_ops(built) == ops(mcp_routes()), _doc_ops(built) ^ ops(mcp_routes())


def test_the_generator_and_the_committed_document_agree(gen, full, committed):
    assert gen._read(gen.DOC_PATH) == gen.serialise(gen.filter_mcp(full, MCP_TAG))
    assert _doc_ops(committed) == _doc_ops(gen.filter_mcp(full, MCP_TAG))


def test_no_untagged_route_is_in_the_document(gen, full, committed):
    leaked = ops(untagged_routes()) & (_doc_ops(committed) | _doc_ops(gen.filter_mcp(full, MCP_TAG)))
    assert not leaked, f"untagged routes on the mcp surface: {sorted(leaked)}"


def test_every_operation_in_the_document_carries_the_tag(gen, full, committed):
    assert _untagged_in(committed) == [] and _untagged_in(gen.filter_mcp(full, MCP_TAG)) == []


def test_control_the_filter_drops_an_untagged_operation_and_the_checks_see_a_leak(gen, full):
    """CONTROL (the instrument can go red): a copy of the schema gains an untagged operation; the
    generator's filter must drop it, and the checks above must flag it if it were present."""
    probe = json.loads(json.dumps(full))
    probe["paths"]["/__untagged_probe__"] = {"get": {"tags": ["not-mcp"], "responses": {"200": {}}}}
    assert "/__untagged_probe__" not in gen.filter_mcp(probe, MCP_TAG)["paths"]
    leaky = json.loads(json.dumps(gen.filter_mcp(full, MCP_TAG)))
    leaky["paths"]["/__untagged_probe__"] = probe["paths"]["/__untagged_probe__"]
    assert _untagged_in(leaky) == [("GET", "/__untagged_probe__")]
    assert ("GET", "/__untagged_probe__") in _doc_ops(leaky) - ops(mcp_routes())
