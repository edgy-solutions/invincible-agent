"""The `orchestrate_access` line says an ask FAILED when it failed: `outcome=failed:<cause>`.

perf's step 7 run (2026-11-28): asks that ended in `route_intent_failed` were audited as
`outcome=completed`. The stream reports a failure as a `pipeline_error` event and then ends
normally, so the wrapper saw a clean end. The architect: "It records what happened."

The rule, sealed here: the FIRST `pipeline_error`'s `cause` (or `unrecorded` when it names none)
makes the outcome `failed:<cause>`. A failure once sent stands when the client then goes away (it
may close on the error); only a raise (`error`) outranks it. A stream with no `pipeline_error`
event stays `completed`, whatever its data text says.

Drives the REAL wrapper and the REAL logger, with frames built by the REAL `_perror`. The same
case through the real stream, against a /route_intent that fails, is in
tests/perf/test_the_routing_limits_are_ordered.py.

Run: uv run pytest tests/routing/test_the_audit_line_says_an_ask_failed.py -q
"""
from __future__ import annotations

import pytest

from tests.routing.test_orchestrate_writes_one_audit_line import (  # noqa: F401
    FULL, VERB, _gen, _lines, _sse, _wrap, arrive, gw)

END = _sse("stream_end", {})


def _fail(cause=None, message="Failed to determine execution intent."):
    return gw._perror(message, kind="understanding", retryable=True, cause=cause)


def _outcome(line):
    (part,) = [p for p in line.split(" ") if p.startswith("outcome=")]
    return part[len("outcome="):]


@pytest.mark.asyncio
async def test_a_stream_that_reports_a_failure_is_audited_failed_with_its_cause(arrive):
    chunks = [*FULL[:3], _fail("route_intent_failed"), END]
    out = [c async for c in _wrap(_gen(chunks))]
    assert out == chunks                                   # the stream passes through untouched
    (line,) = _lines(arrive)
    assert _outcome(line) == "failed:route_intent_failed", line
    assert f"verb={VERB}" in line, line                    # what else it saw is still recorded


@pytest.mark.asyncio
async def test_a_failure_that_names_no_cause_is_failed_unrecorded(arrive):
    [c async for c in _wrap(_gen([_fail(None), END]))]
    (line,) = _lines(arrive)
    assert _outcome(line) == "failed:unrecorded", line


@pytest.mark.asyncio
async def test_the_first_failure_names_the_outcome(arrive):
    [c async for c in _wrap(_gen([_fail("route_intent_failed"), _fail("dagster_run_failed"), END]))]
    (line,) = _lines(arrive)
    assert _outcome(line) == "failed:route_intent_failed", line


@pytest.mark.asyncio
async def test_a_failure_then_a_client_close_stays_failed(arrive):
    g = _wrap(_gen([_fail("route_intent_failed"), END, *FULL]))
    assert "pipeline_error" in await g.__anext__()
    await g.aclose()                                       # the client goes away on the error
    (line,) = _lines(arrive)
    assert _outcome(line) == "failed:route_intent_failed", line


@pytest.mark.asyncio
async def test_a_raise_after_a_failure_is_error(arrive):
    with pytest.raises(RuntimeError, match="boom"):
        async for _ in _wrap(_gen([_fail("route_intent_failed")], then=RuntimeError("boom"))):
            pass
    (line,) = _lines(arrive)
    assert _outcome(line) == "error", line


@pytest.mark.asyncio
async def test_control_a_stream_with_no_failure_event_is_completed(arrive):
    # the same frames but the failure, and a status whose TEXT says pipeline_error: completed
    chunks = [*FULL[:3], _sse("status", {"stage": "routing", "note": "pipeline_error"}), END]
    [c async for c in _wrap(_gen(chunks))]
    (line,) = _lines(arrive)
    assert _outcome(line) == "completed", line


@pytest.mark.asyncio
async def test_control_a_close_with_no_failure_is_closed(arrive):
    g = _wrap(_gen(FULL))
    await g.__anext__()
    await g.aclose()
    (line,) = _lines(arrive)
    assert _outcome(line) == "closed", line
