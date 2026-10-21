"""Ingestion seam (ADR-0041 §8) — the `ingest_status` projection.

SAME SHAPE as `human_task_projection` (see `human_tasks.py` and the module-level note there):
this module owns the WRITE path into the Electric-replicated `ingest_status_projection` table
(sql/create_ingest_status_projection.sql). The cortex-bff `/electric/shape` proxy filters this
table by `(submitted_by = <caller> OR on_behalf_of = <caller>)` — the server-verified authz_id
from the JWT, never client-controlled.

Postgres = the SAME Electric-replicated DB the projector writes (PROJECTOR_POSTGRES_DSN).
psycopg2 (sync); the async gateway wraps these calls in starlette.run_in_threadpool — same
discipline as human_tasks.py.

ONE ROW PER ARRIVAL. A new sha256 gets one row at id = sha256 (content-addressed). A repeat
arrival of a sha256 that already has a row is level-1 dedupe (ADR-0041 §8): rather than silently
no-op or overwrite, it gets its OWN row (`record_duplicate_arrival`) — "records the arrival as
provenance" per the ADR's own wording, because a second drop is a fact about who tried to
resubmit and when, not a fact to discard.

STAGE VOCABULARY MIRRORS `iagent_mesh.ingest.INGEST_STAGES` (lane/ca commit b68926a,
iagent-mesh-sdk; untagged, and the fleet's pinned v0.9.3 lacks this module, so it is mirrored
here rather than imported): received -> extracting -> review -> promoted | rejected
| failed. `detail` is REQUIRED on `rejected`/`failed` (ca's `IngestStatus` rule) — a terminal
state with no reason is unactionable.

THE INGEST ID is minted with `promotion.ingest_id_for` (sha256:<64 lowercase hex>) — the SAME
derivation `document_promotion` requires, so a seam-minted document is never refused promotion
for a spelling mismatch (`promotion.INGEST_ID_RE`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Any, Optional

import psycopg2
import psycopg2.extras

try:
    from .promotion import INGEST_ID_RE
except ImportError:  # pragma: no cover — direct file-load test harness has no parent package
    # tests/test_ingest_status_projection.py loads this module by path (spec_from_file_location,
    # same mechanism test_human_tasks_recipients.py uses for human_tasks.py) so it never needs a
    # live PROJECTOR_POSTGRES_DSN; that loader gives the module no package context, so the
    # relative import above raises. Fall back to the absolute path the rest of the test suite
    # already uses (`from src.iagent import promotion`) — same module object either way.
    import sys as _sys
    from pathlib import Path as _Path
    _repo_root = _Path(__file__).resolve().parents[2]
    if str(_repo_root) not in _sys.path:
        _sys.path.insert(0, str(_repo_root))
    from src.iagent.promotion import INGEST_ID_RE

logger = logging.getLogger(__name__)

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

# The stage vocabulary (ADR-0041 §8), mirroring `iagent_mesh.ingest.INGEST_STAGES` (ca b68926a).
# ORDER meaningful for the SAME reason obtained_via's is (provenance.py): it is a
# degradation-of-completeness path, not a cosmetic list.
RECEIVED, EXTRACTING, REVIEW, PROMOTED, REJECTED, FAILED = (
    "received", "extracting", "review", "promoted", "rejected", "failed")
STAGES = (RECEIVED, EXTRACTING, REVIEW, PROMOTED, REJECTED, FAILED)

# Stages whose `detail` is REQUIRED — the two that end an ingest without landing it, so a
# consumer reading the status is told WHY rather than only THAT (ca's IngestStatus rule).
_DETAIL_REQUIRED_STAGES = (REJECTED, FAILED, "review_rejected")

# Out-of-band terminal: a repeat arrival never enters the ladder above (it never extracts,
# never awaits disposition) — it is a DIFFERENT fact, recorded once and done. Kept separate from
# STAGES so a caller walking the ladder in order does not have to reason about a branch that
# isn't one.
DUPLICATE = "duplicate"

# 2026-10-06 (roll #20 item 4): CASE_OPENED -- the EVENT branch's own next step after
# `received` (POST /ingest/events opens a case directly; it never extracts/reviews/promotes).
# OUT OF BAND LIKE DUPLICATE, for the same reason: STAGES mirrors ca's `INGEST_STAGES` exactly
# (test_the_stage_vocabulary_matches_the_sdk_directly seals that), and case_opened is not in
# ca's SDK -- it is this repo's own event-branch extension. Keeping it out of STAGES keeps that
# seal intact; it is still a legal `update_status` target via ALL_STATUSES below.
CASE_OPENED = "case_opened"
# Out-of-band, SAME SHAPE AS DUPLICATE (architect ruling 2026-10-02): a kind whose
# registration declares `domain` EXPLICITLY as null (`pdf`, `engineering-document`,
# `doors-export` -- "origin resolved by evidence, not kind") never enters `review`'s task-filing
# step at all, so it does not belong on the STAGES ladder either -- it is a different fact
# (no audience exists to file a task against), recorded once and done, same as a duplicate
# arrival. Terminal for doc-tools' stage route and for the retry route: any move out of
# `awaiting_origin` through them (including `failed`) is refused 409. The ONE exit is a
# steward's accepted origin (gateway's `write_origin_route`), which files
# `document_promotion:<owner_domain>` and moves the row to `review` (ruling 2026-10-10 Q2,
# superseding 10-02 for the accept branch only). Reject stays terminal and dropper-only.
AWAITING_ORIGIN = "awaiting_origin"
# Out-of-band terminal (steward-correction ruling 2026-10-10): a steward's NARROW REJECT of a grouped
# review (wrong document / not a notice / duplicate) closes the task, writes nothing, and leaves the
# row here. `detail` (the reason_code) is required -- a consumer is told WHY.
REVIEW_REJECTED = "review_rejected"
# Out-of-band (ruling 2026-10-21, spec 203): the header/title read named no confident leaf (pcn|pdn),
# so the row stops HERE, before parts extraction runs, with the candidates on `leaf_candidates`.
# Same shape as AWAITING_ORIGIN: terminal for doc-tools' stage route and the retry route; the ONE exit
# is the dropper's or steward's `POST /ingest/{id}/leaf`, which re-opens the row at `received`.
AWAITING_KIND = "awaiting_kind"
ALL_STATUSES = STAGES + (DUPLICATE, CASE_OPENED, AWAITING_ORIGIN, REVIEW_REJECTED, AWAITING_KIND)

# The notice leaves a drop can carry as its content_kind (single definition; the gateway imports it).
LEAVES = ("pcn", "pdn")
# Where a row's leaf came from (architect ruling 2026-10-21, "Leaf, final shape"): `declared` -- the
# drop carried a leaf (door or delegate); `title` -- read from the document's title; `corrected` -- a
# person changed it (with `leaf_set_by`). Written WHEN the leaf is written, never computed from kind.
LEAF_SOURCES = ("declared", "title", "corrected")

# ContentKind leaves (mesh_system.ttl's ContentKind tree, ADR-0041 §8) — deterministic,
# declared-at-the-door, never LLM-classified (ADR-0021's precedence). XML (2026-10-07) is the
# third leaf, added for the document that needed it: S1000D data modules, which arrive as
# kind=xml with content_kind=s1000d-data-module (the registered kind rides under the format).
# FILE_KINDS is what POST /ingest accepts; each member is a leaf, sealed both ways by
# tests/test_ingest_content_kind_tree.py.
PDF, CAD, XML = "pdf", "cad", "xml"
FILE_KINDS = (PDF, CAD, XML)
# EVENT (roll #20 item 4): not a file format and not a ContentKind leaf -- POST /ingest/events
# never carries bytes, so there is no `ingress-user/<kind>/<sha256>/` object prefix for it
# (the route passes object_prefix=""). Added to KINDS anyway because `record_received`'s own
# `kind` validation is the only gate this value passes through; widening the TUPLE the comment
# above warns against would be the ContentKind registry (`content_kind` column, a separate
# channel) -- this is the file-format/arrival-shape column instead. The multipart door checks
# FILE_KINDS, not KINDS, so a file cannot be dropped as `event`. KINDS spells its names out
# rather than `FILE_KINDS + (EVENT,)` because cortex-ui's parity test parses this tuple by name.
EVENT = "event"
KINDS = (PDF, CAD, XML, EVENT)

# 2026-10-06 (roll #20 item 4): the event branch's own id shape -- gateway.py mints
# `"evt-" + sha256(f"{content_kind}:{identity_value}").hexdigest()` for POST /ingest/events
# (NOT `promotion.ingest_id_for`'s `sha256:<64 hex>`, since an event is never a document
# `document_promotion` would sweep -- it carries no bytes and is never promoted through that
# path). `record_received`'s own id-shape check below is validated against THIS pattern when
# `kind == EVENT`, never against INGEST_ID_RE -- an event id can never satisfy that pattern by
# construction, so checking it there would refuse every real event-door call.
EVENT_INGEST_ID_RE = re.compile(r"^evt-[0-9a-f]{64}$")

# 2026-10-12 (pipeline failure must reach the row): the failure reason_code the WATCHDOG writes
# (`fail_stale_received`). The reason_code vocabulary is otherwise OPEN -- doc-tools owns its codes
# and this repo does not enumerate them -- so the only thing checked is the SHAPE below. `timeout`
# is the one code this repo itself mints, and the stage route treats it as PROVISIONAL (a late run
# supersedes it), so it is named once here for both sides.
REASON_TIMEOUT = "timeout"
REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS ingest_status_projection (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL,
    object_prefix TEXT NOT NULL,
    submitted_by TEXT NOT NULL,
    on_behalf_of TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL,
    extracted_count INTEGER,
    extracted_total INTEGER,
    duplicate_of TEXT,
    detail TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_isp_submitted_by ON ingest_status_projection (submitted_by);
CREATE INDEX IF NOT EXISTS idx_isp_on_behalf_of ON ingest_status_projection (on_behalf_of);
CREATE INDEX IF NOT EXISTS idx_isp_status ON ingest_status_projection (status);
CREATE INDEX IF NOT EXISTS idx_isp_sha256 ON ingest_status_projection (sha256);

-- 2026-10-03: 'awaiting_disposition' renamed to 'review' (ingest/origin seam, lane/01-seam) --
-- SDK 0.9.7's iagent_mesh.ingest.INGEST_STAGES ships 'review'; no CHECK constraint existed to
-- amend, but a row already written under the old name must be updated or it stops matching
-- STAGES/ALL_STATUSES below. IDEMPOTENT -- a second run matches zero rows.
UPDATE ingest_status_projection SET status = 'review' WHERE status = 'awaiting_disposition';

-- 2026-10-03: origin_suggestion (ingest/origin seam section 6) -- NULLABLE, JSON text; see
-- sql/create_ingest_status_projection.sql's matching comment for why. IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS origin_suggestion TEXT;

-- 2026-10-06: content_kind (review-audience fix) -- NULLABLE. `kind` stays the FILE FORMAT
-- (pdf|cad|xml); this column carries the DECLARED, registry-level content kind (the `content_kind`
-- form field on POST /ingest) so a later stage move can resolve the promotion audience's domain
-- from the registry rather than from the file format. NULL for undeclared drops and for every
-- row written before this column existed. IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS content_kind TEXT;

-- 2026-10-08: extraction_ref -- NULLABLE. The versioned manifest key doc-tools' review POST names
-- (`{base_dir}/generated/{base_name}/{pipeline_version}/manifest.json`); a retry re-derives the
-- promotion task's payload from it. NULL for every row that reached review before this column
-- existed. IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS extraction_ref TEXT;

-- 2026-10-06 (roll #20 item 4): case_id -- NULLABLE. Set only once `POST /ingest/events` has
-- confirmed the case runner actually opened the case (status moves received -> case_opened in
-- the SAME write); NULL while a row sits at `received` and for every row the file-branch door
-- writes (a document never opens a case). IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS case_id TEXT;

-- 2026-10-12 (pipeline failure must reach the row, architect directive): `failure` is JSON text,
-- NULL unless the row is `failed` ({reason_code, reason, step, run_id, pin_digest, failed_at});
-- `run_id` is the last Dagster run id a stage POST reported; `attempt` counts re-opens of a failed
-- row (POST /ingest/{id}/retry), starting at 1. IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS failure TEXT;
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1;

-- 2026-10-13: `notice_id` is the notice's OWN id (e.g. PCN26-184) as the extraction manifest's
-- `doc_id` names it, written when the row moves to review. DISPLAY ONLY, never an identity (it is
-- LLM-extracted). NULL until known. IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS notice_id TEXT;

-- 2026-10-21 (spec 203, the leaf on the row): where the row's leaf came from (declared|title|corrected),
-- the candidates an `awaiting_kind` hold lists (JSON list text), and who/when set the leaf last.
-- All NULLABLE, all IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS leaf_source TEXT;
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS leaf_candidates TEXT;
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS leaf_set_by TEXT;
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS leaf_set_at BIGINT;

-- 2026-10-21 (spec 203b): one-time, idempotent backfill. This is a WRITE of a fact, not an inference:
-- before spec 203 the only writers of a leaf `content_kind` (pcn|pdn) were the drop's form field and
-- the manifest adoption of the drop's sidecar kind, so every such row was declared at the drop.
UPDATE ingest_status_projection SET leaf_source = 'declared' WHERE leaf_source IS NULL AND kind <> 'event' AND lower(content_kind) IN ('pcn','pdn');

-- 2026-10-21 (spec 204, a leaf change at review replaces the task): the promotion task's GENERATION.
-- 0 for every legacy row (its task id is `document_promotion:<id>`); a re-class or re-run at review
-- bumps it, and generation g > 0 names the task `document_promotion:<id>:g<g>`. IDEMPOTENT.
ALTER TABLE ingest_status_projection ADD COLUMN IF NOT EXISTS review_generation INTEGER NOT NULL DEFAULT 0;
"""


