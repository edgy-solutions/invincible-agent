"""An await nobody answered terminates `timed_out` — never with an earlier human's verb.

`_run_definition` records a deadline expiry as `{"status": "TIMED_OUT", "approval": None,
"terminal": "timed_out"}` and ends the definition there. Its `outcome` was then derived only from
steps whose `approval` carries a status, so the expiry contributed nothing:

  * one await, expired          -> `outcome` None. A chaining row on `timed_out` (the ADR-0039
    escalation shape: a deadline that terminates `timed_out`, plus a row) can never fire, and
    None is also what "this definition disposes nothing" yields.
  * two awaits, first answered, second expired -> `outcome` is the FIRST human's verb. A
    concurrence followed by an unanswered acceptance terminates `concurred`/`approved`: an
    unanswered approval auto-approves.

Driven through the real executor with a fake context: `restate.select` is replaced by a script
naming which arm wins each race. No shipped definition carries `deadline_seconds` today, so this
is latent on master and live for the first one that does.

Run: uv run --frozen pytest tests/test_an_unanswered_await_never_reads_as_approved.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("restate")
import restate  # noqa: E402
import main  # noqa: E402  — the real executor, imported as its siblings import it

_EXPIRED = object()


def _await(step_id, *, deadline=None):
    step = {
        "kind": "human_await", "id": step_id, "promise_name": step_id,
        "audience": "seal_kind:SUSTAINMENT", "subject_ref": "{subject}",
        "title": f"{step_id} {{subject}}", "summary": "seal fixture",
        "completion": {"mode": "single", "quorum": "any_of", "claiming": False},
    }
    if deadline:
        step["deadline_seconds"] = deadline
    return step


def _definition(*steps):
    return {
        "id": "seal_two_awaits", "name": "seal", "classification": None,
        "participants": [{"role": "initiator"}],
        "domain_stages": ["open", "closed"],
        "steps": list(steps),
        "observable_state": {"visible": ["domain_stages"], "internal": []},
    }


class _Promise:
    def __init__(self, answer):
        self._answer = answer

    def value(self):
        async def _v():
            return self._answer
        return _v()


class _Ctx:
    """Answers each promise from `answers` by name; `_EXPIRED` means the timer wins that race."""

    def __init__(self, answers):
        self.answers = answers
        self.state: dict = {}

    def key(self):
        return "seal-key"

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        return None  # the register leg is not the subject

    def promise(self, name, type_hint=None):
        return _Promise(self.answers.get(name))

    def sleep(self, delta):
        async def _s():
            return None
        return _s()


@pytest.fixture
def scripted_select(monkeypatch):
    """Replace the race. The winner is read off the promise's scripted answer: `_EXPIRED` makes the
    timer win, anything else is the human's payload."""
    async def _select(**arms):
        approved, expired = arms["approved"], arms["expired"]
        answer = await approved
        expired.close()
        if answer is _EXPIRED:
            return ("expired", None)
        return ("approved", answer)
    monkeypatch.setattr(restate, "select", _select)


async def _drive(answers, *steps):
    return await main._run_definition(
        _Ctx(answers), "wf-seal", _definition(*steps), {"subject": "S-1", "authz_id": "a@x"})


# ── THE SUBJECT ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_LONE_EXPIRED_AWAIT_TERMINATES_TIMED_OUT(scripted_select):
    """The escalation shape: a deadline that terminates `timed_out`, chained by a row on it."""
    out = await _drive({"ack": _EXPIRED}, _await("ack", deadline=60))
    assert out["outcome"] == "timed_out", (
        f"an expired await terminated with outcome {out['outcome']!r} — a chaining row on "
        f"`timed_out` can never fire, and the run is indistinguishable from one that disposes "
        f"nothing")
    assert out["outcome_step_id"] == "ack"


