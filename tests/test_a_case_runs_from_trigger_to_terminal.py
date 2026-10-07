"""The case half of the generic runner: a trigger opens a case, a table chains it, a terminal ends it.

ADR-0039 allows a choice at exactly two moments -- SELECTION when the trigger fires and CHAINING
when a definition terminates -- and says "loops are new instances; every instance is a record".
`WorkflowRunner` is that and nothing domain-specific: every arm below drives it from a policy tree
written in a tmp dir, so what it runs is rows, never Python.

Each arm is a claim about what the case may NOT do:

* OPEN ON AN UNDECLARED TRIGGER, or on an event it could not finish (a missing `requires` fact, a
  key that is not the event's own, a key that could be one of its own instances);
* RUN A DEFINITION TWICE IN ONE INSTANCE -- a loop opens `{case}~{n+1}`, whose promise names are
  its own, so a second approval cannot read the first one's answer;
* LET A CHILD RUN WHAT ITS CASE DID NOT OPEN -- the child is on the ingress, so it takes only
  `(child_of, n)` and reads the rest from the case;
* END ANYWHERE BUT A DECLARED TERMINAL -- no chaining table, a terminal at selection, or a
  runaway cycle is a FAILED case, and a failed case still records and still frees its episode;
* RESOLVE A SIGNAL PAST THE GATE -- `signal` goes through the same `_authorize_resolution` as
  `approve`, after its own vocabulary check.

Run: uv run --frozen pytest tests/test_a_case_runs_from_trigger_to_terminal.py -v
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

yaml = pytest.importorskip("yaml")
pytest.importorskip("restate")
import restate  # noqa: E402
import main  # noqa: E402  — the real executor
import workflow_definition as wd  # noqa: E402  — the SAME module object main validates with
import workflow_runner as wr  # noqa: E402  — the SAME module object main registers
import case_routing as R  # noqa: E402
from iagent_mesh.provenance import AS_OF_UNKNOWN, DIRECT, make_provenance  # noqa: E402

#: Revision 1's provenance as the JSON event door builds it (gateway ``ingest_event``). The
#: double sends it on every run, as the door does; an arm that omits it passes ``provenance=None``.
DOOR_BLOCK = make_provenance(
    authoritative_source="unconfirmed-at-intake", obtained_via=DIRECT, as_of=AS_OF_UNKNOWN,
    ingested_at="2026-10-06T00:00:00Z", ingest_run="event:evt-test", standing="supervised",
    ingest_id="evt-test")


# ── the double: a cluster of keyed contexts ─────────────────────────────────────────────────

class _Promise:
    def __init__(self, ctx, name):
        self.ctx, self.name = ctx, name

    def value(self):
        async def _v():
            answer = self.ctx.cluster.answers.get((self.ctx._key, self.name))
            if answer is None:
                raise AssertionError(
                    f"{self.ctx._key} awaited {self.name!r}, which this arm did not script")
            return answer
        return _v()

    async def resolve(self, payload):
        self.ctx.resolved.append((self.name, payload))


class _Ctx:
    """One key's context. `workflow_call` / `object_call` run the real handler on the target
    key's own context, so state written by the case is what the child reads."""

    def __init__(self, cluster, key):
        self.cluster, self._key = cluster, key
        self.state: dict = {}
        self.runs: list = []
        self.resolved: list = []

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    def clear(self, k):
        self.state.pop(k, None)

    async def get(self, k, **_kw):
        return self.state.get(k)

    async def run(self, name, fn):
        assert name not in self.runs, f"{self._key} journalled {name!r} twice"
        self.runs.append(name)
        return fn()

    def promise(self, name, type_hint=None):
        return _Promise(self, name)

    def sleep(self, delta):
        async def _s():
            return None
        return _s()

    async def workflow_call(self, handler, key, arg):
        return await _body(handler)(self.cluster.ctx(key), arg)

    async def object_call(self, handler, key, arg):
        return await _body(handler)(self.cluster.obj(key), arg)

    def object_send(self, handler, key, arg):
        self.cluster.sends.append((handler, key, arg))


def _body(handler):
    return getattr(handler, "__wrapped__", handler)


