"""AT-LEAST-ONCE INTAKE — a REAPED run is re-armed; a REFUSED one is not.

THE DEFECT. `run_key` was consumed at DISPATCH, not at COMPLETION. Dagster dedups on submission, so
once a RunRequest was submitted the sensor could never produce another run for that artifact however
the run ENDED — and the cursor had already advanced past the object, so neither mechanism would ever
re-see it. A run killed by run monitoring dropped its notice PERMANENTLY and SILENTLY. That is
at-most-once intake on a pipeline whose contract is durable delivery, and it wears the wedge's
signature: nothing red, the artifact simply absent.

Observed live 2026-08-07 — unwedging the cursor released a 9-artifact backlog, the sandbox saturated,
and 6 of 9 runs were reaped.

THE DISCRIMINANT, and the reason this file can be trusted: it was validated against BOTH categories
in real run history before any of it was written.

    reaped           -> FAILURE with ZERO STEP_FAILURE events      (6/6 of the reaped runs)
    designed failure -> FAILURE WITH a STEP_FAILURE event          (3/3 systemic refusals)

`raise Failure(...)` in the op always emits STEP_FAILURE; a monitoring kill emits only
PIPELINE_FAILURE. Both shapes are reproduced below, because a probe that has only ever seen one
category has not been shown to discriminate — it has been shown to agree.

Run:  uv run --frozen python -m pytest tests/test_dispatch_rearm.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dagster import DagsterEventType

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
_spec = importlib.util.spec_from_file_location("ers_rearm", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]

_KEY = "sustainment/inbound/acme/generated/ACME_PCN_1_pdf/review.json"
_URL = f"s3://processing-artifacts/{_KEY}"
_BASE = 'abc123-' + _KEY


# ===========================================================================
# Fakes shaped like the REAL objects, including the event log
# ===========================================================================
class _Status:
    def __init__(self, value):
        self.value = value


class _Event:
    """Mirrors `EventLogEntry.dagster_event.event_type`, which is where the discriminant lives —
    `run.status` says FAILURE for both categories and cannot tell them apart."""

    def __init__(self, event_type):
        self.dagster_event = type("DE", (), {"event_type": event_type})()


class _Run:
    def __init__(self, run_id, status, tags, events=(), url=_URL):
        self.run_id = run_id
        self.status = _Status(status)
        self.tags = tags
        self.events = list(events)
        self.run_config = {"ops": {"start_review_op": {"config": {"review_json_url": url}}}}


class _Instance:
    def __init__(self, runs):
        self._runs = runs

    def get_runs(self, filters=None, limit=None):
        return self._runs[: limit or len(self._runs)]

    def all_logs(self, run_id):
        return next((r.events for r in self._runs if r.run_id == run_id), [])


def _reaped(run_id="r1", attempt=1, key=_KEY):
    """A monitoring kill: PIPELINE_FAILURE, and crucially NO step failure."""
    return _Run(run_id, "FAILURE",
                {ers.TAG_ARTIFACT: key, ers.TAG_ATTEMPT: str(attempt),
                 "review/run_key_base": _BASE},
                [_Event(DagsterEventType.PIPELINE_FAILURE)])


def _refused(run_id="r2", attempt=1, key=_KEY):
    """A DESIGNED failure: `raise Failure(...)` -> STEP_FAILURE, then PIPELINE_FAILURE."""
    return _Run(run_id, "FAILURE",
                {ers.TAG_ARTIFACT: key, ers.TAG_ATTEMPT: str(attempt),
                 "review/run_key_base": _BASE},
                [_Event(DagsterEventType.STEP_FAILURE),
                 _Event(DagsterEventType.PIPELINE_FAILURE)])


class _Ctx:
    def __init__(self, runs):
        self.instance = _Instance(runs)
        self.logged = []
        outer = self

        class _Log:
            def warning(self, m): outer.logged.append(("warning", m))
            def error(self, m): outer.logged.append(("error", m))
            def info(self, m): outer.logged.append(("info", m))
        self.log = _Log()


# ===========================================================================
# THE DISCRIMINANT — both categories, or it proves nothing
# ===========================================================================
def test_a_reaped_run_is_recognised_as_reaped():
    inst = _Instance([_reaped()])
    assert ers._is_reaped(inst, inst._runs[0]) is True


def test_a_DESIGNED_failure_is_NOT_a_reap():
    """The positive control in the other direction. Without this the check could return True for
    everything and every test above would still pass — agreement, not discrimination."""
    inst = _Instance([_refused()])
    assert ers._is_reaped(inst, inst._runs[0]) is False


# ===========================================================================
# THE BEHAVIOUR
# ===========================================================================
def test_a_reaped_artifact_is_RE_ARMED():
    """THE CLAIM. The execution was lost, the pipeline never reached a verdict, and the notice was
    never reviewed — so it is owed another dispatch."""
    reqs = ers._rearm_requests(_Ctx([_reaped()]))
    assert len(reqs) == 1
    assert reqs[0].run_key == f"{_BASE}#a2", "a used run_key can never produce a second run"
    assert reqs[0].tags[ers.TAG_ATTEMPT] == "2"
    cfg = reqs[0].run_config["ops"]["start_review_op"]["config"]
    assert cfg["review_json_url"] == _URL, "the retry must target the SAME artifact"


def test_a_REFUSED_artifact_is_NOT_re_armed():
    """A systemic refusal is a loud red run for ops, intended, once. Retrying it re-refuses until a
    human fixes the grant or the ruleset — `REVIEW_REQUEST_KEY_EPOCH` is the lever for that, and
    turning ops' one red run into an endless stream would bury the signal it exists to raise."""
    assert ers._rearm_requests(_Ctx([_refused()])) == []


