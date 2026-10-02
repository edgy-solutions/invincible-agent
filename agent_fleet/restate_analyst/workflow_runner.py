"""WorkflowRunner — ADR-0039's case runner: select at trigger, run, chain at termination.

A CASE is one Restate workflow keyed by the event's own key. It opens on a declared trigger, asks
the trigger's selection table which definition runs first, runs it, asks the table declared
``after:`` that definition what follows its outcome, and repeats until a table names a terminal.
Nothing here knows a domain: safety acceptance and a maintenance fault differ only in rows.

## EVERY DEFINITION IS ITS OWN INSTANCE, KEYED ``{case}~{n}``

ADR-0039: "loops are new instances" and "every instance is a record". It is also forced: a
definition's promise names derive from its step ids, so running it twice inside ONE workflow would
await a promise the first run already resolved, and the second approval would read the first
one's answer. A child is the same service, so ``/act`` and an ack both resume
``/WorkflowRunner/{instance}/...`` from what the task row or the emitted record names.

## A CHILD RUNS ONLY WHAT ITS CASE OPENED

The child is reachable on the Restate ingress, so it takes nothing from its request but
``(child_of, n)``: the definition, the trigger facts, the outputs and the approval chain come from
the CASE's state, written by the case's own ``run`` before the call. A forged child call can only
run what the case already chose -- and a case key may not contain ``~``, so no trigger can mint one.

## EVERY CHOICE IS JOURNALLED

Selection, each chaining decision and each definition load run inside ``ctx.run``. A case lasts
days; a redeploy that tailored a table mid-case must not reroute it on replay, and the case
record must say which row of which table chose each step.
"""
from __future__ import annotations

from typing import Any, Optional

import restate
from restate import ObjectContext, VirtualObject, Workflow, WorkflowContext, WorkflowSharedContext

#: FROZEN CONTRACT SURFACE — task rows name it, and ``/act`` and acks post to it.
workflow_runner = Workflow("WorkflowRunner")

#: One open case per episode. Keyed by ``case_routing.episode_key``.
case_episode = VirtualObject("CaseEpisode")

#: A table cycle with no human in it would spin forever; this bounds the damage. Not a policy
#: limit -- a case that legitimately loops this often has a different problem.
MAX_INSTANCES = 64


def _main():
    try:  # lazy — main imports THIS module at load time, so the edge must be call-time
        import main as _m  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst import main as _m
    return _m


def _routing():
    try:
        import case_routing as _r  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst import case_routing as _r
    return _r


def _terminal(fn, status_code: int):
    """Run a routing call; a routing failure is TERMINAL inside ``ctx.run`` (a retry of an
    untailored table produces the same gap in thirty seconds)."""
    def _go():
        r = _routing()
        try:
            return fn()
        except r.CaseRoutingError as exc:
            raise restate.TerminalError(str(exc), status_code=status_code) from exc
    return _go


def _child_key(case_id: str, n: int) -> str:
    return f"{case_id}{_routing().CHILD_SEP}{n}"


@workflow_runner.main()
async def run(ctx: WorkflowContext, request: dict) -> dict:
    if "child_of" in request:
        return await _run_instance(ctx, request)
    return await _run_case(ctx, request)


# ── THE CASE ────────────────────────────────────────────────────────────────────────────────

async def _record(ctx, case: dict, *, frm, outcome, to, by=None, reason=None, at_name: str,
                  **extra) -> None:
    """Append one transition -- who and when, always -- and publish the case record."""
    at = await ctx.run(at_name, _main()._now_iso)
    case["transitions"].append({"from": frm, "outcome": outcome, "to": to, "by": by,
                                "at": at, "reason": reason, **extra})
    case["state"] = to
    ctx.set("case", case)