@pytest.mark.asyncio
async def test_AN_EARLIER_APPROVAL_IS_NOT_THE_OUTCOME_OF_A_LATER_EXPIRY(scripted_select):
    """THE AUTO-APPROVE. First human concurs, second never answers."""
    out = await _drive(
        {"concur": {"status": "concurred", "acted_by": "s@x"}, "accept": _EXPIRED},
        _await("concur"), _await("accept", deadline=60))
    assert out["outcome"] != "concurred", (
        "an unanswered acceptance terminated with the earlier concurrence's verb — the "
        "chaining table would release on an approval nobody gave")
    assert out["outcome"] == "timed_out", f"outcome {out['outcome']!r}, expected 'timed_out'"
    assert out["outcome_step_id"] == "accept", (
        f"outcome attributed to {out['outcome_step_id']!r}, not the step that expired")


# ── WHAT THE FIX MUST NOT MOVE ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_timeout_still_manufactures_no_decision(scripted_select):
    """ADR-0034 archives decision records: the expired step carries no approval and no verb."""
    out = await _drive({"ack": _EXPIRED}, _await("ack", deadline=60))
    rec = out["step_results"][-1]
    assert rec["approval"] is None, f"the expired step carries an approval: {rec['approval']!r}"
    assert rec["status"] == "TIMED_OUT"


@pytest.mark.asyncio
async def test_nothing_runs_past_an_expiry(scripted_select):
    out = await _drive(
        {"first": _EXPIRED, "second": {"status": "approved"}},
        _await("first", deadline=60), _await("second"))
    assert [r["step_id"] for r in out["step_results"]] == ["first"], (
        "a step after an expired await ran as though the human had acted")


@pytest.mark.asyncio
async def test_CONTROL_an_answer_inside_the_deadline_is_the_outcome(scripted_select):
    """Shares the deadline gate with the subject and differs only in who wins the race."""
    out = await _drive({"ack": {"status": "approved"}}, _await("ack", deadline=60))
    assert out["outcome"] == "approved"
    assert out["outcome_step_id"] == "ack"


@pytest.mark.asyncio
async def test_CONTROL_two_answered_awaits_take_the_last_verb(scripted_select):
    out = await _drive(
        {"concur": {"status": "concurred"}, "accept": {"status": "rejected"}},
        _await("concur"), _await("accept", deadline=60))
    assert out["outcome"] == "rejected"
    assert out["outcome_step_id"] == "accept"


@pytest.mark.asyncio
async def test_CONTROL_an_await_with_no_deadline_never_races(scripted_select, monkeypatch):
    """No `deadline_seconds` means wait forever: the race is never entered, so the fix must not
    reach this path at all."""
    async def _refuse(**_):
        raise AssertionError("an await with no deadline entered the race")
    monkeypatch.setattr(restate, "select", _refuse)
    out = await _drive({"ack": {"status": "approved"}}, _await("ack"))
    assert out["outcome"] == "approved"


# ── A DEADLINE THE RUNNER CANNOT HONOUR IS REFUSED, NOT IGNORED ─────────────────────────────

@pytest.mark.asyncio
async def test_A_GROUPED_AWAIT_WITH_A_DEADLINE_IS_REFUSED(scripted_select, monkeypatch):
    """The grouped path has no race. Ignoring the field would wait forever with no error."""
    entered: list = []

    async def _grouped(*a, **k):
        entered.append(a)
        return {"step_id": "batch", "kind": "human_await", "status": "approved",
                "approval": {"status": "approved"}}
    monkeypatch.setattr(main, "_run_grouped_human_await", _grouped)
    step = _await("batch", deadline=60)
    step["completion"]["mode"] = "grouped"
    try:
        await _drive({}, step)
    except restate.TerminalError as exc:
        assert "deadline_seconds" in str(exc), f"refused for another reason: {exc}"
        assert not entered, "refused only after the grouped await had already run"
        return
    raise AssertionError("a grouped await declaring a deadline ran — the deadline is ignored")


@pytest.mark.asyncio
async def test_CONTROL_a_grouped_await_without_a_deadline_runs(scripted_select, monkeypatch):
    async def _grouped(*a, **k):
        return {"step_id": "batch", "kind": "human_await", "status": "approved",
                "approval": {"status": "approved"}}
    monkeypatch.setattr(main, "_run_grouped_human_await", _grouped)
    step = _await("batch")
    step["completion"]["mode"] = "grouped"
    out = await _drive({}, step)
    assert out["outcome"] == "approved"
