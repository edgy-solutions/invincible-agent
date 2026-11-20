"""The `/reviews` start payload, built from a doc-tools `review.json`.

Pure: no dagster, no boto3. It lives apart from `defs/extraction_review_sensor.py` so the BFF can
build the same payload the sensor builds without importing the orchestration side. The sensor
re-exports `build_start_review_payload`; there is one function.
"""
import logging
import re

from .extraction_warning import bound_warnings

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_log = logging.getLogger("iagent.defs.extraction_review_sensor")
_PART_FIELD = re.compile(r"parts\[(\d+)\]\.(\w+)")


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
    payload = {
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
        #
        # BOUNDED (architect ruling 2026-11-19: "a reason that reaches a person is a code and a
        # bounded message"). A failed pass's reason can hold the whole exception text, prompt and
        # raw model reply included. Each reason becomes {code, message}; the raw text stays in
        # review.json and in telemetry, never on the card or the triage task.
        "extraction_warnings": bound_warnings(review_json.get("doc_review_reasons")),
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
    # The source document's identity, when doc-tools stamped it. A malformed value is omitted,
    # never repaired: a wrong id would mark the wrong ingest row.
    _sha = review_json.get("source_sha256")
    if isinstance(_sha, str) and _SHA256_RE.match(_sha):
        payload["ingest_id"] = "sha256:" + _sha
    else:
        _log.info("review.json source_sha256 absent or malformed; no ingest_id in the payload")
    return payload
