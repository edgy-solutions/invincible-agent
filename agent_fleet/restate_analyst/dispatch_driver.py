"""PCN/PDN dispatch DRIVER — the durable per-item executor of a resolved disposition.

[[dispatch_plan]] produces a PURE ``DispatchPlan`` (the persona-queue task + the graph-state write as
DATA); this module EXECUTES it durably. The dispatcher is a Restate ``VirtualObject`` keyed by the
``idempotency_key`` (notice_fingerprint x mpn) — the settled idempotency substrate
(docs/plans/pcn-pdn-bulk-resolve.md §1): keyed addressing IS the per-item lock (no check-then-act
TOCTOU), Restate journals each effect, so a redelivered dispatch is a no-op and a crash mid-dispatch
RESUMES rather than halves.

Two-write convergence (§Decisions, §7) — TASK-FIRST, then graph-state:

  1. ``ctx.run("mint_task")``  -> cortex-bff ``/internal/human_tasks/register``  (the persona-queue task)
  2. ``ctx.run("write_state")`` -> engine-o ``/write_item_state``       (idempotent delete+insert)

Order is load-bearing. If one write lands and the other does not: state-without-task is
*silent-and-stuck* (a dashboard row nobody works — the silent-degradation shape the arc kills on
sight); task-without-state is *visible-and-recoverable* (someone sees the task; state re-stamps
idempotently on resume). So mint the task first.

Exactly-one is TWO mechanisms composed:
  (a) ``ctx.run`` journaling makes a crash BETWEEN the writes resume WITHOUT re-running the completed
      step (the task is not double-minted; the idempotent state write is not the concern);
  (b) a durable ``dispatched`` marker on the object makes a second WHOLE invocation to the same key a
      no-op — the dedup-on-(notice x part) the keying "should give for free," asserted not assumed.
The seal is ``tests/test_dispatch_driver.py``'s TWO-DIRECTION failure injection (kill after each write,
replay, assert EXACTLY ONE task and EXACTLY ONE state stamp).

Scope guard (§7): the driver ends at "the durable task EXISTS," NOT at the task completing.
"""
from __future__ import annotations

import os
from datetime import timedelta

import requests
import restate
from restate import ObjectContext, VirtualObject

# Kill-seal test scaffolding (env-gated, default 0 = no-op): durable pauses that make a live process
# kill land PROVABLY in a chosen window (after mint / after state), so the seal's kill is journal-
# confirmed, not assumed. Never fires in normal operation.
_SEAL_PAUSE_AFTER_MINT = float(os.getenv("PCN_SEAL_PAUSE_AFTER_MINT_S", "0"))
_SEAL_PAUSE_AFTER_STATE = float(os.getenv("PCN_SEAL_PAUSE_AFTER_STATE_S", "0"))

try:  # same lazy-import dance as the other restate_analyst cores (container flattens the dir)
    from dispatch_plan import plan_dispatch  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.dispatch_plan import plan_dispatch

# MODULE-LEVEL ON PURPOSE (2026-08-04). Bound here, not inside the register, so a test can
# monkeypatch ``dispatch_driver.mint_service_token`` — a function-local import is unpatchable, which
# would leave the sealed two-direction failure-injection tests unable to run the mint path at all.
# Testability is part of the contract: a credential seam nothing can stub is a seam nothing can seal.
try:
    from utils.service_identity import mint_service_token  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.utils.service_identity import mint_service_token

