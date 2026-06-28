"""Overnight item 3 — `POST /projector/poll` must be gated.

Without a gate, the endpoint is an unauthenticated mutation surface
exposed in every production deploy. The probe asserts the endpoint
returns 404 when the gate env var is unset, and 200 when set.

RED-first discipline per `[[pre-written-fixtures-must-fail-first]]`:
this file lands BEFORE the gate. Run `pytest -k force_poll_gating`
before applying the fix → both legs FAIL (the endpoint responds 200
regardless of env). After the fix, both legs pass.

No cluster connectivity required. Uses FastAPI TestClient against
`create_app(loop=stub_loop)` so neither Neo4j nor Postgres are
touched.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class _StubLoop:
    """Minimal stub: create_app's lifespan calls `loop.run_forever()`
    and stores `loop` on app.state. Endpoints we test here read
    `app.state.loop` — only `get_cursor_state` is used in /watermark
    and we don't hit /watermark, so this stub is sufficient.
    """

    def __init__(self) -> None:
        self.run_calls = 0
        self.apply_calls = 0
        self.closed = False

    async def run_forever(self) -> None:
        self.run_calls += 1
        # Block forever so the lifespan task doesn't immediately
        # complete — that would surface unrelated FastAPI warnings.
        # We never wait for it; the TestClient context exits cleanly.
        import asyncio

        await asyncio.Event().wait()

    def apply_once(self) -> int:
        # If the endpoint IS callable (gate off / wrong), this gets
        # incremented. The probe asserts this stays 0 when the gate
        # is off.
        self.apply_calls += 1
        return 0

    async def apply_once_async(self) -> int:
        # Production force_poll endpoint uses the async variant for the
        # concurrency lock (see ApplyLoop.apply_once_async). The stub
        # just delegates so the gating probe still verifies route
        # presence/absence without exercising real Neo4j/Postgres.
        return self.apply_once()

    def close(self) -> None:
        self.closed = True

    def get_cursor_state(self) -> Any:  # pragma: no cover (not hit here)
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _clear_env():
    """Each test starts with a clean PROJECTOR_ENABLE_FORCE_POLL env."""
    saved = os.environ.pop("PROJECTOR_ENABLE_FORCE_POLL", None)
    yield
    if saved is not None:
        os.environ["PROJECTOR_ENABLE_FORCE_POLL"] = saved
    else:
        os.environ.pop("PROJECTOR_ENABLE_FORCE_POLL", None)


def _make_app(loop: _StubLoop):
    from src.iagent.projector.app import create_app

    return create_app(loop=loop)


def test_force_poll_disabled_returns_404_when_env_unset() -> None:
    """RED-first reason (before fix): the endpoint is mounted
    unconditionally, so POST returns 200 regardless of env. Probe
    fails on `assert resp.status_code == 404`.

    GREEN reason (after fix): conditional registration — when
    PROJECTOR_ENABLE_FORCE_POLL is unset, the route is not in the
    router and FastAPI returns 404.
    """
    loop = _StubLoop()
    app = _make_app(loop)
    with TestClient(app) as client:
        resp = client.post("/projector/poll")
    assert resp.status_code == 404, (
        f"Expected 404 when PROJECTOR_ENABLE_FORCE_POLL is unset, "
        f"got {resp.status_code}: {resp.text!r}. The endpoint is "
        f"either mounted unconditionally (the gap this probe targets) "
        f"or the conditional logic is misreading the env."
    )
    assert loop.apply_calls == 0, (
        f"`apply_once` was called {loop.apply_calls} times even though "
        f"the endpoint is supposed to be gated off. The 404 is not "
        f"actually preventing the mutation."
    )


def test_force_poll_enabled_returns_200_when_env_true() -> None:
    """GREEN: with the gate flipped, the endpoint works as before.
    The probe + fix together preserve the test affordance for
    explicit opt-in callers (the Hop 2 phase suite sets this in its
    test bootstrap).
    """
    os.environ["PROJECTOR_ENABLE_FORCE_POLL"] = "true"
    loop = _StubLoop()
    app = _make_app(loop)
    with TestClient(app) as client:
        resp = client.post("/projector/poll")
    assert resp.status_code == 200, (
        f"Expected 200 when PROJECTOR_ENABLE_FORCE_POLL=true, got "
        f"{resp.status_code}: {resp.text!r}. The gate is over-locking — "
        f"a deliberate opt-in must still reach the endpoint."
    )
    body = resp.json()
    assert body == {"applied": 0}, (
        f"Endpoint reachable but body shape changed: {body!r}"
    )
    assert loop.apply_calls == 1, (
        f"Endpoint returned 200 but `apply_once` was called "
        f"{loop.apply_calls} times; expected exactly 1."
    )


@pytest.mark.parametrize("truthy", ["true", "True", "TRUE", "1", "yes"])
def test_force_poll_enabled_accepts_common_truthy_values(truthy: str) -> None:
    """Gate accepts common truthy spellings. Per
    `[[optimistic-defaults-are-dishonest]]`, the DEFAULT remains
    "off" — any non-truthy value (including unset, empty string,
    "false") leaves the endpoint 404. This parametrize just exercises
    the truthy table.
    """
    os.environ["PROJECTOR_ENABLE_FORCE_POLL"] = truthy
    loop = _StubLoop()
    app = _make_app(loop)
    with TestClient(app) as client:
        resp = client.post("/projector/poll")
    assert resp.status_code == 200, (
        f"Truthy value {truthy!r} should enable the endpoint; got "
        f"{resp.status_code}"
    )


@pytest.mark.parametrize("falsy", ["", "false", "False", "0", "no"])
def test_force_poll_disabled_for_explicit_falsy_values(falsy: str) -> None:
    """Explicit falsy values stay 404 — same as unset."""
    os.environ["PROJECTOR_ENABLE_FORCE_POLL"] = falsy
    loop = _StubLoop()
    app = _make_app(loop)
    with TestClient(app) as client:
        resp = client.post("/projector/poll")
    assert resp.status_code == 404, (
        f"Falsy value {falsy!r} should leave the endpoint 404; got "
        f"{resp.status_code}"
    )