class _Cluster:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.ctxs: dict = {}
        self.objs: dict = {}
        self.sends: list = []

    def ctx(self, key):
        return self.ctxs.setdefault(key, _Ctx(self, key))

    def obj(self, key):
        return self.objs.setdefault(key, _Ctx(self, key))

    async def start(self, key, trigger, facts, provenance=DOOR_BLOCK):
        req = {"trigger": trigger, "facts": facts}
        if provenance is not None:
            req["provenance"] = provenance
        try:
            return await _body(wr.run)(self.ctx(key), req)
        finally:
            while self.sends:
                h, k, a = self.sends.pop(0)
                await _body(h)(self.obj(k), a)

    def case(self, key):
        return self.ctx(key).state.get("case")


def _answer(verb, who="m@x", comments=""):
    return {"status": verb, "acted_by": who, "comments": comments, "task_id": "t"}


# ── the policy tree ─────────────────────────────────────────────────────────────────────────

_TRIGGERS = {
    "fault": {"trigger": "fault", "selection": "sel", "key": "event_id",
              "episode": ["asset_id", "fault.code"]},
    "needy": {"trigger": "needy", "selection": "sel", "key": "event_id",
              "requires": ["picture.mission_essential"]},
    "to_orphan": {"trigger": "to_orphan", "selection": "sel_orphan", "key": "event_id"},
    "to_untyped": {"trigger": "to_untyped", "selection": "sel_untyped", "key": "event_id"},
    "two_step": {"trigger": "two_step", "selection": "sel_two", "key": "event_id"},
    "closes_at_once": {"trigger": "closes_at_once", "selection": "sel_terminal",
                       "key": "event_id"},
}

_TABLES = {
    "sel": {"decision": "sel", "matches": ["level"], "domain": {"level": ["hi", "lo"]},
            "rows": [{"when": {"level": "hi"}, "then": "review"},
                     {"when": {"level": "lo"}, "then": "review"}]},
    "review_chain": {"decision": "review_chain", "after": "review", "matches": ["outcome"],
                     "domain": {"outcome": ["ok", "again", "timed_out"]},
                     "terminals": ["done", "expired"],
                     "rows": [{"when": {"outcome": "ok"}, "then": "done"},
                              {"when": {"outcome": "again"}, "then": "review"},
                              {"when": {"outcome": "timed_out"}, "then": "expired"}]},
    "sel_orphan": {"decision": "sel_orphan", "matches": ["level"],
                   "domain": {"level": ["hi", "lo"]}, "rows": [{"then": "orphan"}]},
    "sel_untyped": {"decision": "sel_untyped", "matches": ["level"],
                    "domain": {"level": ["hi", "lo"]}, "rows": [{"then": "untyped"}]},
    "sel_two": {"decision": "sel_two", "matches": ["level"],
                "domain": {"level": ["hi", "lo"]}, "rows": [{"then": "first"}]},
    "first_chain": {"decision": "first_chain", "after": "first", "matches": ["outcome"],
                    "domain": {"outcome": ["ok"]}, "rows": [{"then": "second"}]},
    "second_chain": {"decision": "second_chain", "after": "second", "matches": ["outcome"],
                     "domain": {"outcome": ["ok"]}, "terminals": ["done"],
                     "rows": [{"then": "done"}]},
    "sel_terminal": {"decision": "sel_terminal", "matches": ["level"],
                     "domain": {"level": ["hi", "lo"]}, "terminals": ["nothing"],
                     "rows": [{"then": "nothing"}]},
}


def _await(**extra):
    return {"kind": "human_await", "id": "decide", "audience": "maint:{trigger.tier}", **extra}


_DEFINITIONS = {
    "review": {"id": "review", "name": "review", "steps": [_await(task_kind="review_kind")]},
    "orphan": {"id": "orphan", "name": "orphan", "steps": [_await(task_kind="review_kind")]},
    "first": {"id": "first", "name": "first",
              "steps": [_await(task_kind="review_kind", approves=["ok"], role="maintainer")]},
    "second": {"id": "second", "name": "second",
               "steps": [_await(task_kind="review_kind", approves=["ok"], role="supervisor")]},
    "untyped": {"id": "untyped", "name": "untyped", "steps": [_await()]},
}


def _dump(d: Path, rows: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name, row in rows.items():
        (d / f"{name}.yaml").write_text(yaml.safe_dump(row), encoding="utf-8")
    return d


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_TRIGGER_DIR", str(_dump(tmp_path / "triggers", _TRIGGERS)))
    monkeypatch.setenv("DECISION_TABLE_DIR", str(_dump(tmp_path / "decisions", _TABLES)))
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR",
                       str(_dump(tmp_path / "workflows", _DEFINITIONS)))
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {})
    return tmp_path


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(
                            (wf, task["audience"], kind)) or {})
    return rows