CORTEX_BFF_URL = os.getenv("CORTEX_BFF_URL", "http://iagent-cortex-bff:8090")
ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Serialization — DispatchPlan (pure dataclass) -> a JSON-native invocation body
# ---------------------------------------------------------------------------
def plan_to_payload(plan, *, requested_by: str = "", acted_by: str = "",
                    compartment: str = "") -> dict:
    """Flatten a ``DispatchPlan`` to the payload the VirtualObject consumes. Kept flat + JSON-native so
    it rides a Restate invocation body; ``None`` graph_write / human_task pass through as ``None``
    (an unresolved subject has no graph write; ``archive`` has no task).

    NO CREDENTIAL RIDES THIS PAYLOAD (2026-08-04). It used to carry ``user_jwt``. A Restate invocation
    body is JOURNALED and DURABLE, so a token in it is a credential at rest with the journal's
    retention, and — because this object retries — one that can be replayed long after it expired.
    The register now mints at use under the pipeline's own identity, so the field had become dead
    weight AND a standing exposure. Provenance still travels: ``requested_by`` names the human who
    approved. See ``docs/plans/2026-08-04-notice-a-dispatch-failure.md``.

    ``compartment`` is DATA, not a credential, and it rides for one reason: if this dispatch dies
    terminally after a human approved it, the effect-failure has to be ROUTED, and
    ``dispatch_failure:<compartment>`` is the audience that owns it. Carrying it here keeps the
    driver from having to parse a compartment out of an authz key at the moment it is handling a
    failure — deriving identity by string-splitting is how a clean diff denies everyone."""
    gw = plan.graph_write
    ht = plan.human_task
    return {
        "idempotency_key": plan.resolution.idempotency_key,
        "compartment": compartment,
        # TOP-LEVEL TOO, not only inside human_task. An ``archive`` disposition has NO human_task
        # (acknowledge-only, state write alone), so a terminal failure on its graph write would
        # otherwise file an effect-failure row that cannot say whose decision failed to take
        # effect — "(unrecorded)" on the one field an operator most needs.
        "requested_by": requested_by,
        # THE DECIDING HUMAN, carried as its own fact (2026-08-05). Distinct from ``requested_by``
        # (who STARTED the review — a service, in the canonical flow) and never merged into it.
        "acted_by": acted_by,
        "graph_write": None if gw is None else {
            "subject_iri": gw.subject_iri,
            "disposition_state": gw.triples.get("dispositionState", ""),
            "disposition_ref": gw.triples.get("dispositionRef", ""),
            "proposed_by_ruleset": gw.triples.get("proposedByRuleset", ""),
        },
        "human_task": None if ht is None else {
            "task_key": ht.task_key,
            "kind": ht.kind,
            "audience": ht.audience,
            "disposition": ht.disposition,
            "subject_ref": ht.subject_ref,
            "mpn": ht.mpn,
            "notice_fingerprint": ht.notice_fingerprint,
            "title": ht.title,
            "summary": ht.summary,
            "needs_review": ht.needs_review,
            "proposed_by_ruleset": ht.proposed_by_ruleset,
            "subject_unresolved": ht.subject_unresolved,
            # WHO REQUESTED THE WORK (the review's initiator). cortex-bff REQUIRES it — a 422
            # without it. Its meaning is unchanged; see the note on the payload-level twin.
            "requested_by": requested_by,
            "acted_by": acted_by,           # the human who APPROVED — a different fact, its own field
        },
    }


# ---------------------------------------------------------------------------
# The two write executors — sync (run inside ctx.run), suspend-vs-fail discipline
# ---------------------------------------------------------------------------
def _fail_terminal_on_4xx(resp, what: str) -> None:
    """Suspend-vs-fail classifier for a write, generalized past 401/403: ANY 4xx (except 429) is a
    POISONED payload — the request is malformed/unprocessable/denied and will NOT heal on retry, so it
    is TERMINAL (release the item's keyed object), never a retry-and-park DoS. 429 (rate limit) and
    5xx/network are transient and stay RETRYABLE (handled by the caller's raise_for_status). Written
    after a live 422 (missing requested_by) proved a non-401/403 4xx would otherwise park —
    [[feedback_hitl_suspend_vs_fail_ruling]] / the fan-out isolation seal's poisoned-item discipline."""
    if 400 <= resp.status_code < 500 and resp.status_code != 429:
        raise restate.TerminalError(
            f"{what} rejected ({resp.status_code}) — malformed/unprocessable, won't heal on retry; "
            f"failing TERMINALLY (release), not retry-park",
            status_code=resp.status_code,
        )


