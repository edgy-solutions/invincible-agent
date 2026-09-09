"""NUCLEAR-CLEARS-RESTATE SEAL — a wipe must not leave the workflow engine behind.

WHAT WENT WRONG (work, 2026-09-09). The nuclear prime truncated
`human_task_projection` but never touched Restate, which keeps its journal on its
OWN PVC. Thirty `GroupedReview` workflows — the oldest from 2026-07-30 — were left
`suspended` forever, each parked on a promise only its now-deleted human task could
resolve, and each still HOLDING its single-use workflow key.

Nothing reported an error. `ctx.workflow_send` is fire-and-forget, so a send to a
held key is swallowed and `start_review` returns STARTED; the ingress
Idempotency-Key is retained for 24h, so a re-drive REPLAYS the cached response
without executing the handler at all. Six weeks of green Dagster runs, one review.
The review pipeline was never broken — only the state around it.

WHY A "WIPE EVERYTHING" COMMENT COULD NOT CATCH IT. The wipe enumerated the stores
it knew about. Restate was not one of them, and no store announces its own absence.
Durable state that outlives a wipe of everything it REFERENCES is worse than no
state: it silently blocks the retry that would otherwise recover.

WHAT THIS SEALS:
  * the QUIET arm — an emptied journal returns normally, so a working prime is not
    blocked (a seal that only ever raises is indistinguishable from a broken wipe);
  * the LOUD arm — any survivor raises, because a surviving invocation holds a key
    and the next re-drive of its artifact will return STARTED and create nothing;
  * the KILL-THEN-PURGE arm — `purge` accepts only COMPLETED invocations and `kill`
    is ASYNCHRONOUS, so a live invocation must be killed and purged across passes.
    Purging once and declaring victory is the bug wearing a wipe's name;
  * the UNSET arm — a missing RESTATE_ADMIN_URL raises rather than skipping. A wipe
    that silently omits a store is exactly how this shipped;
  * the TIER arm — the purge is reachable ONLY under --nuclear, and runs BEFORE the
    Postgres reset. That order is load-bearing: if Restate fails, the task store is
    still intact and the two stay consistently stale; the reverse order recreates
    the split-brain.

Run: uv run --frozen --with pytest pytest tests/test_prime_nuclear_clears_restate.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "setup" / "prime_databases.py"

# Loaded under a unique name, never bare "prime_databases": this repo has had a
# suite go red purely from sys.modules cache collisions across same-named files.
_MOD_NAME = "prime_databases__nuclear_restate_test"

_ADMIN = "http://restate.test:9070"


def _mod():
    cached = sys.modules.get(_MOD_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_MOD_NAME, None)
        pytest.skip(f"prime_databases not importable here: {type(exc).__name__}: {exc}")
    return m


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _stub_restate(monkeypatch, mod, journal, *, kill_wedged=False):
    """Model the real admin API over an in-memory journal {inv_id: status}.

    `kill` flips a live invocation to "completed" (asynchronously in the real
    engine — here, by the next read, which is what the pass loop must tolerate).
    `purge` removes a COMPLETED invocation and REFUSES a live one, exactly as
    Restate does. `kill_wedged` models an invocation that will not die.
    """
    calls = {"kill": [], "purge": [], "queries": 0}

    def _post(url, json=None, headers=None, proxies=None, verify=None, timeout=None):  # noqa: A002
        assert url == f"{_ADMIN}/query", url
        assert (headers or {}).get("accept") == "application/json", headers
        calls["queries"] += 1
        return _Resp({"rows": [{"id": i, "status": s} for i, s in journal.items()]})

    def _patch(url, proxies=None, verify=None, timeout=None):
        inv, verb = url.rsplit("/", 2)[-2:]
        calls[verb].append(inv)
        if verb == "kill":
            if not kill_wedged:
                journal[inv] = "completed"
            return _Resp()
        if journal.get(inv) != "completed":
            return _Resp(status=409)  # Restate refuses to purge a live invocation
        journal.pop(inv, None)
        return _Resp()

    monkeypatch.setenv("RESTATE_ADMIN_URL", _ADMIN)
    monkeypatch.setattr(mod.requests, "post", _post)
    monkeypatch.setattr(mod.requests, "patch", _patch)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    return calls


def test_empty_journal_returns_quietly(monkeypatch):
    """THE POSITIVE CONTROL. A seal that always raises blocks every prime."""
    mod = _mod()
    _stub_restate(monkeypatch, mod, {})
    mod._reset_restate_journal()  # must not raise


def test_kill_then_purge_across_passes(monkeypatch):
    """A live invocation is KILLED, then PURGED on a later pass — not purged once
    and abandoned. The completed one is purged immediately."""
    mod = _mod()
    # Bound the budget: a CORRECT implementation empties the journal in two
    # instant passes, so this never bites here. It exists so that a regression
    # (purging without ever killing) fails in seconds instead of spinning out the
    # full production budget — a seal that takes three minutes to report a failure
    # is a seal that gets switched off.
    monkeypatch.setattr(mod, "_RESTATE_PURGE_BUDGET_S", 5)
    journal = {"inv_live": "suspended", "inv_done": "completed"}
    calls = _stub_restate(monkeypatch, mod, journal)

    mod._reset_restate_journal()

    assert journal == {}, "the journal must end empty"
    assert calls["kill"] == ["inv_live"], "only the live invocation is killed"
    # inv_done purged on pass 1; inv_live purged on pass 2, after its kill settled.
    assert calls["purge"] == ["inv_done", "inv_live"], calls["purge"]
    assert calls["queries"] >= 2, "must re-read after killing — kill is async"


def test_survivor_raises(monkeypatch):
    """THE LOUD ARM. An invocation that will not die must fail the wipe: it still
    holds a single-use key, and the next re-drive returns STARTED creating nothing."""
    mod = _mod()
    monkeypatch.setattr(mod, "_RESTATE_PURGE_BUDGET_S", 0.05)
    journal = {"inv_wedged": "suspended"}
    _stub_restate(monkeypatch, mod, journal, kill_wedged=True)

    with pytest.raises(RuntimeError) as exc:
        mod._reset_restate_journal()
    msg = str(exc.value)
    assert "inv_wedged" in msg, "the survivor must be NAMED, not merely counted"
    assert "STARTED" in msg, "the message must say what the survivor will silently do"


def test_unset_admin_url_raises(monkeypatch):
    """A wipe that silently omits a store is exactly how this shipped."""
    mod = _mod()
    monkeypatch.delenv("RESTATE_ADMIN_URL", raising=False)
    with pytest.raises(RuntimeError, match="RESTATE_ADMIN_URL"):
        mod._reset_restate_journal()


def test_purge_is_nuclear_only_and_precedes_postgres():
    """THE TIER ARM, read from the SYNTAX TREE rather than from prose.

    Both resets must sit under `if nuclear:`, and Restate must come first — if it
    raises, the task store is still populated and the two remain consistently
    stale. The reverse order is the split-brain itself.
    """
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "wipe_databases"
    )

    guarded: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if not (isinstance(node.test, ast.Name) and node.test.id == "nuclear"):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                guarded.append(call.func.id)

    assert "_reset_restate_journal" in guarded, (
        "the Restate purge must be reachable only under --nuclear"
    )
    assert guarded.index("_reset_restate_journal") < guarded.index(
        "_reset_projection_postgres"
    ), "Restate must be purged BEFORE the task store is truncated"

    # And it must NOT be reachable outside that guard — a stray unguarded call
    # would make a routing wipe destroy in-flight work.
    unguarded = [
        c for c in ast.walk(fn)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        and c.func.id == "_reset_restate_journal"
    ]
    assert len(unguarded) == 1, "exactly one call site, inside the nuclear guard"
