"""PRIME-AWAITS-INGEST SEAL — "Prime complete" must mean the ingest finished.

WHAT WENT WRONG (2026-08-21). prime_databases.py uploaded twelve TTLs, launched
twelve async Dagster ingest runs, printed "=== Prime complete ===", and exited.
The helm hook chain then advanced on that word: ontologySeed(15) and
reregister(20) both ran while the ingest was still QUEUED. engine-f restarted,
re-registered its presentation triples against archetype classes that did not
exist yet, and Contract D refused them SILENTLY.

Every job in the chain reported success. The substrate ended with 0 rendersAs
rows. Only counting the rows told the truth.

WHY THE EXISTING GUARD COULD NOT CATCH IT. The reregister job waits on a
sentinel class before restarting engines -- but it tests EXISTENCE, and the
sandbox primes with wipe=false, so the sentinel class was still present from the
PREVIOUS prime. It was satisfied on the first poll: the job logged
`[ready] sentinel present` and finished in 47s while the mesh ingest was queued.
Existence cannot prove freshness. Only the run status can, which is why the wait
lives here -- at the launcher, which knows which runs are ITS OWN -- rather than
downstream where leftover state is indistinguishable from fresh state.

WHAT THIS SEALS:
  * the QUIET arm -- all runs SUCCESS returns normally, so a working chain is
    not blocked (a seal that only ever raises would be indistinguishable from a
    broken prime);
  * the LOUD arm -- any FAILED run raises, because a downstream step registering
    against a half-ingested class graph produces confidently-wrong routing, and
    that is far more expensive to find than a failed upgrade;
  * the TIMEOUT arm -- runs still pending at the deadline also raise. Silence at
    the deadline is the fire-and-forget bug wearing a wait's name;
  * the POLLING arm -- a run that is QUEUED and only later SUCCEEDS must be
    waited THROUGH, not sampled once. Sampling once is what the sentinel did.

Run: uv run --frozen --with pytest pytest tests/test_prime_awaits_ingest.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "setup" / "prime_databases.py"

# Loaded under a unique name, never bare "prime_databases": this repo has had a
# suite go red purely from sys.modules cache collisions across same-named files.
_MOD_NAME = "prime_databases__await_ingest_test"


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
    def __init__(self, status):
        self._status = status

    def json(self):
        return {"data": {"runOrError": {"__typename": "Run", "status": self._status}}}


def _stub_requests(monkeypatch, mod, script):
    """Serve run statuses from `script`: {run_id: [status, status, ...]}.

    Each poll consumes one entry, so a run can be QUEUED then SUCCESS -- which is
    what distinguishes waiting-through from sampling-once.
    """
    seen = {"polls": 0}

    def _post(url, json=None, timeout=None):  # noqa: A002
        seen["polls"] += 1
        rid = json["query"].split('runId:"')[1].split('"')[0]
        seq = script[rid]
        return _Resp(seq.pop(0) if len(seq) > 1 else seq[0])

    monkeypatch.setattr(mod.requests, "post", _post)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    return seen


def test_all_success_returns_quietly(monkeypatch):
    """THE POSITIVE CONTROL. A seal that always raises blocks every upgrade."""
    m = _mod()
    _stub_requests(monkeypatch, m, {"r1": ["SUCCESS"], "r2": ["SUCCESS"]})
    m._await_ingest_runs([("mesh", "r1"), ("idp", "r2")], "http://dagster/graphql", 60)


def test_a_failed_run_raises(monkeypatch):
    """THE LOUD ARM — the whole reason this function exists."""
    m = _mod()
    _stub_requests(monkeypatch, m, {"r1": ["SUCCESS"], "r2": ["FAILURE"]})
    with pytest.raises(SystemExit) as exc:
        m._await_ingest_runs([("mesh", "r1"), ("idp", "r2")], "http://dagster/graphql", 60)
    assert "did not complete cleanly" in str(exc.value)


def test_a_run_still_queued_at_the_deadline_raises(monkeypatch):
    """Silence at the deadline is the fire-and-forget bug wearing a wait's name."""
    m = _mod()
    _stub_requests(monkeypatch, m, {"r1": ["QUEUED"]})
    with pytest.raises(SystemExit):
        m._await_ingest_runs([("mesh", "r1")], "http://dagster/graphql", 0)


def test_it_waits_THROUGH_a_queued_run(monkeypatch):
    """THE DISCRIMINATING ARM. The sentinel sampled once and called it ready.

    A run that is QUEUED on the first poll and SUCCESS later must be waited
    through — polling more than once is exactly the behaviour that was missing.
    """
    m = _mod()
    seen = _stub_requests(monkeypatch, m, {"r1": ["QUEUED", "QUEUED", "SUCCESS"]})
    m._await_ingest_runs([("mesh", "r1")], "http://dagster/graphql", 60)
    assert seen["polls"] >= 3, f"sampled {seen['polls']}x — did not wait through QUEUED"


def test_runs_without_an_id_are_not_silently_dropped(monkeypatch):
    """A launch that returned no runId is unlaunched work, not finished work."""
    m = _mod()
    _stub_requests(monkeypatch, m, {"r1": ["SUCCESS"]})
    m._await_ingest_runs([("mesh", "r1"), ("ghost", "")], "http://dagster/graphql", 60)