class IngestStatusConfigError(RuntimeError):
    """Raised when the substrate is asked to operate without its backing config (PG DSN).
    Fail LOUD — never silently no-op a security surface. Same posture as HumanTaskConfigError."""


def _pg_connect():
    if not _PG_DSN:
        raise IngestStatusConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def apply_migration() -> None:
    """Create ingest_status_projection if absent. Called at cortex-bff startup.
    No-op (logged by caller) when PG DSN unset so local/dev boot doesn't crash."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


def find_primary_by_sha(sha256: str) -> Optional[dict[str, Any]]:
    """The earliest non-duplicate row for this sha256, or None if this content has never
    landed before. This IS the level-1 dedupe check (ADR-0041 §8) — a hit means "already
    processed", a miss means a genuinely new arrival."""
    if not sha256:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of,
                          source, status, created_at, content_kind
                     FROM ingest_status_projection
                    WHERE sha256 = %s AND status != %s
                    ORDER BY created_at ASC
                    LIMIT 1""",
                (sha256, DUPLICATE),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def _declared_leaf(content_kind, submitted_by, now) -> dict[str, Any]:
    """The drop WRITES the leaf's source (spec 203b): a `content_kind` that is a leaf, lowercased and
    stripped, is `declared` by the submitter at `now`; anything else leaves the three columns NULL."""
    if str(content_kind or "").strip().lower() in LEAVES:
        return {"leaf_source": "declared", "leaf_set_by": submitted_by, "leaf_set_at": now}
    return {"leaf_source": None, "leaf_set_by": None, "leaf_set_at": None}


def record_received(
    *,
    ingest_id: str,
    sha256: str,
    kind: str,
    object_prefix: str,
    submitted_by: str,
    on_behalf_of: str,
    source: Optional[str] = None,
    content_kind: Optional[str] = None,
) -> dict[str, Any]:
    """A genuinely new arrival: one row, id = ingest_id. For `kind in (PDF, CAD)`, `ingest_id`
    must be `promotion.ingest_id_for(body)` — the SAME derivation `document_promotion` requires
    (`promotion.INGEST_ID_RE`) — so a seam-minted document is never refused promotion for a
    spelling mismatch. This is a DIFFERENT spelling from `sha256` (bare hex): the row keeps
    `sha256` as its own column (the dedupe key, and the `ingress-user/{kind}/{sha256}/` object
    prefix) while `id` carries the `sha256:<64 hex>` form. status = received.

    For `kind == EVENT` (roll #20 item 4), `ingest_id` is instead gateway.py's own
    `"evt-" + sha256(...)` mint (`EVENT_INGEST_ID_RE`) — an event is never a document
    `document_promotion` would sweep (no bytes, no promotion path), so `INGEST_ID_RE` is not
    the right shape to check it against; checking it there would refuse every real event-door
    call.

    `content_kind` is the DECLARED, registry-level kind (POST /ingest's `content_kind` form
    field) — None when undeclared. `kind` stays the file format, unchanged.

    ON CONFLICT (id) DO NOTHING (2026-10-06, roll #20 item 4): a repeat `POST /ingest/events`
    for an event_id already holding a row would otherwise crash this write on the PRIMARY KEY
    rather than leave the existing row alone -- the caller (the events door's repeat/backfill
    path) already checked `get_row` first, so this is a race guard, not the normal path. Returns
    the row ACTUALLY in the table afterwards (the existing one on a conflict, the one just
    inserted otherwise) rather than the attempted dict, so a caller never gets back a row
    that disagrees with what a concurrent writer actually landed."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    _id_re = EVENT_INGEST_ID_RE if kind == EVENT else INGEST_ID_RE
    if not _id_re.match(ingest_id or ""):
        raise ValueError(
            f"ingest_id must match {_id_re.pattern!r}, got {ingest_id!r} — a "
            f"mis-spelled id is one `document_promotion` refuses to sweep")
    now = int(time.time() * 1000)
    row = {
        "id": ingest_id, "sha256": sha256, "kind": kind, "object_prefix": object_prefix,
        "submitted_by": submitted_by, "on_behalf_of": on_behalf_of, "source": source,
        "status": RECEIVED, "extracted_count": None, "extracted_total": None,
        "duplicate_of": None, "detail": None, "created_at": now, "updated_at": now,
        "content_kind": content_kind,
        **_declared_leaf(content_kind, submitted_by, now),
    }
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingest_status_projection
                   (id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                    status, extracted_count, extracted_total, duplicate_of, detail,
                    created_at, updated_at, content_kind,
                    leaf_source, leaf_set_by, leaf_set_at)
                   VALUES (%(id)s, %(sha256)s, %(kind)s, %(object_prefix)s, %(submitted_by)s,
                           %(on_behalf_of)s, %(source)s, %(status)s, %(extracted_count)s,
                           %(extracted_total)s, %(duplicate_of)s, %(detail)s,
                           %(created_at)s, %(updated_at)s, %(content_kind)s,
                           %(leaf_source)s, %(leaf_set_by)s, %(leaf_set_at)s)
                   ON CONFLICT (id) DO NOTHING""",
                row,
            )
            # rowcount == 0 means ON CONFLICT DO NOTHING actually fired -- a row for this id
            # already existed (the race the docstring above describes). Re-fetch and return
            # what is REALLY there instead of the attempted (and not written) dict -- a caller
            # must never be told its own write landed when a concurrent one got there first.
            conflicted = cur.rowcount == 0
            if conflicted:
                cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                with cur2:
                    cur2.execute(
                        """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of,
                                  source, status, extracted_count, extracted_total,
                                  duplicate_of, detail, created_at, updated_at, content_kind,
                                  case_id
                             FROM ingest_status_projection WHERE id = %s""",
                        (ingest_id,),
                    )
                    existing = cur2.fetchone()
        conn.commit()
    if conflicted:
        return dict(existing) if existing else row
    return row


def record_duplicate_arrival(
    *,
    sha256: str,
    kind: str,
    object_prefix: str,
    submitted_by: str,
    on_behalf_of: str,
    source: Optional[str],
    original: dict[str, Any],
    content_kind: Optional[str] = None,
) -> dict[str, Any]:
    """A repeat arrival of content already processed. ADR-0041 §8: "records the arrival as
    provenance" — so this WRITES a new row (id = fresh uuid, status = duplicate,
    duplicate_of = original['id']) rather than silently discarding the second drop. The
    caller-facing message ("already processed on <date> from <source>") is derived from
    `original`, not restated here — see gateway.py's ingest route.

    `content_kind` is THIS arrival's own declared kind (not `original`'s) — None when
    undeclared."""
    now = int(time.time() * 1000)
    from datetime import datetime, timezone
    processed_on = datetime.fromtimestamp(
        original["created_at"] / 1000, tz=timezone.utc
    ).date().isoformat()
    detail = f"already processed on {processed_on} from {original.get('source') or 'unknown source'}"
    row = {
        "id": str(uuid.uuid4()), "sha256": sha256, "kind": kind, "object_prefix": object_prefix,
        "submitted_by": submitted_by, "on_behalf_of": on_behalf_of, "source": source,
        "status": DUPLICATE, "extracted_count": None, "extracted_total": None,
        "duplicate_of": original["id"], "detail": detail, "created_at": now, "updated_at": now,
        "content_kind": content_kind,
        **_declared_leaf(content_kind, submitted_by, now),
    }
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingest_status_projection
                   (id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                    status, extracted_count, extracted_total, duplicate_of, detail,
                    created_at, updated_at, content_kind,
                    leaf_source, leaf_set_by, leaf_set_at)
                   VALUES (%(id)s, %(sha256)s, %(kind)s, %(object_prefix)s, %(submitted_by)s,
                           %(on_behalf_of)s, %(source)s, %(status)s, %(extracted_count)s,
                           %(extracted_total)s, %(duplicate_of)s, %(detail)s,
                           %(created_at)s, %(updated_at)s, %(content_kind)s,
                           %(leaf_source)s, %(leaf_set_by)s, %(leaf_set_at)s)""",
                row,
            )
        conn.commit()
    return row


