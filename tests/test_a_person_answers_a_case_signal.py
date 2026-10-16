"""`POST /cases/{case_id}/signals/{signal}` -- a person answers a case's human-audience signal
(architect ruling 2026-10-10: "tier_ack gets a BFF route: a human acknowledgment is a cortex
action"). The route is generic over the signal name; engine-a's WorkflowRunner.signal is the
authority. This file seals the route's own wiring: the actor comes from the token, the body
cannot name one, and every runner refusal reaches the caller as a refusal, never a 200.

The Restate ingress is a fake `httpx.AsyncClient`, as in `tests/test_cases_route.py`.

Run: uv run --frozen pytest -q tests/test_a_person_answers_a_case_signal.py -v
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402


class _FakeResp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = b"x"
        self.text = str(self._body)

    def json(self):
        return self._body


class _FakeRunner:
    def __init__(self, status=200, body=None, boom=False):
        self.status, self.body, self.boom = status, body, boom
        self.posts = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        self.posts.append({"url": url, "json": json})
        if self.boom:
            raise httpx.ConnectError("runner unreachable")
        return _FakeResp(self.status, self.body)


@pytest.fixture
def client_for(monkeypatch):
    def _make(authz_id, runner):
        monkeypatch.setattr(gateway.httpx, "AsyncClient", runner)
        user = SimpleNamespace(authz_id=authz_id,
                               entitlements=SimpleNamespace(cells=[]))
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


_URL = "/cases/C1/signals/tier_ack"


def test_happy_path_posts_the_token_actor_to_the_runner(client_for):
    runner = _FakeRunner(200, {})
    resp = client_for("tier@x", runner).post(_URL, json={"status": "released"})
    assert resp.status_code == 200
    assert resp.json() == {"case_id": "C1", "signal": "tier_ack", "status": "released",
                           "acted_by": "tier@x"}
    assert len(runner.posts) == 1
    assert runner.posts[0]["url"].endswith("/WorkflowRunner/C1/signal")
    assert runner.posts[0]["json"] == {"signal": "tier_ack", "status": "released",
                                       "comments": "", "acted_by": "tier@x"}


def test_a_body_naming_the_actor_is_422_and_nothing_is_sent(client_for):
    runner = _FakeRunner(200, {})
    resp = client_for("tier@x", runner).post(
        _URL, json={"status": "released", "acted_by": "someone@else"})
    assert resp.status_code == 422
    assert runner.posts == []


@pytest.mark.parametrize("runner_status,expect", [(401, 403), (403, 403)])
def test_runner_authority_refusal_is_403_with_its_message(client_for, runner_status, expect):
    runner = _FakeRunner(runner_status, {"message": "not authorized (can_act)"})
    resp = client_for("tier@x", runner).post(_URL, json={"status": "released"})
    assert resp.status_code == expect
    assert "not authorized (can_act)" in resp.text


def test_runner_400_is_400_with_its_message(client_for):
    runner = _FakeRunner(400, {"message": "needs a reason"})
    resp = client_for("tier@x", runner).post(_URL, json={"status": "tier_refused"})
    assert resp.status_code == 400
    assert "needs a reason" in resp.text


def test_unknown_case_is_404(client_for):
    runner = _FakeRunner(404, {"message": "no case"})
    resp = client_for("tier@x", runner).post("/cases/nope/signals/tier_ack",
                                             json={"status": "released"})
    assert resp.status_code == 404


def test_runner_unreachable_is_502(client_for):
    resp = client_for("tier@x", _FakeRunner(boom=True)).post(_URL, json={"status": "released"})
    assert resp.status_code == 502
    assert "ConnectError" in resp.text


def test_runner_5xx_is_502(client_for):
    resp = client_for("tier@x", _FakeRunner(500, {"message": "boom"})).post(
        _URL, json={"status": "released"})
    assert resp.status_code == 502


@pytest.mark.parametrize("authz_id", ["", "   ", None])
def test_no_authz_id_is_401_and_nothing_is_sent(client_for, authz_id):
    runner = _FakeRunner(200, {})
    resp = client_for(authz_id, runner).post(_URL, json={"status": "released"})
    assert resp.status_code == 401
    assert runner.posts == []
