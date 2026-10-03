-- Ingestion seam (ADR-0041 §8, 2026-09-30) — the ingest_status projection.
--
-- SAME SHAPE as human_task_projection (sql/create_human_task_projection.sql): idempotent
-- (IF NOT EXISTS), applied at cortex-bff startup, lives in the same Electric-replicated
-- Postgres, subscribed through the same cortex-bff `/electric/shape` proxy.
--
-- ONE ROW PER ARRIVAL, not one row per document. A genuinely new document (new sha256) gets
-- ONE row at id = sha256 (content-addressed, same convention mesh:body_sha's comment in
-- mesh_system.ttl already uses for doc pages: "a stale object impossible rather than merely
-- detectable"). A REPEAT arrival of a sha256 that already has a row (level-1 dedupe, ADR-0041
-- §8) gets its OWN row — id = a fresh uuid, status = 'duplicate', duplicate_of = the original
-- row's id — because ADR-0041 says the dedupe response "records the arrival as provenance": a
-- second drop of the same bytes is a FACT about who tried to (re)submit it and when, and
-- collapsing it into the original row would erase that fact rather than record it.
--
-- VIEWABILITY: GET /ingest/<id>/status is for the SUBMITTER or the ON_BEHALF_OF principal only
-- (ADR-0041 §8's upload gate: authenticated identity, deny-by-default). Two columns, not one,
-- because `on_behalf_of` can differ from the caller (this seam's on_behalf_of check requires
-- them to be equal in v1 — see ingest_status.py — but the schema does not bake that narrowness
-- in; a future delegated-submission case only needs the check relaxed, not a migration).
--
-- submitted_by / on_behalf_of hold the AUTHZ identity (authz_id = the USER_ENTITLEMENT_CLAIM
-- key: email in sandbox, employee-ID at work-deploy) — same discipline as recipient_id on
-- human_task_projection, for the same reason (no sub<->email bridge to mis-route).

CREATE TABLE IF NOT EXISTS ingest_status_projection (
    -- Content-addressed for a primary row (id = sha256); a fresh uuid for a duplicate-arrival
    -- log row (see the header note above).
    id TEXT PRIMARY KEY,

    -- The uploaded bytes' SHA-256, hex — computed AT THE DOOR (ADR-0041 §8). The level-1 dedupe
    -- key: a second arrival with the same sha256 is the SAME bytes, full stop.
    sha256 TEXT NOT NULL,

    -- ContentKind leaf (ADR-0041 §8's ContentKind tree, mesh_system.ttl): 'pdf' | 'cad' today.
    -- DECLARED at the door (multipart field), never LLM-classified — ADR-0021's precedence.
    kind TEXT NOT NULL,

    -- The object-store prefix this arrival was (or would have been) written under:
    -- ingress-user/<kind>/<sha256>/ (ADR-0041 §2). Recorded even on a duplicate row, so the
    -- dedupe message ("already processed on <date> from <source>") can point at where the
    -- ORIGINAL bytes actually live.
    object_prefix TEXT NOT NULL,

    -- VIEWABILITY FILTER COLUMNS (plain TEXT — Electric rejects generated columns, same lesson
    -- as produced_for_user_id / recipient_id). The proxy injects
    -- `(submitted_by = '<caller>' OR on_behalf_of = '<caller>')` for this table.
    submitted_by TEXT NOT NULL,   -- who called POST /ingest (the authenticated caller)
    on_behalf_of TEXT NOT NULL,   -- who this ingest is attributed to (== submitted_by in v1)

    -- Original filename / declared source, for the dedupe message and audit. Clearance-SAFE by
    -- construction — a filename, never document content.
    source TEXT,

    -- Lifecycle (ADR-0041 §8), mirroring `iagent_mesh.ingest.INGEST_STAGES` (ca b68926a):
    -- 'received' -> 'extracting' -> 'review' -> 'promoted' | 'rejected' |
    -- 'failed'. Plus the out-of-band terminal 'duplicate' for a repeat arrival (see header
    -- note). The column keeps the name `status` (Electric subscribers already read it); only
    -- the vocabulary changed. NO DEFAULT (the writer knows the value).
    status TEXT NOT NULL,

    -- 'extracted n/m' — populated once extraction starts; NULL before then and on a duplicate
    -- row (a duplicate never extracts).
    extracted_count INTEGER,
    extracted_total INTEGER,

    -- Set only on a 'duplicate' row: the id of the primary row this arrival duplicates.
    duplicate_of TEXT,

    -- Free-text status detail — the dedupe message, a rejection reason, etc. Clearance-bounded
    -- (reference + summary, never document content), same discipline as human_task_projection's
    -- `summary`/`comment`.
    detail TEXT,

    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_isp_submitted_by
    ON ingest_status_projection (submitted_by);
CREATE INDEX IF NOT EXISTS idx_isp_on_behalf_of
    ON ingest_status_projection (on_behalf_of);
CREATE INDEX IF NOT EXISTS idx_isp_status
    ON ingest_status_projection (status);
CREATE INDEX IF NOT EXISTS idx_isp_sha256
    ON ingest_status_projection (sha256);

-- 2026-10-03: 'awaiting_disposition' renamed to 'review' (ingest/origin seam, lane/01-seam) --
-- SDK 0.9.7's `iagent_mesh.ingest.INGEST_STAGES` ships 'review', not the name this repo had
-- mirrored ahead of a tag (lane/ca commit b68926a). No CHECK constraint on `status` to amend
-- (there never was one), but any row already written under the old name needs updating or it
-- stops matching `ingest_status.STAGES`/`ALL_STATUSES`. IDEMPOTENT — a second run matches zero
-- rows.
UPDATE ingest_status_projection SET status = 'review' WHERE status = 'awaiting_disposition';
