"""The MCP surface, DERIVED from the app the server serves. Nothing here names a route, a tool or a
tag value of its own: the tag is `ingest_api.MCP_TAG`, the routes are whatever `gateway.app`
registers under it, and the document is whatever the generator writes.

`stub_for(route)` builds a one-route app carrying the route's OWN dependency chain (what the live
route depends on) in front of a handler that only says "reached". It exists so a seal can ask "does
this route's door admit this caller" without ever running a handler (a handler may touch neo4j,
Topaz or an engine; a seal must not).
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent import gateway  # noqa: E402
from src.iagent.ingest_api import MCP_TAG  # noqa: E402


def mcp_routes() -> list[APIRoute]:
    return [r for r in gateway.app.routes if isinstance(r, APIRoute) and MCP_TAG in (r.tags or [])]


def untagged_routes() -> list[APIRoute]:
    return [r for r in gateway.app.routes
            if isinstance(r, APIRoute) and r.include_in_schema and MCP_TAG not in (r.tags or [])]


def ops(routes) -> set[tuple[str, str]]:
    return {(m.upper(), r.path) for r in routes for m in r.methods if m.upper() != "HEAD"}


def concrete_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def stub_for(route: APIRoute) -> FastAPI:
    """The route's dependency chain in front of a handler that cannot do anything."""
    app = FastAPI()
    deps = [Depends(d.call) for d in route.dependant.dependencies]
    deps += list(route.dependencies)

    async def reached():
        return {"reached": True}

    app.add_api_route("/x", reached, methods=["GET"], dependencies=deps)
    return app


def generator():
    spec = importlib.util.spec_from_file_location(
        "_gen_mcp_openapi_seal", ROOT / "scripts" / "generate_mcp_openapi.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod
