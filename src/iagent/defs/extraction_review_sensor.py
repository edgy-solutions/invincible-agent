"""Extraction -> review sensor: the CANONICAL trigger that turns a completed
doc-tools extraction into a grouped disposition review.

The event-driven chain was symmetric until its last hop: a MinIO upload auto-fires
the doc-tools extraction, extraction auto-persists the graph — but starting the
REVIEW required a human with `curl POST /reviews`. That manual seam was construction
scaffolding (it let M1 seal each half in isolation); in production shape it's just
standing in the doorway. This sensor closes the loop with the SAME mechanism the
inbound seam uses: a sensor on an observable artifact.

Design (the three seams, per the ruling):
  * TRIGGER = a `review.json` landing under `**/generated/**` (the "extraction done"
    event). We watch MinIO, cursor-based.
  * IDEMPOTENCY = ONE review per notice. `review.json.doc_id` IS the notice fingerprint
    (engine-a keys the workflow on it), so the RunRequest `run_key` is `doc_id` -> a
    re-ingest/restart that re-emits the same notice is DEDUPED by Dagster (and again by
    the Restate workflow key). No duplicate review in the queue.
  * SUBSTRATE-GAP INVARIANT (the tripwire's contract) = `impacted_parts` is built from
    `review.json`'s `review_items`, the ONLY place per-part `needs_review` exists — NEVER
    reconstructed from the graph. So `REVIEW_STATE_UNSOURCED` stays honest by the sensor's
    OWN source choice, by construction.
  * HONEST FAILURE, ROUTED BY WHO OWNS THE ANSWER = a refusal is surfaced to the persona
    who can act on it, which is not always the operator:
      - SYSTEMIC (RULES_NOT_FOUND / RULESET_INVALID, 403 NOT_ENTITLED_TO_INITIATE, 502,
        anything unrecognized) = a statement about the DEPLOYMENT, true of every notice
        equally -> the op RAISES, the Dagster run FAILS, once, loudly, for ops.
      - PER-NOTICE CONTENT (REVIEW_STATE_UNSOURCED, NO_PARTS_EXTRACTED, NO_AFFECTED_PARTS)
        = a statement about THIS document -> a triage HumanTask to the audience that owns
        it, and the run COMPLETES. Sending these to Dagster was the bug: three notices hit
        REVIEW_STATE_UNSOURCED live and each ceased to exist for everyone whose job is
        processing notices, because the only trace was a red run in a tool the reviewer
        does not open, phrased in pipeline vocabulary. The refusal was real; the AUDIENCE
        was wrong — the invisible-dead-notice failure this sensor rejected polling to
        avoid, reintroduced through the error path. Routing failure itself RAISES, so the
        fix can never become a quieter version of the bug.
    (NO_RESIDUE = an honest non-start, logged + skipped, not a failure.)

The manual `POST /reviews` survives as the ops / re-drive path (same status as re-running
a partition) — NOT the primary trigger.

NB: no `from __future__ import annotations` here on purpose — dagster's pythonic `@op`
config inference needs `StartReviewConfig` as a real type, not a stringized annotation.
"""
import hashlib
import json
import os
import re
from typing import List, Optional, Tuple

import boto3
from botocore.config import Config as _BotoConfig
from dagster import (
    Config,
    DefaultSensorStatus,
    Failure,
    RunRequest,
    SensorEvaluationContext,
    SensorResult,
    SkipReason,
    job,
    op,
    sensor,
)

_ARTIFACT_BUCKET = os.environ.get("ARTIFACT_BUCKET", "processing-artifacts")
# We watch the sustainment inbound tree's generated outputs. Kept broad; the
# endswith("/review.json") filter is what selects the "extraction done" artifact.
_WATCH_PREFIX = os.environ.get("REVIEW_WATCH_PREFIX", "sustainment/")

_PART_FIELD = re.compile(r"parts\[(\d+)\]\.(\w+)")


# ── PURE, unit-testable core ─────────────────────────────────────────────────
def build_start_review_payload(
    review_json: dict, *, doc_type: str = "PCN", domain: str = "SUSTAINMENT",
    request_key: str = "", artifact_uri: str = "",
) -> dict:
    """Build the `/reviews` (start_review) payload from a doc-tools `review.json`.

    impacted_parts is assembled ONLY from `review_items` — the affected_mpn rows carry
    the value + the authoritative per-part `needs_review`, paired with their sibling
    replacement_mpn row. This is deliberately NOT read from the graph (which drops the
    per-part flag): it is what keeps the REVIEW_STATE_UNSOURCED tripwire honest.
    `doc_needs_review` = review.json's DOC-LEVEL `needs_review`. `notice_id` = `doc_id`.

    `request_key` is the ARTIFACT's identity (ETag + key — the same string the sensor's
    run_key is built from), forwarded so the BFF can give Restate an idempotency key. It
    makes a retry after a client timeout ATTACH to the in-flight composition instead of
    racing a second one, and it moves when the CONTENT moves — so a re-extraction correctly
    composes afresh while a retry does not. Third enforcement point of the same rule the
    run_key and the triage task_id already carry: identity from the artifact, never from
    the model-derived `doc_id`.
    """
    by_idx = {}  # type: dict
    for it in review_json.get("review_items", []) or []:
        m = _PART_FIELD.match(it.get("field_path", "") or "")
        if not m:
            continue
        i, field = int(m.group(1)), m.group(2)
        slot = by_idx.setdefault(
            i, {"affected_mpn": None, "replacement_mpn": "", "needs_review": False}
        )
        val = it.get("value") or ""
        if field == "affected_mpn":
            slot["affected_mpn"] = val
            slot["needs_review"] = bool(it.get("needs_review"))
        elif field == "replacement_mpn":
            slot["replacement_mpn"] = val
    impacted_parts = [
        by_idx[i] for i in sorted(by_idx) if by_idx[i]["affected_mpn"]
    ]
    # in_scope_mpns is REQUIRED: start_review's funnel filters out any affected part NOT in this
    # list (out-of-scope) BEFORE building residue. Omitting it filtered EVERY part -> NO_RESIDUE ->
    # the auto-fire silently reviewed nothing (caught live 2026-07-28: the sensor fired + posted, but
    # the review came back NO_RESIDUE because this field was missing; the offline shape-test and a
    # manual witness that hand-supplied in_scope_mpns both masked it). For an auto-review of a whole
    # notice, EVERY affected part is in scope — so scope = the affected MPNs themselves.
    in_scope_mpns = [p["affected_mpn"] for p in impacted_parts]
    # categories DRIVE the disposition proposer: every PCN rule requires a change
    # category, so without them the proposer returns UNCLASSIFIABLE for every part and
    # the UI shows 'needs a disposition' on ALL of them (caught live 2026-07-29 at work;
    # same class as the in_scope_mpns bug — a field the funnel needs, dropped from the
    # payload). Source order: the top-level `categories` (newer doc-tools) ELSE the
    # existing `header.categories` review_item (so the fix works on already-extracted
    # review.json with NO re-extraction). Value may be a list or a comma/;-separated
    # string; normalize to enum-name strings that match the ruleset's pcn:changeClass
    # keys ('Material','Process',…). doc_type likewise prefers the extraction's own.
    cats = review_json.get("categories")
    if not cats:
        cats = next((it.get("value") for it in (review_json.get("review_items") or [])
                     if it.get("field_path") == "header.categories"), None)
    if isinstance(cats, str):
        cats = re.split(r"[,;]", cats)
    categories = [str(c).strip() for c in (cats or []) if str(c).strip()]
    return {
        "notice_id": review_json.get("doc_id"),
        "doc_type": review_json.get("doc_type") or doc_type,
        "categories": categories,
        "impacted_parts": impacted_parts,
        "in_scope_mpns": in_scope_mpns,
        "doc_needs_review": bool(review_json.get("needs_review")),
        # ATTESTATION (not a hint): these parts and their per-part needs_review flags were read
        # STRAIGHT FROM review.json above — the extraction, where review-state is authoritative —
        # never reconstructed from the graph (which drops the per-part flag). start_review's
        # review-state tripwire hunts graph-built requests; it fires when this attestation is
        # ABSENT rather than guessing from the {doc-flagged, no-part-flagged} silhouette, which a
        # CORRECT extraction can legitimately produce (a doc-level-only reason, or zero parts).
        "review_state_source": "extraction",
        # EXTRACTION-QUALITY WARNINGS -> the reviewer. When the extraction degraded (a vision
        # crop timed out, the header pass died), the parts list may be INCOMPLETE — and a
        # partial list is indistinguishable from a complete one unless we say so. Diodes PCN
        # 2683 recorded "2/5 table crops failed — parts likely INCOMPLETE" and it reached
        # nobody, because nothing downstream carried it. Proceeding on degraded data is fine;
        # proceeding SILENTLY is not. Falls back to [] for review.json written before the
        # field existed (older extractions simply carry no warnings).
        "extraction_warnings": list(review_json.get("doc_review_reasons") or []),
        "domain": domain,
        # THE ARTIFACT'S LOCATION — `s3://bucket/key`, the ONLY thing the admission posture is
        # derived from. Distinct from `request_key` below, which is this artifact's IDENTITY
        # (`{epoch}{ETag}-{key}`) and exists for ingress idempotency.
        #
        # THEY WERE CONFLATED ONCE, and it broke every derive: the consumer read `request_key` as a
        # location and asked S3 for a key with an ETag glued to the front. Identity and location are
        # different jobs; one string cannot hold both. Pinned in tests/test_cross_repo_contracts.py
        # and tests/test_artifact_uri_contract.py — the latter builds its payload by calling THIS
        # function, because the parser that broke was written against an invented format and its
        # fixture asserted the same invention.
        "artifact_uri": artifact_uri,
        # ── ADMISSION FACTS: DELIBERATELY NOT SENT (ADR-0034 phase 1.3, consumer half) ────────
        # `format_fingerprint` and `pipeline_version` USED to ride here as caller-asserted facts.
        # They are gone on purpose: ReviewStarter now DERIVES both from the artifact that
        # `artifact_uri` points at.
        #
        # WHY REMOVING THEM IS THE FIX. A caller that can assert the trust key chooses which table
        # row the lookup hits — i.e. selects its own supervision level. `start_review` is reachable
        # as a registered mesh verb, so that was a real surface. Now a caller can lie about exactly
        # ONE thing — WHICH artifact — and the artifact determines everything else, which collapses
        # the trust question to "can the caller read that artifact".
        #
        # DO NOT RE-ADD THEM. Sending them again would not be additive: the starter would still
        # derive, and the two values would silently diverge from what routed the notice. The
        # pointer below is the whole contract. Pinned by tests/test_review_payload_passthrough.py.
        # Transport-level artifact identity for ingress idempotency (see docstring). Empty
        # for a caller that cannot name an artifact — the BFF then sends NO key rather than
        # inventing one, so the call is honestly non-idempotent instead of falsely deduped.
        "request_key": request_key,
        # The doc-tools extraction's trace id (review.json.trace_id), carried through
        # start_review so the review composition nests under the SAME Langfuse trace as
        # the extraction — one trace bucket -> extraction -> review (ADR-0038). Empty for
        # review.json written before doc-tools stamped it.
        "trace_id": review_json.get("trace_id") or "",
    }