def _mint_dispatch_task(task: dict) -> dict:
    """TASK-FIRST executor: register the per-item HumanTask on the disposition's persona queue — the
    "another persona's queue" moment. Same cortex-bff endpoint + SUSPEND-VS-FAIL discipline as
    [[feedback_hitl_suspend_vs_fail_ruling]] / main's ``_register_human_task``: a persistent auth
    DENIAL (401/403) is a FAILURE (``TerminalError``, releases state), never a retry-and-park DoS;
    5xx/network stay retryable. ``task_key`` (notice x part) + the RE-LINK provenance (mpn,
    notice_fingerprint, subject_unresolved) ride in the body so an unresolved-subject task is never an
    orphan — a later pass can stamp state retroactively when the subject becomes resolvable.

    MINTS AT USE (2026-08-04). This used to take a ``user_jwt`` captured when the review STARTED and
    carried in Restate workflow state. A grouped review is DESIGNED to suspend for human latency, so
    that token is ROUTINELY expired by approval time — notice ``M32-A-WITNESS`` sat ~90 minutes and
    both dispatches died on ``401 -> fail-and-release`` 160ms after the approval, leaving the
    projection reading ``approved`` with no effects
    (``docs/plans/2026-08-04-notice-a-dispatch-failure.md``).

    The token is now minted HERE, per call, under the pipeline's own identity. Why per-call and not
    threaded from the fan-out: an ``object_send`` payload is JOURNALED, so a threaded token would be a
    credential at rest in the journal — and this VirtualObject RETRIES, so a threaded token can be
    stale on an attempt that lands minutes later. That is the same defect in miniature. Fresh per
    attempt is the only shape with no staleness window.

    PROVENANCE IS UNAFFECTED and does not travel in the token: ``requested_by`` (the human who
    approved) rides in the body below. The token authorizes the EFFECT; the body records WHO decided.
    Conflating those two facts in one credential is what broke."""
    audience = task.get("audience")
    if not audience:
        # CONFIG error, not transient — a task with no audience can never be actioned. Fail TERMINALLY.
        raise restate.TerminalError(
            f"pcn dispatch task {task.get('task_key')!r} has no audience — cannot register a HumanTask",
            status_code=400,
        )
    body = {
        "kind": task.get("kind", "pcn_disposition"),
        "task_id": task["task_key"],
        "task_key": task["task_key"],          # notice x part — lets cortex-bff dedup a redelivery too
        # The durable workflow this task belongs to. For a grouped-review task this is the
        # GroupedReview KEY, so cortex-bff's /human_tasks/{id}/act can address
        # GroupedReview/{workflow_id}/submit_decision when the reviewer approves — without it the
        # projection row has workflow_id NULL and the approval has nothing to resume (the review would
        # suspend forever). Dispatch tasks are terminal and carry None (harmless; the field is optional).
        "workflow_id": task.get("workflow_id"),
        "audience": audience,
        "title": task.get("title") or f"{task.get('disposition')}: {task.get('mpn')}",
        "summary": task.get("summary") or "",
        "subject_ref": task.get("subject_ref"),
        "disposition": task.get("disposition"),
        # cortex-bff register REQUIRES requested_by (422 without it) — the principal who caused the task
        # (the approver who resolved the grouped review). Found live: the register contract, not
        # inferable from the driver alone.
        "requested_by": task.get("requested_by") or "",
        "needs_review": task.get("needs_review", False),
        "proposed_by_ruleset": task.get("proposed_by_ruleset"),
        # RE-LINK provenance (rider): unresolved subject -> no graph write, but the task carries enough
        # to re-resolve and stamp state later. Without these, unresolved tasks are permanent orphans.
        "mpn": task.get("mpn"),
        "notice_fingerprint": task.get("notice_fingerprint"),
        "subject_unresolved": task.get("subject_unresolved", False),
        # THE APPROVING HUMAN, on the ROW, at last (2026-08-05). Ordinary dispatch rows carried the
        # same misattribution the effect-failure row did — `requested_by: svc:review-starter` — so
        # this lands here too, not only on the triage path.
        #
        # NAMED `approved_by`, NOT `acted_by`, AND THE DIFFERENCE IS LOAD-BEARING. The projection
        # already HAS an `acted_by` column, and it means "who resolved THIS row" — which for a
        # freshly-registered dispatch task must stay NULL until its assignee acts. Writing the
        # upstream approver under that name would put two different meanings behind one identifier,
        # the exact hazard this repo already documents for the `pcn_disposition` kind-vs-audience
        # collision. So: `payload.approved_by` = who approved the UPSTREAM review; the row's own
        # `acted_by` column = who resolved THIS task. Neither can be mistaken for the other.
        #
        # Rides in `payload` (a pass-through jsonb) rather than as a new column: additive, no
        # migration, and nothing existing changes shape.
        "payload": {"approved_by": task.get("acted_by") or ""},
    }
    # MINT AT USE — fresh service-identity token, never a stored one. A ServiceTokenError propagates
    # (retryable): a Keycloak blip is transient INFRA, not an authorization denial, so it must NOT
    # fail-and-release the way a 401 on the register does.
    headers = {"Authorization": f"Bearer {mint_service_token()}"}
    resp = requests.post(
        f"{CORTEX_BFF_URL}/internal/human_tasks/register",
        json=body, headers=headers, timeout=_HTTP_TIMEOUT,
    )
    if resp.status_code in (401, 403):
        raise restate.TerminalError(
            f"access denied ({resp.status_code}) registering pcn dispatch task {task['task_key']!r} "
            f"(audience {audience!r}) -> {CORTEX_BFF_URL}; failing (state released)",
            status_code=403,
        )
    _fail_terminal_on_4xx(resp, f"cortex-bff register of pcn dispatch task {task['task_key']!r}")
    resp.raise_for_status()  # 5xx / 429 / network stay RETRYABLE (transient, SHOULD retry)
    return resp.json()


