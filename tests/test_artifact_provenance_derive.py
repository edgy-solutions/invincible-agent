"""DERIVE the trust key from the artifact — and REFUSE rather than floor-fall when it is unreadable.

THE DISTINCTION THIS FILE EXISTS TO ENFORCE, ruled at design time rather than discovered in an
incident:

    bucket unreachable / object absent / unparseable / schema-alien  -> REFUSE, loudly
    well-formed artifact, no `pipeline_version` stamped              -> SUPERVISED floor, attested

Floor-falling on a fetch failure would let an S3 outage silently convert every admission to
supervised — safe, invisible, and **indistinguishable from policy**. The floor is the honest answer
for *provenance missing from a well-formed artifact*; it is the wrong answer for *couldn't read the
artifact at all*. An outage must not read as a healthy answer.

The two outcomes are also LEGIBLE apart: a floor-fall attests
``admitted_by=policy-default-missing-provenance``, so the back-corpus of unstamped artifacts
degrades safely AND visibly instead of looking like a real supervised decision.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.utils.artifact_provenance import (  # noqa: E402
    ArtifactUnreadable, derive_provenance, parse_pointer,
)

_REVIEW = {
    "doc_id": "PCN-1",
    "doc_type": "PCN",
    "pipeline_version": "doc-tools@446fbae",
    "review_items": [{"field_path": "header.mfr", "value": "Qorvo"}],
}


class _FakeS3:
    """Minimal S3 stand-in. `payload=None` raises on get — the unreachable/absent mode."""

    def __init__(self, payload, raises=None):
        self._payload = payload
        self._raises = raises

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3's casing
        if self._raises is not None:
            raise self._raises
        body = self._payload
        if not isinstance(body, (bytes, str)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        return {"Body": type("B", (), {"read": staticmethod(lambda: body)})()}


# ===========================================================================
# THE FLOOR ARM — well-formed artifact, no producer stamp
# ===========================================================================
def test_a_well_formed_artifact_without_a_stamp_takes_the_floor_and_SAYS_SO():
    """The back-corpus. Every artifact produced before doc-tools stamped itself lands here, and it
    must degrade SAFE and LEGIBLE — not safe and silent."""
    artifact = {**_REVIEW}
    del artifact["pipeline_version"]
    d = derive_provenance("s3://b/k/review.json", s3=_FakeS3(artifact))
    assert d.version_missing is True
    assert d.pipeline_version == ""
    assert d.format_fingerprint == "qorvo/pcn/v1", (
        "the fingerprint must still derive — a missing VERSION is not a missing FORMAT")


@pytest.mark.parametrize("sentinel", ["unset", "unstamped", "doc-tools@unstamped", "  UNSET  "])
def test_a_sentinel_stamp_is_treated_as_MISSING_not_as_a_version(sentinel):
    """A sentinel means 'provenance missing'. Treating it as a version would let the trust table be
    keyed on the absence of information — which the table's own validator now forbids, and this is
    the same rule enforced one layer earlier so the two cannot disagree."""
    d = derive_provenance("s3://b/k", s3=_FakeS3({**_REVIEW, "pipeline_version": sentinel}))
    assert d.version_missing is True
    assert d.pipeline_version == ""


def test_a_real_stamp_derives_both_components():
    d = derive_provenance("s3://b/k", s3=_FakeS3(_REVIEW))
    assert (d.format_fingerprint, d.pipeline_version) == ("qorvo/pcn/v1", "doc-tools@446fbae")
    assert d.version_missing is False


# ===========================================================================
# THE REFUSAL ARM — four modes, one verdict
# ===========================================================================
def test_unreachable_or_absent_REFUSES():
    """Deliberately not distinguished into different verdicts: both are 'could not read', both
    refuse. Splitting them would tempt a future author into floor-falling on one."""
    with pytest.raises(ArtifactUnreadable) as ei:
        derive_provenance("s3://b/k", s3=_FakeS3(None, raises=RuntimeError("NoSuchKey")))
    assert "could not read artifact" in str(ei.value)


def test_unparseable_REFUSES():
    with pytest.raises(ArtifactUnreadable) as ei:
        derive_provenance("s3://b/k", s3=_FakeS3(b"{not json"))
    assert "not parseable JSON" in str(ei.value)


def test_a_json_scalar_REFUSES():
    with pytest.raises(ArtifactUnreadable):
        derive_provenance("s3://b/k", s3=_FakeS3(b'"just a string"'))


def test_SCHEMA_ALIEN_refuses_rather_than_deriving_unknown_from_nothing():
    """THE SUBTLE ONE. A readable JSON object that is not a review.json would otherwise derive
    `unknown/pcn/v1` — a perfectly plausible fingerprint from an unrelated object. That would make
    the pointer a reference to ANY object rather than to a REVIEW, and a caller could aim it at
    something whose derived key happens to be promoted."""
    with pytest.raises(ArtifactUnreadable) as ei:
        derive_provenance("s3://b/k", s3=_FakeS3({"totally": "unrelated"}))
    assert "not a review.json" in str(ei.value)


def test_an_absent_pointer_REFUSES_rather_than_defaulting():
    """No pointer means no artifact means no derivable posture. Defaulting would resurrect exactly
    the caller-asserted key this change removes."""
    with pytest.raises(ArtifactUnreadable):
        derive_provenance("", s3=_FakeS3(_REVIEW))


# ===========================================================================
# Pointer shapes — the sensor's `request_key` is `<etag>:<key>`
# ===========================================================================
def test_pointer_forms(monkeypatch):
    monkeypatch.setenv("ARTIFACT_BUCKET", "processing-artifacts")
    assert parse_pointer("s3://b/some/key.json") == ("b", "some/key.json")
    # the sensor's request_key: ETag rides in front for ingress idempotency, not part of the key
    assert parse_pointer("abc123:notices/n1/generated/review.json") == (
        "processing-artifacts", "notices/n1/generated/review.json")
    assert parse_pointer("notices/n1/generated/review.json") == (
        "processing-artifacts", "notices/n1/generated/review.json")


def test_no_bucket_anywhere_REFUSES_rather_than_guessing(monkeypatch):
    monkeypatch.delenv("ARTIFACT_BUCKET", raising=False)
    with pytest.raises(ArtifactUnreadable) as ei:
        parse_pointer("some/key.json")
    assert "refusing to guess" in str(ei.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