# PER-NOTICE CONTENT refusals: statements about THIS document, which only the
# sustainment reviewer can answer ("this notice could not be prepared"). Everything else
# — RULES_NOT_FOUND, RULESET_INVALID, a missing capability grant, a 502 — is a statement
# about the DEPLOYMENT or the PIPELINE, affects every notice equally, and belongs to ops.
# The distinction was always encoded in these status codes; it just was not acted on, so
# content problems went to the one persona who cannot fix them.
_CONTENT_REFUSALS = frozenset({
    "REVIEW_STATE_UNSOURCED",
    "NO_PARTS_EXTRACTED",
    "NO_AFFECTED_PARTS",
})


def _status_of(body: dict) -> Optional[str]:
    """The engine's own status string, wherever the HTTP layer put it.

    A 200 carries it at the top level; a refusal is re-raised by the BFF as
    `HTTPException(detail=<engine body>)`, and FastAPI serializes that as
    `{"detail": {...}}`. Reading only the top level therefore sees None for EVERY
    refusal — which is fine while all refusals share one fate, and silently wrong the
    moment they don't. Routing depends on this string, so it is unwrapped explicitly.
    """
    if not isinstance(body, dict):
        return None
    if isinstance(body.get("status"), str):
        return body["status"]
    detail = body.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("status"), str):
        return detail["status"]
    return None


def classify_start_review(status_code: int, body: dict) -> Tuple[str, str]:
    """Map a `/reviews` response to a sensor outcome (PURE).

    Returns (outcome, detail), where outcome is one of:
      * "started"           — 200 STARTED
      * "no_residue_skip"   — 200 NO_RESIDUE (an honest non-start, not an error)
      * "refused_content"   — this NOTICE is unprocessable -> route to the reviewers who
                              own the answer (a triage task), and let the run COMPLETE
      * "refused_systemic"  — the deployment/pipeline is broken -> FAIL the Dagster run,
                              loudly, once, for ops

    THE SPLIT IS THE POINT. Both used to be "refused" -> failed run, so a vendor's PCN
    that failed content validation left one trace: a red run phrased in pipeline
    vocabulary, in a tool the reviewer does not open. Reserving `failed` for
    infrastructure also stops content problems from polluting the pipeline's health
    signal.

    Systemic by construction: 403 NOT_ENTITLED_TO_INITIATE (a missing capability grant —
    every notice fails the same way), RULES_NOT_FOUND / RULESET_INVALID (a deployment
    condition; fifty identical triage tasks would be worse than one loud failure), any
    5xx/transport error, and anything unrecognized. Unknown statuses route SYSTEMIC on
    purpose: filing a triage task tells a human "look at this document", which is a
    false statement when the truth is "the pipeline is broken."
    """
    status = _status_of(body)
    if status_code == 200:
        if status == "STARTED":
            return "started", f"workflow_id={body.get('workflow_id')} count={body.get('count')}"
        if status == "NO_RESIDUE":
            return "no_residue_skip", f"nothing to review: {body.get('counts')}"
        # PER-NOTICE CONTENT REFUSALS THAT ARRIVE AS 200, NOT 422. The BFF re-raises only
        # {REVIEW_STATE_UNSOURCED, RULESET_INVALID, RULES_NOT_FOUND} as 422
        # (`_PCN_REVIEW_BAD_REQUEST`); every other engine status passes through with the
        # ingress's own 200. So these two — both statements about THIS document — would
        # otherwise fall to the "unexpected 200" branch below and be reported to OPS.
        # Found by tracing reachability on the live cluster, not by the offline seal, which
        # had encoded the 422 shape for all three content codes: the wire shape was verified
        # for one and ASSUMED for the others.
        if status in _CONTENT_REFUSALS:
            return "refused_content", f"{status}: {body}"
        # The initiator deny no longer arrives as a 200 — it is a 403 NOT_ENTITLED_TO_INITIATE
        # (handled below). Any other 200 status is unexpected, and unknown routes to ops.
        return "refused_systemic", f"unexpected 200 status={status!r} body={body}"
    if status_code == 403:
        return "refused_systemic", (
            f"NOT_ENTITLED_TO_INITIATE — the auto-starter (svc:review-starter) lacks "
            f"can_invoke(mesh:startReview); grant it in capability_grants.yaml: {body}"
        )
    if status_code == 422 and status in _CONTENT_REFUSALS:
        return "refused_content", f"{status}: {body}"
    if status_code == 422:
        return "refused_systemic", f"start_review refused (ruleset/deployment): {body}"
    return "refused_systemic", f"start_review failed: HTTP {status_code} {body}"


# Human-readable renderings of the refusal codes a reviewer will actually see. The queue
# row is the ONLY thing they get, so it says what happened to their document in their
# vocabulary — not the engine's status constant.
_REFUSAL_PROSE = {
    "REVIEW_STATE_UNSOURCED": (
        "The extraction did not attest where its review flags came from, so the notice "
        "could not be prepared for review."
    ),
    "NO_PARTS_EXTRACTED": "No parts could be read out of this notice.",
    "NO_AFFECTED_PARTS": "The notice was read, but no affected parts were found in it.",
}