def _write_disposition_state(gw: dict) -> dict:
    """STATE-SECOND executor: stamp disposition state onto the item's node via engine-o's IDEMPOTENT
    (delete-then-insert) ``/write_item_state``, so a re-stamp on resume never duplicates.
    Called only when the subject resolved (an unresolved subject has no ``graph_write`` — the task
    carries the re-link provenance instead). A 400 (malformed IRI) is TERMINAL, not retry-and-park."""
    body = {
        "subject_iri": gw["subject_iri"],
        "disposition_state": gw["disposition_state"],
        "disposition_ref": gw["disposition_ref"],
        "proposed_by_ruleset": gw.get("proposed_by_ruleset", ""),
    }
    resp = requests.post(
        f"{ENGINE_O_URL}/write_item_state", json=body, timeout=_HTTP_TIMEOUT,
    )
    _fail_terminal_on_4xx(resp, f"engine-o disposition-state write for {gw['subject_iri']!r}")
    resp.raise_for_status()  # 5xx / 429 / network stay RETRYABLE (transient, should retry)
    return resp.json()


# ---------------------------------------------------------------------------
# EFFECT-FAILURE SURFACING — "approved, but the effects died" is a refusal one stage later
# ---------------------------------------------------------------------------
# WHICH AUDIENCE OWNS AN EFFECT-FAILURE — ruled, not improvised (evening packet, addition 1).
# `dispatch_failure:<compartment>` is an OPERATOR audience, deliberately NOT the reviewer's. The
# workflow-1 dispatch-gate ruling put effect execution under the pipeline's own identity: the
# reviewer's job ends at the DECISION. Routing an infrastructure failure back to the person who
# made the decision (option (a)) hands alice a 401 she cannot fix; routing it to the approver
# personally (option (c)) invents per-user routing no audience uses today.
#
# DIVERGENCE FROM ITS SIBLINGS, DELIBERATE AND WRITTEN DOWN BEFORE DEVIATING. The other dispatch
# queues are compartment-FLAT (`qualification`, `procurement`, `sourcing`). This one is
# compartment-SCOPED because existence-of-a-task is need-to-know (the same existence-oracle
# argument policy/task_grants.yaml makes at the top), and an effect-failure row names a notice.
# Flat would also mean one operator set for every compartment at work-deploy — and widening it
# later is a rename on a live-synced identity surface, i.e. expand/contract, i.e. expensive. The
# siblings being flat is their unresolved question, not a precedent to copy.
_DISPATCH_FAILURE_AUDIENCE = "dispatch_failure:{compartment}"

