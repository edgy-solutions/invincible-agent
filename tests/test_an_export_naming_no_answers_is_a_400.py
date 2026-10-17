"""RULED 2026-10-17: `POST /export/package` naming no answers (and no template) is a 400
`no_answers`, before any engine sees it. An empty list used to export the recipient's whole
program -- a disclosure path nothing in the UI can reach (cortex-ui disables the button on an
empty board). The check is a shape fault, so it precedes the recipient checks (409/403)."""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402

SCOPE = "notional-customer-alpha"


@pytest.fixture
def world(monkeypatch):
    calls: list = []
    user = type("U", (), {
        "authz_id": "alice@example.com", "id": "sub-alice", "email": "alice@example.com",
        "roles": [], "persona": None, "entitled_domains": [], "is_authenticated": True,
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None, **k):
            calls.append(url)
            raise AssertionError(f"an engine was called: {url}")

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    with TestClient(gateway.app, raise_server_exceptions=False) as c:
        yield c, calls
    gateway.app.dependency_overrides.clear()


def test_empty_answers_with_a_recipient_is_a_400_and_no_engine_call(world):
    c, calls = world
    r = c.post("/export/package", json={"recipient_scope": SCOPE, "answers": []})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == {"reason": "no_answers"}
    assert len(calls) == 0, calls


def test_omitted_answers_is_the_same_400_and_no_engine_call(world):
    c, calls = world
    r = c.post("/export/package", json={"recipient_scope": SCOPE})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == {"reason": "no_answers"}
    assert len(calls) == 0, calls


def test_no_answers_and_no_recipient_is_a_400_not_a_409(world):
    c, calls = world
    r = c.post("/export/package", json={"answers": []})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == {"reason": "no_answers"}
    assert len(calls) == 0, calls


def test_control_a_template_with_no_answers_reaches_the_template_path(world, monkeypatch):
    c, _ = world
    reached: list = []

    async def _template(body, request, current_user, as_of):
        reached.append(body.template_id)
        return {"ok": True}

    monkeypatch.setattr(gateway, "_export_package_from_template", _template)
    r = c.post("/export/package", json={"template_id": "program_finance"})
    assert r.status_code == 200, r.text
    assert reached == ["program_finance"]