def _label_from_key(source_key: str) -> str:
    """A human-recognizable name for a document when the header pass produced NO doc_id.

    doc-tools writes `<dir>/generated/<filename_with_dots_as_underscores>/review.json`, so
    the document's own name is the last path segment that is neither the artifact filename
    nor the structural `generated/` marker. Walking back past those matters: the naive
    "parent directory" is `generated` for one layout and the real name for another, and a
    row titled "Notice generated could not be prepared" tells a reviewer nothing about
    which document to open — which is the entire job of this row.
    """
    parts = [p for p in source_key.split("/") if p][:-1]        # drop review.json
    while parts and parts[-1] == "generated":
        parts.pop()
    return parts[-1] if parts else (source_key or "(unnamed)")


def build_triage_payload(*, source_key: str, notice_id: Optional[str], reason_code: str,
                         detail: str, warnings: Optional[List[str]] = None,
                         domain: str = "SUSTAINMENT", audience: Optional[str] = None,
                         pages: Optional[List[dict]] = None) -> dict:
    """Build the `/triage_tasks` body for a content-refused notice (PURE).

    `task_id` is derived from the ARTIFACT KEY, which is unique by construction — NOT
    from `notice_id`, which is an LLM-extracted field that degrades to a shared fallback
    exactly when extraction is going wrong (every PDF in one inbox became "inbound",
    live 2026-07-30). Keying triage on it would collapse N dead notices into one task and
    re-create, inside the fix, the same silent loss the fix exists to end. The design note
    that first specified this said "key the task on doc_id the way the sensor keys its
    runs" — the sensor stopped keying runs that way for this reason, and the two moved
    together.

    The notice_id still travels, as DISPLAY: a human recognizes "PCN-2683", not a hash.
    """
    label = notice_id or _label_from_key(source_key)
    prose = _REFUSAL_PROSE.get(reason_code, "This notice could not be prepared for review.")
    lines = [f"Notice {label} could not be prepared for review.", prose]
    for w in warnings or []:
        lines.append(str(w))
    lines.append(f"Extraction artifact: {source_key}")
    return {
        "task_id": "triage-" + hashlib.sha1(source_key.encode()).hexdigest()[:12],
        "subject_ref": source_key,
        "title": f"Notice {label} could not be prepared for review",
        "summary": " ".join(lines),
        "reason_code": reason_code or "UNKNOWN",
        "domain": domain,
        "audience": audience,
        # Clearance-safe: identifiers and the refusal reason, never notice content.
        # PAGE RENDERS — the card's INSTRUMENT, and the reason this task needs evidence MORE
        # than a review does, not less. Alice is asked to judge whether a notice the machine
        # COULD NOT READ matters; without the pages she has strictly less to look at than for
        # a notice it read fine, which is backwards. The failed extraction still ran the
        # partition, so the renders exist — they were simply never carried.
        #
        # Clearance-safe: these are s3 URLs + page numbers, the same references the review
        # card already carries, never notice content.
        "payload": {"notice_id": notice_id, "source_key": source_key,
                    "detail": detail[:500], "warnings": list(warnings or []),
                    "pages": [{"page": p.get("page"), "s3_url": p.get("s3_url")}
                              for p in (pages or []) if p.get("s3_url")]},
    }


# ── S3 + HTTP glue (cluster-side; mocked in tests) ───────────────────────────
def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT_URL"],
        aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        region_name=os.environ.get("MINIO_REGION", "us-east-1"),
        config=_BotoConfig(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def _list_new_review_jsons(s3, bucket: str, prefix: str, since: Optional[str]) -> List[dict]:
    """New `**/review.json` objects under prefix, CHRONOLOGICALLY after the cursor.

    Returns full objects (Key + ETag + LastModified) because identity downstream is
    content-addressed, not name-addressed.

    THIS REPLACED A LEXICOGRAPHIC `StartAfter` CURSOR, which lost work twice in one day.
    `StartAfter` skips everything sorting BELOW the cursor, forever and silently: a drop
    at `.../onsemi_look/...` was invisible behind a cursor at `.../onsemi_run6/...`
    ('l' < 'r'), and `.../inbound/generated/...` was invisible behind the same cursor
    ('g' < 'o'). Sort position is not arrival order, so a lexicographic cursor cannot
    answer "what is new" — and its failure mode is silence, which is the worst available.

    Ordering by LastModified is arrival order, so a new object ANYWHERE in the keyspace
    is seen. This is the contract dag-tools' S3SensorComponent already implements
    (`dag_tools/components/s3_sensor/utils.py: get_s3_keys` — "chronological S3 keys
    using LastModified for cursor pagination"); it is adopted here VERBATIM in semantics
    so the two sensors agree. See the note in the sensor docstring on why this repo takes
    the contract rather than the component itself.
    """
    objs: List[dict] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []) or []:
            if o["Key"].endswith("/review.json") and o.get("LastModified"):
                objs.append(o)
    objs.sort(key=lambda o: (o["LastModified"], o["Key"]))
    if not since:
        return objs
    # Strictly-after the cursor timestamp. Ties are broken by key so a cursor landing
    # mid-second cannot drop its co-timestamped siblings.
    return [o for o in objs if _cursor_of(o) > since]


def _cursor_of(o: dict) -> str:
    """The cursor value for an object: its arrival time, then its key as a tiebreak.
    Sortable as a plain string, which is all Dagster's cursor storage carries."""
    return f"{o['LastModified'].isoformat()}|{o['Key']}"


def _is_current_cursor_form(cursor: str) -> bool:
    """True when `cursor` is `<iso8601>|<key>` — the form `_cursor_of` writes.

    The OLD form was a bare S3 key (lexicographic `StartAfter`). Telling them apart is the whole
    migration: they are both non-empty strings, and comparing across the two is not merely
    inaccurate, it is INCOHERENT.
    """
    head, sep, _ = (cursor or "").partition("|")
    if not sep:
        return False
    from datetime import datetime  # noqa: PLC0415 — local; this is a format probe, not a clock read
    try:
        datetime.fromisoformat(head)
    except ValueError:
        return False
    return True


class _CursorUnmigratable(Exception):
    """The stored cursor is in the old form and cannot be translated — surfaced, never swallowed."""


def _migrate_cursor(s3, bucket: str, stored: Optional[str]) -> Optional[str]:
    """Translate a PRE-MIGRATION cursor (a bare key) into the current `<iso>|<key>` form.

    WHY THIS EXISTS — a live wedge, found 2026-08-07 and dead since the cursor change landed.
    Switching from a lexicographic `StartAfter` cursor to a LastModified one changed the STORED
    VALUE'S FORMAT, and nothing migrated the value already in Dagster's cursor storage. The
    comparison `_cursor_of(o) > since` then ran an ISO timestamp against a bare S3 key:
    `"2026-08-07T…|sustainment/…" > "sustainment/inbound/zz_look/…"` is FALSE for every object,
    because `'2' < 's'`. Every review.json was filtered out, forever, and the sensor reported
    *"no new extractions (review.json) after cursor …"* — a message that is false and looks healthy.

    **The migration bug wears the costume of the bug the migration fixed.** The lexicographic cursor
    was replaced precisely because its failure mode was silent skipping; the replacement reintroduced
    silent skipping through its own changeover. A format change to a PERSISTED value is a migration
    even when no schema is involved — the same expand/contract reasoning the audience-key rename got,
    applied to a cursor.

    Translation is faithful and automatic: the old cursor named the last KEY processed, so its
    object's `LastModified` is exactly the timestamp the new cursor should carry. Nothing re-fires
    and nothing is skipped that would not have been.

    If that object is GONE it cannot be translated, and this RAISES rather than guessing. Both
    guesses are bad: treating it as no-cursor re-fires the entire corpus into humans' queues, and
    silently adopting `now` skips anything in flight. An operator setting the cursor is a declared
    intent; either guess is an accident.
    """
    cur = (stored or "").strip()
    if not cur or _is_current_cursor_form(cur):
        return cur or None
    try:
        head = s3.head_object(Bucket=bucket, Key=cur)
    except Exception as exc:  # noqa: BLE001
        raise _CursorUnmigratable(
            f"stored cursor {cur!r} is in the PRE-MIGRATION form (a bare S3 key) and the object it "
            f"names no longer exists ({type(exc).__name__}), so it cannot be translated to the "
            f"current '<iso>|<key>' form. Comparing the two forms filters out EVERY object — the "
            f"sensor is wedged, not idle. Reset the cursor in Dagster (Sensors -> "
            f"extraction_review_sensor -> Edit cursor) to '<iso8601>|<key>' at the point processing "
            f"should resume, e.g. '2026-08-07T00:00:00+00:00|'."
        ) from exc
    migrated = f"{head['LastModified'].isoformat()}|{cur}"
    print(f"CURSOR MIGRATED (pre-LastModified form): {cur!r} -> {migrated!r}", flush=True)
    return migrated