async def _run_case(ctx: WorkflowContext, request: dict) -> dict:
    R = _routing()
    case_id = ctx.key()
    name = str(request.get("trigger") or "")
    facts = request.get("facts")
    if not isinstance(facts, dict):
        raise restate.TerminalError(
            f"a case opens on a trigger and its event's facts; got facts={type(facts).__name__}",
            status_code=400)

    def _intake():
        trig = R.load_trigger(name)
        flat = R.flatten(facts)
        R.check_intake(trig, flat, case_id)
        return {"trigger": trig.model_dump(), "flat": flat, "episode": R.episode_key(trig, flat)}

    intake = await ctx.run("intake", _terminal(_intake, 400))
    trig = R.Trigger.model_validate(intake["trigger"])
    flat, episode = intake["flat"], intake["episode"]

    case: dict = {"case_id": case_id, "trigger": name, "state": None, "terminal": None,
                  "episode": episode, "instances": [], "transitions": []}
    await _record(ctx, case, frm=None, outcome="received", to="received", by="system",
                  at_name="at_received")

    # ── TRIAGE: one open case per episode ───────────────────────────────────────────────────
    if episode:
        owner = await ctx.object_call(claim, key=episode, arg={"case_id": case_id})
        if owner != case_id:
            await _record(ctx, case, frm="received", outcome="duplicate", to="attached",
                          by="system", reason=f"episode {episode} is open in case {owner}",
                          at_name="at_attached")
            return {"case_id": case_id, "status": "ATTACHED", "attached_to": owner,
                    "transitions": case["transitions"]}
    await _record(ctx, case, frm="received", outcome="triaged", to="triaged", by="system",
                  at_name="at_triaged")

    try:
        sel = await ctx.run("select", _terminal(lambda: R.select(trig, flat), 422))
        definition_id = sel["then"]
        await _record(ctx, case, frm="triaged", outcome="selected", to=definition_id,
                      by="system", reason=f"{sel['table']} row {sel['row']}",
                      at_name="at_selected")

        outputs: dict = {}
        chain: list = []
        for n in range(1, MAX_INSTANCES + 1):
            instance = _child_key(case_id, n)
            ctx.set(f"instance:{n}", {"definition_id": definition_id, "trigger": facts,
                                      "outputs": outputs, "approval_chain": chain})
            case["instances"].append({"n": n, "instance_id": instance,
                                      "definition_id": definition_id})
            ctx.set("case", case)

            env = await ctx.workflow_call(run, key=instance, arg={"child_of": case_id, "n": n})
            outputs = env.get("outputs") or {}
            chain = env.get("approval_chain") or []

            term = R.termination_facts(flat, env, definition_id)
            nxt = await ctx.run(f"chain_{n}", _terminal(lambda: R.chain(definition_id, term), 422))
            step = (outputs.get(definition_id) or {}).get(env.get("outcome_step_id")) or {}
            await _record(
                ctx, case, frm=definition_id, outcome=env.get("outcome"), to=nxt["then"],
                # WHO: the actor the gate VERIFIED for the deciding step; a timer or a system
                # step has none, and the record says so rather than borrowing the trigger's.
                by=step.get("acted_by") or "system", reason=step.get("comments") or None,
                at_name=f"at_{n}", instance_id=instance,
                decided_by=f"{nxt['table']} row {nxt['row']}")
            if nxt["terminal"]:
                case["terminal"] = nxt["then"]
                ctx.set("case", case)
                break
            definition_id = nxt["then"]
        else:
            raise restate.TerminalError(
                f"case {case_id} opened {MAX_INSTANCES} instances without reaching a terminal -- "
                "a chaining cycle with no human in it", status_code=500)
    except restate.TerminalError as exc:
        # A FAILED CASE IS STILL A RECORD, and it frees its episode: a refusal that held the
        # episode would make every later event for that fault a silent duplicate.
        await _record(ctx, case, frm=case["state"], outcome="failed", to="failed", by="system",
                      reason=str(exc), at_name="at_failed")
        if episode:
            ctx.object_send(release, key=episode, arg={"case_id": case_id})
        raise

    if episode:
        ctx.object_send(release, key=episode, arg={"case_id": case_id})
    return {"case_id": case_id, "status": "CLOSED", "terminal": case["terminal"],
            "transitions": case["transitions"], "approval_chain": chain}


# ── ONE INSTANCE ────────────────────────────────────────────────────────────────────────────