def _parse_failure(raw: Any) -> Optional[dict[str, Any]]:
    """`failure` is stored as JSON text; a dict (or None) is what a consumer sees. A malformed
    value reads as None rather than raising -- the status route then synthesises from `detail`."""
    if not raw:
        return None
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return val if isinstance(val, dict) else None


def _parse_candidates(raw: Any) -> Optional[list]:
    """`leaf_candidates` is stored as JSON list text; a list (or None) is what a consumer sees."""
    if not raw:
        return None
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return list(val) if isinstance(val, list) else None


def get_row(ingest_id: str) -> Optional[dict[str, Any]]:
    """The row for `ingest_id`, unscoped to any caller, or None if it does not exist.

    Deliberately NOT caller-scoped (unlike `get_status_for`, which is existence-oracle-safe
    by scoping to `submitted_by`/`on_behalf_of`): this is asked by a SERVICE identity (the
    doc-tools pipeline) about an ingest_id it was already handed at drop time, not by an
    end user browsing a queue -- same reasoning as `human_tasks.task_exists`'s own docstring.
    The caller-facing gate here is the route's service-identity check, not row scoping."""
    if not ingest_id:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                          status, extracted_count, extracted_total, duplicate_of, detail,
                          created_at, updated_at, content_kind, extraction_ref,
                          failure, run_id, attempt, notice_id,
                          leaf_source, leaf_candidates, leaf_set_by, leaf_set_at, review_generation
                     FROM ingest_status_projection
                    WHERE id = %s""",
                (ingest_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    out["failure"] = _parse_failure(out.get("failure"))
    out["leaf_candidates"] = _parse_candidates(out.get("leaf_candidates"))
    return out


def update_status(
    ingest_id: str,
    status: str,
    *,
    extracted_count: Optional[int] = None,
    extracted_total: Optional[int] = None,
    detail: Optional[str] = None,
    case_id: Optional[str] = None,
    extraction_ref: Optional[str] = None,
    failure: Optional[dict] = None,
    run_id: Optional[str] = None,
    notice_id: Optional[str] = None,
    content_kind: Optional[str] = None,
) -> None:
    """Advance a row through the ladder (received -> extracting -> review ->
    promoted|rejected|failed), or (received -> case_opened) on the event branch. Not called by
    the ingest route itself for a DOCUMENT arrival (which only ever writes `received`) — this is
    the seam the classifier/extraction/review pipeline and the document_promotion fulfillment
    call as a document progresses. The EVENT door (`POST /ingest/events`) is the one caller that
    moves a row to `case_opened`, carrying `case_id` (roll #20 item 4).

    `detail` is REQUIRED (non-blank) on `rejected`/`failed` — ca's IngestStatus rule: a
    terminal state with no reason reaches an operator as "something happened" and is
    unactionable.

    `case_id` is OPTIONAL and additive: omitted (None), the column is left as it was
    (COALESCE), same discipline as `detail`/`extracted_count`/`extracted_total` above --
    a call that only moves the stage never has to restate a case_id it already wrote.

    `extraction_ref` is the versioned manifest key doc-tools' review POST names; same discipline:
    written only when given, never cleared by a call that omits it.

    `failure` (2026-10-12) is the structured reason {reason_code, reason, step, run_id, pin_digest,
    failed_at}; it is valid ONLY with status `failed` (ValueError otherwise). Any OTHER status
    writes `failure = NULL`, so a move off `failed` (a late run superseding a watchdog timeout)
    clears it. `run_id` follows the COALESCE discipline: written only when given.

    `notice_id` (2026-10-13) is the extraction manifest's `doc_id`, DISPLAY ONLY; same COALESCE
    discipline: None leaves it unchanged, so a later stage move never erases it.

    `content_kind` (architect ruling 2026-10-16) is the kind the review ADOPTED from the extraction
    manifest for a row the drop left NULL. It is written ONLY WHERE THE COLUMN IS NULL
    (`COALESCE(content_kind, %s)`): a kind the dropper declared is never overwritten by what the
    extractor later says, and None leaves the column as it was. When that COALESCE fills a NULL column
    with a leaf (pcn|pdn) the SAME UPDATE sets `leaf_source='declared'` (only where it is NULL): the
    sidecar kind is the drop's declaration, adopted."""
    if status not in ALL_STATUSES:
        raise ValueError(f"status must be one of {ALL_STATUSES}, got {status!r}")
    if status in _DETAIL_REQUIRED_STAGES and not (detail and detail.strip()):
        raise ValueError(
            f"update_status(status={status!r}) requires a non-blank detail — a {status!r} "
            f"with no reason is unactionable (ca's IngestStatus rule)")
    if failure is not None and status != FAILED:
        raise ValueError(f"update_status(failure=...) is valid only with status {FAILED!r}, "
                         f"got {status!r}")
    failure_json = json.dumps(failure) if (status == FAILED and failure is not None) else None
    now = int(time.time() * 1000)
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ingest_status_projection
                      SET status = %s, extracted_count = COALESCE(%s, extracted_count),
                          extracted_total = COALESCE(%s, extracted_total),
                          detail = COALESCE(%s, detail), case_id = COALESCE(%s, case_id),
                          extraction_ref = COALESCE(%s, extraction_ref),
                          failure = %s, run_id = COALESCE(%s, run_id),
                          notice_id = COALESCE(%s, notice_id),
                          content_kind = COALESCE(content_kind, %s),
                          leaf_source = CASE WHEN content_kind IS NULL AND leaf_source IS NULL
                                              AND lower(trim(%s)) IN ('pcn','pdn')
                                             THEN 'declared' ELSE leaf_source END,
                          updated_at = %s
                    WHERE id = %s""",
                (status, extracted_count, extracted_total, detail, case_id, extraction_ref,
                 failure_json, run_id, notice_id, content_kind, content_kind, now, ingest_id),
            )
        conn.commit()


def set_leaf(ingest_id: str, leaf: str, source: str, *, set_by: str, from_statuses,
             to_status: Optional[str] = None, bump_attempt: bool = False,
             bump_generation: bool = False, expect_generation: Optional[int] = None,
             now_ms: Optional[int] = None) -> Optional[dict]:
    """Write the row's leaf (spec 203): ONE atomic guarded UPDATE ... RETURNING. `content_kind` is
    OVERWRITTEN (not COALESCEd -- a correction must beat what the drop declared), `leaf_source`,
    `leaf_set_by`, `leaf_set_at` and `updated_at` are written and `leaf_candidates` cleared. With
    `to_status` the stage moves in the same write; with `bump_attempt` the row is re-opened for a
    relaunch (`attempt` + 1, `failure` and `detail` cleared). The guard is
    `status = ANY(from_statuses) AND kind <> 'event'`; a `title` source additionally requires the
    row's `leaf_source` to be NULL or already `title`, so a title never overwrites a declared
    or corrected leaf. Spec 204: `bump_generation` adds 1 to `review_generation` (the promotion
    task's generation) in the same write; `expect_generation` adds `AND review_generation = %s` to the
    guard, so a write that lost a race to another generation bump matches nothing. Returns the updated
    row as a dict, or None if nothing matched."""
    if leaf not in LEAVES:
        raise ValueError(f"leaf must be one of {LEAVES}, got {leaf!r}")
    if source not in LEAF_SOURCES:
        raise ValueError(f"source must be one of {LEAF_SOURCES}, got {source!r}")
    if to_status is not None and to_status not in ALL_STATUSES:
        raise ValueError(f"to_status must be one of {ALL_STATUSES}, got {to_status!r}")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    sets = ["content_kind = %s", "leaf_source = %s", "leaf_set_by = %s", "leaf_set_at = %s",
            "updated_at = %s", "leaf_candidates = NULL"]
    params: list[Any] = [leaf, source, set_by, now, now]
    if to_status is not None:
        sets.append("status = %s")
        params.append(to_status)
    if bump_attempt:
        sets += ["attempt = attempt + 1", "failure = NULL", "detail = NULL"]
    if bump_generation:
        sets.append("review_generation = review_generation + 1")
    where = "id = %s AND status = ANY(%s) AND kind <> 'event'"
    params += [ingest_id, list(from_statuses)]
    if expect_generation is not None:
        where += " AND review_generation = %s"
        params.append(int(expect_generation))
    if source == "title":
        where += " AND (leaf_source IS NULL OR leaf_source = 'title')"
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"UPDATE ingest_status_projection SET {', '.join(sets)} WHERE {where} RETURNING *",
                tuple(params),
            )
            r = cur.fetchone()
        conn.commit()
    if not r:
        return None
    out = dict(r)
    out["failure"] = _parse_failure(out.get("failure"))
    out["leaf_candidates"] = _parse_candidates(out.get("leaf_candidates"))
    return out


def list_leafless_extracting(*, older_than_seconds: int, limit: int = 50,
                             now_ms: Optional[int] = None) -> list[dict]:
    """Document rows at `extracting` whose last stage move is older than `older_than_seconds` and
    that carry NO leaf (`content_kind` not pcn/pdn), oldest first, LIMIT `limit` (spec 204, the
    manifest-leaf backstop). EVENT rows never appear. Read-only; the caller decides leaf-capability."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, kind, object_prefix, content_kind, leaf_source, status, updated_at,
                          attempt, review_generation
                     FROM ingest_status_projection
                    WHERE status = 'extracting' AND kind <> 'event' AND updated_at < %s
                      AND (content_kind IS NULL OR NOT (lower(content_kind) = ANY(%s)))
                    ORDER BY updated_at ASC, id ASC
                    LIMIT %s""",
                (now - older_than_seconds * 1000, list(LEAVES), limit),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def hold_for_kind(ingest_id: str, *, candidates, detail: str, run_id: Optional[str] = None,
                  from_statuses) -> bool:
    """Park a row at `awaiting_kind` (spec 203): the title read named no confident leaf. ONE guarded
    UPDATE; `candidates` is a list of `{leaf, score, evidence_ref}` dicts: an entry is kept only when
    its `leaf` (lowercased) is in LEAVES, later duplicates of a leaf are dropped, the list is sorted
    by `score` descending (stable), capped at 3 and stored as JSON list text of
    `{"leaf", "score", "evidence_ref": {page, bbox[, note]}}` (`note` dropped when None). The guard also refuses a row that already carries a leaf (`content_kind` pcn/pdn): a
    correction that landed between the caller's read and this write must win, never be held. True
    when a row matched, False otherwise."""
    seen: list[dict] = []
    for c in candidates or []:
        c = c if isinstance(c, dict) else {}
        leaf = str(c.get("leaf") or "").strip().lower()
        if leaf not in LEAVES or any(x["leaf"] == leaf for x in seen):
            continue
        ev = c.get("evidence_ref")
        if hasattr(ev, "model_dump"):
            ev = ev.model_dump()
        ev = dict(ev or {})
        if ev.get("note") is None:
            ev.pop("note", None)
        seen.append({"leaf": leaf, "score": c.get("score"), "evidence_ref": ev})
    seen.sort(key=lambda x: x["score"] if x["score"] is not None else 0, reverse=True)
    seen = seen[:3]
    now = int(time.time() * 1000)
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ingest_status_projection
                      SET status = 'awaiting_kind', leaf_candidates = %s, detail = %s,
                          run_id = COALESCE(%s, run_id), updated_at = %s
                    WHERE id = %s AND status = ANY(%s) AND kind <> 'event'
                      AND (content_kind IS NULL OR NOT (content_kind = ANY(%s)))""",
                (json.dumps(seen), detail, run_id, now, ingest_id, list(from_statuses),
                 list(LEAVES)),
            )
            n = cur.rowcount
        conn.commit()
    return n > 0


def record_origin_suggestion(ingest_id: str, suggestion: dict[str, Any]) -> None:
    """Record an `origin_resolver.resolve()` hit on the arrival's own row (section 6).
    `suggestion` is stored as JSON text -- see the column's migration comment. Never called for
    a miss (`resolve() -> None`); the column simply stays NULL, which `get_status_for` reports
    as `None`, not as "resolution pending" -- there is no third state here."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingest_status_projection SET origin_suggestion = %s WHERE id = %s",
                (json.dumps(suggestion), ingest_id),
            )
        conn.commit()


def get_status_unscoped(ingest_id: str) -> Optional[dict[str, Any]]:
    """The status row for `ingest_id` with NO caller scoping. ONLY for a route that has already
    proved the caller is a SERVICE (the pin-driven retry): a person must never reach this, because
    the scoped lookup above is what keeps another user's queue invisible. `pin_digest` is the row's
    recorded extractor pin when the projection carries one (the column is a follow-up; absent -> the
    key is simply missing and the retry refuses `no_recorded_pin`)."""
    if not ingest_id:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                          status, extracted_count, extracted_total, duplicate_of, detail,
                          created_at, updated_at, origin_suggestion, content_kind, case_id,
                          extraction_ref, failure, run_id, attempt, notice_id,
                          leaf_source, leaf_candidates, leaf_set_by, leaf_set_at, review_generation
                     FROM ingest_status_projection
                    WHERE id = %s""",
                (ingest_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    out["origin_suggestion"] = json.loads(out["origin_suggestion"]) if out.get("origin_suggestion") else None
    out["failure"] = _parse_failure(out.get("failure"))
    out["leaf_candidates"] = _parse_candidates(out.get("leaf_candidates"))
    return out


def get_status_for(ingest_id: str, *, caller_id: str) -> Optional[dict[str, Any]]:
    """The status of an ingest THIS caller submitted or is the on_behalf_of principal for, or
    None otherwise.

    EXISTENCE-ORACLE SAFE BY SCOPING: filtered on `submitted_by = caller OR on_behalf_of =
    caller`, exactly like `human_tasks.get_task_resolution`'s `recipient_id = caller` scoping —
    a caller who is neither gets None, indistinguishable from "no such ingest", preserving the
    deny-by-default 404 and never revealing another user's queue.

    `origin_suggestion` is parsed back from its stored JSON text to a dict, or left `None` when
    the column is NULL (no suggestion was ever recorded for this row).
    """
    if not ingest_id or not caller_id:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                          status, extracted_count, extracted_total, duplicate_of, detail,
                          created_at, updated_at, origin_suggestion, content_kind, case_id,
                          extraction_ref, failure, run_id, attempt, notice_id,
                          leaf_source, leaf_candidates, leaf_set_by, leaf_set_at, review_generation
                     FROM ingest_status_projection
                    WHERE id = %s AND (submitted_by = %s OR on_behalf_of = %s)""",
                (ingest_id, caller_id, caller_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    out["origin_suggestion"] = json.loads(out["origin_suggestion"]) if out.get("origin_suggestion") else None
    out["failure"] = _parse_failure(out.get("failure"))
    out["leaf_candidates"] = _parse_candidates(out.get("leaf_candidates"))
    return out


def list_mine(*, caller_id: str, limit: int,
              before: Optional[tuple[int, str]] = None) -> list[dict]:
    """The document drops THIS caller submitted or is the on_behalf_of principal for, newest first
    (architect ruling 2026-10-16, GET /ingest/mine). Same columns and the same `origin_suggestion` /
    `failure` parsing as `get_status_for`, and the same EXISTENCE-ORACLE scoping
    (`submitted_by = caller OR on_behalf_of = caller`), so another user's rows are never listed.
    EVENT rows are excluded, as in `list_pending_retries`: a drop is a document.

    Keyset paging, never OFFSET: `before` is `(created_at, id)` of the last row already seen and
    the next page is everything strictly older in `(created_at DESC, id DESC)` order. An empty
    `caller_id` lists nothing and does not query."""
    if not caller_id:
        return []
    sql = """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                    status, extracted_count, extracted_total, duplicate_of, detail,
                    created_at, updated_at, origin_suggestion, content_kind, case_id,
                    extraction_ref, failure, run_id, attempt, notice_id,
                          leaf_source, leaf_candidates, leaf_set_by, leaf_set_at, review_generation
               FROM ingest_status_projection
              WHERE (submitted_by = %s OR on_behalf_of = %s) AND kind <> 'event'"""
    params: list[Any] = [caller_id, caller_id]
    if before is not None:
        sql += " AND (created_at, id) < (%s, %s)"
        params += [before[0], before[1]]
    sql += """
              ORDER BY created_at DESC, id DESC
              LIMIT %s"""
    params.append(limit)
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["origin_suggestion"] = json.loads(d["origin_suggestion"]) if d.get("origin_suggestion") else None
        d["failure"] = _parse_failure(d.get("failure"))
        d["leaf_candidates"] = _parse_candidates(d.get("leaf_candidates"))
        out.append(d)
    return out


def fail_stalled(*, stage: str, older_than_seconds: int, now_ms: Optional[int] = None) -> list[str]:
    """The WATCHDOG (2026-10-12, pipeline failure must reach the row; extended to `extracting`
    2026-10-16): mark every document row that has sat at `stage` for longer than
    `older_than_seconds` as `failed:timeout`, naming the stage in `failure.step`, and return the
    ids. ONE atomic UPDATE ... RETURNING, so two BFF replicas ticking at once cannot both claim a
    row, and the `status = <stage>` predicate is re-evaluated at write time.

    Only RECEIVED and EXTRACTING are watched (ValueError otherwise). `review`,
    `awaiting_origin` and `awaiting_kind` are deliberately NOT: each waits on a steward's human decision, which is not
    a pipeline stall, and failing it would discard a task a person is still entitled to act on.

    EVENT rows are excluded: an event row at `received` is the case runner's fact, not the
    pipeline's (POST /ingest/events moves it to `case_opened`, or it stays because the runner
    refused), and its fix is to resend the event -- a pipeline timeout would be a false claim.

    `failure` is built in SQL so each row carries its OWN `run_id` (the last run a stage POST
    reported, if any). `pin_digest` is NULL: a timeout means nothing ran far enough to pin."""
    if stage not in (RECEIVED, EXTRACTING):
        raise ValueError(f"fail_stalled watches only {RECEIVED!r} and {EXTRACTING!r}, got {stage!r}")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    where = "of arrival" if stage == RECEIVED else f"of entering {EXTRACTING}"
    reason = f"no stage move was reported within {older_than_seconds} seconds {where}"
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ingest_status_projection
                      SET status = 'failed', updated_at = %s, detail = %s,
                          failure = jsonb_build_object(
                              'reason_code', %s::text, 'reason', %s::text, 'step', %s::text,
                              'run_id', run_id, 'pin_digest', NULL, 'failed_at', %s::bigint)::text
                    WHERE status = %s AND kind <> 'event' AND updated_at < %s
                RETURNING id""",
                (now, reason, REASON_TIMEOUT, reason, stage, now, stage,
                 now - older_than_seconds * 1000),
            )
            ids = [r[0] for r in cur.fetchall()]
        conn.commit()
    return ids


