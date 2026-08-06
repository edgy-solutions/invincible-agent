"""DERIVE the trust key from the artifact — fetch `review.json` by pointer, compute both components.

WHAT THIS REPLACES AND WHY. The trust key `(format_fingerprint, pipeline_version)` used to arrive as
two CALLER-ASSERTED FACTS in the start_review payload. A caller who can assert them chooses which
table row the lookup hits — i.e. selects its own supervision level. `start_review` is reachable as a
registered mesh verb, so that is a real surface, not a pipeline talking to itself.

THE POINTER-NOT-FACTS SHAPE. Callers supply the ARTIFACT REFERENCE only (something they already
supply). Everything else is read from the artifact. A caller can then lie about exactly ONE thing —
WHICH artifact — and the artifact determines the rest, which collapses the trust question to "can
the caller read that artifact": an entitlement question the system already knows how to ask.

FAILURE SEMANTICS ARE RULED HERE, AT DESIGN TIME, NOT DISCOVERED IN AN INCIDENT:

    bucket unreachable / object absent / unparseable / schema-alien  -> REFUSE, loudly
    well-formed artifact, `pipeline_version` field absent            -> SUPERVISED floor, attested

**A fetch failure is a REFUSAL, not a floor-fall.** The supervised floor is the honest degradation
for *provenance missing from a well-formed artifact*. It is the WRONG answer for *couldn't read the
artifact at all*, because floor-falling on a fetch failure lets an S3 outage silently convert every
admission to supervised — safe, invisible, and indistinguishable from policy. An outage must not
read as a healthy answer. (Same distinction as a probe returning `None` rather than `[]`.)
"""
from __future__ import annotations

import json
import os
from typing import Optional

__all__ = ["ArtifactUnreadable", "DerivedProvenance", "derive_provenance"]

# The sentinel a producer stamps when its own identity was not baked in. Recognised here so the
# floor decision is made on MEANING, not on a string comparison scattered across callers.
_SENTINELS = frozenset({"", "unset", "unstamped", "unknown", "none"})


class ArtifactUnreadable(RuntimeError):
    """The artifact could not be read or is not a review.json. NEVER a floor-fall — the caller
    refuses. Carries the reason so the refusal names which of the four modes occurred."""


class DerivedProvenance:
    """The trust key as DERIVED, plus whether provenance was actually present.

    ``version_missing`` is not cosmetic: it is what lets the caller attest
    ``policy-default-missing-provenance`` instead of recording a supervised decision that looks
    identical to a real one. The back-corpus of unstamped artifacts degrades SAFE **and legibly**.
    """

    __slots__ = ("format_fingerprint", "pipeline_version", "version_missing")

    def __init__(self, format_fingerprint: str, pipeline_version: str, version_missing: bool):
        self.format_fingerprint = format_fingerprint
        self.pipeline_version = pipeline_version
        self.version_missing = version_missing

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return (f"DerivedProvenance(fingerprint={self.format_fingerprint!r}, "
                f"version={self.pipeline_version!r}, missing={self.version_missing})")


def _client():
    """S3 client from the credentials engine-a ALREADY carries.

    `MINIO_*` rather than `AWS_*` deliberately — those are the names in this pod's env. They were
    provisioned fleet-wide long before anything read them; this is the first consumer.
    """
    import boto3  # imported lazily so a missing dep fails at USE, naming this seam

    endpoint = os.getenv("MINIO_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL") or ""
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def parse_pointer(pointer: str) -> tuple[str, str]:
    """`s3://bucket/key` or a bare `key` (bucket from ``ARTIFACT_BUCKET``) -> (bucket, key).

    The sensor's `request_key` is `<etag>:<key>` — the ETag rides in front for idempotency. Split
    it off here rather than at the call site, so exactly one place knows the pointer's shape.
    """
    p = (pointer or "").strip()
    if not p:
        raise ArtifactUnreadable("no artifact pointer supplied — nothing to derive from")
    if p.startswith("s3://"):
        rest = p[len("s3://"):]
        bucket, _, key = rest.partition("/")
        if not bucket or not key:
            raise ArtifactUnreadable(f"malformed s3 pointer {pointer!r}")
        return bucket, key
    # `<etag>:<path/to/review.json>` — the ETag is an idempotency rider, not part of the key.
    if ":" in p and not p.startswith("/"):
        head, _, tail = p.partition(":")
        if tail and "/" in tail:
            p = tail
    bucket = os.getenv("ARTIFACT_BUCKET") or ""
    if not bucket:
        raise ArtifactUnreadable(
            f"pointer {pointer!r} names no bucket and ARTIFACT_BUCKET is unset — refusing to guess "
            f"which bucket an admission decision should be derived from")
    return bucket, p


def derive_provenance(pointer: str, *, s3=None) -> DerivedProvenance:
    """Fetch the artifact and derive `(format_fingerprint, pipeline_version)`.

    Raises ``ArtifactUnreadable`` for every mode in which the artifact could not be READ or is not a
    review.json. Returns a ``DerivedProvenance`` with ``version_missing=True`` when the artifact is
    well-formed but carries no producer stamp — the ONLY case that degrades to the floor.
    """
    try:
        from utils.format_fingerprint import format_fingerprint  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.utils.format_fingerprint import format_fingerprint

    bucket, key = parse_pointer(pointer)
    client = s3 or _client()

    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        # Covers unreachable AND absent. Deliberately NOT distinguished into different verdicts —
        # both are "could not read", both refuse. Distinguishing them would tempt a future author
        # into floor-falling on one of them.
        raise ArtifactUnreadable(
            f"could not read artifact s3://{bucket}/{key}: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        review = json.loads(body)
    except Exception as exc:  # noqa: BLE001
        raise ArtifactUnreadable(
            f"artifact s3://{bucket}/{key} is not parseable JSON: {exc}") from exc

    if not isinstance(review, dict):
        raise ArtifactUnreadable(
            f"artifact s3://{bucket}/{key} parsed to {type(review).__name__}, not an object")

    # SCHEMA-ALIEN CHECK. A readable JSON object that is not a review.json must REFUSE, not derive
    # `unknown/pcn/v1` from nothing — otherwise pointing at any object in the bucket yields a
    # plausible fingerprint, and the pointer stops being a reference to a REVIEW.
    if "review_items" not in review and "doc_id" not in review:
        raise ArtifactUnreadable(
            f"artifact s3://{bucket}/{key} carries neither `review_items` nor `doc_id` — it is not "
            f"a review.json, and deriving an admission key from an unrelated object would let any "
            f"readable object stand in for a review")

    fingerprint = format_fingerprint(review)
    raw_version = str(review.get("pipeline_version") or "").strip()
    missing = raw_version.lower() in _SENTINELS or raw_version.lower().rsplit("@", 1)[-1] in _SENTINELS
    return DerivedProvenance(
        format_fingerprint=fingerprint,
        pipeline_version="" if missing else raw_version,
        version_missing=missing,
    )