def _run_key_of(o: dict) -> str:
    """CONTENT-ADDRESSED run key: ETag (content hash) + the artifact key.

    Identity comes from what the artifact IS and where it lives — never from a value
    something else derived. The previous run_key was `doc_id`, an LLM-EXTRACTED header
    field, so when the header model degraded every notice in one inbox derived the same
    fallback and Dagster's run-key dedup silently ate all but the first. A model-derived
    value must never key deterministic machinery.

    ETag CAVEAT, declared rather than assumed: ETag is the content MD5 only for
    single-part uploads. review.json is written by a single PUT (kilobytes, far under any
    multipart threshold), so ETag is content-shaped on this path today. If a producer ever
    switches to multipart, ETag becomes UPLOAD-shaped: identical content uploaded
    differently yields a different ETag and the sensor RE-FIRES. That is degradation in
    the SAFE direction — a re-fire is absorbed by the workflow's per-notice fingerprint
    idempotency, whereas a missed fire is silent data loss. This asymmetry is why ETag is
    acceptable here and would NOT be for a skip-on-match ledger.
    """
    return f"{o.get('ETag', 'no-etag').strip(chr(34))}-{o['Key']}"


def mint_service_token(*, timeout: float = 15.0) -> str:
    """Mint a FRESH access token for the auto-starter service identity (svc:review-starter) via Keycloak
    client-credentials — per RUN, so there is no static JWT to expire (closes the user_jwt-staleness
    follow-up). The token's authz_id resolves to svc:review-starter via the client's hardcoded-claim mapper;
    the pipeline acts under its OWN entitled identity, never a borrowed human token.

    Mint is part of the OBSERVABLE seam: a failure (Keycloak down, secret rotated, client disabled) RAISES
    dagster.Failure and NAMES the cause -> the Dagster run FAILS, visible. "Keycloak was down so no reviews
    started and nothing said so" is precisely the invisible-dead-notice this pipeline was built to refuse.

    THIN WRAPPER since 2026-08-04. The mint LOGIC moved to ``agent_fleet/utils/service_identity.py`` so
    engine-a can mint at the point of use too (the notice-A defect: a token captured at review START and
    reused for the dispatch mint at APPROVAL time is stale by design across human latency — see
    ``docs/plans/archive/2026-08-04-notice-a-dispatch-failure.md``). engine-a's image does NOT ship ``src/iagent``,
    so this function was never importable there; ``agent_fleet/utils`` is the one tree BOTH runtimes carry.
    ONE implementation, two callers — never two escapers of the same meaning.

    This wrapper exists ONLY to keep the Dagster failure contract: the shared helper raises a plain
    ``ServiceTokenError`` (engine-a must not depend on Dagster) and we re-raise it as ``dagster.Failure``
    with the SAME description, so the sensor's proven test is unchanged and still discriminating."""
    try:
        from agent_fleet.utils.service_identity import ServiceTokenError, mint_service_token as _mint
    except ImportError:  # container layout that flattens agent_fleet/utils -> utils
        from utils.service_identity import ServiceTokenError, mint_service_token as _mint  # type: ignore[no-redef]

    try:
        return _mint(timeout=timeout)
    except ServiceTokenError as exc:
        raise Failure(description=str(exc))


# start_review's composition cost scales with PART COUNT — it resolves a subject, checks
# entitlement and evaluates the ruleset PER PART. 30s was sized when a notice meant a
# handful of parts; the text-layer extractor routinely yields hundreds (402 on a real
# Diodes notice), and the POST then times out client-side while the server keeps
# composing — the intermittent httpx.ReadTimeout seen in production, reproduced here.
# A timeout shorter than the work is not a safety property, it is a guaranteed failure at
# scale. Env-tunable because the right value follows the largest notice in a corpus.
_SUBMIT_TIMEOUT = float(os.getenv("REVIEW_SUBMIT_TIMEOUT", "300"))


def submit_review(payload: dict, *, bff_url: str, token: str, timeout: float = _SUBMIT_TIMEOUT,
                  source: str = ""):
    """POST the payload to cortex-bff `/reviews` (single identity-stamped entry) and
    classify. RAISES dagster.Failure on a SYSTEMIC refusal (-> failed run, for ops).
    Returns (outcome, detail, body) for started / no_residue_skip / refused_content —
    the caller routes a content refusal to the humans who own the answer.

    `source` is the review.json this payload came FROM, and it is named in every failure
    on purpose. The failure text used to carry only `notice_id` — which is DERIVED, and
    when the header pass fails it degrades to a fallback that can be identical across
    documents ("inbound" for every PDF in one inbox, live 2026-07-30). Triage then reads
    "start_review refused for inbound" N times with no way to tell WHICH notice failed.
    The s3 key is the one identifier that is unique by construction and points straight at
    the artifact you need to open."""
    import httpx

    resp = httpx.post(
        f"{bff_url.rstrip('/')}/reviews",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text[:500]}
    outcome, detail = classify_start_review(resp.status_code, body)
    if outcome == "refused_systemic":
        where = f" [source: {source}]" if source else ""
        raise Failure(
            description=(f"start_review refused for notice_id={payload.get('notice_id')!r}"
                         f"{where}: {detail}")
        )
    return outcome, detail, body


def file_triage_task(triage: dict, *, bff_url: str, token: str, timeout: float = 30.0,
                     source: str = "") -> dict:
    """POST a content refusal to cortex-bff `/triage_tasks` so it lands in the queue of
    the people who own the answer about that notice.

    EVERY failure here RAISES. That is the load-bearing decision: this call is the only
    thing standing between a refused notice and invisibility, so a routing failure must
    degrade to the OLD behaviour (a loud red Dagster run) and never to silence. A 403
    means the service lacks can_invoke(mesh:fileTriageTask); a 422 means the audience has
    zero entitled actors — both are deployment gaps that would otherwise make refusals
    vanish exactly as before, behind a green run that looks like it worked. A gate that
    quietly swallows the thing it guards is the broken-closed failure, not a safety
    property.
    """
    import httpx

    try:
        resp = httpx.post(
            f"{bff_url.rstrip('/')}/triage_tasks",
            json=triage,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        raise Failure(description=(
            f"triage routing UNREACHABLE for {source or triage.get('subject_ref')}: {exc}. "
            f"The notice was refused AND could not be routed — failing loudly so it is not lost."
        ))
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text[:500]}
    if resp.status_code != 200:
        raise Failure(description=(
            f"triage routing REFUSED (HTTP {resp.status_code}) for "
            f"{source or triage.get('subject_ref')}: {body}. The notice was refused AND could "
            f"not be routed to a human — failing loudly so it is not lost."
        ))
    return body




