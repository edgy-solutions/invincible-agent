-- document_promotion's decision record (ADR-0041 Open §1, ruled 2026-09-30).
--
-- The approval plane's Postgres, beside human_task_projection. Idempotent (IF NOT EXISTS),
-- applied at cortex-bff startup by promotion_stores.apply_migration, which holds the copy
-- that runs; this file mirrors it.
--
-- ONE ROW PER DOCUMENT. record_id is derived from the ingest_id, and both are unique, so a
-- second decision is refused by the insert (ON CONFLICT DO NOTHING) and answered with the
-- stored decision. `record` is the decision record's canonical JSON text. Nothing updates
-- or deletes a row: a rejection sweeps the document, never its record.
--
-- NOT REPLICATED. This table is not one of the Electric shape proxy's served tables.
CREATE TABLE IF NOT EXISTS document_decision_record (
    record_id TEXT PRIMARY KEY,
    ingest_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL,
    acted_by TEXT NOT NULL,
    acted_at BIGINT NOT NULL,
    record TEXT NOT NULL
);
