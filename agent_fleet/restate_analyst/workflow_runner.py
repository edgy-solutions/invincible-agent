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

## A RETURN TO A PROPOSAL READS THE PICTURE AS IT IS NOW

A chaining row may say ``refresh_input: true``. Before the definition it opens runs, the case reads
the newest revision of its input from both sources, in order: what the source PUSHED (the same
event_id again, through ``revise``, kept on the episode) and what the trigger's ``pull`` stub verb
returns. A newer one replaces the facts the next instance and the next chaining table read; the
case record keeps ``input_revisions[]`` and every instance sees ``input.revision``. The original
event is revision 1. Nothing is written to a store.

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
        R.check_intake(trig, flat, case_id, facts=facts)
        return {"trigger": trig.model_dump(), "flat": flat, "episode": R.episode_key(trig, flat)}

    intake = await ctx.run("intake", _terminal(_intake, 400))
    trig = R.Trigger.model_validate(intake["trigger"])
    flat, episode = intake["flat"], intake["episode"]

    case: dict = {"case_id": case_id, "trigger": name, "state": None, "terminal": None,
                  "episode": episode, "instances": [], "transitions": []}
    await _record(ctx, case, frm=None, outcome="received", to="received", by="system",
                  at_name="at_received")
    # THE ORIGINAL EVENT IS REVISION 1. A refresh appends; the instance sees the newest.
    case["input_revisions"] = [{"rev": 1, "event_id": case_id,
                                "received_at": case["transitions"][-1]["at"],
                                "provenance": "pushed"}]
    current = {"revision": 1, "event_id": case_id, "provenance": "pushed",
               "received_at": case["input_revisions"][0]["received_at"]}
    ctx.set("case", case)

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
            # THE CASE'S OWN IDENTITY travels with every instance, so a record an instance emits
            # can name the case it belongs to as well as the definition that emitted it.
            ctx.set(f"instance:{n}", {"definition_id": definition_id, "trigger": facts,
                                      "outputs": outputs, "approval_chain": chain,
                                      "case": {"case_id": case_id, "trigger": name},
                                      "input": dict(current)})
            case["instances"].append({"n": n, "instance_id": instance,
                                      "definition_id": definition_id})
            ctx.set("case", case)

            env = await ctx.workflow_call(run, key=instance, arg={"child_of": case_id, "n": n})
            outputs = env.get("outputs") or {}
            chain = env.get("approval_chain") or []

            term = R.termination_facts(flat, env, definition_id, case["transitions"])
            nxt = await ctx.run(f"chain_{n}", _terminal(lambda: R.chain(definition_id, term), 422))
            step = (outputs.get(definition_id) or {}).get(env.get("outcome_step_id")) or {}
            refreshed: dict = {}
            if nxt.get("refresh_input") and not nxt["terminal"]:
                fresh = await _refresh(ctx, trig, case, episode, current, facts, n)
                if fresh:
                    facts, flat, current = fresh["facts"], fresh["flat"], fresh["current"]
                refreshed = {"input_revision": current["revision"]}
            await _record(
                ctx, case, frm=definition_id, outcome=env.get("outcome"), to=nxt["then"],
                # WHO: the actor the gate VERIFIED for the deciding step; a timer or a system
                # step has none, and the record says so rather than borrowing the trigger's.
                by=step.get("acted_by") or "system", reason=step.get("comments") or None,
                at_name=f"at_{n}", instance_id=instance,
                decided_by=f"{nxt['table']} row {nxt['row']}", **refreshed)
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