def _page_renders(s3, bucket: str, review_key: str) -> list:
    """Page renders for this notice — from MANIFEST.json, its SIBLING, not from review.json.

    THE BUG THIS FIXES, found before the eyeball rather than by it: the summon was wired to
    `review.json["pages"]`, and review.json HAS NO SUCH FIELD. Zero artifacts in the bucket
    carry one. The renders are written by doc-tools' document_parser into the MANIFEST
    (`pages: [{page, s3_url, basename, width, height, dpi}]`), which sits beside review.json in
    the same generated/ directory. So the card would have rendered its no-renders state for
    every notice, forever, while the tests stayed green — because they PASSED pages in
    explicitly and never asked whether the producer emits that field at all.

    That is the reachability class at the source end: I sealed the transport of a value nobody
    produces. The seal below now pins the SOURCE (manifest, not review) so the wiring cannot
    silently drift back.

    Missing/unreadable manifest -> [] , which the card renders as its honest no-renders state.
    A notice whose manifest is gone genuinely has no renders to show.
    """
    key = review_key.rsplit("/", 1)[0] + "/manifest.json"
    try:
        m = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except Exception:  # noqa: BLE001
        return []
    return [p for p in (m.get("pages") or []) if p.get("s3_url")]


# ── ADR-0034 Phase 1: a decision record for EVERY processed notice ──────────
# RETIRED 2026-08-10. `PIPELINE_VERSION` was an env var the deploy never set, read here to
# re-derive a decision the starter had already made. Both its consumers now take the starter's
# returned `admission` instead. Left as a named tombstone rather than deleted silently, because the
# next author reaching for "the pipeline version" should be sent to the artifact-derived one:
#   the version that matters is the EXTRACTOR's, stamped into review.json by doc-tools and derived
#   by ReviewStarter — never an env var on a reader.


def _format_fingerprint(review: dict, key: str = "") -> str:
    """Thin wrapper over the ONE implementation in ``agent_fleet/utils/format_fingerprint.py``.

    MOVED 2026-08-06 (ADR-0034 phase 1.3). ``ReviewStarter`` now derives this same value from the
    artifact it fetches, so there are two consumers — and two copies of an admission-key computation
    are two chances to disagree. A disagreement here is SILENT AND SAFE: fingerprints stop matching
    the table, every promoted format falls to the supervised floor, and nothing is wrong except that
    a governed decision has no effect.

    The wrapper survives so this module's existing call sites and their proven tests are UNCHANGED —
    the same shape ``extraction_review_sensor.mint_service_token`` kept when its implementation moved
    to ``utils/service_identity.py``. ``key`` is accepted and ignored, as it always was; it is
    optional now so new callers do not have to pass a value the computation never read.
    """
    # ABSOLUTE, NOT RELATIVE, and that is load-bearing: this module is loaded BY FILE PATH in
    # several suites (importlib, no package context), where a `from ..x import y` raises
    # "attempted relative import with no known parent package". The first cut used a relative
    # import and broke five previously-green tests — the module has to stay importable standalone.
    try:
        from agent_fleet.utils.format_fingerprint import format_fingerprint  # noqa: PLC0415
    except ImportError:  # pragma: no cover — repo root not on sys.path
        import sys as _sys  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415
        _root = _Path(__file__).resolve().parents[3]
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from agent_fleet.utils.format_fingerprint import format_fingerprint  # noqa: PLC0415
    return format_fingerprint(review)


def _emit_record(context, *, review: dict, key: str, request_key: str, outcome: str,
                 checks: list, ruleset_ref: str, admitted_by: str = "content",
                 warnings=None, admission: dict = None) -> None:
    """Record what was decided and WHAT IT WAS DECIDED ON. Never raises past a bug in the
    record itself: the writer fails soft on transport (an audit outage must not become a
    review outage) while a malformed record still raises, because that is an emitter bug."""
    try:
        from ..decision_record import NOT_COMPOSED, build_decision_record  # noqa: PLC0415
        from ..decision_record_writer import DECISION_RECORD_ERA, graph_writer  # noqa: PLC0415
        # THE RUNG THE ROUTING ACTUALLY READ (ADR-0034 phase 1.3), not the born-default constant.
        # Before 1.3 this was hardcoded `DEFAULT_RUNG` — honest while nothing consulted the table,
        # and a lie the moment something did. The routing decision has just become consequential,
        # so its provenance becomes row data on day ONE rather than being retrofitted after the
        # first "why did this notice go autonomous?" question.
        #
        # DERIVED FROM THE SAME PAIR THE ROUTER USES, so the record documents the decision the
        # pipeline actually made. `admitted_by` stays the caller's (`human` / `escalation`);
        # `policy` is stamped only where no human was in the loop.
        #
        # FLOOR ON ANY DOUBT: an unreadable table records `supervised`, which is both the safe
        # direction and the truth — ReviewStarter supervises on the same failure.
        # RECORD THE DECISION; DO NOT RE-MAKE IT (2026-08-10).
        #
        # This block used to call `rung_for(fingerprint, _PIPELINE_VERSION)` — a SECOND derivation
        # of a decision `start_review` had already made — using an env var the deploy never set.
        # Result: every record in the corpus said `supervised` while the starter routed `monitored`,
        # and `pipelineVersion` was the sentinel too. The audit trail answered the trust arc's
        # central question wrong, plausibly, and invisibly.
        #
        # `admission` is the starter's OWN decision, returned in its response. When it is present we
        # record it verbatim. When it is ABSENT — the NO_PARTS_EXTRACTED / NO_AFFECTED_PARTS
        # branches, which never call start_review — there IS no admission decision, and the record
        # says so with `not-admitted` rather than inventing a rung by asking the table a question
        # nobody asked it. A record that fabricates a posture for a notice that was never admitted
        # is the same lie one field over.
        _adm = admission if isinstance(admission, dict) else {}
        _fp = _adm.get("format_fingerprint") or _format_fingerprint(review, key)
        _rung = _adm.get("rung") or "not-admitted"
        # THE VERSION IS AN ARTIFACT FACT, NOT AN ADMISSION DECISION — so falling back to the
        # artifact's own stamp is reading, not re-deriving. doc-tools writes `pipeline_version` into
        # review.json; the starter DERIVES from that same stamp. Both read one producer fact, so
        # they cannot disagree the way the old env var did. (The record schema requires it — "trust
        # is keyed on it" — so a never-admitted notice still records the extractor that produced it.)
        _pipe = _adm.get("pipeline_version") or str(review.get("pipeline_version") or "")
        _tbl = _adm.get("trust_table_ref") or _trust_table_ref()
        rec = build_decision_record(
            request_key=request_key,
            source_key=key,
            notice_id=review.get("doc_id"),
            pipeline_version=_pipe,
            format_fingerprint=_fp,
            outcome=outcome,
            admitted_by=_adm.get("admitted_by") or admitted_by,
            checks=checks,
            governing={"ruleset_ref": ruleset_ref or NOT_COMPOSED,
                       "trust_table_ref": _tbl,
                       "domain": "SUSTAINMENT"},
            trust_rung=_rung,
            era=DECISION_RECORD_ERA,
            warnings=list(warnings or []),
        )
        res = graph_writer(rec)
        context.log.info(f"decision record {rec['record_id']} outcome={outcome} "
                         f"era={rec['era']} -> {res}")
    except Exception as exc:  # noqa: BLE001
        # A record must never take down the pipeline that produces it (see the writer's
        # docstring for why this is the one place the reporting path fails SOFT). Logged at
        # WARNING with the artifact named, so a hole in the corpus is findable.
        context.log.warning(f"decision record NOT emitted for {key}: {type(exc).__name__}: {exc}")


def _trust_table_ref() -> str:
    """The trust table's content hash rides into every record. Phase 1 does not yet CONSULT
    the table for routing (that is 1.3); recording its state from day one means the corpus can
    later tell records written under different admission policy apart."""
    try:
        from ..trust_table import load_trust_table  # noqa: PLC0415
        return load_trust_table().ref
    except Exception:  # noqa: BLE001
        return "trust@unavailable"