def _facts(event_id="E-1", **extra):
    return {"event_id": event_id, "asset_id": "A-7", "fault": {"code": "F12"},
            "level": "hi", "tier": "ORG", **extra}


async def _refused(coro, status):
    # ANY exception, then its type: a refusal that escapes as a raw error is not a refusal the
    # runtime turns into a terminal failure -- it is a retry loop.
    with pytest.raises(Exception) as exc:
        await coro
    assert isinstance(exc.value, restate.TerminalError), repr(exc.value)
    assert exc.value.status_code == status, (exc.value.status_code, str(exc.value))
    return str(exc.value)


def _hops(case):
    return [(t["from"], t["outcome"], t["to"]) for t in case["transitions"]]


# ── 1. TRIGGER → SELECT → RUN → CHAIN → TERMINAL ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_CASE_RUNS_FROM_TRIGGER_TO_A_DECLARED_TERMINAL(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok", "m@x", "fine")})
    out = await c.start("E-1", "fault", _facts())
    assert out["status"] == "CLOSED" and out["terminal"] == "done", out
    case = c.case("E-1")
    assert _hops(case) == [(None, "received", "received"), ("received", "triaged", "triaged"),
                           ("triaged", "selected", "review"), ("review", "ok", "done")], _hops(case)
    sel, last = case["transitions"][2], case["transitions"][3]
    assert sel["reason"] == "sel row 0" and sel["by"] == "system", sel
    # WHO: the actor the gate verified on the deciding step, and the row of the table that chose.
    assert (last["by"], last["reason"], last["instance_id"], last["decided_by"]) == (
        "m@x", "fine", "E-1~1", "review_chain row 0"), last
    assert all(t["at"] for t in case["transitions"]), case["transitions"]
    assert registered == [("E-1~1", "maint:ORG", "review_kind")], registered


@pytest.mark.asyncio
async def test_EVERY_CHOICE_IS_JOURNALLED(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await c.start("E-1", "fault", _facts())
    assert {"intake", "select", "chain_1"} <= set(c.ctx("E-1").runs), c.ctx("E-1").runs
    assert "definition" in c.ctx("E-1~1").runs, c.ctx("E-1~1").runs


@pytest.mark.asyncio
async def test_A_LOOP_OPENS_A_NEW_INSTANCE(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("again", "a@x"),
                  ("E-1~2", "approval_decide"): _answer("ok", "b@x")})
    out = await c.start("E-1", "fault", _facts())
    case = c.case("E-1")
    assert _hops(case)[-2:] == [("review", "again", "review"), ("review", "ok", "done")], case
    assert [t.get("by") for t in case["transitions"][-2:]] == ["a@x", "b@x"]
    assert [i["instance_id"] for i in case["instances"]] == ["E-1~1", "E-1~2"], case["instances"]
    assert [r[0] for r in registered] == ["E-1~1", "E-1~2"], registered
    assert out["terminal"] == "done"


@pytest.mark.asyncio
async def test_AN_EXPIRY_CHAINS_ON_TIMED_OUT_AND_NOBODY_DECIDED_IT(policy, registered, monkeypatch):
    defs = dict(_DEFINITIONS, review={"id": "review", "name": "review",
                                      "steps": [_await(task_kind="review_kind",
                                                       deadline_seconds=60)]})
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", str(_dump(policy / "wf2", defs)))

    async def _select(**arms):
        arms["approved"].close()
        arms["expired"].close()
        return ("expired", None)
    monkeypatch.setattr(restate, "select", _select)
    out = await _Cluster().start("E-1", "fault", _facts())
    assert out["terminal"] == "expired", out
    last = out["transitions"][-1]
    assert (last["outcome"], last["by"]) == ("timed_out", "system"), last


