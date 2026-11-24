"""Pure derivations of the grouped review's identities: workflow key and derived request keys.

Stdlib only, so the BFF can import it without the Restate SDK. `review_starter` re-exports every
name here; a caller of `review_starter.compose_workflow_id` is unchanged.
"""
from __future__ import annotations

import hashlib
from typing import Optional


def compose_workflow_id(notice_id: str, approver: str, request_key: Optional[str] = None) -> str:
    """The grouped review's Restate workflow key. PURE, so its properties are testable.

    RESTATE WORKFLOW KEYS ARE SINGLE-USE. A key can be submitted exactly once, ever; a second
    ``workflow_send`` to the same key does nothing — and because that send is fire-and-forget,
    ``start_review`` still returns STARTED. Combine that with a key derived from ``notice_id``
    (the LLM-extracted doc_id) and two failures compound into one silent, permanent one:

      * TWO DOCUMENTS SHARING A doc_id collapse into ONE review — a real hazard, since doc_id
        degrades to a shared fallback exactly when extraction is going wrong.
      * A NOTICE WHOSE FIRST ATTEMPT DIED can never produce a review again. The key is spent,
        re-extraction cannot change it (the header pass yields the same doc_id), and every
        retry logs STARTED. Live at work 2026-07-31: eleven notices, eleven STARTED, ONE
        review — the other ten permanently unrecoverable without hand-editing doc_ids.

    So the key carries the ARTIFACT's identity (ETag + s3 key, hashed) as a discriminator —
    the same identity the sensor's run_key, the triage task_id and the ingress idempotency key
    already use. FOURTH enforcement point of one rule: identity comes from what the artifact
    IS and where it lives, never from a value a model derived.

    What each case now does:
      * same artifact re-sent      -> same key -> correctly idempotent, no duplicate review
      * RE-EXTRACTION (new bytes)  -> new key  -> a genuinely new review, which is the point:
                                      a corrected extraction must be reviewable, and today it
                                      silently is not
      * two docs, one doc_id       -> different keys -> no collision

    `notice_id` stays in the key as a HUMAN-READABLE prefix: these keys are read in Restate's
    UI and in logs during incidents, and an opaque hash would have made this very bug harder
    to see. Readability is the reason it is there — it is no longer load-bearing for identity.

    NO request_key (the hand-driven ops/re-drive path) falls back to the old shape. That path
    is then subject to the single-use constraint, exactly as before — honest rather than
    silently uniquified, and the same choice the ingress key makes when it cannot name an
    artifact.
    """
    base = f"pcn-review-{notice_id}-{approver}"
    rk = (request_key or "").strip()
    if not rk:
        return base
    return f"{base}-{hashlib.sha1(rk.encode()).hexdigest()[:10]}"


ESCALATION_MARKER = "escalated-from"


def escalation_request_key(request_key: str, refusing_invocation_id: str) -> str:
    """The request_key an ESCALATED admission carries — derived, never reused.

    THE TRAP THIS EXISTS TO AVOID, in production shape. When an autonomous run refuses (a
    `needs_review` row, a row with no disposition) the notice must reach a human, and the honest way
    is a fresh admission through the front door — same `ReviewStarter`, full provenance, real
    audience. But the BFF derives its ingress idempotency key from `(request_key, approver)`, and an
    escalation naturally carries the SAME artifact key and the SAME `svc:review-starter` as the
    autonomous admission that just refused. Restate would therefore ATTACH the escalation to the
    prior invocation and hand back the AutonomousReview's own result: the escalation silently
    swallowed, the notice dropped, nothing red.

    That is not a hypothetical — it is the leg-3 collision from the phase-1.3 witness, where two legs
    differing only in table state shared an artifact and the second returned the first's answer. It
    was caught there by a readback naming the wrong notice, not by anything going red.

    So the escalated admission mints a DERIVED identity: the original key plus a marker naming the
    refusing invocation. Same repair pattern as the dispatch re-arm's attempt suffix (`…#a2`) — a
    genuinely new admission that still POINTS BACK, so the decision record can carry the chain
    (`admitted_by: escalation`, the refusing run, the rule that refused) instead of a fresh identity
    with no history.

    Deterministic and idempotent BY CONSTRUCTION: escalating the same refusing run twice yields the
    same key, so a workflow replay re-escalates onto the same admission rather than minting a second
    review for one notice. Re-derivation is safe; that is the property Restate replay requires.
    """
    base = (request_key or "").strip()
    inv = (refusing_invocation_id or "").strip()
    if not inv:
        # An escalation that cannot name its refusing run would be indistinguishable from a fresh
        # admission — and would collide with it. Refuse rather than mint an ambiguous identity.
        raise ValueError(
            "escalation_request_key needs the REFUSING invocation id: without it the derived key "
            "collapses onto the original admission's key and the escalation is swallowed by ingress "
            "idempotency (the leg-3 collision, in production shape)."
        )
    if not base:
        # No original key (the hand-driven ops path). Still derive something distinct and traceable.
        return f"{ESCALATION_MARKER}:{inv}"
    return f"{base}|{ESCALATION_MARKER}:{inv}"


REISSUE_MARKER = "reissued-from"


def reissue_request_key(request_key: str, superseded_workflow_id: str) -> str:
    """The request_key a RE-ISSUED grouped review carries — derived, never reused.

    The original review's workflow key is single-use: once spent, re-driving the same artifact lands
    on it and does nothing. And the BFF derives its ingress idempotency key from
    `(request_key, approver)`, so a re-issue carrying the ORIGINAL key would be attached to the old
    admission and swallowed, nothing red. Same trap, same repair as `escalation_request_key`.

    So the re-issue mints a DERIVED key: the original key plus a marker naming the superseded
    workflow. That yields a new workflow key and a new task id (`grouped:<key>`) that still POINT
    BACK at what they replace. Deterministic: re-issuing the same workflow twice gives the same key.
    """
    base = (request_key or "").strip()
    old = (superseded_workflow_id or "").strip()
    if not old:
        raise ValueError(
            "reissue_request_key needs the SUPERSEDED workflow id: without it the derived key "
            "collapses onto the original admission's key and the re-issue is swallowed by ingress "
            "idempotency."
        )
    if not base:
        return f"{REISSUE_MARKER}:{old}"
    return f"{base}|{REISSUE_MARKER}:{old}"