def test_a_SUCCEEDED_artifact_is_NOT_re_armed():
    ok = _Run("r3", "SUCCESS", {ers.TAG_ARTIFACT: _KEY, ers.TAG_ATTEMPT: "1"})
    assert ers._rearm_requests(_Ctx([_reaped("r1"), ok])) == []


@pytest.mark.parametrize("status", ["QUEUED", "STARTING", "STARTED", "NOT_STARTED"])
def test_an_IN_FLIGHT_attempt_suppresses_re_arm(status):
    """Without this a live attempt is re-armed alongside itself EVERY TICK — a delivery guarantee
    turned into the outage it was meant to prevent.

    THE ATTEMPT NUMBERS ARE DELIBERATE. The first version of this test gave the live run the HIGHER
    attempt, so `latest` was the live run and the separate `latest.status != FAILURE` check absorbed
    the mutation — deleting the in-flight guard left the suite green. The guard was decoration and
    the test agreed with it. Here the live run is the LOWER attempt, so `latest` is the reaped one
    and this guard is the only thing standing between a running job and a duplicate of itself.
    """
    live = _Run("r4", status, {ers.TAG_ARTIFACT: _KEY, ers.TAG_ATTEMPT: "1"})
    assert ers._rearm_requests(_Ctx([_reaped("r1", attempt=2), live])) == []


def test_a_CANCELED_attempt_is_NOT_re_armed():
    """Cancellation is a human decision. Re-arming over it is worse than the gap this closes: the
    operator would have no way to make the pipeline stop trying."""
    stopped = _Run("r5", "CANCELED", {ers.TAG_ARTIFACT: _KEY, ers.TAG_ATTEMPT: "1"},
                   [_Event(DagsterEventType.PIPELINE_CANCELED)])
    assert ers._rearm_requests(_Ctx([stopped])) == []


def test_attempts_are_BOUNDED_and_exhaustion_is_LOUD():
    """Giving up silently would rebuild the exact hole this closes, one layer further in."""
    runs = [_reaped(f"r{i}", attempt=i) for i in range(1, ers._MAX_DISPATCH_ATTEMPTS + 1)]
    ctx = _Ctx(runs)
    assert ers._rearm_requests(ctx) == []
    errs = [m for lvl, m in ctx.logged if lvl == "error"]
    assert any("DISPATCH EXHAUSTED" in m for m in errs), "exhaustion must be an EVENT, not a default"
    assert any("has NOT been reviewed" in m for m in errs), (
        "the message must say what is TRUE OF THE NOTICE, not just that a retry budget ran out")


def test_UNTAGGED_history_is_INVISIBLE_to_the_re_arm():
    """THE OPT-IN BOUNDARY, and the reason this needs no epoch and no deletions. Runs predating the
    feature carry no tag, so the six reaped runs that exposed the defect — prior sessions' unsettled
    witness fixtures and extraction experiments — can never be re-armed. Re-driving those would file
    experiments into humans' review queues."""
    legacy = _Run("old", "FAILURE", {}, [_Event(DagsterEventType.PIPELINE_FAILURE)])
    assert ers._rearm_requests(_Ctx([legacy])) == []


def test_two_artifacts_are_judged_INDEPENDENTLY():
    """Grouping is per-artifact; one settled notice must not mask another's lost dispatch."""
    other = "sustainment/inbound/beta/generated/B_pdf/review.json"
    runs = [_reaped("r1", key=_KEY),
            _Run("r2", "SUCCESS", {ers.TAG_ARTIFACT: other, ers.TAG_ATTEMPT: "1"})]
    reqs = ers._rearm_requests(_Ctx(runs))
    assert [r.tags[ers.TAG_ARTIFACT] for r in reqs] == [_KEY]


def test_a_context_with_NO_INSTANCE_does_not_wedge_new_dispatch():
    """`context.instance` RAISES when no instance ref was provided — it does not return None — so
    `getattr(context, "instance", None)` is not a guard, it is a false one.

    Found by two UNRELATED cursor tests going red, which is the wrong way to find it: the re-arm was
    one attribute access away from becoming a precondition for first delivery. Pinned here so the
    property is claimed where it belongs instead of being an accident of another file's coverage.
    """
    class _NoInstance:
        @property
        def instance(self):
            raise RuntimeError("no instance reference was provided")

        log = type("L", (), {"warning": staticmethod(lambda m: None),
                             "error": staticmethod(lambda m: None)})()

    assert ers._rearm_requests(_NoInstance()) == []