@pytest.mark.asyncio
async def test_THE_APPROVAL_CHAIN_CROSSES_INSTANCES(policy, registered):
    """A supervisor's approval is the SECOND entry of the proposal's chain, not the first of a new
    one: the case carries the chain from instance to instance."""
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok", "m@x"),
                  ("E-1~2", "approval_decide"): _answer("ok", "s@x")})
    out = await c.start("E-1", "two_step", _facts())
    assert [(e["step"], e["role"], e["approver_sub"], e["decision_record_ref"])
            for e in out["approval_chain"]] == [
        (1, "maintainer", "m@x", "E-1~1:decide"), (2, "supervisor", "s@x", "E-1~2:decide")], out


# ── 2. INTAKE REFUSES WHAT THE CASE COULD NOT FINISH ────────────────────────────────────────

@pytest.mark.asyncio
async def test_AN_UNDECLARED_TRIGGER_IS_REFUSED(policy, registered):
    msg = await _refused(_Cluster().start("E-1", "no_such", _facts()), 400)
    assert "no_such" in msg and registered == []


@pytest.mark.asyncio
async def test_A_MISSING_REQUIRED_FACT_IS_REFUSED_AT_INTAKE(policy, registered):
    msg = await _refused(_Cluster().start("E-1", "needy", _facts()), 400)
    assert "picture.mission_essential" in msg and registered == []


@pytest.mark.asyncio
async def test_A_KEY_THAT_IS_NOT_THE_EVENTS_IS_REFUSED(policy, registered):
    msg = await _refused(_Cluster().start("E-2", "fault", _facts("E-1")), 400)
    assert "event_id" in msg and registered == []


@pytest.mark.asyncio
async def test_A_CASE_KEY_SHAPED_LIKE_AN_INSTANCE_IS_REFUSED(policy, registered):
    msg = await _refused(_Cluster().start("E~1", "fault", _facts("E~1")), 400)
    assert "reserved" in msg and registered == []


@pytest.mark.asyncio
async def test_A_TRIGGER_FACT_MAY_NOT_STAND_IN_FOR_AN_OUTCOME(policy, registered):
    msg = await _refused(_Cluster().start("E-1", "fault", _facts(outcome="ok")), 400)
    assert "outcome" in msg and registered == []


# ── 3. A CHILD RUNS ONLY WHAT ITS CASE OPENED ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_FORGED_CHILD_IS_REFUSED(policy, registered):
    c = _Cluster()
    run = _body(wr.run)
    # the right shape of key, but the case opened nothing
    await _refused(run(c.ctx("E-1~1"), {"child_of": "E-1", "n": 1}), 403)
    # a key that is not instance n of the case it names
    await _refused(run(c.ctx("E-9"), {"child_of": "E-1", "n": 1}), 400)
    await _refused(run(c.ctx("E-1~2"), {"child_of": "E-1", "n": 1}), 400)
    await _refused(run(c.ctx("E-1~True"), {"child_of": "E-1", "n": True}), 400)
    assert registered == []


