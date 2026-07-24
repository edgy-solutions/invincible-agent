"""PCN/PDN dispatch DRIVER — the durable per-item executor of a resolved disposition.

[[pcn_dispatch]] produces a PURE ``DispatchPlan`` (the persona-queue task + the graph-state write as
DATA); this module EXECUTES it durably. The dispatcher is a Restate ``VirtualObject`` keyed by the
``idempotency_key`` (notice_fingerprint x mpn) — the settled idempotency substrate
(docs/plans/pcn-pdn-bulk-resolve.md §1): keyed addressing IS the per-item lock (no check-then-act
TOCTOU), Restate journals each effect, so a redelivered dispatch is a no-op and a crash mid-dispatch
RESUMES rather than halves.

Two-write convergence (§Decisions, §7) — TASK-FIRST, then graph-state:

  1. ``ctx.run("mint_task")``  -> cortex-bff ``/internal/human_tasks/register``  (the persona-queue task)
  2. ``ctx.run("write_state")`` -> engine-o ``/write_pcn_disposition_state``       (idempotent delete+insert)

Order is load-bearing. If one write lands and the other does not: state-without-task is
*silent-and-stuck* (a dashboard row nobody works — the silent-degradation shape the arc kills on
sight); task-without-state is *visible-and-recoverable* (someone sees the task; state re-stamps
idempotently on resume). So mint the task first.

Exactly-one is TWO mechanisms composed:
  (a) ``ctx.run`` journaling makes a crash BETWEEN the writes resume WITHOUT re-running the completed
      step (the task is not double-minted; the idempotent state write is not the concern);
  (b) a durable ``dispatched`` marker on the object makes a second WHOLE invocation to the same key a
      no-op — the dedup-on-(notice x part) the keying "should give for free," asserted not assumed.
The seal is ``tests/test_pcn_driver.py``'s TWO-DIRECTION failure injection (kill after each write,
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
    from pcn_dispatch import plan_dispatch  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.pcn_dispatch import plan_dispatch

CORTEX_BFF_URL = os.getenv("CORTEX_BFF_URL", "http://iagent-cortex-bff:8090")
ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Serialization — DispatchPlan (pure dataclass) -> a JSON-native invocation body
# ---------------------------------------------------------------------------
def plan_to_payload(plan, *, user_jwt: str = "", requested_by: str = "") -> dict:
    """Flatten a ``DispatchPlan`` to the payload the VirtualObject consumes. Kept flat + JSON-native so
    it rides a Restate invocation body; ``None`` graph_write / human_task pass through as ``None``
    (an unresolved subject has no graph write; ``archive`` has no task)."""
    gw = plan.graph_write
    ht = plan.human_task
    return {
        "idempotency_key": plan.resolution.idempotency_key,
        "user_jwt": user_jwt,
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
            "requested_by": requested_by,   # the approver who resolved the batch (cortex-bff requires it)
        },
    }


# ---------------------------------------------------------------------------
# The two write executors — sync (run inside ctx.run), suspend-vs-fail discipline
# ---------------------------------------------------------------------------
def _mint_dispatch_task(task: dict, user_jwt: str) -> dict:
    """TASK-FIRST executor: register the per-item HumanTask on the disposition's persona queue — the
    "another persona's queue" moment. Same cortex-bff endpoint + SUSPEND-VS-FAIL discipline as
    [[feedback_hitl_suspend_vs_fail_ruling]] / main's ``_register_human_task``: a persistent auth
    DENIAL (401/403) is a FAILURE (``TerminalError``, releases state), never a retry-and-park DoS;
    5xx/network stay retryable. ``task_key`` (notice x part) + the RE-LINK provenance (mpn,
    notice_fingerprint, subject_unresolved) ride in the body so an unresolved-subject task is never an
    orphan — a later pass can stamp state retroactively when the subject becomes resolvable."""
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
    }
    headers = {"Authorization": f"Bearer {user_jwt}"} if user_jwt else {}
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
    resp.raise_for_status()  # 5xx / network stay RETRYABLE (cortex-bff momentarily down SHOULD retry)
    return resp.json()


def _write_disposition_state(gw: dict) -> dict:
    """STATE-SECOND executor: stamp disposition state onto the item's node via engine-o's IDEMPOTENT
    (delete-then-insert) ``/write_pcn_disposition_state``, so a re-stamp on resume never duplicates.
    Called only when the subject resolved (an unresolved subject has no ``graph_write`` — the task
    carries the re-link provenance instead). A 400 (malformed IRI) is TERMINAL, not retry-and-park."""
    body = {
        "subject_iri": gw["subject_iri"],
        "disposition_state": gw["disposition_state"],
        "disposition_ref": gw["disposition_ref"],
        "proposed_by_ruleset": gw.get("proposed_by_ruleset", ""),
    }
    resp = requests.post(
        f"{ENGINE_O_URL}/write_pcn_disposition_state", json=body, timeout=_HTTP_TIMEOUT,
    )
    if resp.status_code == 400:
        raise restate.TerminalError(
            f"engine-o rejected disposition-state write for {gw['subject_iri']!r} (400); failing",
            status_code=400,
        )
    resp.raise_for_status()  # 5xx / network stay RETRYABLE (transient, should retry)
    return resp.json()


# ---------------------------------------------------------------------------
# The dispatcher — one VirtualObject per item, keyed by idempotency_key
# ---------------------------------------------------------------------------
pcn_dispatch_item = VirtualObject("PcnDispatchItem")


@pcn_dispatch_item.handler()
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

    user_jwt = request.get("user_jwt", "")
    task = request.get("human_task")
    gw = request.get("graph_write")
    outcome = {
        "idempotency_key": key,
        "task_minted": False,
        "state_written": False,
        "subject_unresolved": bool(task and task.get("subject_unresolved")),
    }

    # 1) TASK FIRST — visible-and-recoverable if the second write never lands.
    if task:
        minted = await ctx.run("mint_task", lambda t=task: _mint_dispatch_task(t, user_jwt))
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

    # KILL-SEAL WINDOW B (env-gated): a durable pause between the state write and the exactly-one marker,
    # so a kill here proves resume re-runs NEITHER write (both journaled) and still sets the marker once.
    if _SEAL_PAUSE_AFTER_STATE:
        await ctx.sleep(timedelta(seconds=_SEAL_PAUSE_AFTER_STATE))

    ctx.set("dispatched", outcome)  # exactly-one marker — persists on this object's key
    return outcome


# ---------------------------------------------------------------------------
# Fan-out — one grouped approval -> N per-item dispatches (execution grain, §1)
# ---------------------------------------------------------------------------
def fan_out_dispatch(ctx, resolutions, *, notice_fingerprint: str, notice_id: str = "", user_jwt: str = "", requested_by: str = "") -> list[str]:
    """Fan ONE grouped approval out to N per-item dispatches. Each ``ItemResolution`` is planned then
    SENT (fire-and-forget) to its own ``PcnDispatchItem`` keyed by ``idempotency_key`` — per-item,
    idempotent, OUTSIDE the workflow graph (§7). The Restate invocation ``idempotency_key`` is that
    same key, so even a re-fan-out from a workflow replay collapses onto the same invocation. Returns
    the keys dispatched (audit)."""
    keys: list[str] = []
    for res in resolutions:
        plan = plan_dispatch(res, notice_fingerprint=notice_fingerprint, notice_id=notice_id)
        payload = plan_to_payload(plan, user_jwt=user_jwt, requested_by=requested_by)
        ctx.object_send(dispatch, key=res.idempotency_key, arg=payload, idempotency_key=res.idempotency_key)
        keys.append(res.idempotency_key)
    return keys
