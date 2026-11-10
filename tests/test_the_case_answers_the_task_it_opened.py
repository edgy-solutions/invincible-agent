"""The case answers the task it opened (Chris, 2026-11-07, saf).

`task_id` is taken from the runner that mints the task. The id is minted inside the case's
INSTANCE, where it registers the human task; the instance tells the case (`task_opened`) and the
door asks the case (`opened_task`). Nothing derives `{case}~n:step`, so the ids below are the ones
the double's `_register_human_task` was handed, captured, never restated.

Arms
  a  a case that reaches a human_await resolves OPENED_TASK on the CASE's ctx with the id the
     instance registered;
  b  a case that ends at once (a terminal at selection) resolves `{"task_id": None}`, so a
     waiter never hangs;
  c  two awaits in sequence keep the FIRST id;
  d  `opened_task` answers the resolved value;
  e  control: with the instance's `workflow_call` to `task_opened` removed, arm a fails.
  f  an instance that loses the peek-then-resolve race answers the winner instead of failing.

Run: uv run --frozen pytest tests/test_the_case_answers_the_task_it_opened.py -v
"""
from __future__ import annotations

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: F401
    _Cluster, _answer, _body, _facts, _refused, main, policy, restate, wr,
)


@pytest.fixture
def minted(monkeypatch):
    """Capture the id of every task the instances register."""
    ids: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack", case_id=None: ids.append(task["id"]) or {})
    monkeypatch.setattr(main, "_expire_human_task", lambda wf, task: None)
    return ids


def _opened(cluster, case):
    return [p for n, p in cluster.ctx(case).resolved if n == wr.OPENED_TASK]


@pytest.mark.asyncio
async def test_a_case_that_reaches_a_human_await_resolves_the_id_the_instance_registered(policy, minted):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await c.start("E-1", "fault", _facts())
    assert minted, "the instance registered no task"
    assert _opened(c, "E-1") == [{"task_id": minted[0]}]


@pytest.mark.asyncio
async def test_a_case_that_ends_at_once_resolves_no_task(policy, minted):
    c = _Cluster()
    await _refused(c.start("E-1", "closes_at_once", _facts()), 422)
    assert minted == []
    assert _opened(c, "E-1") == [{"task_id": None}]


@pytest.mark.asyncio
async def test_two_awaits_in_sequence_keep_the_first_id(policy, minted):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok", "m@x"),
                  ("E-1~2", "approval_decide"): _answer("ok", "s@x")})
    await c.start("E-1", "two_step", _facts())
    assert len(minted) == 2 and minted[0] != minted[1], minted
    assert _opened(c, "E-1") == [{"task_id": minted[0]}]


@pytest.mark.asyncio
async def test_opened_task_answers_the_resolved_value(policy, minted):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await c.start("E-1", "fault", _facts())
    out = await _body(wr.opened_task)(c.ctx("E-1"), {})
    assert out == {"task_id": minted[0]}


@pytest.mark.asyncio
async def test_control_without_the_instances_call_the_case_learns_no_id(policy, minted, monkeypatch):
    """The control for arm a: drop the instance's `task_opened` call and arm a's assertion is
    false (the case then closes with `None`, not the registered id)."""
    async def _no_call(self, handler, key, arg):
        if getattr(handler, "__name__", "") == "task_opened":
            return None
        return await _body(handler)(self.cluster.ctx(key), arg)
    from tests.test_a_case_runs_from_trigger_to_terminal import _Ctx
    monkeypatch.setattr(_Ctx, "workflow_call", _no_call)
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await c.start("E-1", "fault", _facts())
    assert minted and _opened(c, "E-1") != [{"task_id": minted[0]}]
    assert _opened(c, "E-1") == [{"task_id": None}]


class _RacedPromise:
    """A promise another instance resolved between this caller's peek and its resolve: the first
    peek reads empty, the resolve is refused as Restate refuses a second completion."""
    def __init__(self, winner):
        self.winner, self.peeks, self.resolved = winner, 0, []

    async def peek(self):
        self.peeks += 1
        return None if self.peeks == 1 else self.winner

    async def resolve(self, value):
        self.resolved.append(value)
        raise restate.TerminalError("promise already completed", status_code=409)


class _RacedCtx:
    def __init__(self, promise):
        self._p = promise

    def promise(self, name, type_hint=None):
        assert name == wr.OPENED_TASK
        return self._p


@pytest.mark.asyncio
async def test_an_instance_that_loses_the_race_answers_the_winner_and_does_not_fail():
    """Arm f: peek-then-resolve is not atomic. The loser's refused resolve must not fail the
    instance (its `workflow_call` would raise); it answers the id the winner holds."""
    p = _RacedPromise({"task_id": "the-winners-id"})
    out = await _body(wr.task_opened)(_RacedCtx(p), {"task_id": "the-losers-id"})
    assert p.resolved == [{"task_id": "the-losers-id"}], "the race was not exercised"
    assert out == {"task_id": "the-winners-id"}