def _extraction_checks(review: dict, payload: dict) -> list:
    """The checks the pipeline ALREADY ran, recorded with their INPUTS rather than as
    verdicts. Nothing new is computed here — this is the discard-pattern cure: values the
    extraction already produced stop being thrown away."""
    from ..decision_record import make_check  # noqa: PLC0415
    stats = review.get("stats") or {}
    checks = [
        make_check("parts_extracted", verdict="ok" if payload["impacted_parts"] else "none",
                   inputs={"extracted": len(payload["impacted_parts"]),
                           "doc_flagged": bool(payload["doc_needs_review"]),
                           "text_layer_parts": stats.get("text_layer_parts"),
                           "vision_used": stats.get("vision_used")}),
        make_check("crops", verdict="degraded" if stats.get("crops_failed") else "ok",
                   inputs={"used": stats.get("n_crops_used"), "failed": stats.get("crops_failed"),
                           "missing": stats.get("crops_missing"),
                           "truncated": stats.get("crops_truncated")}),
    ]
    # Both reason fields — `doc_review_reasons` AND `review_reasons`. Two producers write
    # them under different names and the sensor historically read only the first, so the
    # cross-check findings were dropped before anyone could see them (live 2026-07-31).
    reasons = list(review.get("doc_review_reasons") or []) + list(review.get("review_reasons") or [])
    if reasons:
        checks.append(make_check("extraction_reasons", verdict="flagged",
                                 inputs={"reasons": reasons[:10], "count": len(reasons)}))
    return checks


# ── Dagster op / job / sensor ────────────────────────────────────────────────
# Where a content refusal is routed. EMPTY (the default) means the BFF's default: the
# domain's own review audience — the people already responsible for these notices. That is
# right while refusals are rare, which they should now be (the text-layer extractor removed
# the failure mode that produced most of them). SWITCH CONDITION, stated so the decision is
# revisitable rather than forgotten: if refusals become common enough to clutter the review
# queue, point this at a dedicated `triage:<compartment>` audience and grant it in
# task_grants.yaml. The routing rule — content to the owner, systemic to ops — is the
# durable part; which audience owns triage is a tuning knob.
_TRIAGE_AUDIENCE = os.getenv("REVIEW_TRIAGE_AUDIENCE", "").strip()

# OPS ESCAPE FROM A CACHED SYSTEMIC REFUSAL. The ingress idempotency key is derived from the
# ARTIFACT, which is exactly right for a retry — and wrong for the case found live
# (2026-07-31): a notice refused NOT_ENTITLED_TO_INITIATE because a capability grant was
# missing. A refusal is a COMPLETED invocation, so once the grant was fixed, re-driving the
# identical artifact ATTACHED to the stored 403 and replayed the refusal — the pipeline
# correctly refusing to redo work whose inputs had not changed, while the thing that
# actually changed was the ENVIRONMENT.
#
# The asymmetry is the point: a CONTENT refusal is fixed by re-extracting (new ETag -> new
# key -> composes afresh, automatically). A SYSTEMIC refusal is fixed OUTSIDE the artifact —
# a grant, a ruleset, a deploy — and nothing about the artifact moves, so nothing invalidates
# the key. Bumping this epoch after such a fix invalidates every cached refusal at once,
# which is precisely the ops intent ("I fixed the grant; re-drive everything").
#
# Deliberately MANUAL rather than derived from live config state: keying on a config hash
# would silently re-compose every notice on any unrelated config change — the opposite
# failure, and a far more expensive one at 173s/notice. An operator bumping a value is a
# declared intent; a hash drifting is an accident.
_REQUEST_KEY_EPOCH = (lambda e: f"{e}|" if e else "")(os.getenv("REVIEW_REQUEST_KEY_EPOCH", "").strip())


# ── AT-LEAST-ONCE DISPATCH: re-arm a REAPED run (2026-08-08) ─────────────────
# THE DEFECT THIS CLOSES. `run_key` was consumed at DISPATCH, not at COMPLETION. Dagster's dedup is
# keyed on submission, so once a RunRequest was submitted the sensor could never produce another run
# for that artifact — no matter how the run ENDED. And the cursor had already advanced past the
# object, so neither mechanism would ever re-see it. A run killed by run monitoring therefore dropped
# its notice PERMANENTLY and SILENTLY: no retry, no log, no trace. That is at-most-once intake on a
# pipeline whose entire contract is durable delivery, and it has the wedge's signature — nothing red,
# the artifact simply absent.
#
# Observed live 2026-08-07: unwedging the cursor released a 9-artifact backlog in one tick, the
# sandbox saturated (user-code gRPC health-check timeouts, cortex-bff liveness failures), and 6 of 9
# runs were reaped — "marked as failed from outside the execution context".
#
# A REAP IS NOT A FAILURE, and the distinction is the whole design. This pipeline DELIBERATELY fails
# a run on a systemic refusal (`classify_start_review` -> `refused_systemic` -> `raise Failure`): that
# is a loud red run for ops, intended, and retrying it would just re-refuse until a human fixes the
# grant or the ruleset — the `REVIEW_REQUEST_KEY_EPOCH` lever already exists for that. A REAP is the
# opposite: the execution was LOST, the pipeline never reached a verdict, and there is nothing for a
# human to act on. Re-arming everything would spam; re-arming nothing loses notices.
#
# THE DISCRIMINANT, validated against BOTH categories in real run history rather than assumed:
#   reaped            -> FAILURE with ZERO `STEP_FAILURE` events (6/6 of the runs above)
#   designed failure  -> FAILURE WITH a `STEP_FAILURE` event  (3/3 older systemic refusals)
# `raise Failure(...)` inside the op always emits STEP_FAILURE; a monitoring kill emits only
# PIPELINE_FAILURE. A probe that cannot see both categories cannot discriminate, so both were checked.
_MAX_DISPATCH_ATTEMPTS = int(os.getenv("REVIEW_MAX_DISPATCH_ATTEMPTS", "3"))
# How far back to look for re-armable runs. Bounded so the tick cost stays flat; event logs are read
# only for the FAILED runs in this window, never for all of them.
_REARM_SCAN_LIMIT = int(os.getenv("REVIEW_REARM_SCAN_LIMIT", "60"))

TAG_ARTIFACT = "review/artifact_key"
TAG_ATTEMPT = "review/attempt"


def _rearm_run_key(base: str, attempt: int) -> str:
    """Attempt 1 keeps the ORIGINAL key, so the normal path is byte-identical to before this feature.
    Later attempts get a distinct suffix, because a used run_key can never produce a second run."""
    return base if attempt <= 1 else f"{base}#a{attempt}"


def _is_reaped(instance, run) -> bool:
    """FAILED, but the step never failed — the execution was lost, not refused.

    Reading the event log is the only place this is knowable; `run.status` says FAILURE for both.
    """
    from dagster import DagsterEventType  # noqa: PLC0415

    for ev in instance.all_logs(run.run_id):
        de = getattr(ev, "dagster_event", None)
        if de is not None and de.event_type == DagsterEventType.STEP_FAILURE:
            return False
    return True


_IN_FLIGHT = frozenset({"QUEUED", "NOT_STARTED", "STARTING", "STARTED", "MANAGED", "CANCELING"})


