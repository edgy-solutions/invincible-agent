-- Hop 2 of the projector build plan (commit 0eda9f7 of
-- docs/plans/projector-build-plan.md, §3.3 Decision 2 + §3.4 Decision 3
-- Option C + §5 schema).
--
-- This migration is idempotent — re-running is safe. The projector
-- applies it at startup; no separate Alembic step.
--
-- INTERIM under Decisions 0+1+3 (per
-- [[coupled-interim-mechanisms-retire-together]]): the `watermark` COLUMN
-- and the `durability_status` column both retire when the Restate+topic
-- successor lands (topic offset becomes position; the durable handler
-- replaces the recorded-state field). The wide-table-with-discriminator
-- shape itself (Decision 2) is PERMANENT.

-- ── Projection table (wide, kind-discriminated) ──
CREATE TABLE IF NOT EXISTS answer_artifact_projection (
    id TEXT PRIMARY KEY,
    -- INTERIM under Decisions 0+1+3? NO — `kind` is the discriminator
    -- (Decision 2, permanent). The default 'answer' is NOT an
    -- optimistic default per [[optimistic-defaults-are-dishonest]]: at
    -- Hop 2 the projector writes only AnswerArtifact rows, so the
    -- discriminator value is unambiguous at write time, and the
    -- planning doc §3.3 calls this out explicitly. Part B (publish
    -- backend) writes 'published' rows explicitly, not via default.
    kind TEXT NOT NULL DEFAULT 'answer',

    -- Decision 3 Option C: every row carries a top-level monotonic
    -- watermark. INTERIM — retires when topic offset replaces it.
    watermark BIGINT NOT NULL,

    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    valid_as_of BIGINT NOT NULL,
    valid_until BIGINT,

    -- pipeline-lifecycle status (`pending` | `complete` | `failed`).
    -- NO DEFAULT per [[optimistic-defaults-are-dishonest]] — the
    -- gateway is the only layer that knows which value is correct;
    -- defaulting here would re-create the failure-mode-1 trap one
    -- layer over.
    status TEXT NOT NULL,

    -- substrate-write status (`persistence_pending` | `durable` |
    -- `persistence_failed`). INTERIM under Decision 0. NO DEFAULT —
    -- same rule as status.
    durability_status TEXT NOT NULL,

    message_id TEXT NOT NULL,
    question_text TEXT NOT NULL,
    resolved_intent JSONB NOT NULL,
    routing JSONB,                  -- nullable per Hop-1 honest-absent
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    graph_trace JSONB NOT NULL DEFAULT '[]'::jsonb,
    rendered_output JSONB,          -- nullable per Hop-1 honest-absent
    produced_by JSONB NOT NULL,
    produced_for JSONB NOT NULL,
    derived_from_artifact_id TEXT,

    -- ADR-0024 Part B columns (nullable at Hop 2; populated when
    -- kind='published'). Schema room left so Part B doesn't need a
    -- migration past column-additions.
    target_system TEXT,
    target_locator TEXT,
    promotion_path TEXT,
    superseded_by TEXT,
    orphaned_as_of BIGINT
);

CREATE INDEX IF NOT EXISTS idx_aap_watermark
    ON answer_artifact_projection (watermark);
CREATE INDEX IF NOT EXISTS idx_aap_kind
    ON answer_artifact_projection (kind);

-- 2026-06-30: per-user isolation interim. The cortex-bff
-- `/electric/shape` proxy filters subscriptions on the authenticated
-- user's `sub`. Electric's WHERE-clause parser supports a subset of
-- PostgreSQL expressions and does NOT accept the `->>` JSONB path
-- operator, so the WHERE clause must reference a plain column.
--
-- Originally tried as a `GENERATED ALWAYS AS (produced_for->>'user_id')
-- STORED` column — Electric refused to replicate it with "The
-- following columns are generated and cannot be included in
-- replication." Switched to a regular TEXT column populated by the
-- projector at write time (apply_loop.py reads produced_for.user_id
-- and writes it to this column on INSERT/UPDATE).
--
-- IDEMPOTENT — re-running the migration on a cluster that already
-- has the column is a no-op via IF NOT EXISTS. New clusters get the
-- column at first creation. Backfill on existing data:
--   UPDATE answer_artifact_projection
--   SET produced_for_user_id = produced_for->>'user_id'
--   WHERE produced_for_user_id IS NULL;
ALTER TABLE answer_artifact_projection
    ADD COLUMN IF NOT EXISTS produced_for_user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_aap_produced_for_user_id
    ON answer_artifact_projection (produced_for_user_id);

