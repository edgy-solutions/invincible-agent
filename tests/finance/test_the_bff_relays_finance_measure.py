"""POST /finance/measure/{fn}: a thin BFF relay to finance_agent `/measure/{fn}` (MCP item 2).

Driven through the real route. The httpx double returns a REAL `httpx.Response`, so the wire's
shape (status, headers, body bytes) is what the route parses.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from src.iagent import gateway

BEARER = "tok-abc"
AUTHZ = "alice@example.com"
PARAMS = {"program": "NP-MERIDIAN", "as_of": "2026-09-30"}
ENGINE_200 = {"measure": "eac", "output_uri": "dist/eac.duckdb", "rows": [{"wbs": "1.1", "eac": "12.50"}]}
NEEDS = {"needs_slots": ["program"], "question": "Which program?", "slots": ["program", "as_of"]}
REFUSAL = {"error": "program_not_visible",
           "refusal": {"policy_id": "program_members", "missing_binding": "can_view_program(program)",
                       "candidates": []},
           "message": "You are not a member of the program this request names."}


class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = AUTHZ
    email = AUTHZ


@pytest.fixture
def wire(monkeypatch):
    seen: list[httpx.Request] = []
    box: dict = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            req = httpx.Request("POST", url, json=json, headers=headers)
            seen.append(req)
            if "raise" in box:
                raise box["raise"]
            return httpx.Response(box["status"], content=box["content"],
                                  headers={"content-type": "application/json"}, request=req)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    box["seen"] = seen
    return box


@pytest.fixture
def client():
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User()
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


def _post(c, fn="eac"):
    return c.post(f"/finance/measure/{fn}", json={"params": PARAMS},
                  headers={"Authorization": f"Bearer {BEARER}"})


def test_a_200_is_relayed_with_the_callers_bearer_and_identity(wire, client):
    import json
    compact = json.dumps(ENGINE_200, separators=(",", ":")).encode()  # JSONResponse's own form
    wire.update(status=200, content=compact)
    r = _post(client)
    assert r.status_code == 200
    req = wire["seen"][0]
    assert str(req.url).endswith("/measure/eac")
    assert json.loads(req.content) == {"params": PARAMS, "user_email": AUTHZ}
    assert req.headers["authorization"] == f"Bearer {BEARER}"
    assert r.content == compact
    assert r.json() == ENGINE_200


def test_a_needs_slots_422_is_relayed_unchanged(wire, client):
    import json
    wire.update(status=422, content=json.dumps({"detail": NEEDS}).encode())
    r = _post(client)
    assert r.status_code == 422
    assert r.json()["detail"] == NEEDS


def test_a_policy_403_keeps_its_refusal_fields(wire, client):
    import json
    wire.update(status=403, content=json.dumps({"detail": REFUSAL}).encode())
    r = _post(client)
    assert r.status_code == 403
    ref = r.json()["detail"]["refusal"]
    assert ref["policy_id"] == "program_members"
    assert ref["missing_binding"] == "can_view_program(program)"
    assert ref["candidates"] == []
    # relay_refusal NAMES the grantor; the engine did not send one.
    assert "grantable_by" in ref


def test_a_404_stays_404(wire, client):
    import json
    wire.update(status=404, content=json.dumps({"detail": "unknown measure"}).encode())
    assert _post(client, "nope").status_code == 404


def test_an_unreachable_engine_is_a_502_not_an_empty_200(wire, client):
    wire["raise"] = httpx.ConnectError("refused")
    r = _post(client)
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "fin_engine_unreachable"


def test_control_no_bearer_is_401_and_nothing_reaches_the_engine(wire):
    import json
    wire.update(status=200, content=json.dumps(ENGINE_200).encode())
    gateway.app.dependency_overrides.clear()
    with TestClient(gateway.app) as c:
        r = c.post("/finance/measure/eac", json={"params": PARAMS})
    assert r.status_code == 401
    assert wire["seen"] == []


@pytest.mark.parametrize("raw", ["%2E%2E", "eac%3Fx=1", "eac%23frag", ".hidden"])
def test_a_name_that_is_not_one_plain_segment_never_reaches_the_engine(wire, client, raw):
    """`fn` is spliced into the engine URL. Decoded, these would climb to the engine's root
    (`..`), smuggle a query or fragment, or name a dot-file; each is refused before any call."""
    import json
    wire.update(status=200, content=json.dumps(ENGINE_200).encode())
    r = _post(client, raw)
    assert r.status_code == 422, r.text
    assert wire["seen"] == []


def test_a_422_is_never_completed_as_a_policy_refusal(wire, client):
    """relay_refusal passes a plain needs_slots dict through, so arm b alone cannot tell the 422
    branch from the policy branch. A 422 detail that happens to carry a `refusal` shape does:
    the 422 branch relays it untouched (no `grantable_by` added)."""
    import json
    detail = {**NEEDS, "refusal": {"policy_id": "program_members",
                                   "missing_binding": "can_view_program(program)", "candidates": []}}
    wire.update(status=422, content=json.dumps({"detail": detail}).encode())
    r = _post(client)
    assert r.status_code == 422
    assert r.json()["detail"] == detail
