"""Tests for the DagsterRunTracker virtual object.

Covers the bug fix where the tracker used to short-circuit on any cached
``dagster_run_id`` regardless of whether that run was still active. After
the fix, the tracker consults Dagster's GraphQL ``runOrError.status`` and
only dedupes against non-terminal runs.

Two surfaces are tested:

1. ``_fetch_dagster_run_status`` — the small helper that calls Dagster's
   GraphQL and maps responses to a Dagster ``RunStatus`` string.
2. ``get_or_launch_run`` — the handler logic, exercised through a hand-
   rolled FakeObjectContext that records ``get`` / ``set`` / ``clear`` /
   ``run`` calls without booting the Restate runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


# Make agent_fleet importable from the iagent repo root.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.restate_analyst import dagster_run_tracker as tracker_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Hand-rolled ObjectContext stand-in
# ---------------------------------------------------------------------------
class FakeObjectContext:
    """Minimal stand-in for restate.ObjectContext.

    Stores ``get`` state in a dict, treats ``run`` as "call the lambda
    immediately and return its awaited result." Records every state-mutation
    call so tests can assert behavior.
    """

    def __init__(self, initial_state: dict | None = None):
        self._state: dict[str, Any] = dict(initial_state or {})
        self.calls: list[tuple] = []

    async def get(self, key: str):
        return self._state.get(key)

    def set(self, key: str, value: Any) -> None:
        self.calls.append(("set", key, value))
        self._state[key] = value

    def clear(self, key: str) -> None:
        self.calls.append(("clear", key))
        self._state.pop(key, None)

    async def run(self, name: str, fn):
        # In real Restate this is durably journaled; for tests we just call it.
        result = fn()
        if hasattr(result, "__await__"):
            result = await result
        self.calls.append(("run", name))
        return result


# ---------------------------------------------------------------------------
# httpx stub plumbed via monkeypatch
# ---------------------------------------------------------------------------
class _StubResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _StubAsyncClient:
    """Captures POSTs and returns scripted responses."""

    last_post: dict | None = None

    def __init__(self, scripted: list[_StubResponse] | _StubResponse):
        if isinstance(scripted, _StubResponse):
            scripted = [scripted]
        self._queue = list(scripted)
        self.posts: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url: str, json: dict):
        self.posts.append({"url": url, "json": json})
        _StubAsyncClient.last_post = self.posts[-1]
        return self._queue.pop(0)


@pytest.fixture
def httpx_scripted(monkeypatch):
    """Returns a callable that scripts the next N httpx responses."""
    holder: dict[str, _StubAsyncClient] = {}

    def _install(*responses: _StubResponse):
        client = _StubAsyncClient(list(responses))
        # Each `async with httpx.AsyncClient(...) as c:` produces the same
        # instance so tests can read .posts off it.
        monkeypatch.setattr(
            tracker_mod.httpx, "AsyncClient",
            lambda *a, **k: client,
        )
        holder["client"] = client
        return client

    return _install


# ---------------------------------------------------------------------------
# Unwrap the @handler-decorated coroutine so we can call it directly
# ---------------------------------------------------------------------------
_HANDLER = tracker_mod.get_or_launch_run.__wrapped__


# ---------------------------------------------------------------------------
# _fetch_dagster_run_status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_status_returns_run_status(httpx_scripted):
    httpx_scripted(_StubResponse({
        "data": {"runOrError": {"__typename": "Run", "status": "STARTED"}}
    }))
    status = await tracker_mod.fetch_dagster_run_status(
        "http://dagster", "run-123"
    )
    assert status == "STARTED"


@pytest.mark.asyncio
async def test_fetch_status_terminal_success(httpx_scripted):
    httpx_scripted(_StubResponse({
        "data": {"runOrError": {"__typename": "Run", "status": "SUCCESS"}}
    }))
    status = await tracker_mod.fetch_dagster_run_status(
        "http://dagster", "run-123"
    )
    assert status == "SUCCESS"


@pytest.mark.asyncio
async def test_fetch_status_run_not_found_maps_to_canceled(httpx_scripted):
    """If Dagster lost the run entirely, treat it as terminal so we relaunch."""
    httpx_scripted(_StubResponse({
        "data": {"runOrError": {"__typename": "RunNotFoundError"}}
    }))
    status = await tracker_mod.fetch_dagster_run_status(
        "http://dagster", "run-gone"
    )
    assert status == "CANCELED"


@pytest.mark.asyncio
async def test_fetch_status_dagster_unreachable_returns_none(monkeypatch):
    """Transient Dagster outage → return None → caller keeps cached id."""
    class _ExplodingClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def post(self, *a, **k):
            raise RuntimeError("connection refused")
    monkeypatch.setattr(
        tracker_mod.httpx, "AsyncClient", lambda *a, **k: _ExplodingClient()
    )
    status = await tracker_mod.fetch_dagster_run_status(
        "http://dagster", "run-123"
    )
    assert status is None


# ---------------------------------------------------------------------------
# get_or_launch_run — empty slot → launch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_slot_launches_new_run(httpx_scripted):
    """No cached run_id → launch a fresh Dagster run."""
    httpx_scripted(_StubResponse({
        "data": {"launchRun": {
            "__typename": "LaunchRunSuccess",
            "run": {"runId": "new-run-1"},
        }}
    }))
    ctx = FakeObjectContext()
    result = await _HANDLER(ctx, {
        "dagster_url": "http://dagster",
        "mutation": "mutation { launchRun ... }",
        "variables": {"foo": "bar"},
    })
    assert result == "new-run-1"
    # State was set with the new run id
    assert ("set", "dagster_run_id", "new-run-1") in ctx.calls


# ---------------------------------------------------------------------------
# get_or_launch_run — active cached run → DEDUPE (return existing)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_active_run_is_returned_without_relaunching(httpx_scripted):
    """Cached run is still STARTED → return existing id, do not launch."""
    client = httpx_scripted(_StubResponse({
        "data": {"runOrError": {"__typename": "Run", "status": "STARTED"}}
    }))
    ctx = FakeObjectContext({"dagster_run_id": "active-run"})
    result = await _HANDLER(ctx, {
        "dagster_url": "http://dagster",
        "mutation": "...",
        "variables": {},
    })
    assert result == "active-run"
    # Only the status query was made — no launchRun mutation.
    assert len(client.posts) == 1
    # State was not mutated.
    assert not any(c[0] == "set" for c in ctx.calls)
    assert not any(c[0] == "clear" for c in ctx.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_status",
    ["QUEUED", "NOT_STARTED", "STARTING", "STARTED", "CANCELING", "MANAGED"],
)
async def test_all_non_terminal_statuses_dedupe(httpx_scripted, active_status):
    client = httpx_scripted(_StubResponse({
        "data": {"runOrError": {"__typename": "Run", "status": active_status}}
    }))
    ctx = FakeObjectContext({"dagster_run_id": "active-run"})
    result = await _HANDLER(ctx, {
        "dagster_url": "http://dagster",
        "mutation": "...",
        "variables": {},
    })
    assert result == "active-run"
    assert len(client.posts) == 1


# ---------------------------------------------------------------------------
# get_or_launch_run — terminal cached run → CLEAR + LAUNCH fresh
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["SUCCESS", "FAILURE", "CANCELED"])
async def test_terminal_run_is_replaced_with_fresh_launch(
    httpx_scripted, terminal_status,
):
    """Cached run is terminal → clear it, launch a new run, save new id."""
    client = httpx_scripted(
        _StubResponse({
            "data": {"runOrError": {"__typename": "Run", "status": terminal_status}}
        }),
        _StubResponse({
            "data": {"launchRun": {
                "__typename": "LaunchRunSuccess",
                "run": {"runId": "fresh-run"},
            }}
        }),
    )
    ctx = FakeObjectContext({"dagster_run_id": "old-finished-run"})
    result = await _HANDLER(ctx, {
        "dagster_url": "http://dagster",
        "mutation": "...",
        "variables": {},
    })
    assert result == "fresh-run"
    assert len(client.posts) == 2  # status check + launch
    assert ("clear", "dagster_run_id") in ctx.calls
    assert ("set", "dagster_run_id", "fresh-run") in ctx.calls


# ---------------------------------------------------------------------------
# Defensive: Dagster status unknown → treat as still-active, keep dedup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_status_keeps_existing_run(monkeypatch):
    """If we cannot reach Dagster to confirm the cached run's status, we
    must NOT relaunch — otherwise a Dagster outage would cause every
    subsequent request to mint a duplicate run."""
    class _Unreachable:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def post(self, *a, **k):
            raise RuntimeError("dagster down")
    monkeypatch.setattr(
        tracker_mod.httpx, "AsyncClient", lambda *a, **k: _Unreachable()
    )
    ctx = FakeObjectContext({"dagster_run_id": "active-run"})
    result = await _HANDLER(ctx, {
        "dagster_url": "http://dagster",
        "mutation": "...",
        "variables": {},
    })
    assert result == "active-run"
    assert not any(c[0] == "clear" for c in ctx.calls)
    assert not any(c[0] == "set" for c in ctx.calls)


# ---------------------------------------------------------------------------
# Missing payload fields short-circuit safely
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_dagster_url_returns_none():
    ctx = FakeObjectContext()
    result = await _HANDLER(ctx, {"mutation": "...", "variables": {}})
    assert result is None
    assert ctx.calls == []


@pytest.mark.asyncio
async def test_missing_mutation_returns_none():
    ctx = FakeObjectContext()
    result = await _HANDLER(ctx, {"dagster_url": "http://dagster"})
    assert result is None
    assert ctx.calls == []


# ---------------------------------------------------------------------------
# Failed launch (Dagster validation error) does not poison state
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_launch_does_not_save_run_id(httpx_scripted):
    httpx_scripted(_StubResponse({
        "data": {"launchRun": {
            "__typename": "RunConfigValidationInvalid",
            "errors": [{"message": "bad config"}],
        }}
    }))
    ctx = FakeObjectContext()
    result = await _HANDLER(ctx, {
        "dagster_url": "http://dagster",
        "mutation": "...",
        "variables": {},
    })
    assert result is None
    assert not any(c[0] == "set" for c in ctx.calls)
