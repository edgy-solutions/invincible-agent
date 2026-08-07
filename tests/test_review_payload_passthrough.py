"""CROSS-COMPONENT CONTRACT: every field the sensor sends must survive the BFF.

THE LIVE REGRESSION (2026-07-30). The sensor gained `review_state_source` (the
provenance attestation that disarms start_review's laundering tripwire) and
`extraction_warnings` (the "PARTS MAY BE MISSING" text a reviewer must see). Both were
built end-to-end and verified at every seam I TOUCHED — and both were silently dropped
at the one seam I did not: cortex-bff's `/reviews`, which HAND-ENUMERATES each field
into a Pydantic model and then re-enumerates it into the forwarded body. Pydantic drops
undeclared keys, so the attestation never reached the tripwire and every honest sensor
request was refused with REVIEW_STATE_UNSOURCED. The docstring even claimed the BFF
"forwards the extraction payload verbatim" — it did not.

That is the resolution-discard pattern at a request boundary: a producer computes
something correct and a hand-maintained consumer quietly discards it. A field-by-field
review cannot prevent the NEXT one; a test that derives its expectations FROM THE
PRODUCER can.

So this test asks the sensor what it produces and asserts the BFF accepts and forwards
ALL of it. Adding a field to the payload builder without teaching the BFF now fails
here instead of in production.

Run:  uv run --frozen python -m pytest tests/test_review_payload_passthrough.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
_spec = importlib.util.spec_from_file_location("ers_contract", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]


def _review_json() -> dict:
    """A review.json carrying EVERY signal the sensor knows how to read, so the payload
    it builds is the widest one the BFF must accept."""
    return {
        "doc_id": "PCN-23-0171",
        "trace_id": "trace-abc-123",   # doc-tools stamps this; it must reach the ReviewStarter
        "doc_type": "PDN",
        "categories": ["Material", "Process"],
        "needs_review": True,
        "doc_review_reasons": ["PARTS MAY BE MISSING: 2/5 table crops failed"],
        "review_items": [
            {"field_path": "header.categories", "value": ["Material", "Process"]},
            {"field_path": "parts[0].affected_mpn", "value": "MPN-A", "needs_review": False},
            {"field_path": "parts[0].replacement_mpn", "value": "MPN-A-R"},
        ],
    }


def _bff_fields() -> set:
    """The field names cortex-bff's ReviewStartRequest declares. Imported lazily and
    skipped if the BFF's heavy deps are unavailable in this env — the point is the
    CONTRACT, and it must not silently vanish, so an import failure skips loudly."""
    try:
        from src.iagent.gateway import ReviewStartRequest  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"cortex-bff gateway not importable here: {type(e).__name__}: {e}")
    return set(ReviewStartRequest.model_fields.keys())


# Keys the sensor sends that the BFF deliberately does NOT take from the caller.
# `approver` is stamped from the authenticated identity — a client-supplied approver
# would let a caller start a review as someone else — and `domain` selects the audience.
_BFF_OWNS = {"approver"}


def test_bff_accepts_every_field_the_sensor_sends():
    """THE CONTRACT. Derived from the producer, so a new payload field fails here."""
    payload = ers.build_start_review_payload(_review_json())
    declared = _bff_fields()
    missing = set(payload) - declared - _BFF_OWNS
    assert not missing, (
        f"cortex-bff's ReviewStartRequest does not declare {sorted(missing)} — Pydantic "
        f"DROPS undeclared keys, so these are silently lost between the sensor and "
        f"start_review. This is exactly how review_state_source went missing and refused "
        f"every notice with REVIEW_STATE_UNSOURCED."
    )


def test_the_two_fields_that_were_actually_dropped_are_declared():
    """Explicit regression pins, so the general test above can never be weakened into
    passing while THESE two specifically go missing again."""
    declared = _bff_fields()
    assert "review_state_source" in declared, "the tripwire attestation must survive the BFF"
    assert "extraction_warnings" in declared, "the reviewer-facing degradation warnings must survive the BFF"
    # IDENTITY AND LOCATION, both declared, as SEPARATE fields. If either is undeclared Pydantic
    # drops it and the other silently absorbs its role — which is how the conflation was born.
    assert "request_key" in declared, "the artifact IDENTITY (ingress idempotency) must survive the BFF"
    assert "artifact_uri" in declared, "the artifact LOCATION (admission derive) must survive the BFF"


def test_attestation_is_actually_populated_by_the_sensor():
    """The BFF forwarding a field is useless if the sensor stopped sending it. Both ends
    of the contract, asserted together."""
    payload = ers.build_start_review_payload(_review_json())
    assert payload["review_state_source"] == "extraction"
    assert payload["extraction_warnings"] == ["PARTS MAY BE MISSING: 2/5 table crops failed"]
    assert payload["trace_id"] == "trace-abc-123"   # the extraction trace id, forwarded (ADR-0038)


def test_forwarded_body_carries_them_not_just_the_model():
    """Declaring the field is only half of it — the handler builds the downstream body by
    hand-enumerating AGAIN, so a field can be accepted and still dropped one line later.
    Assert against the handler's source that both names reach the forwarded body."""
    src = (_ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    # Scope to the HANDLER, not a byte window. This assertion previously scanned the 2000
    # characters above the POST, which made it a distance check disguised as a content check:
    # adding a comment block between the body dict and the call pushed the dict out of range
    # and the test failed while the code was correct (2026-07-31). A window measures layout;
    # the function body is what the claim is actually about.
    start = src.index("async def start_review(")
    end = src.index("\ndef ", start)             # first top-level def after the handler
    handler = src[start:end]
    for field in ("review_state_source", "extraction_warnings"):
        assert f'"{field}": req.{field}' in handler, (
            f"{field} is declared on the model but never forwarded in the start_review body"
        )
    # request_key joined them: review IDENTITY is derived from it downstream (the workflow key),
    # so dropping it here silently restores the single-use-key trap that made ten notices at
    # work permanently unable to produce a review.
    assert 'body["request_key"] = req.request_key or ""' in handler
    # trace_id joins them (ADR-0038): the extraction trace id must reach the ReviewStarter
    # so the review can nest under the SAME Langfuse trace as the extraction.
    assert 'body["trace_id"] = req.trace_id or ""' in handler
    # ── THE POINTER IS NOW THE WHOLE ADMISSION CONTRACT (ADR-0034 phase 1.3, consumer half) ────
    # This pin USED to protect `format_fingerprint` / `pipeline_version`. Those are gone: the
    # starter DERIVES both from the artifact, so a caller can no longer assert the trust key and
    # choose its own supervision level.
    #
    # THE POINTER IS `artifact_uri`, NOT `request_key`, and the correction is the whole lesson.
    # This pin was first written against `request_key` — because the same comment above was already
    # calling it "the artifact pointer", and it does move with the artifact, so it READS like one.
    # It is not: `request_key` is `{epoch}{ETag}-{key}`, an IDENTITY minted for ingress idempotency.
    # Fetching it asks S3 for a key with an ETag glued to the front, and every derive refused. The
    # pin guarded the wrong string and stayed green, because a pin can only be as right as the
    # contract it names.
    #
    # BOTH are now asserted, separately, because they do different jobs and a hop that drops either
    # one loses something distinct: `request_key` -> ingress dedup + the workflow key;
    # `artifact_uri` -> the admission posture. The admission half fails LOUDLY (the starter refuses
    # an underivable posture) rather than silently, which is the refuse-vs-floor split working.
    #
    # Guarding fields nothing sends would be worse than not guarding: a green pin over a dead
    # contract reads as coverage.
    assert 'body["artifact_uri"] = req.artifact_uri or ""' in handler, (
        "the artifact LOCATION no longer reaches the forwarded body — the starter cannot derive the "
        "admission posture and every notice refuses"
    )
    for dead in ("format_fingerprint", "pipeline_version"):
        assert f'body["{dead}"]' not in handler, (
            f"{dead} is being forwarded again — it is DERIVED from the artifact now, and a "
            f"caller-asserted copy would silently diverge from what actually routed the notice"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