def _rearm_requests(context) -> List[RunRequest]:
    """One more dispatch for each artifact whose ONLY attempts were reaped.

    UNTAGGED RUNS ARE INVISIBLE HERE, and that is deliberate rather than incidental. Only runs
    dispatched by the tagging code carry `review/artifact_key`, so history predating this feature can
    never be re-armed — including the six reaped runs that exposed the defect, which were prior
    sessions' unsettled witness fixtures and extraction experiments. Re-driving those would file
    experiments into humans' review queues. The tag IS the opt-in boundary, so no epoch, no cutoff
    timestamp, and no deletion of anyone else's residue is required to bound this safely.
    """
    from dagster import RunsFilter  # noqa: PLC0415

    # `context.instance` RAISES when no instance ref was provided — it does not return None — so a
    # bare `getattr(..., None)` is not a guard here. Caught 2026-08-08 by two unrelated cursor tests
    # going red: the re-arm was one attribute access away from becoming a PRECONDITION for new
    # dispatch, which is exactly the inversion this feature must never make. A retry mechanism that
    # can block first delivery is worse than the gap it fills. The access is inside the try for that
    # reason, not for tidiness.
    try:
        inst = context.instance
        runs = inst.get_runs(filters=RunsFilter(job_name="start_review_job"),
                             limit=_REARM_SCAN_LIMIT)
    except Exception as exc:  # noqa: BLE001 — re-arm must never wedge NEW dispatch
        context.log.warning(f"re-arm scan unavailable ({type(exc).__name__}: {exc}); "
                            f"new dispatch is unaffected")
        return []

    by_artifact: dict = {}
    for r in runs:
        art = (r.tags or {}).get(TAG_ARTIFACT)
        if art:
            by_artifact.setdefault(art, []).append(r)

    out: List[RunRequest] = []
    for art, group in by_artifact.items():
        statuses = {r.status.value for r in group}
        # SETTLED OR MOVING — nothing is owed. This is the LOAD-BEARING guard, and it is written as
        # one condition on purpose: an earlier version also re-checked `latest.status != FAILURE`,
        # which made this line redundant under the usual ordering and therefore un-sealable — the
        # break-on-purpose for it stayed green because the other check absorbed the mutation. A guard
        # a mutation cannot reach is decoration. Remove this and a live attempt gets re-armed
        # alongside itself every tick: a delivery guarantee turned into the outage it was meant to
        # prevent.
        if "SUCCESS" in statuses or (statuses & _IN_FLIGHT):
            continue
        # A HUMAN STOPPED IT. Cancellation is intent, and re-arming over intent is worse than the
        # gap this closes — the operator would have no way to make the pipeline stop trying.
        if "CANCELED" in statuses:
            continue
        attempts = [int((r.tags or {}).get(TAG_ATTEMPT) or 1) for r in group]
        latest = max(group, key=lambda r: int((r.tags or {}).get(TAG_ATTEMPT) or 1))
        if not _is_reaped(inst, latest):
            continue                                   # a DESIGNED failure stays failed, once, for ops
        n = max(attempts)
        if n >= _MAX_DISPATCH_ATTEMPTS:
            # GIVING UP IS AN EVENT, NOT A DEFAULT. Exhausting retries silently would rebuild the
            # exact hole this closes, one layer further in.
            context.log.error(
                f"DISPATCH EXHAUSTED for {art} after {n} attempts, all REAPED (never refused) — this "
                f"notice has NOT been reviewed and will not be retried automatically. Re-drive it via "
                f"the ops path, or raise REVIEW_MAX_DISPATCH_ATTEMPTS if the cause was load."
            )
            continue
        cfg = latest.run_config or {}
        url = (((cfg.get("ops") or {}).get("start_review_op") or {}).get("config") or {}).get(
            "review_json_url")
        if not url:
            context.log.warning(f"cannot re-arm {art}: the reaped run carries no review_json_url")
            continue
        # The run_config is taken FROM THE REAPED RUN, not rebuilt from a fresh listing: the artifact
        # may have moved or aged out of the cursor window, and the thing being retried is THAT
        # dispatch. Downstream double-composition is already prevented — the BFF's ingress
        # idempotency key is (request_key, approver) and request_key is ETag+key, so a retry ATTACHES
        # to any in-flight or completed composition instead of racing a second one.
        base = (latest.tags or {}).get("review/run_key_base") or art
        context.log.warning(
            f"RE-ARMING {art} (attempt {n + 1}/{_MAX_DISPATCH_ATTEMPTS}) — the previous run was "
            f"REAPED, not refused, so the notice was never actually reviewed")
        out.append(RunRequest(
            run_key=_rearm_run_key(base, n + 1),
            run_config={"ops": {"start_review_op": {"config": {"review_json_url": url}}}},
            tags={TAG_ARTIFACT: art, TAG_ATTEMPT: str(n + 1), "review/run_key_base": base},
        ))
    return out


class StartReviewConfig(Config):
    review_json_url: str  # s3://bucket/.../review.json
    doc_type: str = "PCN"
    domain: str = "SUSTAINMENT"   # selects both the review audience and the triage audience


@op
def start_review_op(context, config: StartReviewConfig) -> None:
    """Read the extraction's review.json, build the tripwire-safe payload, and start the
    review via cortex-bff. A refusal RAISES (failed run); NO_RESIDUE logs + skips.

    Identity: the review INITIATOR is the auto-starter service account (svc:review-starter). The op mints
    a fresh token per run via client-credentials (mint_service_token); the BFF stamps the approver from
    that token's authz_id (=svc:review-starter). The reviewer is resolved separately from the review
    audience grant, not from this token. DEPLOY REQ: svc:review-starter must hold can_invoke(mesh:startReview)
    (capability_grants.yaml) — an ungranted initiator is refused NOT_ENTITLED_TO_INITIATE (403 -> failed run).
    See docs/reference/identity-mint-contract.md + capability_grants.yaml."""
    bucket = _ARTIFACT_BUCKET
    src = config.review_json_url
    key = src[len(f"s3://{bucket}/"):] if src.startswith(f"s3://{bucket}/") else src
    s3 = _s3_client()
    obj = s3.get_object(Bucket=bucket, Key=key)
    review = json.loads(obj["Body"].read())
    # The ETag comes from the SAME read that produced `review`, so the idempotency key and
    # the composed content cannot disagree — a separate HEAD could observe a re-extraction
    # landing between the two calls and key this request to content it did not read.
    request_key = f"{_REQUEST_KEY_EPOCH}{(obj.get('ETag') or 'no-etag').strip(chr(34))}-{key}"
    # THE ARTIFACT'S LOCATION, as its own field — never `request_key`, which is its IDENTITY.
    # Full `s3://bucket/key` so the consumer never resolves a bare key against an ambient bucket
    # env var; both halves travel together and the two runtimes cannot disagree about where this
    # artifact lives. (`request_key` keeps doing exactly one job: ingress idempotency.)
    artifact_uri = f"s3://{bucket}/{key}"
    payload = build_start_review_payload(review, doc_type=config.doc_type, domain=config.domain,
                                         request_key=request_key, artifact_uri=artifact_uri)
    if not payload["notice_id"]:
        raise Failure(description=f"review.json {key} has no doc_id (notice_id)")
    bff_url = os.environ["CORTEX_BFF_URL"]
    token = mint_service_token()   # per-run client-credentials; RAISES loudly on mint failure (failed run)
    if not payload["impacted_parts"]:
        # ZERO PARTS — and the two cases are NOT the same statement, so they must not share
        # a fate. This branch used to log-and-return for both, which meant the flagship case
        # of the refusal-routing design ("The extraction did not produce any affected parts
        # (2/5 table crops failed)") could never REACH the routing built for it: the sensor
        # swallowed it here, one layer above, and the run went GREEN. Found by tracing
        # reachability on the cluster; the offline seal could not see it because it tested
        # the routing, not whether anything arrives at the routing.
        if payload["doc_needs_review"]:
            # The document ITSELF says "review me" and extraction produced nothing to review.
            # That is a document we could not prepare — exactly a per-notice content refusal,
            # and the reviewer is the only one who can act on it. Routed WITHOUT calling
            # start_review, because there is nothing to compose; the classification is
            # already certain here.
            triage = build_triage_payload(
                source_key=key, notice_id=payload.get("notice_id"),
                reason_code="NO_PARTS_EXTRACTED",
                detail="the extraction flagged this document for review and produced no "
                       "affected parts",
                warnings=payload.get("extraction_warnings"),
                domain=config.domain, audience=_TRIAGE_AUDIENCE or None,
                pages=_page_renders(s3, bucket, key),
            )
            filed = file_triage_task(triage, bff_url=bff_url, token=token, source=src)
            context.log.warning(
                f"NO_PARTS_EXTRACTED for notice={payload['notice_id']} source={src} -> routed "
                f"to {filed.get('audience')} as task {filed.get('task_id')} "
                f"({filed.get('status')}, recipients={filed.get('recipients', 'n/a')})"
            )
            _emit_record(context, review=review, key=key, request_key=request_key,
                         outcome="NO_PARTS_EXTRACTED", checks=_extraction_checks(review, payload),
                         ruleset_ref="", warnings=payload.get("extraction_warnings"))
            return
        # Not flagged AND no parts: an honest empty, the same shape as NO_RESIDUE. Filing a
        # task for every one of these would flood the queue with "nothing to do" — the
        # rubber-stamp pressure the trust work is explicitly trying to avoid.
        context.log.info(f"no impacted parts in {key} and the doc is not flagged; "
                         f"nothing to review — skipping (honest empty)")
        # A record HERE is the point of "every processed notice". This branch is the quietest
        # outcome in the pipeline — no review, no task, no failure — so without a record it is
        # the one decision that leaves no trace at all, which is exactly the audit gap.
        _emit_record(context, review=review, key=key, request_key=request_key,
                     outcome="NO_AFFECTED_PARTS", checks=_extraction_checks(review, payload),
                     ruleset_ref="", warnings=payload.get("extraction_warnings"))
        return
    # Log the source BEFORE the call: if the POST times out or the process dies, this line
    # is the only record of WHICH document the run was working on.
    context.log.info(
        f"start_review -> notice_id={payload['notice_id']!r} parts={len(payload['impacted_parts'])} "
        f"attested={payload.get('review_state_source')!r} source={src}"
    )
    outcome, detail, body = submit_review(payload, bff_url=bff_url, token=token, source=src)
    if outcome == "refused_content":
        # THIS NOTICE is unprocessable — a statement only the reviewer can answer. Route it
        # to them and let the run COMPLETE: a content problem is not a pipeline failure, and
        # recording it as one both misaddresses the message and poisons the health signal.
        # The refusal is NOT swallowed — file_triage_task raises if it cannot deliver.
        triage = build_triage_payload(
            source_key=key, notice_id=payload.get("notice_id"),
            reason_code=_status_of(body) or "", detail=detail,
            warnings=payload.get("extraction_warnings"),
            domain=config.domain, audience=_TRIAGE_AUDIENCE or None,
            pages=_page_renders(s3, bucket, key),
        )
        filed = file_triage_task(triage, bff_url=bff_url, token=token, source=src)
        _emit_record(context, review=review, key=key, request_key=request_key,
                     outcome=_status_of(body) or "REFUSED_CONTENT",
                     checks=_extraction_checks(review, payload),
                     admission=(body or {}).get("admission"),
                     ruleset_ref=(body or {}).get("ruleset_ref", ""),
                     warnings=payload.get("extraction_warnings"))
        context.log.warning(
            f"start_review refused_content ({triage['reason_code']}) for notice="
            f"{payload['notice_id']} source={src} -> routed to {filed.get('audience')} "
            f"as task {filed.get('task_id')} ({filed.get('status')}, "
            f"recipients={filed.get('recipients', 'n/a')})"
        )
        return
    context.log.info(f"start_review {outcome}: notice={payload['notice_id']} source={src} -> {body}")
    from ..decision_record import make_check as _mk  # noqa: PLC0415
    _checks = _extraction_checks(review, payload)
    _counts = (body or {}).get("counts") or {}
    if _counts:
        # The funnel's own numbers — input/residue/filtered/auto_disposed — are INPUTS, not a
        # verdict. "NO_RESIDUE" alone cannot tell a later reader whether nothing was in scope
        # or everything was auto-disposed, and those are different facts about the pipeline.
        _checks.append(_mk("residue_funnel",
                                  verdict="residue" if _counts.get("residue") else "empty",
                                  inputs=dict(_counts)))
    _emit_record(context, review=review, key=key, request_key=request_key,
                 outcome=_status_of(body) or outcome.upper(), checks=_checks,
                 admission=(body or {}).get("admission"),
                 ruleset_ref=(body or {}).get("ruleset_ref", ""),
                 warnings=payload.get("extraction_warnings"))