# Shown when a review was resolved BEFORE the actor was carried through the decision payload — an
# in-flight review at the 2026-08-05 deploy, and nothing else. Says WHY it is absent rather than
# leaving a blank an operator would read as "nobody", because a missing value that explains itself
# is actionable and one that does not is a second mystery.
_NO_ACTOR = "(unrecorded — review resolved before the actor was carried)"


def _file_dispatch_failure_triage(*, idempotency_key: str, compartment: str, task: dict,
                                  cause: str, requested_by: str = "", acted_by: str = "") -> dict:
    """Mint a triage row for a dispatch that died TERMINALLY after a human already approved it.

    THE LIE THIS ENDS. Before this existed, a grouped review could read ``approved`` while its
    effects died 160ms later and NOTHING ANYWHERE DISAGREED — the human believes the decision
    executed, the projection agrees, and the only dissent is a ``TerminalError`` in a Restate
    journal nobody reads. Notice A produced exactly that state for an hour.

    EMIT, DO NOT ONLY DETECT. The ``extraction_refusal`` shape already proves how an unprocessable
    input reaches the people who own it; "approved but effects failed" is the same shape one stage
    later, so it reuses the same route (``/triage_tasks``) rather than inventing a channel.

    EVERY FAILURE HERE RAISES, and raises TERMINALLY — the same load-bearing decision as the
    sensor's ``file_triage_task``. This call is the only thing standing between a dead effect and
    invisibility, so a routing failure must be LOUDER than the failure it reports, never quieter.
    Terminal rather than retryable because both plausible routing failures are deployment gaps that
    do not heal on retry (403 = the pipeline lacks ``can_invoke(mesh:fileTriageTask)``; 422 = the
    audience has zero entitled actors), and a retry loop on top of an already-terminal dispatch is
    the retry-park DoS the suspend-vs-fail ruling forbids. The compound message names BOTH facts,
    so whoever reads it learns the effect died AND that the report could not be delivered.
    """
    if not compartment:
        # FAIL TO NONE AND ATTEST, never route to a broken key. `dispatch_failure:` with an empty
        # tail matches no Topaz relation, so emitting it anyway would file a row that reaches
        # nobody — an invisible report of an invisible failure, which is strictly worse than a
        # loud refusal. An optimistic default here would be dishonest.
        raise restate.TerminalError(
            f"dispatch {idempotency_key!r} failed terminally ({cause}) AND the effect-failure could "
            f"not be routed: no compartment on the payload, so the audience would be "
            f"{_DISPATCH_FAILURE_AUDIENCE.format(compartment='')!r}, which grants nobody. "
            f"An approval is now settled with no effects and no triage row.",
            status_code=500,
        )
    audience = _DISPATCH_FAILURE_AUDIENCE.format(compartment=compartment)
    mpn = task.get("mpn") or ""
    # The task's own field first (it is the one the register used), then the payload-level fallback
    # that covers the no-task dispositions.
    #
    # WHAT THIS VALUE ACTUALLY IS, and why the row no longer calls it "approved by" (found live
    # 2026-08-05, EFFECTFAIL02). It is the workflow's ``approver``, which start_review stamps from
    # WHOEVER STARTED THE REVIEW — and in the canonical flow that is the sensor's service identity,
    # not a human. The live row read "Approved by: svc:review-starter" while the grouped review's
    # ``acted_by`` said ``alice@example.com``. So the field is not missing, it is MISATTRIBUTING:
    # a false statement on the one field an effect-failure row exists to carry.
    #
    # RESOLVED 2026-08-05 (same night, ruled): the actor now travels from ``/act`` through the
    # decision payload into the fan-out as DATA, so the row can finally name the approving human
    # DIRECTLY instead of pointing at where to look. Both facts are kept, in separate fields,
    # because they answer different questions and merging them is what produced the lie.
    started_by = task.get("requested_by") or requested_by or ""
    approved_by = task.get("acted_by") or acted_by or ""
    body = {
        # Identity from the DISPATCH's own idempotency key (notice x part), so a redelivery that
        # fails again files the SAME row rather than a second one — /triage_tasks is idempotent on
        # task_id and answers ALREADY_FILED. Identity from the artifact, never model-derived.
        "task_id": f"dispatch-failure:{idempotency_key}",
        "audience": audience,
        "domain": compartment,
        "reason_code": "DISPATCH_FAILED_AFTER_APPROVAL",
        "subject_ref": task.get("subject_ref") or mpn or idempotency_key,
        "title": f"Dispatch failed after approval — {mpn or idempotency_key}",
        "summary": (
            f"A human approved this disposition and the dispatch then failed terminally, so the "
            f"decision is recorded as settled but its effects never landed. "
            f"Part: {mpn or '(unknown)'}. Queue: {task.get('audience') or '(none)'}. "
            f"Disposition: {task.get('disposition') or '(none)'}. "
            f"Approved by: {approved_by or _NO_ACTOR}. "
            f"Review started by: {started_by or '(unrecorded)'}. "
            f"Cause: {cause}"
        ),
        "payload": {
            "idempotency_key": idempotency_key,
            "notice_fingerprint": task.get("notice_fingerprint") or "",
            "mpn": mpn,
            "disposition": task.get("disposition") or "",
            "target_audience": task.get("audience") or "",
            # PROVENANCE, kept separate from authorization on purpose — conflating "who decided"
            # with "what authorized the effect" in one value is what caused notice A. NAMED FOR
            # WHAT IT IS: the review's INITIATOR (a service, in the canonical sensor-driven flow),
            # NOT the approver. See the comment above ``started_by``.
            "review_started_by": started_by,
            # The DECIDING human. Named `approved_by` rather than `acted_by` on purpose — the
            # projection's own `acted_by` column means "who resolved THIS row" (i.e. the operator
            # who works this triage task), and one identifier must not carry two meanings.
            "approved_by": approved_by,
            "cause": cause,
        },
    }
    try:
        resp = requests.post(
            f"{CORTEX_BFF_URL}/triage_tasks", json=body,
            headers={"Authorization": f"Bearer {mint_service_token()}"},
            timeout=_HTTP_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — unreachable reporter is a LOUDER failure, never silent
        raise restate.TerminalError(
            f"dispatch {idempotency_key!r} failed terminally ({cause}) AND the effect-failure could "
            f"not be routed: {CORTEX_BFF_URL}/triage_tasks unreachable ({exc}). An approval is now "
            f"settled with no effects and no triage row.",
            status_code=500,
        ) from exc
    if resp.status_code != 200:
        raise restate.TerminalError(
            f"dispatch {idempotency_key!r} failed terminally ({cause}) AND the effect-failure could "
            f"not be routed: /triage_tasks answered {resp.status_code} for audience {audience!r} "
            f"({resp.text[:200]}). A 403 means the pipeline lacks can_invoke(mesh:fileTriageTask); "
            f"a 422 means that audience has zero entitled actors. An approval is now settled with "
            f"no effects and no triage row.",
            status_code=500,
        )
    return resp.json()


# ---------------------------------------------------------------------------
# The dispatcher — one VirtualObject per item, keyed by idempotency_key
# ---------------------------------------------------------------------------
dispatch_item = VirtualObject("DispatchItem")


@dispatch_item.handler()
async def dispatch(ctx: ObjectContext, request: dict) -> dict:
    """Execute ONE item's dispatch durably (keyed by ``idempotency_key`` = notice x part).

    TASK-FIRST then graph-state — two journaled ``ctx.run`` steps, so a crash BETWEEN them resumes
    without re-running the completed step. A durable ``dispatched`` marker makes a second WHOLE
    invocation to this key a no-op (exactly-one). ``archive`` -> no task (state only); an unresolved
    subject -> task only (no state to stamp), carrying the re-link provenance.
    """
    key = ctx.key()

    # DEDUP across invocations: a redelivered/duplicate dispatch to this key returns the prior outcome
    # unchanged — the dedup-on-(notice x part) the VirtualObject keying gives, made explicit not assumed.
    prior = await ctx.get("dispatched")
    if prior:
        return prior

    task = request.get("human_task")
    gw = request.get("graph_write")
    outcome = {
        "idempotency_key": key,
        "task_minted": False,
        "state_written": False,
        "subject_unresolved": bool(task and task.get("subject_unresolved")),
    }

    # A TERMINAL failure of either write means this dispatch will NEVER happen — and the human has
    # ALREADY approved. So the failure is surfaced to the operators who own execution before it is
    # re-raised. Only TerminalError is caught: a retryable failure has not given up yet, and filing
    # a triage row for a blip Restate is about to retry successfully would cry wolf.
    try:
        # 1) TASK FIRST — visible-and-recoverable if the second write never lands.
        if task:
            minted = await ctx.run("mint_task", lambda t=task: _mint_dispatch_task(t))
            outcome["task_minted"] = True
            outcome["task"] = minted

        # KILL-SEAL WINDOW A (env-gated, default 0 -> no-op): a DURABLE pause between the two writes, so a
        # process kill during it lands PROVABLY after mint and before state — the Restate journal then shows
        # mint_task completed + this sleep pending at kill. Test scaffolding for the live two-direction
        # failure-injection seal; never fires in normal operation. See docs/plans/pcn-kill-seal-run-card.md.
        if _SEAL_PAUSE_AFTER_MINT:
            await ctx.sleep(timedelta(seconds=_SEAL_PAUSE_AFTER_MINT))

        # 2) STATE SECOND — idempotent (delete-then-insert); skipped honestly for an unresolved subject.
        if gw:
            written = await ctx.run("write_state", lambda g=gw: _write_disposition_state(g))
            outcome["state_written"] = True
            outcome["state"] = written
    except restate.TerminalError as exc:
        # JOURNALED, so a replay does not re-file (and /triage_tasks is idempotent on task_id as the
        # second line of defence — belt and braces, because this row is the ONLY dissent from a
        # projection that reads "approved").
        await ctx.run(
            "file_dispatch_failure_triage",
            lambda: _file_dispatch_failure_triage(
                idempotency_key=key, compartment=request.get("compartment") or "",
                task=task or {}, cause=str(exc),
                requested_by=request.get("requested_by") or "",
                acted_by=request.get("acted_by") or "",
            ),
        )
        # RE-RAISE, ALWAYS. Surfacing the failure must never CONVERT it into a success: Restate still
        # records a failed invocation, the item's keyed object is still released, and — critically —
        # the `dispatched` marker below is NOT reached, so a later redelivery is free to try again
        # rather than no-opping on a dispatch that never happened.
        raise

    # KILL-SEAL WINDOW B (env-gated): a durable pause between the state write and the exactly-one marker,
    # so a kill here proves resume re-runs NEITHER write (both journaled) and still sets the marker once.
    if _SEAL_PAUSE_AFTER_STATE:
        await ctx.sleep(timedelta(seconds=_SEAL_PAUSE_AFTER_STATE))

    ctx.set("dispatched", outcome)  # exactly-one marker — persists on this object's key
    return outcome


# ---------------------------------------------------------------------------
# Fan-out — one grouped approval -> N per-item dispatches (execution grain, §1)
# ---------------------------------------------------------------------------
def fan_out_dispatch(ctx, resolutions, *, notice_fingerprint: str, notice_id: str = "",
                     requested_by: str = "", acted_by: str = "",
                     compartment: str = "") -> list[str]:
    """Fan ONE grouped approval out to N per-item dispatches. Each ``ItemResolution`` is planned then
    SENT (fire-and-forget) to its own ``DispatchItem`` keyed by ``idempotency_key`` — per-item,
    idempotent, OUTSIDE the workflow graph (§7). The Restate invocation ``idempotency_key`` is that
    same key, so even a re-fan-out from a workflow replay collapses onto the same invocation. Returns
    the keys dispatched (audit)."""
    keys: list[str] = []
    for res in resolutions:
        plan = plan_dispatch(res, notice_fingerprint=notice_fingerprint, notice_id=notice_id)
        payload = plan_to_payload(plan, requested_by=requested_by, acted_by=acted_by,
                                  compartment=compartment)
        ctx.object_send(dispatch, key=res.idempotency_key, arg=payload, idempotency_key=res.idempotency_key)
        keys.append(res.idempotency_key)
    return keys