@pytest.mark.asyncio
async def test_A_CHILD_TAKES_ITS_DEFINITION_FROM_THE_CASE_NOT_THE_REQUEST(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    c.ctx("E-1").state["instance:1"] = {"definition_id": "review", "trigger": _facts(),
                                        "outputs": {}, "approval_chain": []}
    env = await _body(wr.run)(c.ctx("E-1~1"), {"child_of": "E-1", "n": 1,
                                               "definition_id": "orphan"})
    assert env["definition_id"] == "review", env


# ── 4. A CASE ENDS ONLY AT A TERMINAL A TABLE DECLARES ──────────────────────────────────────

@pytest.mark.asyncio
async def test_A_DEFINITION_NO_TABLE_FOLLOWS_FAILS_THE_CASE(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    msg = await _refused(c.start("E-1", "to_orphan", _facts()), 422)
    assert "after: orphan" in msg
    last = c.case("E-1")["transitions"][-1]
    assert (last["from"], last["to"]) == ("orphan", "failed") and "after: orphan" in last["reason"]


@pytest.mark.asyncio
async def test_A_TERMINAL_AT_SELECTION_IS_REFUSED(policy, registered):
    c = _Cluster()
    msg = await _refused(c.start("E-1", "closes_at_once", _facts()), 422)
    assert "nothing" in msg and registered == []
    assert c.case("E-1")["state"] == "failed"


@pytest.mark.asyncio
async def test_AN_OUTCOME_OUTSIDE_THE_CHAINING_DOMAIN_FAILS_THE_CASE(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("weird")})
    msg = await _refused(c.start("E-1", "fault", _facts()), 422)
    assert "weird" in msg and c.case("E-1")["state"] == "failed"


@pytest.mark.asyncio
async def test_A_RUNAWAY_CYCLE_IS_BOUNDED(policy, registered, monkeypatch):
    monkeypatch.setattr(wr, "MAX_INSTANCES", 3)
    c = _Cluster({(f"E-1~{n}", "approval_decide"): _answer("again") for n in (1, 2, 3, 4)})
    msg = await _refused(c.start("E-1", "fault", _facts()), 500)
    assert "3 instances" in msg and len(registered) == 3, (msg, registered)


@pytest.mark.asyncio
async def test_AN_AWAIT_WITH_NO_DECLARED_KIND_IS_REFUSED(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    msg = await _refused(c.start("E-1", "to_untyped", _facts()), 500)
    assert "task_kind" in msg and registered == []


# ── 5. ONE OPEN CASE PER EPISODE ────────────────────────────────────────────────────────────

def _episode(facts):
    t = R.Trigger.model_validate(_TRIGGERS["fault"])
    return R.episode_key(t, R.flatten(facts))


@pytest.mark.asyncio
async def test_A_SECOND_EVENT_IN_AN_OPEN_EPISODE_ATTACHES(policy, registered):
    c = _Cluster()
    c.obj(_episode(_facts("E-2"))).state["open"] = "E-1"
    out = await c.start("E-2", "fault", _facts("E-2"))
    assert (out["status"], out["attached_to"]) == ("ATTACHED", "E-1"), out
    assert _hops(c.case("E-2"))[-1] == ("received", "duplicate", "attached")
    assert registered == [] and c.obj(_episode(_facts())).state["open"] == "E-1"


@pytest.mark.asyncio
async def test_ANOTHER_FAULT_ON_THE_SAME_ASSET_IS_ANOTHER_EPISODE(policy, registered):
    """The episode is the declared facts' VALUES: a held episode for F12 must not swallow F13."""
    c = _Cluster({("E-2~1", "approval_decide"): _answer("ok")})
    c.obj(_episode(_facts("E-1"))).state["open"] = "E-1"
    other = dict(_facts("E-2"), fault={"code": "F13"})
    assert _episode(other) != _episode(_facts("E-1"))
    out = await c.start("E-2", "fault", other)
    assert out["status"] == "CLOSED", out


@pytest.mark.asyncio
async def test_A_CLOSED_CASE_FREES_ITS_EPISODE(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok"),
                  ("E-2~1", "approval_decide"): _answer("ok")})
    await c.start("E-1", "fault", _facts("E-1"))
    assert "open" not in c.obj(_episode(_facts())).state
    out = await c.start("E-2", "fault", _facts("E-2"))
    assert out["status"] == "CLOSED", out


@pytest.mark.asyncio
async def test_A_FAILED_CASE_STILL_RECORDS_AND_FREES_ITS_EPISODE(policy, registered):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("weird"),
                  ("E-2~1", "approval_decide"): _answer("ok")})
    await _refused(c.start("E-1", "fault", _facts("E-1")), 422)
    assert c.case("E-1")["transitions"][-1]["outcome"] == "failed"
    assert "open" not in c.obj(_episode(_facts())).state, (
        "a refused case held its episode: every later event for that fault is a silent duplicate")
    out = await c.start("E-2", "fault", _facts("E-2"))
    assert out["status"] == "CLOSED", out


@pytest.mark.asyncio
async def test_ONLY_THE_HOLDER_RELEASES_AN_EPISODE(policy):
    c = _Cluster()
    o = c.obj("ep-x")
    assert await _body(wr.claim)(o, {"case_id": "E-1"}) == "E-1"
    assert await _body(wr.claim)(o, {"case_id": "E-2"}) == "E-1"
    await _body(wr.release)(o, {"case_id": "E-2"})
    assert o.state.get("open") == "E-1", o.state


# ── 6. ROUTING DECLARATIONS ─────────────────────────────────────────────────────────────────

def test_TWO_TABLES_AFTER_ONE_DEFINITION_ARE_REFUSED():
    t = {"a": {"decision": "a", "after": "review"}, "b": {"decision": "b", "after": "review"}}
    with pytest.raises(R.CaseRoutingError, match="after: review"):
        R.chaining_index(t)


