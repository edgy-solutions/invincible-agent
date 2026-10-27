-- A frontend's render menu, as the BFF last accepted it (architect ruling Q9, 2026-10-19).
--
-- A render menu is a registration like an engine's, and registrations survive prime: the BFF
-- keeps the last accepted menu per frontend here and replays it into the graph after a wipe.
-- Idempotent (IF NOT EXISTS), applied on first use by frontend_menu_store, which holds the copy
-- that runs; this file mirrors it.
--
-- ONE ROW PER FRONTEND. Unlike the decision ledger this row is meant to be replaced: an accepted
-- registration upserts it. `menu` is the canonical JSON text of the admitted capability list.
CREATE TABLE IF NOT EXISTS frontend_menu (
    frontend_id TEXT PRIMARY KEY,
    frontend_version TEXT NOT NULL DEFAULT '',
    menu_sha256 TEXT NOT NULL,
    menu TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    registered_at BIGINT NOT NULL
);
