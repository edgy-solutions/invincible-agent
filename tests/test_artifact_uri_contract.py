"""IDENTITY IS NOT LOCATION — the producer's real `artifact_uri`, driven end to end.

THE BUG THIS EXISTS TO PREVENT RECURRING. The consumer-derive read `request_key` as a pointer.
`request_key` is `{epoch}{ETag}-{key}` — an IDENTITY minted for ingress idempotency — so the derive
asked S3 for a key with an ETag glued to the front and refused every notice.

WHY NO TEST CAUGHT IT, which is the part worth not repeating:
  * the parser's docstring claimed the format was `<etag>:<key>` (COLON). The sensor has always
    emitted a DASH. The format was INVENTED;
  * the fixture asserted that same invented format, so parser and test agreed with each other and
    neither ever agreed with the producer;
  * the live witness hand-supplied a bare key in the shape the parser expected, so the composed
    sensor path was never driven.

Three mutually-reinforcing self-references, zero contact with the emitter. So this file's rule is:
**the payload under test is built by the PRODUCER'S OWN FUNCTION**, never hand-written here.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.utils.artifact_provenance import (  # noqa: E402
    REASON_ARTIFACT_ABSENT, REASON_MALFORMED_POINTER, REASON_SCHEMA_ALIEN,
    REASON_STORE_UNREACHABLE, REASON_UNPARSEABLE, ArtifactUnreadable, derive_provenance,
    parse_pointer,
)


def _sensor_module():
    """Load the sensor BY FILE PATH (no package context) — the same way its own suite does, so this
    test exercises the module as shipped rather than a re-import that might resolve differently."""
    path = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
    spec = importlib.util.spec_from_file_location("_sensor_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_REVIEW = {
    "doc_id": "PCN-1", "doc_type": "PCN", "doc_type_source": "extraction",
    "pipeline_version": "doc-tools@446fbae",
    "review_items": [{"field_path": "header.mfr", "value": "Qorvo"}],
}


# ===========================================================================
# THE CONTRACT — read FROM the producer, never asserted about it
# ===========================================================================
def test_the_producer_emits_artifact_uri_and_the_consumer_can_parse_IT():
    """THE SEAM, closed. The payload is built by the sensor's own builder; the URI it emits must be
    exactly what the consumer's parser accepts. If either side changes shape, this goes red."""
    sensor = _sensor_module()
    payload = sensor.build_start_review_payload(
        _REVIEW, request_key="epoch|abc123-notices/n1/generated/review.json",
        artifact_uri="s3://processing-artifacts/notices/n1/generated/review.json")

    assert "artifact_uri" in payload, "the producer stopped emitting the pointer"
    bucket, key = parse_pointer(payload["artifact_uri"])
    assert bucket == "processing-artifacts"
    assert key == "notices/n1/generated/review.json"


def test_the_IDENTITY_string_is_REFUSED_as_a_pointer():
    """THE EXACT BUG, pinned. A `request_key` handed to the parser must be refused — and refused as
    a MALFORMED POINTER, not as an unreadable artifact, because the artifact is fine and the caller
    is wrong."""
    sensor = _sensor_module()
    payload = sensor.build_start_review_payload(
        _REVIEW, request_key="epoch|711028c340016a6a-sustainment/inbound/x/review.json",
        artifact_uri="s3://b/k/review.json")
    identity = payload["request_key"]

    with pytest.raises(ArtifactUnreadable) as ei:
        parse_pointer(identity)
    assert ei.value.reason == REASON_MALFORMED_POINTER
    assert "identity and location are different fields" in str(ei.value)


def test_identity_and_location_are_DIFFERENT_fields_on_the_payload():
    """They must not be the same string, or the conflation is back with a new name."""
    sensor = _sensor_module()
    payload = sensor.build_start_review_payload(
        _REVIEW, request_key="epoch|abc-notices/n/review.json",
        artifact_uri="s3://processing-artifacts/notices/n/review.json")
    assert payload["request_key"] != payload["artifact_uri"]


