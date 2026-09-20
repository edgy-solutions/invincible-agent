"""The `review_request` CONSUMER — the durable half that actually opens the acceptance.

`engine-safety` has emitted `review_request` on every drafted risk assessment since 2026-09-12
and **nothing has ever read it** (R-076). This is the reader. It is a Restate workflow rather
than a gateway function for one reason: the acceptance it opens is a HUMAN AWAIT that may suspend
for days, and for Serious/High it is the SECOND act of a chain whose first act must be disposed
before the second can exist. That is durable execution's job, not a request handler's.

## WHAT IT DOES, IN ORDER

    read the level off the trigger the gateway lifted from the draft's review_request
    ask `safety_acceptance_selection` which definition opens an acceptance at that level
    load THAT definition from the runtime registry — never from the request
    run it on the shared executor, which owns `human_await` and therefore owns register_task

## THE DEFINITION IS LOADED, NOT SUPPLIED, AND THAT IS THE WHOLE SECURITY ARGUMENT

`grouped_review` states it plainly: *"a client-supplied process would be exactly the laundering
`_run_definition`'s stage-2 verifier exists to prevent."* Here it is sharper still. A caller that
could name the definition could name `safety_acceptance_direct` for a High hazard and skip the
user representative's concurrence that MIL-STD-882E §4.3.7 requires BEFORE acceptance — a
bypass that would leave a perfectly ordinary-looking acceptance record behind it.

**So the trigger carries FACTS (hazard, level) and never the ROUTE.** Same shape as
`review_starter`, which computes its trust rung server-side "because handing the route over the
wire would let anyone entitled to `mesh:startReview` select their own supervision level".

## A SELECTION FAILURE IS TERMINAL, NEVER A RETRY AND NEVER A DEFAULT

An unknown level, a table with no row, a table that is not shipped: none of these get better by
being retried, and none of them has a safe default — `policy/decisions/README.md` rules that a
fall-through "means NO DEFINITION WAS CHOSEN at the moment a human risk decision was due". They
become `restate.TerminalError`, so the workflow FAILS AND RELEASES rather than parking a hazard
in a queue nobody is looking at.

**AND THE FAILURE IS NOT SILENT ANYWHERE.** The caller gets the refusal, because a drafted hazard
whose acceptance could not be opened must not render as a completed turn.
"""
from __future__ import annotations

import restate
from restate import Workflow, WorkflowContext

#: FROZEN CONTRACT SURFACE — the gateway calls `/SafetyAcceptance/{key}/run` by hand, the same
#: way it calls `/GroupedReview/{key}/submit_decision`. Renaming this renames a URL.
safety_acceptance = Workflow("SafetyAcceptance")


def _selection():
    """The decision half, from the leaf module that owns it.

    Dual-path because the import root differs between the Restate service (flattened into
    `/app`) and the test harness — the idiom this package already uses. NOT fail-soft: an
    unimportable selector is a refusal, and the caller must hear it. A default here would be a
    definition chosen by an ImportError.
    """
    try:
        import acceptance_selection  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst import acceptance_selection
    return acceptance_selection


@safety_acceptance.main()
async def run(ctx: WorkflowContext, request: dict) -> dict:
    """Open the acceptance the draft asked for, by the route the table chooses.

    `request` is `acceptance_selection.acceptance_trigger(review_request)` — flat scalars,
    because `_run_definition` binds a definition's `{placeholders}` from top-level scalars only
    and the fields it needs live one level down inside `review_request["payload"]`.
    """
    try:  # lazy — main imports THIS module at load time, so the edge must be call-time
        import main as _main  # type: ignore[no-redef]
        from workflow_definition import get_workflow_definition  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst import main as _main
        from agent_fleet.restate_analyst.workflow_definition import get_workflow_definition

    sel = _selection()

    level = str(request.get("level") or "")
    if not level:
        # THE TRIGGER, NOT THE TABLE. Distinguished from "the table has no row for this level"
        # because they are different defects with different owners: this one is the caller's.
        raise restate.TerminalError(
            "safety acceptance triggered with no `level` — the selection table matches on it and "
            f"cannot be evaluated without it (trigger keys: {sorted(request)}). The gateway "
            "builds this trigger with `acceptance_selection.acceptance_trigger`.",
            status_code=400,
        )

    try:
        definition_id = sel.select(level)
    except sel.AcceptanceSelectionError as exc:
        # TERMINAL, and the message is the table's own. Retrying an untailored level produces the
        # same gap in thirty seconds; the fix is a decision-table row, which is a human act.
        raise restate.TerminalError(
            f"no acceptance definition selected for level {level!r}: {exc}", status_code=422,
        ) from exc

    try:
        definition = get_workflow_definition(definition_id)
    except Exception as exc:  # noqa: BLE001
        # THE TABLE CHOSE A DEFINITION THIS RUNTIME DOES NOT HAVE. `get_workflow_definition`
        # already distinguishes "no definitions shipped" from "no such id" and names both the
        # directories and the inventory, so its message is carried verbatim rather than
        # summarised into something less useful.
        raise restate.TerminalError(
            f"{sel.SELECTION_DECISION} selected {definition_id!r} for level {level!r} and this "
            f"runtime cannot load it: {type(exc).__name__}: {exc}",
            status_code=500,
        ) from exc

    envelope = await _main._run_definition(
        ctx, ctx.key(), definition.model_dump(), request,
    )

    awaited = [
        r for r in envelope.get("step_results", []) if r.get("kind") == "human_await"
    ]
    if not awaited:
        # THE DEFINITION RAN AND ASKED NOBODY. An acceptance process with no human step has
        # silently become an automatic acceptance, which is the one outcome ADR-0051 says this
        # verb may never produce ("this engine cannot accept it"). Loud, because an empty {}
        # here would read to the caller as an acceptance that completed.
        raise restate.TerminalError(
            f"{definition_id} ran for {request.get('hazard_id')!r} and produced NO human_await "
            f"result — steps ran: {[r.get('step_id') for r in envelope.get('step_results', [])]}. "
            "An acceptance process that asks no human has accepted the risk by omission.",
            status_code=500,
        )

    return {
        # WHICH ROUTE WAS TAKEN, carried out so the caller's record can say what opened without
        # re-reading a table that may have been tailored since. Same reason `review_starter`
        # carries `trust_rung` onto the workflow it starts.
        "definition_id": definition_id,
        "selected_by": sel.SELECTION_DECISION,
        "level": level,
        "hazard_id": request.get("hazard_id"),
        "steps": [r.get("step_id") for r in awaited],
        "status": awaited[-1].get("status"),
    }