def fail_stale_received(*, older_than_seconds: int, now_ms: Optional[int] = None) -> list[str]:
    """The `received` half of the watchdog; see `fail_stalled`."""
    return fail_stalled(stage=RECEIVED, older_than_seconds=older_than_seconds, now_ms=now_ms)


def list_pending_retries(*, limit: int) -> list[dict]:
    """Retried document drops awaiting relaunch (architect ruling 2026-10-12, Shape 1): rows at
    `received` whose `attempt` is above 1, oldest first. `retry_failed` re-opens a row at
    `received` with `attempt` + 1, but doc-tools' sensor cannot see it again (its S3 cursor has
    passed the object), so doc-tools polls this listing and launches each entry with the Dagster
    run_key `{id}-a{attempt}`. A first attempt (`attempt` = 1) is the sensor's own and is never
    listed. EVENT rows are excluded for the same reason as in `fail_stale_received`. Read-only."""
    keys = ("id", "attempt", "kind", "content_kind", "object_prefix", "sha256", "run_id",
            "updated_at")
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, attempt, kind, content_kind, object_prefix, sha256, run_id, updated_at
                     FROM ingest_status_projection
                    WHERE status = 'received' AND attempt > 1 AND kind <> 'event'
                    ORDER BY updated_at ASC, id ASC
                    LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
    return [dict(zip(keys, r)) for r in rows]