def test_a_broken_run_store_does_NOT_wedge_new_dispatch():
    """The re-arm is an ADDITION to intake and must never become a precondition for it — a retry
    mechanism that can block first delivery is worse than the gap it fills."""
    class _Boom(_Instance):
        def get_runs(self, filters=None, limit=None):
            raise RuntimeError("run store unavailable")

    ctx = _Ctx([])
    ctx.instance = _Boom([])
    assert ers._rearm_requests(ctx) == []
    assert any("re-arm scan unavailable" in m for _, m in ctx.logged)


# ===========================================================================
# WIRED — the sensor itself, not just the helper
# ===========================================================================
class _ListS3:
    def __init__(self, objects):
        self._objects = objects

    def get_paginator(self, _op):
        objects = self._objects

        class _P:
            @staticmethod
            def paginate(**_kw):
                return [{"Contents": objects}]
        return _P()

    def head_object(self, Bucket, Key):  # noqa: N803
        raise RuntimeError("NoSuchKey")

    def get_object(self, Bucket, Key):  # noqa: N803
        import json as _j
        body = _j.dumps({"doc_id": "ACME-1", "review_items": []}).encode()
        return {"Body": type("B", (), {"read": staticmethod(lambda: body)})()}


def _drive(monkeypatch, rearms, objects, cursor):
    """Run the real sensor. `rearms` is produced by the REAL `_rearm_requests` in the test below and
    then injected, so this exercises the WIRING while the re-arm's own logic stays sealed above."""
    from dagster import build_sensor_context  # noqa: PLC0415

    monkeypatch.setattr(ers, "_s3_client", lambda: _ListS3(objects))
    monkeypatch.setattr(ers, "_rearm_requests", lambda _ctx: rearms)
    return ers.extraction_review_sensor(build_sensor_context(cursor=cursor))


def test_the_SENSOR_re_arms_even_when_NO_new_artifact_landed(monkeypatch):
    """THE WIRING, and the case the obvious implementation gets wrong. A reaped run is work the
    pipeline OWES, owed whether or not a new artifact happened to arrive this tick. Gating retries
    behind new arrivals makes delivery depend on unrelated traffic — the same 'silent unless
    something else happens' shape as the cursor wedge.
    """
    rearms = ers._rearm_requests(_Ctx([_reaped()]))       # the REAL function's output
    assert rearms, "precondition: the re-arm produced nothing to wire"
    result = _drive(monkeypatch, rearms, objects=[],
                    cursor=f"{datetime(2026, 8, 8, tzinfo=timezone.utc).isoformat()}|zzz")
    keys = [r.run_key for r in getattr(result, "run_requests", []) or []]
    assert keys == [f"{_BASE}#a2"], (
        f"an empty listing skipped instead of re-arming (got {result!r}) — the notice stays lost")


def test_the_SENSOR_carries_re_arms_ALONGSIDE_new_dispatch(monkeypatch):
    """Both kinds of work in one tick. An implementation that returns early on either branch drops
    the other, and the drop is silent in both directions."""
    obj = {"Key": "sustainment/inbound/new/generated/N_pdf/review.json", "ETag": '"zzz"',
           "LastModified": datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)}
    rearms = ers._rearm_requests(_Ctx([_reaped()]))
    result = _drive(monkeypatch, rearms, objects=[obj], cursor=None)
    keys = {r.run_key for r in getattr(result, "run_requests", []) or []}
    assert f"{_BASE}#a2" in keys, "the re-arm was dropped when a new artifact arrived"
    assert ers._run_key_of(obj) in keys, "the new artifact was dropped when a re-arm was pending"


def test_the_SENSOR_tags_every_new_dispatch(monkeypatch):
    """The tags ARE the delivery ledger: `run_key` is consumed at dispatch and says nothing about how
    a run ended, so without them no later tick can tell that an artifact was never reviewed."""
    obj = {"Key": _KEY, "ETag": '"abc123"',
           "LastModified": datetime(2026, 8, 8, 3, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(ers, "_rearm_requests", lambda ctx: [])
    monkeypatch.setattr(ers, "_s3_client", lambda: _ListS3([obj]))
    from dagster import build_sensor_context  # noqa: PLC0415
    result = ers.extraction_review_sensor(build_sensor_context(cursor=None))
    reqs = getattr(result, "run_requests", []) or []
    assert reqs, "no dispatch at all"
    assert reqs[0].tags.get(ers.TAG_ARTIFACT) == _KEY
    assert reqs[0].tags.get(ers.TAG_ATTEMPT) == "1"
    assert reqs[0].run_key == ers._run_key_of(obj), (
        "attempt 1 must keep the ORIGINAL run_key — this feature must not re-dispatch history")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