async def _refresh(ctx, trig, case: dict, episode: Optional[str], current: dict, facts: dict,
                   n: int) -> Optional[dict]:
    """The input revision received after ``current``, newest of both sources, or None.

    PUSHED FIRST: the revision the source sent again, kept on the episode. PULLED SECOND: the
    trigger's ``pull`` stub verb, rendered with ``{kept}`` in its context -- declared now, so the
    real picture endpoint retires a stub rather than adding a second mechanism. The newest
    ``received_at`` wins, a tie goes to the pulled one, then the higher ``rev``
    (``case_routing.newest_revision``). The winner passes intake again and must stay in the case's episode:
    ``keep_revision`` is reachable on the ingress as well as through ``revise``, so what was kept
    is never trusted as checked, and neither is what a pull returns."""
    R = _routing()
    case_id = case["case_id"]
    kept = (await ctx.object_call(newest_revision, key=episode, arg={"case_id": case_id})
            if episode else None)

    def _pull():
        if not trig.pull:
            return None
        try:
            from workflow_definition import load_stub_verbs  # type: ignore[no-redef]
        except ImportError:  # pragma: no cover — import path differs by runtime
            from agent_fleet.restate_analyst.workflow_definition import load_stub_verbs
        stub = load_stub_verbs().get(trig.pull)
        if stub is None:
            raise restate.TerminalError(
                f"trigger {trig.trigger!r} pulls with {trig.pull!r}, which no stub verb declares",
                status_code=500)
        got = _main()._render(stub.returns, {"kept": kept}, where=f"pull verb {trig.pull}")
        return None if got is None else {**got, "provenance": "pulled", "verb": trig.pull}

    pulled = await ctx.run(f"pull_{n}", _pull)
    on = {"rev": current["revision"], "received_at": current["received_at"],
          "provenance": current["provenance"], "facts": facts}
    best = await ctx.run(f"newest_{n}", _terminal(
        lambda: R.newest_revision(on, [kept, pulled]), 500))
    if best is None:
        return None
    flat = await ctx.run(f"refresh_{n}", _terminal(
        lambda: R.check_revision(trig, best["facts"], case_id, episode), 422))
    case["input_revisions"].append({k: best.get(k) for k in
                                    ("rev", "event_id", "received_at", "provenance")})
    return {"facts": best["facts"], "flat": flat,
            "current": {"revision": best["rev"], "event_id": best.get("event_id"),
                        "provenance": best.get("provenance"),
                        "received_at": best.get("received_at")}}


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
            from workflow_definition import (  # type: ignore[no-redef]
                UnboundPlaceholder, bind_placeholders, get_workflow_definition)
        except ImportError:  # pragma: no cover — import path differs by runtime
            from agent_fleet.restate_analyst.workflow_definition import (
                UnboundPlaceholder, bind_placeholders, get_workflow_definition)
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
        # A DIRECT CALL'S ENDPOINT IS DEPLOYMENT WIRING, BOUND HERE, AT ADMISSION. Nothing else on
        # this path binds it, so `{origin_write_endpoint}` reached the HTTP client verbatim and
        # the write failed as an unusable URL -- after `resolution` had already emitted. Bound
        # from CONFIG ONLY, never from the trigger: the call carries the case runner's own bearer
        # token, and a fact on an event must not choose where that token is sent.
        bound = wf.model_dump(mode="json")
        for st in bound["steps"]:
            if st["kind"] == "direct_call":
                try:
                    st["endpoint"] = bind_placeholders(
                        {"id": wf.id, "endpoint": st["endpoint"]}, {})["endpoint"]
                except UnboundPlaceholder as exc:
                    raise restate.TerminalError(
                        f"step {st['id']!r}: {exc}", status_code=500) from exc
        return bound

    definition = await ctx.run("definition", _load)
    return await _main()._run_definition(
        ctx, ctx.key(), definition, spec["trigger"],
        workflow_service="WorkflowRunner", from_registry=True,
        outputs=spec["outputs"], approval_chain=spec["approval_chain"], case=spec.get("case"),
        case_input=spec.get("input"))


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
    if status in (await ctx.get(m._signal_reason_key(name)) or []) \
            and not str(request.get("comments") or "").strip():
        raise restate.TerminalError(
            f"signal {name!r} answered {status!r} needs a reason (the definition's "
            "`reason_required`); the case carries it onto the next hop", status_code=400)
    acted_by = await m._authorize_resolution(ctx, name, request.get("acted_by"))
    await ctx.promise(name, type_hint=dict).resolve(
        {"status": status, "comments": request.get("comments", ""), "acted_by": acted_by})
    return {"signal": name, "status": status}


@workflow_runner.handler()
async def case(ctx: WorkflowSharedContext, request: Any = None) -> Optional[dict]:
    """The case record: state, transitions (from, outcome, to, by, at, reason), instances."""
    return await ctx.get("case")


@workflow_runner.handler()
async def revise(ctx: WorkflowSharedContext, request: dict) -> dict:
    """A NEWER PICTURE OF THE EVENT THIS CASE OPENED ON -- the same event_id, sent again.

    Restate runs a workflow key once, so a repeat event_id cannot start a second case; it arrives
    here instead. It passes the same intake as the original, must stay in the case's episode, and
    is kept on the episode as revision k (the original is 1). Nothing reads it until a chaining
    row says ``refresh_input``: a revision never changes an instance already running."""
    R = _routing()
    case_id = ctx.key()
    case = await ctx.get("case")
    if not case:
        raise restate.TerminalError(f"no case {case_id!r} to revise", status_code=404)
    if not case.get("episode"):
        raise restate.TerminalError(
            f"case {case_id!r}'s trigger declares no episode, so a revision has nowhere to be kept",
            status_code=409)
    facts = request.get("facts")
    await ctx.run("revise_intake", _terminal(lambda: R.check_revision(
        R.load_trigger(case["trigger"]), facts, case_id, case["episode"]), 400))
    at = await ctx.run("revise_at", _main()._now_iso)
    return await ctx.object_call(keep_revision, key=case["episode"], arg={
        "case_id": case_id, "event_id": case_id, "facts": facts, "received_at": at})


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
    """Close the episode -- only by the case that holds it -- and drop its kept revision, which
    belongs to that case: the next case on this episode opens on its own event."""
    if await ctx.get("open") == request.get("case_id"):
        ctx.clear("open")
        ctx.clear("revision")


@case_episode.handler()
async def keep_revision(ctx: ObjectContext, request: dict) -> dict:
    """Keep a pushed revision for the case holding this episode. A closed case, or another
    case's event, keeps nothing: its refresh would never read it, or would read the wrong one.
    A ``received_at`` the refresh could not order is refused HERE: this handler is reachable on
    the ingress, and the same value refused at the refresh would fail the case instead."""
    holder = await ctx.get("open")
    if not holder or holder != request.get("case_id"):
        raise restate.TerminalError(
            f"case {request.get('case_id')!r} does not hold this episode (open: {holder!r}); "
            "a revision is kept only for the open case", status_code=409)
    _terminal(lambda: _routing().received_at(request), 400)()
    prev = await ctx.get("revision")
    kept = {"rev": (prev["rev"] if prev else 1) + 1, "event_id": request["event_id"],
            "received_at": request["received_at"], "provenance": "pushed",
            "facts": request["facts"]}
    ctx.set("revision", kept)
    return {"case_id": holder, "revision": kept["rev"]}


@case_episode.handler()
async def newest_revision(ctx: ObjectContext, request: dict) -> Optional[dict]:
    """The newest revision kept on this episode, else None. IT IS THE HOLDER'S BY CONSTRUCTION:
    only the holder keeps one (``keep_revision``), ``release`` drops it with the episode, and only
    the holder refreshes -- an attached case returns before it runs anything."""
    return await ctx.get("revision")
