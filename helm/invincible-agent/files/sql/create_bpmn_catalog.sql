-- ==========================================================================
-- bpmn_catalog — stores simplified BPMN JSON workflow definitions
--
-- Run this directly against your Postgres database:
--   psql -h localhost -U iagent -d iagent -f sql/create_bpmn_catalog.sql
-- ==========================================================================

CREATE TABLE IF NOT EXISTS bpmn_catalog (
    workflow_id   TEXT        PRIMARY KEY,
    name          TEXT        NOT NULL,
    bpmn_payload  JSONB       NOT NULL,
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Auto-update the updated_at column on every UPDATE
CREATE OR REPLACE FUNCTION update_bpmn_catalog_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_bpmn_catalog_updated_at ON bpmn_catalog;
CREATE TRIGGER trg_bpmn_catalog_updated_at
    BEFORE UPDATE ON bpmn_catalog
    FOR EACH ROW
    EXECUTE FUNCTION update_bpmn_catalog_updated_at();

-- Index for the most common query pattern (active workflows)
CREATE INDEX IF NOT EXISTS idx_bpmn_catalog_active
    ON bpmn_catalog (is_active)
    WHERE is_active = TRUE;
