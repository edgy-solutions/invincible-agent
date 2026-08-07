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


# WHY THE PRECONDITION IS NAMED, not just the failure (added 2026-08-06 after a live misdiagnosis).
#
# The first release of this module refused a malformed pointer with the SAME message shape as an
# unreadable artifact — "could not read artifact s3://…". That is true and useless: the artifact was
# perfectly readable; the POINTER was wrong. Debugging it worked despite the message, not because of
# it. A refusal must be legible about WHICH PRECONDITION FAILED, or it sends the reader to the wrong
# subsystem — here, to S3 instead of to the caller.
REASON_MALFORMED_POINTER = "malformed_pointer"     # the caller's fault; the store was never asked
REASON_ARTIFACT_ABSENT = "artifact_absent"         # the store answered, and said no such object
REASON_STORE_UNREACHABLE = "store_unreachable"     # the store did not answer at all
REASON_UNPARSEABLE = "unparseable"                 # bytes returned, not JSON
REASON_SCHEMA_ALIEN = "schema_alien"               # JSON returned, not a review.json


class ArtifactUnreadable(RuntimeError):
    """The admission posture could not be DERIVED. NEVER a floor-fall — the caller refuses.

    ``reason`` names which precondition failed, so a refusal points at the subsystem that actually
    broke. ``artifact_absent`` and ``store_unreachable`` are deliberately DISTINCT: one is a
    caller/data problem and one is an outage, they are told apart at the boto3 error, and conflating
    them is how an outage gets debugged as a bad key.
    """

    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


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
    """ONE accepted form: ``s3://bucket/key``. Anything else is REFUSED, naming what was received.

    NO BARE-KEY TOLERANCE, and that is the point. An earlier version accepted a bare key and filled
    the bucket in from ``ARTIFACT_BUCKET`` — which quietly required producer and consumer to agree
    on an ambient env var across two runtimes. Tolerance IS the coupling: a fallback path is where
    the next shape assumption hides. The full URI carries its own bucket, so producer and consumer
    cannot disagree about where the artifact lives.

    IT ALSO ACCEPTED A FORMAT THAT NEVER EXISTED. It documented the sensor's `request_key` as
    ``<etag>:<key>`` — colon-separated — and the sensor has always emitted
    ``{epoch}{ETag}-{key}``. The stripping branch therefore never fired, the whole identity string
    went to S3 as a key, and every derive refused. The parser was written against an INVENTED
    producer format and its fixture asserted the same invention, so the two agreed with each other
    and never with the producer. Hence: one form, refused otherwise, and a contract test that reads
    the producer.
    """
    p = (pointer or "").strip()
    if not p:
        raise ArtifactUnreadable(
            "no artifact_uri supplied — the admission posture is derived FROM the artifact, so "
            "there is nothing to derive from",
            reason=REASON_MALFORMED_POINTER,
        )
    if not p.startswith("s3://"):
        raise ArtifactUnreadable(
            f"artifact_uri {p!r} is not an s3:// URI. The ONLY accepted form is "
            f"'s3://<bucket>/<key>' — a bare key is refused rather than resolved against an "
            f"ambient bucket, because that makes the location depend on two runtimes agreeing on "
            f"an env var. (If this looks like an idempotency key such as '<etag>-<key>', it is: "
            f"identity and location are different fields.)",
            reason=REASON_MALFORMED_POINTER,
        )
    bucket, _, key = p[len("s3://"):].partition("/")
    if not bucket or not key:
        raise ArtifactUnreadable(
            f"artifact_uri {p!r} is malformed — 's3://<bucket>/<key>' needs both a bucket and a "
            f"key; got bucket={bucket!r} key={key!r}",
            reason=REASON_MALFORMED_POINTER,
        )
    return bucket, key


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
        # ABSENT vs UNREACHABLE are told apart HERE, and the verdict is the same (refuse) while the
        # REASON is not. Both refuse — that part was always right — but a reader debugging
        # "artifact_absent" goes to the producer and a reader debugging "store_unreachable" goes to
        # MinIO, and sending them to the wrong one costs the whole debugging session.
        code = ""
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = str((resp.get("Error") or {}).get("Code") or "")
        absent = code in ("NoSuchKey", "NoSuchBucket", "404") or "NoSuchKey" in str(exc)
        raise ArtifactUnreadable(
            (f"artifact s3://{bucket}/{key} does not exist ({code or type(exc).__name__}) — the "
             f"store answered and said so, so this is a bad pointer or a missing object, NOT an "
             f"outage")
            if absent else
            (f"artifact store did not answer for s3://{bucket}/{key}: "
             f"{type(exc).__name__}: {exc} — this is an OUTAGE, not a bad pointer; the posture is "
             f"undecidable until it returns"),
            reason=REASON_ARTIFACT_ABSENT if absent else REASON_STORE_UNREACHABLE,
        ) from exc

    try:
        review = json.loads(body)
    except Exception as exc:  # noqa: BLE001
        raise ArtifactUnreadable(
            f"artifact s3://{bucket}/{key} is not parseable JSON: {exc}",
            reason=REASON_UNPARSEABLE) from exc

    if not isinstance(review, dict):
        raise ArtifactUnreadable(
            f"artifact s3://{bucket}/{key} parsed to {type(review).__name__}, not an object",
            reason=REASON_SCHEMA_ALIEN)

    # SCHEMA-ALIEN CHECK. A readable JSON object that is not a review.json must REFUSE, not derive
    # `unknown/pcn/v1` from nothing — otherwise pointing at any object in the bucket yields a
    # plausible fingerprint, and the pointer stops being a reference to a REVIEW.
    if "review_items" not in review and "doc_id" not in review:
        raise ArtifactUnreadable(
            f"artifact s3://{bucket}/{key} carries neither `review_items` nor `doc_id` — it is not "
            f"a review.json, and deriving an admission key from an unrelated object would let any "
            f"readable object stand in for a review",
            reason=REASON_SCHEMA_ALIEN)

    fingerprint = format_fingerprint(review)
    raw_version = str(review.get("pipeline_version") or "").strip()
    missing = raw_version.lower() in _SENTINELS or raw_version.lower().rsplit("@", 1)[-1] in _SENTINELS
    return DerivedProvenance(
        format_fingerprint=fingerprint,
        pipeline_version="" if missing else raw_version,
        version_missing=missing,
    )