async def _run_instance(ctx: WorkflowContext, request: dict) -> dict:
    case_id = str(request.get("child_of") or "")
    n = request.get("n")
    if not case_id or not isinstance(n, int) or isinstance(n, bool) or ctx.key() != _child_key(case_id, n):
        raise restate.TerminalError(
            f"instance key {ctx.key()!r} is not instance {n!r} of case {case_id!r}",
            status_code=400)
    spec = await ctx.workflow_call(instance_spec, key=case_id, arg={"n": n})
    if not spec:
        raise restate.TerminalError(
            f"case {case_id!r} opened no instance {n} -- an instance runs only what its case chose",
            status_code=403)

    def _load():
        try:
            from workflow_definition import get_workflow_definition  # type: ignore[no-redef]
        except ImportError:  # pragma: no cover — import path differs by runtime
            from agent_fleet.restate_analyst.workflow_definition import get_workflow_definition
        try:
            wf = get_workflow_definition(spec["definition_id"])
        except Exception as exc:  # noqa: BLE001
            raise restate.TerminalError(
                f"case {case_id} chose {spec['definition_id']!r} and this runtime cannot load it: "
                f"{type(exc).__name__}: {exc}", status_code=500) from exc
        # EVERY SINGLE AWAIT DECLARES ITS KIND. `/act` keys the decision's vocabulary and reason
        # on the row's kind; a case runner has no caller to supply one, and a shared default
        # would put every case's answers under one gate (the HAZ-1003 defect, generalised).
        undeclared = [s.id for s in wf.steps if s.kind == "human_await"
                      and s.completion.mode != "grouped" and not s.task_kind]
        if undeclared:
            raise restate.TerminalError(
                f"{wf.id}: human_await step(s) {undeclared} declare no task_kind; the case runner "
                "registers no row under a kind nobody declared", status_code=500)
        return wf.model_dump(mode="json")

    definition = await ctx.run("definition", _load)
    return await _main()._run_definition(
        ctx, ctx.key(), definition, spec["trigger"],
        workflow_service="WorkflowRunner", from_registry=True,
        outputs=spec["outputs"], approval_chain=spec["approval_chain"])


# ── HANDLERS ────────────────────────────────────────────────────────────────────────────────

@workflow_runner.handler()
async def instance_spec(ctx: WorkflowSharedContext, request: dict) -> Optional[dict]:
    """What the case opened as instance ``n`` -- read by the instance, written only by ``run``."""
    return await ctx.get(f"instance:{int(request['n'])}")


@workflow_runner.handler()
async def approve(ctx: WorkflowSharedContext, request: dict) -> dict:
    """Resolve a human await on an instance -- the one shared gate, ``main._approve_impl``."""
    return await _main()._approve_impl(ctx, request)


@workflow_runner.handler()
async def signal(ctx: WorkflowSharedContext, request: dict) -> dict:
    """Resolve a ``signal_await`` -- a system's answer. The vocabulary check is HERE because no
    task row stands in front of a signal: ``accepts`` was journalled by the await itself."""
    m = _main()
    name = str(request.get("signal") or "")
    accepts = await ctx.get(m._signal_accepts_key(name))
    if not accepts:
        raise restate.TerminalError(
            f"no signal {name!r} is awaited on {ctx.key()!r}", status_code=403)
    status = request.get("status")
    if status not in accepts:
        raise restate.TerminalError(
            f"signal {name!r} accepts {accepts}, not {status!r}", status_code=400)
    acted_by = await m._authorize_resolution(ctx, name, request.get("acted_by"))
    await ctx.promise(name, type_hint=dict).resolve(
        {"status": status, "comments": request.get("comments", ""), "acted_by": acted_by})
    return {"signal": name, "status": status}


@workflow_runner.handler()
async def case(ctx: WorkflowSharedContext, request: Any = None) -> Optional[dict]:
    """The case record: state, transitions (from, outcome, to, by, at, reason), instances."""
    return await ctx.get("case")


@workflow_runner.handler()
async def outbox(ctx: WorkflowSharedContext, request: dict) -> list:
    """What an instance has emitted on a channel. Read on the INSTANCE, which is where the
    emitting step waits for its answer; each record names the instance an answer goes to."""
    return list(await ctx.get(f"outbox:{request.get('channel')}") or [])


@case_episode.handler()
async def claim(ctx: ObjectContext, request: dict) -> str:
    """The open case for this episode: the caller's, if none was open."""
    cur = await ctx.get("open")
    if cur:
        return cur
    ctx.set("open", request["case_id"])
    return request["case_id"]


@case_episode.handler()
async def release(ctx: ObjectContext, request: dict) -> None:
    """Close the episode -- only by the case that holds it."""
    if await ctx.get("open") == request.get("case_id"):
        ctx.clear("open")