# ===========================================================================
# ONE ACCEPTED FORM — bare keys REFUSED, not tolerated
# ===========================================================================
@pytest.mark.parametrize("bad", [
    "notices/n1/generated/review.json",                 # bare key — the tolerated form, now refused
    "epoch|abc123-notices/n1/review.json",              # an identity string
    "/notices/n1/review.json",
    "s3://",
    "s3://bucket-only",
    "",
])
def test_only_a_full_s3_uri_is_accepted(bad):
    """Bare-key tolerance WAS the coupling: resolving it against `ARTIFACT_BUCKET` made the location
    depend on two runtimes agreeing on an env var, and a fallback path is where the next shape
    assumption hides. One form, refused otherwise."""
    with pytest.raises(ArtifactUnreadable) as ei:
        parse_pointer(bad)
    assert ei.value.reason == REASON_MALFORMED_POINTER


def test_a_bare_key_is_refused_EVEN_WHEN_artifact_bucket_is_set(monkeypatch):
    """The tolerance is gone for real — not merely unreachable because the env happens to be unset.
    Without this, the refusal could pass for the wrong reason on a machine with no ARTIFACT_BUCKET."""
    monkeypatch.setenv("ARTIFACT_BUCKET", "processing-artifacts")
    with pytest.raises(ArtifactUnreadable) as ei:
        parse_pointer("notices/n1/generated/review.json")
    assert ei.value.reason == REASON_MALFORMED_POINTER


# ===========================================================================
# REFUSAL LEGIBILITY — every refusal names WHICH precondition failed
# ===========================================================================
class _S3:
    def __init__(self, exc=None, payload=None):
        self._exc, self._payload = exc, payload

    def get_object(self, Bucket, Key):  # noqa: N803
        if self._exc:
            raise self._exc
        body = self._payload
        if not isinstance(body, bytes):
            import json as _j
            body = _j.dumps(body).encode()
        return {"Body": type("B", (), {"read": staticmethod(lambda: body)})()}


def test_ABSENT_and_UNREACHABLE_are_told_apart():
    """The row the refuse-vs-floor table gained. Both refuse — that was always right — but a reader
    debugging `artifact_absent` goes to the PRODUCER and one debugging `store_unreachable` goes to
    MinIO. Sending them to the wrong subsystem costs the session; tonight's misdiagnosis is the
    evidence."""
    class _ClientError(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    with pytest.raises(ArtifactUnreadable) as absent:
        derive_provenance("s3://b/missing.json", s3=_S3(exc=_ClientError()))
    assert absent.value.reason == REASON_ARTIFACT_ABSENT
    assert "NOT an outage" in str(absent.value)

    with pytest.raises(ArtifactUnreadable) as down:
        derive_provenance("s3://b/k.json", s3=_S3(exc=OSError("connection refused")))
    assert down.value.reason == REASON_STORE_UNREACHABLE
    assert "OUTAGE" in str(down.value)


def test_unparseable_and_schema_alien_are_told_apart():
    with pytest.raises(ArtifactUnreadable) as a:
        derive_provenance("s3://b/k", s3=_S3(payload=b"{not json"))
    assert a.value.reason == REASON_UNPARSEABLE

    with pytest.raises(ArtifactUnreadable) as b:
        derive_provenance("s3://b/k", s3=_S3(payload={"totally": "unrelated"}))
    assert b.value.reason == REASON_SCHEMA_ALIEN


def test_every_refusal_carries_a_reason():
    """A refusal without a reason is the old message shape returning — true and useless."""
    for pointer, s3 in [("", None), ("bare/key", None), ("s3://b/k", _S3(payload=b"{bad"))]:
        with pytest.raises(ArtifactUnreadable) as ei:
            derive_provenance(pointer, s3=s3 or _S3(payload=_REVIEW))
        assert getattr(ei.value, "reason", None), f"refusal for {pointer!r} names no precondition"


# ===========================================================================
# THE HAPPY PATH, through the producer's own URI
# ===========================================================================
def test_a_producer_emitted_uri_derives_the_full_key():
    sensor = _sensor_module()
    payload = sensor.build_start_review_payload(
        _REVIEW, request_key="epoch|abc-x/review.json",
        artifact_uri="s3://processing-artifacts/x/review.json")
    d = derive_provenance(payload["artifact_uri"], s3=_S3(payload=_REVIEW))
    assert d.format_fingerprint == "qorvo/pcn/v1"
    assert d.pipeline_version == "doc-tools@446fbae"
    assert d.version_missing is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
