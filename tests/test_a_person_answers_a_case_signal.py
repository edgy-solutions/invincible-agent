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

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("status", request=None, response=self)


_NO_CASE = object()


class _FakeRunner:
    """Answers the shared `case` handler with `case` (default: C1 with one instance, `C1~1`;
    `_NO_CASE` answers the empty 200 Restate gives for a case that does not exist) and every
    other POST (the signal) with `status` / `body`."""

    def __init__(self, status=200, body=None, boom=False, case="default"):
        self.status, self.body, self.boom = status, body, boom
        if case == "default":
            case = {"instances": [{"n": 1, "instance_id": "C1~1", "definition_id": "maint_release"}]}
        self.case = case
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
        if url.endswith("/case"):
            if self.case is _NO_CASE:
                resp = _FakeResp(200)
                resp.content = b""
                return resp
            return _FakeResp(200, self.case)
        return _FakeResp(self.status, self.body)

    @property
    def signal_posts(self):
        return [p for p in self.posts if p["url"].endswith("/signal")]


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
    assert resp.json() == {"case_id": "C1", "instance_id": "C1~1", "signal": "tier_ack",
                           "status": "released", "acted_by": "tier@x"}
    assert len(runner.signal_posts) == 1
    assert runner.signal_posts[0]["url"].endswith("/WorkflowRunner/C1~1/signal")
    assert runner.signal_posts[0]["json"] == {"signal": "tier_ack", "status": "released",
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
    runner = _FakeRunner(404, {"message": "no case"}, case=_NO_CASE)
    resp = client_for("tier@x", runner).post("/cases/nope/signals/tier_ack",
                                             json={"status": "released"})
    assert resp.status_code == 404
    assert runner.signal_posts == []


def test_runner_404_on_the_signal_is_404(client_for):
    runner = _FakeRunner(404, {"message": "no case"})
    resp = client_for("tier@x", runner).post(_URL, json={"status": "released"})
    assert resp.status_code == 404


def test_a_case_with_no_instance_is_forwarded_to_the_case_key(client_for):
    runner = _FakeRunner(403, {"message": "no signal 'tier_ack' is awaited on 'C1'"},
                         case={"instances": []})
    resp = client_for("tier@x", runner).post(_URL, json={"status": "released"})
    assert resp.status_code == 403
    assert runner.signal_posts[0]["url"].endswith("/WorkflowRunner/C1/signal")


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


# --- D1: the signal reaches the awaiting INSTANCE (lane/74 live walk 10-17) -----------------
_CASE = "712382d7-00c2-5610-a3cf-0e1c9ef5ea70"
_DEFS = ["maint_fault_propose", "maint_supervisor_review", "maint_release"]


class _KeyedRunner(_FakeRunner):
    """The real runner's shape: `signal_accepts:tier_ack` is journalled on `<case>~3` ONLY, so a
    signal answers 200 for that key and the runner's own TerminalError for any other."""

    def __init__(self):
        super().__init__(case={"instances": [
            {"n": n, "instance_id": f"{_CASE}~{n}", "definition_id": d}
            for n, d in enumerate(_DEFS, start=1)]})
        self.accepts = {f"{_CASE}~3": {"tier_ack": ["released"]}}

    async def post(self, url, json=None, **kw):
        if url.endswith("/case"):
            return await super().post(url, json=json, **kw)
        self.posts.append({"url": url, "json": json})
        from urllib.parse import unquote
        key = unquote(url.split("/WorkflowRunner/")[1].rsplit("/signal", 1)[0])
        if json["status"] in self.accepts.get(key, {}).get(json["signal"], []):
            return _FakeResp(200)
        return _FakeResp(403, {"code": 403,
                               "message": f"no signal '{json['signal']}' is awaited on '{key}'"})


def test_a_case_id_reaches_the_instance_that_awaits_the_signal(client_for):
    runner = _KeyedRunner()
    resp = client_for("tier@x", runner).post(f"/cases/{_CASE}/signals/tier_ack",
                                             json={"status": "released"})
    assert resp.status_code == 200, resp.text
    assert runner.signal_posts[0]["url"].endswith(f"/WorkflowRunner/{_CASE}~3/signal")
    assert resp.json()["instance_id"] == f"{_CASE}~3"
    assert resp.json()["case_id"] == _CASE


def test_control_an_instance_id_is_forwarded_unchanged(client_for):
    runner = _KeyedRunner()
    resp = client_for("tier@x", runner).post(f"/cases/{_CASE}~3/signals/tier_ack",
                                             json={"status": "released"})
    assert resp.status_code == 200, resp.text
    assert runner.signal_posts[0]["url"].endswith(f"/WorkflowRunner/{_CASE}~3/signal")
    assert not any(p["url"].endswith("/case") for p in runner.posts)


def test_the_gateways_separator_is_the_runners():
    from agent_fleet.restate_analyst.case_routing import CHILD_SEP
    assert gateway._CASE_INSTANCE_SEP == CHILD_SEP