@job
def start_review_job():
    start_review_op()


@sensor(
    job=start_review_job,
    default_status=DefaultSensorStatus.STOPPED,   # opt-in per environment (like the inbound sensor)
    minimum_interval_seconds=30,
)
def extraction_review_sensor(context: SensorEvaluationContext):
    """Watch MinIO for completed extractions (review.json) and start one review per ARTIFACT.

    CURSOR = arrival time (LastModified), RUN_KEY = content hash + artifact key. Both are
    the contract dag-tools' S3SensorComponent already implements; this repo adopts the
    SEMANTICS rather than the component because invincible-agent does not depend on
    dag_tools and does not use the Dagster components system — taking the component would
    mean adding a cross-repo dependency AND adopting a framework here, which is an
    architectural decision, not a port. (It would also need two upstream changes: the
    component's `partition_name` is mandatory, and reviews should NOT be partitioned — a
    backfill would mint duplicate reviews into humans' queues — and its default
    `filter_patterns` EXCLUDES "/generated/", which is exactly where review.json lives, so
    an unmodified adoption would silently match nothing.) If that dependency is later
    taken, this function is the thing deleted, and the seal below carries over unchanged.

    WHY THE IDENTITY CHANGED. run_key was `doc_id` — an LLM-EXTRACTED header field. When
    the header model degraded, every notice in one inbox derived the same fallback
    ("inbound"), and Dagster's run-key dedup silently discarded all but the first: no run,
    no failure, no log line. A model-derived value must never key deterministic machinery.
    `doc_id` is now what it should always have been — display/grouping metadata carried in
    the payload — while identity comes from the artifact itself.
    """
    s3 = _s3_client()
    # A STORED CURSOR IN THE OLD FORM IS NOT "no new work" — it is an incoherent comparison, and it
    # must never be reported as an idle sensor. See `_migrate_cursor`: the format changed under a
    # persisted value and the mismatch filtered out every object while the skip message read healthy.
    try:
        since = _migrate_cursor(s3, _ARTIFACT_BUCKET, context.cursor)
    except _CursorUnmigratable as exc:
        # LOUD, and distinct from the idle skip below. Raising every 30s would drown the daemon log;
        # a skip whose reason NAMES the wedge and the operator action is the honest middle — the
        # failure this whole guard exists to prevent was a skip reason that lied.
        context.log.error(str(exc))
        return SkipReason(f"CURSOR WEDGED — not idle: {exc}")
    # RE-ARM BEFORE THE EMPTY CHECK. A reaped run is work the pipeline OWES, and it is owed whether
    # or not a new artifact happened to land this tick — gating retries behind new arrivals would
    # make delivery depend on unrelated traffic, which is the same "silent unless something else
    # happens" shape as the wedge. Never allowed to wedge new dispatch: it fails soft to [].
    rearms = _rearm_requests(context)
    objs = _list_new_review_jsons(s3, _ARTIFACT_BUCKET, _WATCH_PREFIX, since)
    if not objs:
        if rearms:
            return SensorResult(run_requests=rearms)
        return SkipReason(f"no new extractions (review.json) after cursor {since}")
    requests = list(rearms)
    last = since
    for o in objs:
        key = o["Key"]
        try:
            review = json.loads(s3.get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"].read())
        except Exception as exc:  # noqa: BLE001 — a malformed artifact shouldn't wedge the cursor
            context.log.warning(f"skip unreadable {key}: {exc}")
            last = _cursor_of(o)
            continue
        notice_id = review.get("doc_id")
        if not notice_id:
            context.log.warning(f"skip {key}: review.json carries no doc_id")
            last = _cursor_of(o)
            continue
        requests.append(
            RunRequest(
                # Content-addressed: re-uploading identical content dedups; two DIFFERENT
                # notices can no longer collide, however their doc_ids were derived.
                run_key=_run_key_of(o),
                run_config={
                    "ops": {"start_review_op": {"config": {
                        "review_json_url": f"s3://{_ARTIFACT_BUCKET}/{key}",
                    }}}
                },
                # THE TAGS ARE THE DELIVERY LEDGER. `run_key` alone cannot answer "was this artifact
                # ever actually reviewed?" — it is consumed at dispatch and says nothing about how the
                # run ended. These carry the artifact identity and the attempt number into the run
                # record, which is the only durable place a later tick can read them from. They also
                # BOUND the re-arm: history without them is invisible to it (see `_rearm_requests`).
                tags={TAG_ARTIFACT: key, TAG_ATTEMPT: "1",
                      "review/run_key_base": _run_key_of(o)},
            )
        )
        # Advance only past objects we actually DISPATCHED or deliberately skipped, in
        # arrival order — so a mid-tick failure re-sees the rest next tick instead of
        # stepping over them.
        last = _cursor_of(o)
    context.update_cursor(last or "")
    return SensorResult(run_requests=requests)
