"""The CROPFAIL fixture — a notice the extraction FLAGGED and could not read.

WHY THIS IS COMMITTED CODE AND NOT A ONE-OFF SNIPPET. This is the input the refusal-routing
path exists for, and the pipeline no longer produces it: the vision-cap + text-layer work
took PCN-2683 from "2 of 5 table crops failed" to 402/402 parts in under a second. The
failure path's motivating input was engineered out of existence by the pipeline getting
better — a permanent condition, not a temporary gap (see README.md).

The mutation, stated so it can be re-derived if doc-tools changes shape:
  * `needs_review = True`            -> the document ITSELF asks for review
  * every `parts[i].*` review_item removed -> extraction produced NOTHING to review
  * `doc_review_reasons` carries the crop-failure text -> the WHY a reviewer must see
Everything else is left exactly as the real extraction wrote it, so the fixture keeps the
producer's real shape (fields, ordering, page records) rather than a remembered one.

Together those three make the flagship case of docs/reference/refusal-routing-design.md:

    Notice PCN-2683 could not be prepared for review.
    The extraction did not produce any affected parts (2/5 table crops failed).

Used live on 2026-07-31 to witness deny-before-grant, then allow, then idempotent re-drive.
"""
from __future__ import annotations

import copy

CROP_FAILURE_REASON = "PARTS MAY BE MISSING: 2/5 table crops failed"

# The witness key. Kept here so the live drop and the offline tests name the SAME artifact —
# if they drift, the thing witnessed is not the thing sealed.
WITNESS_KEY = (
    "sustainment/inbound/witness_cropfail/generated/Diodes_PCN_2683_CROPFAIL_pdf/review.json"
)


def make_cropfail_review(real_review: dict, *, doc_id: str = "PCN-2683-CROPFAIL") -> dict:
    """Turn a REAL review.json into the flagged-and-empty notice.

    Takes the real artifact as an argument on purpose: the fixture must never be authored
    from memory. Pass the output of a genuine doc-tools extraction.
    """
    r = copy.deepcopy(real_review)
    r["doc_id"] = doc_id
    r["needs_review"] = True
    r["review_items"] = [
        it for it in (r.get("review_items") or [])
        if not str(it.get("field_path", "")).startswith("parts[")
    ]
    r["doc_review_reasons"] = [CROP_FAILURE_REASON]
    return r


def assert_evokes_the_failure(review: dict) -> None:
    """The fixture must EVOKE the path, not merely resemble it. Called by the seal so a
    future edit that quietly makes this reviewable fails here rather than turning the
    refusal-routing tests into a green that exercises nothing."""
    assert review.get("needs_review") is True, (
        "the doc-level flag is what makes this NO_PARTS_EXTRACTED rather than an honest "
        "empty — without it the sensor correctly skips and the triage path is never entered"
    )
    parts = [it for it in (review.get("review_items") or [])
             if str(it.get("field_path", "")).startswith("parts[")]
    assert not parts, f"fixture still carries {len(parts)} part rows; it would compose a review"
    assert any(CROP_FAILURE_REASON in str(x) for x in (review.get("doc_review_reasons") or [])), (
        "the reviewer-facing WHY is the fixture's whole point"
    )