-- 2026-07-09: the answer's factual S·P headline (ADR-0028 Decision 4).
-- Composed once at the gateway write point from the captured routing
-- facts (subject label · verb label; fallback → structured
-- fallback_reason) — NOT an LLM summary, never re-derived on read. The
-- card in the answer-first left column leads with it. Nullable: rows
-- that predate the field carry NULL (honest-absent — no headline
-- captured); the projector writes "" for those and the card degrades
-- to question_text. IDEMPOTENT via IF NOT EXISTS.
ALTER TABLE answer_artifact_projection
    ADD COLUMN IF NOT EXISTS summary TEXT;

-- 2026-08-24: how long the answer took, in milliseconds, or NULL.
-- Measured at the ONE site where status flips to 'complete' (gateway.py),
-- from the bundle's own valid_as_of to that instant — birth-to-complete for
-- this bundle, which is what the name means and what a refactor must not
-- quietly redefine by substituting a request or step timestamp.
--
-- NULLABLE AND MOSTLY NULL ON DAY ONE. Every row written before this column
-- existed has no measurement and never will; 0 would be a CLAIM that those
-- answers returned instantly. The UI renders NULL as nothing, never as 0s.
-- Zero is a legal value (a cache hit is a real sub-millisecond result), so
-- NULL and 0 must stay distinct rather than collapsing on falsy.
--
-- SUCCESS PATH ONLY. A 'failed' artifact has a wall-clock lifetime, but that
-- is not an answer's duration — merging them would make any later
-- "median answer time" silently include 502 deaths. IDEMPOTENT via IF NOT EXISTS.
ALTER TABLE answer_artifact_projection
    ADD COLUMN IF NOT EXISTS duration_ms BIGINT;

-- ── Projector cursor (internal resumable state, NOT synced) ──
--
-- Decision 4 (Option C revised): the `GET /projector/watermark` HTTP
-- endpoint reads this table — the projector's own apply position. NOT
-- a synced-to-client row (that died with Decision 3's Option C).
--
-- Single-row table guarded by the CHECK constraint. The CHECK is the
-- "default the failure-revealing value" form of
-- [[optimistic-defaults-are-dishonest]] applied to a multiplicity
-- constraint: a default that allows multiple cursor rows would silently
-- corrupt the loop; the CHECK forces a INSERT…ON CONFLICT shape.
CREATE TABLE IF NOT EXISTS projector_cursor (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_applied_watermark BIGINT NOT NULL DEFAULT 0,
    last_apply_at BIGINT NOT NULL DEFAULT 0,
    apply_count BIGINT NOT NULL DEFAULT 0
);

-- Seed the single cursor row. ON CONFLICT DO NOTHING so re-running this
-- migration is idempotent.
INSERT INTO projector_cursor (id, last_applied_watermark, last_apply_at, apply_count)
VALUES (1, 0, 0, 0)
ON CONFLICT (id) DO NOTHING;

-- ── Skip log (observable trailing-step failures per
--    [[feedback-trailing-steps-nonfatal]]) ──
--
-- Per the planning prompt's "every skipped artifact is logged with
-- structured detail" — a silent skip is the trap; an observable skip
-- is the right shape. The projector inserts a row here for every
-- artifact it skipped during apply (JSON-parse failure, constraint
-- violation, etc.). Counterpart to the structured logger output;
-- this is the queryable surface for operations.
CREATE TABLE IF NOT EXISTS projector_skip_log (
    id BIGSERIAL PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    watermark BIGINT NOT NULL,
    skipped_at BIGINT NOT NULL,
    exception_class TEXT NOT NULL,
    exception_message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_psl_artifact_id
    ON projector_skip_log (artifact_id);
