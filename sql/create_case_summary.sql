-- Case summary (ruled 2026-10-16): every terminal transition of a case (released / failed /
-- rejected) writes the case summary -- state, final reason, transitions, seeded_by, artifact ids --
-- to this row, so the record outlives Restate. A case record is durable evidence, not runtime
-- state: Restate's retention for a workflow is a clock, this table is not.
--
-- Written by POST /internal/cases/{case_id}/summary (svc:case-runner only) through
-- src/iagent/case_summary.py, which applies this same DDL at cortex-bff startup. Idempotent
-- (IF NOT EXISTS) and re-deliverable: the upsert is ON CONFLICT (case_id) DO UPDATE.
--
-- artifact_ids is derived SERVER-SIDE from the graph (AnswerArtifact.case_id), never taken from
-- the runner's word.

CREATE TABLE IF NOT EXISTS case_summary (
    case_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    final_reason TEXT,
    transitions JSONB NOT NULL,
    seeded_by TEXT,
    artifact_ids JSONB NOT NULL DEFAULT '[]',
    terminal_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
