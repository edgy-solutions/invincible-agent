"""Doubles for the FRACAS per-caller program filter (ADR-0056 Q2).

The seams are the REAL boundaries, not the function under test: the caller comes from
`iagent_mesh.transport_auth.current_caller` (what the engine reads), and Topaz is an
`httpx.MockTransport` behind the real `utils/program_membership.can_view_program`, so the
request payload that goes out is the real one. The mapping file is the real shipped overlay.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
SAMPLE_OVERLAY = REPO / "policy" / "overlays" / "sample"

ALICE, BOB, CAROL = "alice@example.com", "bob@example.com", "carol@example.com"
ALL_PROGRAMS = {ALICE: {"SANDBOX_PROGRAM_ALPHA", "SANDBOX_PROGRAM_BRAVO"}}


def install(monkeypatch, *, caller, members=None, topaz_down=False, overlay_dirs=None,
            http_status=None):
    """caller: the authz_id of the request (None = unresolved). members: {authz_id: {program}}."""
    from iagent_mesh import transport_auth
    from agent_fleet.utils import program_membership as pm

    ident = transport_auth.CallerIdentity(caller, verified=bool(caller), reason="test")
    monkeypatch.setattr(transport_auth, "current_caller", lambda: ident)
    monkeypatch.setenv("PLATFORM_PROGRAM_OVERLAY_DIRS",
                       str(SAMPLE_OVERLAY) if overlay_dirs is None else overlay_dirs)
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://topaz.test")
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        if topaz_down:
            raise httpx.ConnectError("topaz is down", request=request)
        if http_status:
            return httpx.Response(http_status)
        body = json.loads(request.content)
        asked.append(body)
        ok = body["object_id"] in (members or {}).get(body["subject_id"], set())
        return httpx.Response(200, json={"check": ok})

    real_client = getattr(pm.httpx.Client, "_real", pm.httpx.Client)

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(*a, **kw)

    factory._real = real_client
    monkeypatch.setattr(pm.httpx, "Client", factory)
    return asked
