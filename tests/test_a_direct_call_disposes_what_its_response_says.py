"""A DIRECT CALL DISPOSES WHAT ITS RESPONSE SAYS -- WHEN, AND ONLY WHEN, IT DECLARES WHERE.

Ruled 2026-10-03. A `direct_call` record carried no `disposition`, so a definition whose deciding
act is a call (the origin case's writer: `written` or `write_refused`) terminated with
`outcome: None`, and its chaining table had nothing to match. The ruling is opt-in:
`outcome_from: <response field>` on the step. Declared, the step's disposition is that field's
value, and a response without it is a TerminalError that names it -- never a None the table would
read as "decided nothing". Undeclared, a direct call disposes nothing, exactly as before.

Driven through the case runner's own cluster double, so the arms read the transition a chaining
table actually took, not a record field.

Run: uv run --frozen pytest tests/test_a_direct_call_disposes_what_its_response_says.py -v
"""
from __future__ import annotations

import pytest

# One cluster double, the case runner's own -- not a second one free to drift from it.
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: F401 -- sets the path
    _answer, _Cluster, _dump, main, restate, wd)

import spo_step_executor as ex  # noqa: E402 -- the SAME module object main imports the call from

_TRIGGERS = {"writes": {"trigger": "writes", "selection": "sel_w", "key": "event_id"}}

_TABLES = {
    "sel_w": {"decision": "sel_w", "matches": ["level"], "domain": {"level": ["hi"]},
              "rows": [{"then": "write"}]},
    "write_chain": {"decision": "write_chain", "after": "write", "matches": ["outcome"],
                    "domain": {"outcome": ["written", "write_refused", "ok"]},
                    "terminals": ["resolved", "refused", "reviewed"],
                    "rows": [{"when": {"outcome": "written"}, "then": "resolved"},
                             {"when": {"outcome": "write_refused"}, "then": "refused"},
                             {"when": {"outcome": "ok"}, "then": "reviewed"}]},
}

_CALL = {"kind": "direct_call", "id": "w", "endpoint": "http://writer.test/write",
         "capability": "origin:write"}
_AWAIT = {"kind": "human_await", "id": "decide", "audience": "maint:ORG", "task_kind": "review_kind"}


def _policy(tmp_path, monkeypatch, steps):
    monkeypatch.setenv("CASE_TRIGGER_DIR", str(_dump(tmp_path / "triggers", _TRIGGERS)))
    monkeypatch.setenv("DECISION_TABLE_DIR", str(_dump(tmp_path / "decisions", _TABLES)))
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", str(_dump(
        tmp_path / "workflows", {"write": {"id": "write", "name": "write", "steps": steps}})))
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {})
    monkeypatch.setattr(main, "_register_human_task", lambda wf, task, kind="workflow_ack": {})


@pytest.fixture
def respond(monkeypatch):
    """The writer's response, and the calls that reached it."""
    said = {"body": None, "calls": []}

    def call(step, ident, **kw):
        said["calls"].append(step["id"])
        return said["body"]
    monkeypatch.setattr(ex, "execute_direct_call", call)
    return said


async def _run(answers=None):
    c = _Cluster(answers or {})
    out = await c.start("E-1", "writes", {"event_id": "E-1", "level": "hi"})
    return out, c


async def _closed(answers=None):
    """A case that did not CLOSE is the arm's red, named -- not an exception the arm never states."""
    try:
        return await _run(answers)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"the case ended in {type(exc).__name__}: {exc}") from exc


def _last_hop(c):
    t = c.case("E-1")["transitions"][-1]
    return (t["from"], t["outcome"], t["to"], t["by"])


@pytest.mark.parametrize("status,terminal", [("written", "resolved"), ("write_refused", "refused")])
@pytest.mark.asyncio
async def test_A_DECLARED_FIELD_IS_THE_STEPS_DISPOSITION(tmp_path, monkeypatch, respond,
                                                         status, terminal):
    _policy(tmp_path, monkeypatch, [{**_CALL, "outcome_from": "status"}])
    respond["body"] = {"status": status, "reason": "because"}
    out, c = await _closed()
    assert respond["calls"] == ["w"]
    assert (out["status"], out["terminal"]) == ("CLOSED", terminal), out
    # A call decides nothing on a person's behalf: the hop is the system's.
    assert _last_hop(c) == ("write", status, terminal, "system"), c.case("E-1")["transitions"]


@pytest.mark.parametrize("body", [{"reason": "no status"}, {"status": None}, {"status": ""},
                                  {"status": 3}, ["written"], None],
                         ids=["absent", "none", "empty", "not-a-string", "a-list", "no-body"])
@pytest.mark.asyncio
async def test_A_RESPONSE_WITHOUT_THE_DECLARED_FIELD_IS_TERMINAL_AND_NAMES_IT(
        tmp_path, monkeypatch, respond, body):
    _policy(tmp_path, monkeypatch, [{**_CALL, "outcome_from": "status"}])
    respond["body"] = body
    with pytest.raises(Exception) as exc:
        await _run()
    err = exc.value
    assert isinstance(err, restate.TerminalError), repr(err)
    assert err.status_code == 502, (err.status_code, str(err))
    assert "'w'" in str(err) and "outcome_from 'status'" in str(err), str(err)


@pytest.mark.asyncio
async def test_AN_UNDECLARED_CALL_DISPOSES_NOTHING(tmp_path, monkeypatch, respond):
    """The call comes LAST and its response carries a `status` a table would match, so a call
    that disposed without declaring would take the outcome from the human before it."""
    _policy(tmp_path, monkeypatch, [_AWAIT, _CALL])
    respond["body"] = {"status": "written"}
    out, c = await _closed({("E-1~1", "approval_decide"): _answer("ok", "m@x", "fine")})
    assert respond["calls"] == ["w"]
    assert out["terminal"] == "reviewed", out
    assert _last_hop(c) == ("write", "ok", "reviewed", "m@x")


def test_THE_FIELD_IS_DECLARED_ON_THE_STEP_AND_NAMES_SOMETHING():
    step = wd.DirectCallStep.model_validate({**_CALL, "outcome_from": "status"})
    assert step.outcome_from == "status"
    assert wd.DirectCallStep.model_validate(_CALL).outcome_from is None
    with pytest.raises(Exception):
        wd.DirectCallStep.model_validate({**_CALL, "outcome_from": ""})