def test_A_TRIGGER_TWO_OVERLAYS_DECLARE_IS_REFUSED(tmp_path, monkeypatch):
    seed = _dump(tmp_path / "seed", {})
    o1 = _dump(tmp_path / "o1", {"fault": _TRIGGERS["fault"]})
    o2 = _dump(tmp_path / "o2", {"fault": _TRIGGERS["fault"]})
    monkeypatch.setenv("CASE_TRIGGER_DIR", f"{seed}{__import__('os').pathsep}{o1}"
                                           f"{__import__('os').pathsep}{o2}")
    with pytest.raises(R.CaseRoutingError, match="two overlays"):
        R.load_triggers()


def test_AN_EPISODE_BELONGS_TO_ITS_TRIGGER():
    """Two triggers declaring the same facts are two episode spaces: a lifecycle event must not
    attach to an open fault case because the asset and code happen to agree."""
    a = R.Trigger.model_validate(_TRIGGERS["fault"])
    b = R.Trigger.model_validate(dict(_TRIGGERS["fault"], trigger="lifecycle"))
    flat = R.flatten(_facts())
    assert R.episode_key(a, flat) != R.episode_key(b, flat)
    assert R.episode_key(R.Trigger.model_validate(_TRIGGERS["to_orphan"]), flat) is None


def test_THE_CHOSEN_OPTION_IS_A_CHAINING_FACT():
    env = {"outcome": "replace_now", "outcome_step_id": "decide",
           "outputs": {"d": {"decide": {"chosen": {"readiness": "FMC", "dmc": ["X"]}}}}}
    facts = R.termination_facts({"level": "hi"}, env, "d")
    assert facts == {"level": "hi", "outcome": "replace_now", "outcome_repeated": False,
                     "chosen.readiness": "FMC"}, facts


# ── 7. A SIGNAL PASSES THE SAME GATE AS AN APPROVAL ─────────────────────────────────────────

def _signal_ctx(accepts=("acked",), audience="ops:ORG"):
    c = _Cluster().ctx("E-1~1")
    if accepts:
        c.state[main._signal_accepts_key("ack")] = list(accepts)
    if audience:
        c.state[main._audience_key("ack")] = audience
    return c


@pytest.mark.asyncio
async def test_A_SIGNAL_NOBODY_AWAITS_IS_REFUSED():
    await _refused(_body(wr.signal)(_signal_ctx(accepts=()), {"signal": "ack", "status": "acked",
                                                               "acted_by": "s@x"}), 403)


@pytest.mark.asyncio
async def test_A_SIGNAL_OUTSIDE_ITS_VOCABULARY_IS_REFUSED(monkeypatch):
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: True)
    ctx = _signal_ctx()
    await _refused(_body(wr.signal)(ctx, {"signal": "ack", "status": "approved",
                                          "acted_by": "s@x"}), 400)
    assert ctx.resolved == []


@pytest.mark.asyncio
async def test_A_SIGNAL_GOES_THROUGH_THE_AUTHORITY_GATE(monkeypatch):
    seen: list = []
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: seen.append((aud, who)) or False)
    ctx = _signal_ctx()
    await _refused(_body(wr.signal)(ctx, {"signal": "ack", "status": "acked"}), 401)
    await _refused(_body(wr.signal)(ctx, {"signal": "ack", "status": "acked",
                                          "acted_by": "s@x"}), 403)
    assert seen == [("ops:ORG", "s@x")] and ctx.resolved == []
    del ctx.state[main._audience_key("ack")]
    await _refused(_body(wr.signal)(ctx, {"signal": "ack", "status": "acked",
                                          "acted_by": "s@x"}), 403)


@pytest.mark.asyncio
async def test_AN_AUTHORIZED_SIGNAL_RESOLVES_WITH_THE_VERIFIED_ACTOR(monkeypatch):
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: True)
    ctx = _signal_ctx()
    await _body(wr.signal)(ctx, {"signal": "ack", "status": "acked", "acted_by": " s@x ",
                                 "comments": "c"})
    assert ctx.resolved == [("ack", {"status": "acked", "comments": "c", "acted_by": "s@x"})]


def test_THE_CASE_RUNNER_IS_REGISTERED_AND_ALLOWED():
    from src.iagent import human_tasks
    assert "WorkflowRunner" in human_tasks.ALLOWED_WORKFLOW_SERVICES
    assert main.workflow_runner is wr.workflow_runner and main.case_episode is wr.case_episode
