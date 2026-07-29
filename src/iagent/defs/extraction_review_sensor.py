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
  * HONEST FAILURE = if `start_review` REFUSES (422 tripwire/rules, or 403
    NOT_ENTITLED_TO_INITIATE — the auto-starter lacks can_invoke(mesh:startReview)), the op
    RAISES -> the Dagster run FAILS, visible to the operator. The sensor is now that operator;
    nothing swallowed. (NO_RESIDUE = an honest non-start, logged + skipped, not a failure.)

The manual `POST /reviews` survives as the ops / re-drive path (same status as re-running
a partition) — NOT the primary trigger.

NB: no `from __future__ import annotations` here on purpose — dagster's pythonic `@op`
config inference needs `StartReviewConfig` as a real type, not a stringized annotation.
"""
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
    review_json: dict, *, doc_type: str = "PCN", domain: str = "SUSTAINMENT"
) -> dict:
    """Build the `/reviews` (start_review) payload from a doc-tools `review.json`.

    impacted_parts is assembled ONLY from `review_items` — the affected_mpn rows carry
    the value + the authoritative per-part `needs_review`, paired with their sibling
    replacement_mpn row. This is deliberately NOT read from the graph (which drops the
    per-part flag): it is what keeps the REVIEW_STATE_UNSOURCED tripwire honest.
    `doc_needs_review` = review.json's DOC-LEVEL `needs_review`. `notice_id` = `doc_id`.
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
        "domain": domain,
    }


def classify_start_review(status_code: int, body: dict) -> Tuple[str, str]:
    """Map a `/reviews` response to a sensor outcome (PURE).

    Returns (outcome, detail): "started" (success), "no_residue_skip" (honest non-start —
    nothing to review, not an error), or "refused" (surface as a FAILED run).
      - 200 STARTED               -> started
      - 200 NO_RESIDUE            -> no_residue_skip
      - 403 NOT_ENTITLED_TO_INITIATE -> refused (a CONFIG gap: the auto-starter lacks
                                   can_invoke(mesh:startReview) — the loud-fail outcome for the operator)
      - 422 (REVIEW_STATE_UNSOURCED / RULESET_INVALID / RULES_NOT_FOUND) -> refused
      - anything else (502 unreachable / non-200) -> refused
    """
    status = (body or {}).get("status")
    if status_code == 200:
        if status == "STARTED":
            return "started", f"workflow_id={body.get('workflow_id')} count={body.get('count')}"
        if status == "NO_RESIDUE":
            return "no_residue_skip", f"nothing to review: {body.get('counts')}"
        # The initiator deny no longer arrives as a 200 — it is a 403 NOT_ENTITLED_TO_INITIATE
        # (handled below). Any other 200 status is unexpected.
        return "refused", f"unexpected 200 status={status!r} body={body}"
    if status_code == 403:
        return "refused", (
            f"NOT_ENTITLED_TO_INITIATE — the auto-starter (svc:review-starter) lacks "
            f"can_invoke(mesh:startReview); grant it in capability_grants.yaml: {body}"
        )
    if status_code == 422:
        return "refused", f"start_review refused (tripwire/rules): {body}"
    return "refused", f"start_review failed: HTTP {status_code} {body}"


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


def _list_new_review_jsons(s3, bucket: str, prefix: str, since_key: Optional[str]) -> List[str]:
    """New `**/review.json` keys under prefix, lexically after the cursor. Simple + cheap;
    the endswith filter selects only the extraction-done artifact."""
    keys: List[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket, "Prefix": prefix}
    if since_key:
        kwargs["StartAfter"] = since_key
    for page in paginator.paginate(**kwargs):
        for o in page.get("Contents", []) or []:
            k = o["Key"]
            if k.endswith("/review.json"):
                keys.append(k)
    return sorted(keys)