def retry_failed(ingest_id: str, *, now_ms: Optional[int] = None) -> Optional[int]:
    """Re-open a `failed` document row at `received` (2026-10-12): clears `failure` and `detail`,
    bumps `attempt`, and returns the NEW attempt -- or None if no row matched. ONE atomic UPDATE:
    the `status = 'failed'` condition makes two concurrent retries safe (the second matches nothing
    and gets None). Event rows never match (their fix is to resend the event). This only re-opens
    the row; it does not relaunch the pipeline."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ingest_status_projection
                      SET status = 'received', failure = NULL, detail = NULL,
                          attempt = attempt + 1, updated_at = %s
                    WHERE id = %s AND status = 'failed' AND kind <> 'event'
                RETURNING attempt""",
                (now, ingest_id),
            )
            r = cur.fetchone()
        conn.commit()
    return r[0] if r else None


def ingests_naming_notice(notice_id: str, *, exclude_ingest_id: str) -> list[str]:
    """The ingest ids of OTHER arrivals whose status row names `notice_id`, oldest first. The
    graph's SUBJECT_TO edge carries no ingest id, so this is the best available attribution of a
    stale edge to an earlier ingest: a candidate list, not proof."""
    if not notice_id:
        return []
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM ingest_status_projection
                    WHERE notice_id = %s AND id <> %s
                    ORDER BY created_at""",
                (notice_id, exclude_ingest_id),
            )
            rows = cur.fetchall()
    return [r[0] for r in rows]
