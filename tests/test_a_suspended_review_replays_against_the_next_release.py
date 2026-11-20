"""A review suspended under the live release replays against the next release's code.

Restate replays a suspended workflow's journal against the CURRENT code: every journaled command
before the suspension must match in order, key AND value, or the invocation fails with
VMException 570 and retries forever. A new `ctx.set(...)` inserted before the promise await breaks
every review already suspended (a0e0f115's `ingest_id` did, live; 709da14e's `artifact_uri` would).

The workflow input is journaled, so its key set is deterministic on replay: a review started by the
live release has no `artifact_uri` key; one started by master's starter always has it. The write is
therefore made only when the key is in the input.

Arms:
  1  the live release's input: the `set` subsequence equals LIVE_PRE_AWAIT, and no `artifact_uri` write
  2  master's starter input (also an empty value): `artifact_uri` is written with its value, others in order
  3  the reader serves "" for state that lacks the key

Run: uv run pytest tests/test_a_suspended_review_replays_against_the_next_release.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent_fleet" / "restate_analyst"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("restate")
pytest.importorskip("fastapi")

import dispatch_driver  # noqa: E402
import grouped_review_workflow as grw  # noqa: E402
import main as ra_main  # noqa: E402
from tests.test_steward_correction import _Ctx, _request, _step  # noqa: E402

# A RECORDED JOURNAL SHAPE, not a derivation: the `set` keys the LIVE release journals before the
# promise await in `_run_grouped_human_await`, copied from
# `git show 36393237:agent_fleet/restate_analyst/main.py` lines 2143-2154 (36393237 is the live
# release tag). The last entry is the audience key, `_audience_key(promise_name)`.
# It may only change by a gated append.
_PROMISE = "decision"
LIVE_PRE_AWAIT = [
    "batch_items", "approver", "notice_fingerprint", "ingest_id", "notice_id", "doc_type",
    "pipeline_version", "extraction_warnings", ra_main._audience_key(_PROMISE),
]


class _Suspended(Exception):
    """Raised at the promise await: the run stops exactly where a suspension would."""


class _Recorder:
    def __init__(self):
        self.ops = []

    def key(self):  # not journaled
        return "wf-replay"

    def set(self, k, v):
        self.ops.append(("set", k, v))

    async def get(self, k):
        self.ops.append(("get", k, None))

    async def run(self, name, fn):
        self.ops.append(("run", name, None))
        return None

    def promise(self, name, type_hint=None):
        self.ops.append(("promise", name, None))
        raise _Suspended()

    def clear(self, k):
        self.ops.append(("clear", k, None))


async def _record(monkeypatch, request):
    monkeypatch.setattr(dispatch_driver, "_mint_dispatch_task", lambda task: {"ok": True})
    ctx = _Recorder()
    with pytest.raises(_Suspended):
        await ra_main._run_grouped_human_await(ctx, "wf-1", _step(), _PROMISE, request, {}, "")
    return ctx.ops


def _set_keys(ops):
    return [k for op, k, _ in ops if op == "set"]


@pytest.mark.asyncio
async def test_arm1_the_live_releases_input_journals_exactly_what_it_journaled(monkeypatch):
    request = _request()
    assert "artifact_uri" not in request, "arm 1's input must be the live release's shape"
    ops = await _record(monkeypatch, request)
    assert ("set", "artifact_uri") not in [(o, k) for o, k, _ in ops]
    assert _set_keys(ops) == LIVE_PRE_AWAIT


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["s3://bucket/p/review.json", ""])
async def test_arm2_a_starter_input_with_the_key_writes_it_in_order(monkeypatch, uri):
    ops = await _record(monkeypatch, _request(artifact_uri=uri))
    assert ("set", "artifact_uri", uri) in ops
    assert [k for k in _set_keys(ops) if k != "artifact_uri"] == LIVE_PRE_AWAIT
    keys = _set_keys(ops)
    assert keys.index("artifact_uri") == keys.index("extraction_warnings") + 1


@pytest.mark.asyncio
async def test_arm3_the_reader_serves_blank_for_state_without_the_key():
    state = {"batch_items": [], "approver": "a@example.com", "notice_fingerprint": "N1",
             "notice_id": "N1", "doc_type": "PCN"}
    assert "artifact_uri" not in state
    out = await grw.get_batch.__wrapped__(_Ctx(None, state=state))
    assert out["artifact_uri"] == ""
