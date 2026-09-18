"""Reading a page's bytes back from the object store — RULED 2026-09-15.

WHY AN ENGINE MAY HOLD THIS CLIENT WHEN IT MAY NOT HOLD A DRIVER. The one-client rule bans an
engine from reaching a SUBSTRATE — graph, ontology, vectors, traces, datasets — because a query
language in a slot is arbitrary code in a query's clothes, and because those reads must carry the
caller's identity and record provenance. Fetching a fixed object by a locator the graph handed
you is none of that: there is no query, no language, and no choice of what to read. The row names
one key and this returns those bytes.

THE RULING IS ADR-0047'S DEPLOYED-ARTIFACT RULE APPLIED TO A DOCUMENT: **the row is the claim, the
bytes are the act, and the engine serves only when they agree.** So this module's whole job is to
return exactly what the store held, unaltered — the hash assertion lives in `explain()`, and a
helpful transformation here (decoding, normalising newlines, stripping a BOM) would break the
assertion downstream while looking like tidiness.

NO IDENTITY IS CARRIED AND THAT IS NOT AN OVERSIGHT. A page body is the same bytes for every
caller: the corpus is not entitlement-partitioned, and the row that named this key was already
reached through a governed read. Adding an initiator here would suggest a per-caller answer this
store cannot give.
"""
from __future__ import annotations

import os
from typing import Optional


class BodyUnavailable(Exception):
    """The locator named an object the store does not have.

    DISTINCT FROM A SHA MISMATCH, and the distinction is the diagnosis: a missing object means the
    prime did not upload it or uploaded it elsewhere, while a mismatch means something wrote over
    it. Collapsing them into one error would send the next reader to the wrong half of the system.
    """


class MinioBodyStore:
    """Bucket-relative key in, bytes out.

    The bucket is resolved from `DOCS_BUCKET` at read time rather than baked into the locator, so
    a row is correct in every deployment. It is NOT the ontology bucket — a separate bucket is
    what keeps a markdown body away from a TTL parser, and the prime refuses to upload if the two
    names are ever pointed at one place.
    """

    def __init__(self, *, bucket: Optional[str] = None, client=None):
        self.bucket = bucket or os.environ.get("DOCS_BUCKET", "doc-pages")
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        import boto3
        from botocore.config import Config

        # MinIO compatibility: boto3 1.36 switched the default request-checksum algorithm to one
        # MinIO rejects. Pinned to the pre-1.36 behaviour, the same way the prime's uploader is —
        # an engine that read with different settings than the writer used would fail on exactly
        # the objects the prime wrote, which is every object it will ever be asked for.
        self._client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or os.environ.get("MINIO_URL"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            config=Config(request_checksum_calculation="when_required",
                          response_checksum_validation="when_required"),
        )
        return self._client

    def read(self, locator: str) -> bytes:
        """The page's bytes, exactly as the store holds them. No decoding, no normalising."""
        if "://" in locator or locator.startswith("urn:"):
            # A work-side page names a store that is not this one. Refusing by NAME beats
            # guessing at a bucket, and the discriminator is the scheme, as the vocabulary says.
            raise BodyUnavailable(
                f"{locator!r} names a store this engine does not read. Bucket-relative keys are "
                f"the platform corpus; a scheme means a work-side page, whose store is elsewhere.")
        try:
            obj = self._get_client().get_object(Bucket=self.bucket, Key=locator)
            return obj["Body"].read()
        except Exception as exc:  # noqa: BLE001 — boto raises a family, and the cause is the point
            raise BodyUnavailable(
                f"no object at {self.bucket}/{locator}: {exc}. The row names this key, so either "
                f"the prime did not upload the page or it uploaded it under a different sha. "
                f"Re-run scripts/generate_docs_corpus.py, commit, and re-prime.") from exc
