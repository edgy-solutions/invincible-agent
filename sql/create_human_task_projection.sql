-- HITL substrate (2026-07-09) — the HumanTask queue projection.
--
-- Lives in the SAME Electric-replicated Postgres as answer_artifact_projection,
-- and is subscribed by cortex-ui through the SAME cortex-bff `/electric/shape`
-- proxy. Idempotent (IF NOT EXISTS) — applied at cortex-bff startup, no separate
-- Alembic step, same discipline as create_answer_artifact_projection.sql.
--
-- TWO-LAYERS-ONE-TRUTH (the load-bearing property): who may SEE/ACT on a task is
-- a Topaz `can_act` decision on the task's `audience`. Registration resolves that
-- decision to a set of authorized actor AUTHZ-IDs and materializes ONE ROW PER
-- ACTOR here (recipient_id = an authorized actor's authz_id). The Electric proxy
-- filters this table by `recipient_id = <server-verified caller authz_id>` — so
-- the replication-layer filter (what a subscription RECEIVES) and the application-
-- layer gate (Topaz can_act re-checked at /act) derive from the SAME decision and
-- cannot diverge.
--
-- recipient_id holds the AUTHORIZATION identity (authz_id = the
-- USER_ENTITLEMENT_CLAIM key Topaz is seeded by: email in sandbox, employee-ID at
-- work-deploy) — NOT sub, NOT necessarily email. Keying the whole task path on the
-- ONE authz identity (a) ELIMINATES the recurring sub<->email bridge (no mapping to
-- mis-route), and (b) keeps the SCHEMA identity-key-agnostic: switching the
-- deployment's identity key is a config change (the knob), never a column migration.
--
-- EXISTENCE-ORACLE / CLEARANCE-BOUNDED PAYLOAD: a row's mere existence reveals a
-- task is pending; deny-by-default (no actor grant -> no row for that caller ->
-- their subscription never receives it). The payload columns carry a clearance-
-- SAFE reference + summary ONLY — never compartmented content the viewer isn't
-- cleared for (the task references AnswerArtifact X by id; it does not embed X's
-- content). A viewer authorized for the TASK but not the CONTENT still cannot leak.

CREATE TABLE IF NOT EXISTS human_task_projection (
    -- Synthetic per-(task,recipient) row id. One logical task fans out to N rows
    -- (one per authorized actor); task_id ties them together for resolution.
    id TEXT PRIMARY KEY,

    -- Task-type discriminator: 'workflow_ack' (Case 2 — a suspended Restate
    -- workflow awaits this approval) | 'access_request' (Case 3 — async grant
    -- request, nothing suspended). Drives the resolution fulfillment backend.
    kind TEXT NOT NULL,

    -- The logical task (same across all recipient rows). For workflow_ack this is
    -- the Restate UserTask id whose promise `approval_<task_id>` resumes the run.
    task_id TEXT NOT NULL,

    -- Restate workflow key (BPMNWorkflowRunner instance) for the resolve call.
    -- NULL for access_request tasks (no suspended workflow).
    workflow_id TEXT,

    -- The Topaz task_audience key this task's can_act is gated on
    -- (e.g. 'promotion:DATA_ENGINEERING'). Recorded for audit + the /act re-check.
    audience TEXT NOT NULL,

    -- VIEWABILITY FILTER COLUMN (plain TEXT — Electric rejects generated columns,
    -- same lesson as produced_for_user_id). One authorized actor's email; the
    -- proxy injects `recipient_id = '<verified caller email>'` for this table.
    recipient_id TEXT NOT NULL,

    -- Lifecycle: 'pending' | 'approved' | 'rejected' | 'expired'. NO DEFAULT
    -- (per [[optimistic-defaults-are-dishonest]] — the writer knows the value).
    status TEXT NOT NULL,

    -- CLEARANCE-SAFE payload — reference + summary, never compartmented content.
    title TEXT NOT NULL,           -- short label, e.g. "Approve promotion"
    summary TEXT NOT NULL,         -- clearance-safe one-liner
    requested_by TEXT NOT NULL,    -- who initiated the workflow (email)
    subject_ref TEXT,              -- a reference/URN (AnswerArtifact id), NOT content
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,  -- clearance-bounded extra fields

    -- Resolution audit (populated on /act).
    acted_by TEXT,                 -- the authorized actor who resolved it
    acted_at BIGINT,
    decision TEXT,                 -- 'approved' | 'rejected'
    comment TEXT,

    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_htp_recipient_id
    ON human_task_projection (recipient_id);
CREATE INDEX IF NOT EXISTS idx_htp_task_id
    ON human_task_projection (task_id);
CREATE INDEX IF NOT EXISTS idx_htp_status
    ON human_task_projection (status);