def mint_service_token(*, timeout: float = 15.0) -> str:
    """Mint a FRESH access token for the auto-starter service identity (svc:review-starter) via Keycloak
    client-credentials — per RUN, so there is no static JWT to expire (closes the user_jwt-staleness
    follow-up). The token's authz_id resolves to svc:review-starter via the client's hardcoded-claim mapper;
    the pipeline acts under its OWN entitled identity, never a borrowed human token.

    Mint is part of the OBSERVABLE seam: a failure (Keycloak down, secret rotated, client disabled) RAISES
    dagster.Failure and NAMES the cause -> the Dagster run FAILS, visible. "Keycloak was down so no reviews
    started and nothing said so" is precisely the invisible-dead-notice this pipeline was built to refuse."""
    import httpx

    realm_url = os.environ["KEYCLOAK_REALM_URL"].rstrip("/")
    client_id = os.environ["REVIEW_STARTER_CLIENT_ID"]
    client_secret = os.environ["REVIEW_STARTER_CLIENT_SECRET"]
    token_url = f"{realm_url}/protocol/openid-connect/token"
    try:
        resp = httpx.post(
            token_url,
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — transport failure is a loud, named failure, never silent
        raise Failure(description=f"mint_service_token: Keycloak token endpoint unreachable at {token_url}: {exc}")
    if resp.status_code != 200:
        raise Failure(
            description=f"mint_service_token: client-credentials mint failed HTTP {resp.status_code} for "
            f"client {client_id!r} at {token_url}: {resp.text[:300]}"
        )
    tok = (resp.json() or {}).get("access_token")
    if not tok:
        raise Failure(description=f"mint_service_token: token response carried no access_token: {resp.text[:300]}")
    return tok


def submit_review(payload: dict, *, bff_url: str, token: str, timeout: float = 30.0):
    """POST the payload to cortex-bff `/reviews` (single identity-stamped entry) and
    classify. RAISES dagster.Failure on a refusal (-> failed run). Returns (outcome, body)
    for started / no_residue_skip."""
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
    if outcome == "refused":
        raise Failure(description=f"start_review refused for {payload.get('notice_id')}: {detail}")
    return outcome, body


# ── Dagster op / job / sensor ────────────────────────────────────────────────
class StartReviewConfig(Config):
    review_json_url: str  # s3://bucket/.../review.json
    doc_type: str = "PCN"


@op
def start_review_op(context, config: StartReviewConfig) -> None:
    """Read the extraction's review.json, build the tripwire-safe payload, and start the
    review via cortex-bff. A refusal RAISES (failed run); NO_RESIDUE logs + skips.

    Identity: the review INITIATOR is the auto-starter service account (svc:review-starter). The op mints
    a fresh token per run via client-credentials (mint_service_token); the BFF stamps the approver from
    that token's authz_id (=svc:review-starter). The reviewer is resolved separately from the review
    audience grant, not from this token. DEPLOY REQ: svc:review-starter must hold can_invoke(mesh:startReview)
    (capability_grants.yaml) — an ungranted initiator is refused NOT_ENTITLED_TO_INITIATE (403 -> failed run).
    See docs/plans/identity-mint-contract.md + capability_grants.yaml."""
    bucket = _ARTIFACT_BUCKET
    src = config.review_json_url
    key = src[len(f"s3://{bucket}/"):] if src.startswith(f"s3://{bucket}/") else src
    s3 = _s3_client()
    review = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    payload = build_start_review_payload(review, doc_type=config.doc_type)
    if not payload["notice_id"]:
        raise Failure(description=f"review.json {key} has no doc_id (notice_id)")
    if not payload["impacted_parts"]:
        context.log.info(f"no impacted parts in {key}; nothing to review — skipping")
        return
    bff_url = os.environ["CORTEX_BFF_URL"]
    token = mint_service_token()   # per-run client-credentials; RAISES loudly on mint failure (failed run)
    outcome, body = submit_review(payload, bff_url=bff_url, token=token)
    context.log.info(f"start_review {outcome}: notice={payload['notice_id']} -> {body}")


@job
def start_review_job():
    start_review_op()


@sensor(
    job=start_review_job,
    default_status=DefaultSensorStatus.STOPPED,   # opt-in per environment (like the inbound sensor)
    minimum_interval_seconds=30,
)
def extraction_review_sensor(context: SensorEvaluationContext):
    """Watch MinIO for completed extractions (review.json) and start ONE review per notice.
    run_key = doc_id (the notice fingerprint) -> Dagster dedups re-ingests/restarts."""
    s3 = _s3_client()
    since = context.cursor or None
    keys = _list_new_review_jsons(s3, _ARTIFACT_BUCKET, _WATCH_PREFIX, since)
    if not keys:
        return SkipReason("no new extractions (review.json) since cursor")
    requests = []
    last = since
    for key in keys:
        try:
            review = json.loads(s3.get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"].read())
        except Exception as exc:  # noqa: BLE001 — a malformed artifact shouldn't wedge the cursor
            context.log.warning(f"skip unreadable {key}: {exc}")
            last = key
            continue
        notice_id = review.get("doc_id")
        if not notice_id:
            last = key
            continue
        requests.append(
            RunRequest(
                run_key=str(notice_id),   # ONE review per notice (fingerprint). Dagster dedups.
                run_config={
                    "ops": {"start_review_op": {"config": {
                        "review_json_url": f"s3://{_ARTIFACT_BUCKET}/{key}",
                    }}}
                },
            )
        )
        last = key
    context.update_cursor(last or "")
    return SensorResult(run_requests=requests)
