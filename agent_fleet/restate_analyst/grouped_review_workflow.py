"""PCN/PDN grouped-review WORKFLOW — the orchestrator call-site that composes the sealed cores.

The durable glue over the pure/sealed layers: register ONE grouped HumanTask for a whole
per-approver batch, suspend on ``ctx.promise().value()``, and — on an ACCEPTED decision — run
``resolve_batch`` and fan out to the per-item dispatch driver ([[dispatch_driver]]). One approval resolves
N items (the fan-OUT dual of the Slice-5 join).

Two joints this call-site must answer, each sealed (tests/test_grouped_review_workflow.py):

1. **Refusal routing — the POLICY-failure sibling of suspend-vs-fail.** The grouped review resolves
   with a ``BulkDecision``, but the bulk-resolve core can REFUSE it (an unverified row with no
   explicit override, a row with no disposition, a blank override reason). The ``submit_decision``
   shared handler validates the decision against the SERVER-AUTHORED batch BEFORE waking the
   workflow: a refusal leaves the review SUSPENDED and returns "still pending, here's why" — it never
   resolves the promise, so NO fan-out fires. Only an accepted decision wakes the workflow. This is
   the sibling of the auth suspend-vs-fail the driver inherited: there a persistent DENIAL fails
   rather than parks; here a policy REFUSAL re-pends rather than dispatches an undefined effect.

2. **Fan-out partial-failure isolation.** ``fan_out_dispatch`` runs inside the workflow's journaled
   context (so a transient send failure retries and the idempotent keys converge), and each item is
   its own keyed VirtualObject invocation — a poisoned item (malformed payload -> engine-o 400)
   TERMINAL-fails ITS OWN object without wedging the other N-1. Per-item isolation is the point of the
   execution grain; the seal asserts it once so it is a property, not an assumption.

The batch is SERVER-AUTHORED upstream (``run_funnel`` -> ``grouped_review`` already applied the
relevance funnel + the per-approver existence-oracle) and persisted in workflow state, so
``submit_decision`` validates against what the server offered, never client-supplied items.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import restate
from restate import Workflow, WorkflowContext, WorkflowSharedContext

try:  # lazy-import dance (container flattens the dir)
    from workflow_bulk_resolve import BulkDecision, Override, PartItem, ReviewBatch, resolve_batch  # type: ignore[no-redef]
    from dispatch_driver import _mint_dispatch_task, fan_out_dispatch  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_bulk_resolve import (
        BulkDecision, Override, PartItem, ReviewBatch, resolve_batch,
    )
    from agent_fleet.restate_analyst.dispatch_driver import _mint_dispatch_task, fan_out_dispatch


# ---------------------------------------------------------------------------
# Serialization — PartItem <-> JSON-native state (the batch rides workflow state)
# ---------------------------------------------------------------------------
def _partitem_to_dict(it: PartItem) -> dict:
    return {
        "mpn": it.mpn, "relevance": it.relevance, "subject": it.subject,
        "proposed_disposition": it.proposed_disposition, "needs_review": it.needs_review,
        "proposed_by_ruleset": it.proposed_by_ruleset,
    }


def _partitem_from_dict(d: dict) -> PartItem:
    return PartItem(
        mpn=d["mpn"], relevance=d.get("relevance", 1.0), subject=d.get("subject"),
        proposed_disposition=d.get("proposed_disposition"), needs_review=d.get("needs_review", False),
        proposed_by_ruleset=d.get("proposed_by_ruleset"),
    )


def batch_items_to_state(batch: ReviewBatch) -> list[dict]:
    return [_partitem_to_dict(it) for it in batch.items]


def _reviewbatch_from_state(approver: str, items_state: list[dict]) -> ReviewBatch:
    return ReviewBatch(approver=approver, items=[_partitem_from_dict(d) for d in items_state])


def _build_bulk_decision(raw: dict) -> BulkDecision:
    """Reconstruct a BulkDecision from the wire. ``Override.__post_init__`` REJECTS a blank reason
    (capture-why is structural), so a blank-reason override raises ValueError HERE -> routed as a
    refusal by ``evaluate_submission``, never a silent accept."""
    overrides: dict = {}
    for mpn, ov in (raw.get("overrides") or {}).items():
        overrides[mpn] = Override(disposition=ov["disposition"], reason=ov.get("reason", ""))
    return BulkDecision(overrides=overrides)


# ---------------------------------------------------------------------------
# The refusal joint — pure, so it seals without a runtime (rider 1's core)
# ---------------------------------------------------------------------------
@dataclass
class Submission:
    """The outcome of validating a grouped decision against the server batch. ``accepted`` gates the
    wake: only an accepted submission resolves the promise and fans out; a refused one carries the
    ``reason`` back to the still-suspended review."""
    accepted: bool
    resolutions: list = field(default_factory=list)
    reason: str = ""


def evaluate_submission(batch: ReviewBatch, raw_decision: dict, *, notice_fingerprint: str) -> Submission:
    """Validate a grouped decision against the SERVER-AUTHORED batch — the policy-failure sibling of
    suspend-vs-fail. Any policy-shaped refusal from the bulk-resolve core (unverified row without an
    explicit override, a row with no disposition, a blank override reason) becomes a REFUSED
    submission carrying the reason; a clean pass becomes ACCEPTED with the N per-item resolutions.
    Pure — no Restate — so the joint seals as a unit test."""
    try:
        decision = _build_bulk_decision(raw_decision)
        resolutions = resolve_batch(batch, decision, notice_fingerprint=notice_fingerprint)
    except ValueError as exc:
        return Submission(accepted=False, reason=str(exc))
    return Submission(accepted=True, resolutions=resolutions)


# ---------------------------------------------------------------------------
# The durable workflow
# ---------------------------------------------------------------------------
grouped_review = Workflow("GroupedReview")


def _compartment_from_request(request: dict) -> str:
    """The compartment this review belongs to — the only part of the audience the TRIGGER
    supplies.

    The definition declares the audience SHAPE (``disposition_review:{compartment}``) and the
    invocation supplies the compartment as DATA. That split is deliberate and is an authz
    boundary, not a convenience: if the trigger could hand over a whole audience string, a
    caller would be choosing who may act on its own review, which is laundering access
    through the process plane. Taking only the tail means a caller can influence WHICH
    compartment reviews it, never WHICH NAMESPACE decides — ``totally_other:X`` still yields
    ``disposition_review:X``.
    """
    explicit = request.get("compartment")
    if explicit:
        return str(explicit)
    audience = request.get("audience") or ""
    return audience.split(":", 1)[1] if ":" in audience else ""


@grouped_review.main()
async def run(ctx: WorkflowContext, request: dict) -> dict:
    """DELEGATES to the git-asserted definition (M3.2 build 3).

    This handler used to carry the grouped mechanics inline. Those mechanics are now the
    ``human_await`` step kind's OWNED behaviour in the executor, selected by the definition's
    declared ``completion.mode: grouped`` — so this workflow's PROCESS lives in
    ``policy/workflows/grouped_review.yaml`` (git-asserted, reviewed, diffable) and its
    RUNNER is the same ``_run_definition`` that runs every other definition. That is the
    whole M3.2 acceptance: the runner is definition-driven, not class-driven.

    THREE THINGS DELIBERATELY DO NOT CHANGE, because they are frozen contract surfaces:
      * the service name ``GroupedReview`` and the URLs cortex-bff calls by hand
        (``/GroupedReview/{key}/submit_decision``, ``/get_batch``);
      * ``submit_decision`` / ``get_batch`` themselves — still shared handlers reading the
        same workflow-state keys, which is why the executor writes exactly those keys;
      * this handler's RETURN SHAPE (``status``/``count``/``dispatched_keys``). The executor
        returns a step-results envelope; it is mapped back here rather than propagated, so a
        caller reading the workflow result sees no change.

    The definition is loaded from the RUNTIME registry, never from the request. A
    client-supplied process would be exactly the laundering ``_run_definition``'s stage-2
    verifier exists to prevent.
    """
    try:  # lazy — main imports THIS module at load time, so the edge must be call-time
        import main as _main  # type: ignore[no-redef]
        from workflow_definition import get_workflow_definition  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst import main as _main
        from agent_fleet.restate_analyst.workflow_definition import get_workflow_definition

    definition = get_workflow_definition("grouped_review")
    trigger = {**request, "compartment": _compartment_from_request(request)}
    envelope = await _main._run_definition(ctx, ctx.key(), definition.model_dump(), trigger)

    grouped = next(
        (r for r in envelope.get("step_results", []) if r.get("completion") == "grouped"),
        None,
    )
    if grouped is None:
        # The definition ran but no grouped step reported — the process no longer contains the
        # step this handler exists to run. Loud, because a silent {} here would read to every
        # caller as a review that completed with nothing to dispatch.
        raise restate.TerminalError(
            "grouped_review definition produced no grouped human_await result — "
            f"steps ran: {[r.get('step_id') for r in envelope.get('step_results', [])]}",
            status_code=500,
        )
    return {
        "status": grouped["status"],
        "count": grouped["count"],
        "dispatched_keys": grouped["dispatched_keys"],
    }


async def _run_inline_LEGACY(ctx: WorkflowContext, request: dict) -> dict:
    """The pre-M3.2 inline implementation, RETAINED UNWIRED as the cutover's reference.

    Not dead code and not a fallback: nothing calls it, and it must not acquire a caller.
    It is here so the drain/cutover can diff behaviour against the delegated path, and it
    retires with the sealed inline-task path (the pre-existing follow-up) rather than on its
    own schedule — the two are the same decision.
    """
    approver = request["approver"]
    audience = request.get("audience") or approver
    notice_fingerprint = request["notice_fingerprint"]
    notice_id = request.get("notice_id", "")
    doc_type = request.get("doc_type", "PCN")
    user_jwt = request.get("user_jwt", "")
    batch_items = request["batch_items"]

    # Persist the server-authored batch — submit_decision validates against THIS, not client input.
    # notice_id/doc_type are stored too so the reviewer's batch-read (get_batch) can label the notice
    # without the client re-supplying it.
    ctx.set("batch_items", batch_items)
    ctx.set("approver", approver)
    ctx.set("notice_fingerprint", notice_fingerprint)
    ctx.set("notice_id", notice_id)
    ctx.set("doc_type", doc_type)
    # Extraction-quality warnings travel with the batch so get_batch can hand them to the
    # reviewer alongside the parts they qualify (a degraded extraction's parts list may be
    # incomplete; unsaid, it reads as complete).
    ctx.set("extraction_warnings", list(request.get("extraction_warnings") or []))

    # ONE grouped HumanTask for the whole batch (1 approval resolves N). Register durably BEFORE
    # suspending, mirroring the sealed HITL mechanics.
    grouped_task = {
        # DERIVED FROM THE WORKFLOW KEY, not re-invented from the notice. This was
        # `grouped:{notice_fingerprint}:{approver}` — a SECOND independent derivation from the
        # LLM-extracted doc_id, carrying the same collision hazard as the workflow key it sits
        # beside: two documents sharing a doc_id produced one task id as well as one workflow.
        # The grouped task is 1:1 with this workflow, so its identity should COME FROM the
        # workflow rather than be computed in parallel and hope to agree. One identity, one
        # derivation, N consumers.
        "task_key": f"grouped:{ctx.key()}",
        # This workflow's OWN key — the address submit_decision is invoked on
        # (GroupedReview/{workflow_id}/submit_decision). Carried into the register body so cortex-bff's
        # /human_tasks/{id}/act can resume THIS workflow when the reviewer approves. Without it the
        # projection row's workflow_id is NULL and the approval can't reach the suspended promise.
        "workflow_id": ctx.key(),
        "audience": audience,
        "kind": "grouped_review",
        "disposition": "grouped_review",
        "title": f"Review {len(batch_items)} affected part(s) — notice {notice_id or notice_fingerprint}",
        "summary": f"{len(batch_items)} affected part(s) need a disposition review",
        "mpn": "",
        "notice_fingerprint": notice_fingerprint,
        # The INITIATOR, honest on the reviewer's own card. For a pipeline-started review this is
        # svc:review-starter (the sensor's service identity); the UI renders "(automated)" off the svc:
        # PREFIX, not a name check, so every future service identity reads correctly for free. Previously
        # omitted -> the grouped-review card shipped requested_by="" and showed no provenance at all.
        "requested_by": approver,
    }
    await ctx.run("register_grouped_task", lambda: _mint_dispatch_task(grouped_task, user_jwt))

    # Suspend until submit_decision resolves the promise with a VALIDATED decision.
    raw_decision = await ctx.promise("decision", type_hint=dict).value()
    # This batch is now SETTLED. Mark it so a SECOND submission (a teammate racing
    # in the window before the projection rows flip) is refused with the truth
    # instead of being re-validated into a hollow `accepted: true` while nothing
    # further happens — the durable promise is write-once, so the second submit
    # never woke anything, and reporting success for it is the worst of the three
    # dishonest outcomes (the reviewer walks away believing their overrides landed).
    # A deterministic BOOLEAN on purpose: WHO/WHEN provenance comes from the
    # projection (acted_by/acted_at), so no non-deterministic clock enters the
    # journaled workflow.
    ctx.set("decision_consumed", True)

    # Re-derive resolutions from the server batch + the validated decision (authority stays server-side).
    batch = _reviewbatch_from_state(approver, batch_items)
    submission = evaluate_submission(batch, raw_decision, notice_fingerprint=notice_fingerprint)
    if not submission.accepted:
        # Invariant: submit_decision only resolves accepted decisions. Reaching here is a broken
        # invariant, not a user refusal — fail terminally (release), don't park.
        raise restate.TerminalError(
            f"grouped decision failed validation after wake: {submission.reason}", status_code=400,
        )

    # Fan out INSIDE the journaled workflow context: each send is durable/retryable, each item its own
    # keyed VirtualObject invocation (per-item isolation — a poisoned item fails only itself).
    keys = fan_out_dispatch(
        ctx, submission.resolutions,
        notice_fingerprint=notice_fingerprint, notice_id=notice_id, user_jwt=user_jwt,
        requested_by=approver,   # the approver who resolved the batch is the task's requester
    )
    return {"status": "DISPATCHED", "count": len(keys), "dispatched_keys": keys}


@grouped_review.handler()
async def submit_decision(ctx: WorkflowSharedContext, request: dict) -> dict:
    """Validate a grouped decision against the server batch BEFORE waking the workflow (rider 1).

    Refused -> the review stays SUSPENDED, returns ``still_pending`` + reason, NO promise resolved,
    NO fan-out. Accepted -> resolve the promise, the workflow resumes and fans out. Treating every
    submission as approval-shaped is exactly the bug this guards: an approver clicks accept-all with
    one unverified row and the workflow would otherwise dispatch an undefined effect."""
    batch_items = await ctx.get("batch_items")
    if batch_items is None:
        raise restate.TerminalError("no active grouped review for this workflow", status_code=404)
    # ALREADY SETTLED (the multiplayer race): the batch's decision was consumed by a
    # teammate. Refuse EXPLICITLY rather than re-validate into a hollow acceptance —
    # the promise is write-once, so a second resolve wakes nothing, and returning
    # `accepted: true` for it tells a reviewer their overrides landed when they were
    # discarded. `already_resolved` is a distinct, terminal-for-this-caller outcome;
    # cortex-bff maps it to 409 and joins the projection's acted_by/acted_at so the
    # reviewer is told WHO settled it (state here stays a deterministic boolean).
    if await ctx.get("decision_consumed"):
        return {"status": "already_resolved", "accepted": False,
                "reason": "this review was already resolved by a member of its audience"}
    approver = await ctx.get("approver")
    notice_fingerprint = await ctx.get("notice_fingerprint")

    batch = _reviewbatch_from_state(approver, batch_items)
    submission = evaluate_submission(batch, request.get("decision", {}), notice_fingerprint=notice_fingerprint)
    if not submission.accepted:
        # POLICY refusal — re-pend, surface why. The promise is NOT resolved; the workflow stays put.
        return {"status": "still_pending", "accepted": False, "reason": submission.reason}

    await ctx.promise("decision", type_hint=dict).resolve(request.get("decision", {}))
    return {"status": "accepted", "accepted": True, "resolved_count": len(submission.resolutions)}


@grouped_review.handler()
async def get_batch(ctx: WorkflowSharedContext) -> dict:
    """Serve the reviewer THIS approver's authored batch — so the UI can show the parts + proposed
    dispositions + needs_review flags before deciding (blind accept-all can't handle a needs_review row).

    TWO-OBJECT AT BIRTH (rider): ``batch_items`` in workflow state is ALREADY the per-approver-filtered
    batch — the funnel + can_act filtering happened upstream in grouped_review, and only THIS approver's
    residue was ever authored into the workflow arg. So we return exactly that state and nothing else: no
    audit_withheld, no other-approver residue exists here to leak, so a batch-read can never become the
    existence oracle Slice 3 closed. The seal asserts the returned items are exactly the authored batch —
    'safe by construction' is a claim until observed."""
    batch_items = await ctx.get("batch_items")
    if batch_items is None:
        raise restate.TerminalError("no active grouped review for this workflow", status_code=404)
    approver = await ctx.get("approver")
    notice_fingerprint = await ctx.get("notice_fingerprint")
    notice_id = await ctx.get("notice_id")
    doc_type = await ctx.get("doc_type")
    return {
        "batch_id": f"grouped:{notice_fingerprint}:{approver}",
        "approver": approver,
        "notice_id": notice_id or notice_fingerprint,
        "notice_type": doc_type or "PCN",
        "notice_fingerprint": notice_fingerprint,
        "items": batch_items,   # exactly the authored per-approver batch — nothing else from state
        # Extraction-quality warnings QUALIFYING that batch (e.g. "PARTS MAY BE MISSING: 2/5
        # table crops failed"). Not per-approver state and not redacted content — a statement
        # about how much to trust the list the reviewer is about to disposition.
        "extraction_warnings": list(await ctx.get("extraction_warnings") or []),
    }
