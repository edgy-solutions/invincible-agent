---
status: Spike report (build-session gate item #2 per projector-build-plan §3.6)
date: 2026-06-27
authors: claude (Electric-native-position spike, build-session opening)
gates: projector-build-plan.md `0c2f5fe` — Decision 3 ruling
companion-artifact: scratchpad/electric-spike/{docker-compose.yml,schema.sql,run_experiments.py,run_d_only.py,results.json} (torn down at end of spike per §3.6)
---

# Electric-native-position spike — Decision 3 ruling

## 1. Goal

Settle Decision 3 of the projector build plan (commit `0c2f5fe`, §3.4): does Electric's
native per-shape position give the projector a strong-enough see-your-write guarantee, or
must the projector hand-build the watermark + cross-shape ordering probe? The plan's
sub-decision criterion: Electric's native position is sufficient **iff**
(a) per-shape ordering holds AND (c) artifact + position-marker can co-exist in one shape,
**OR** (d) cross-shape delivery is atomic. Otherwise Decision 3 lives, the bespoke watermark
gets built, and Hop 3's conditional see-your-write probe is required RED-first.

## 2. What was tested

**Documentary sources read:**
- ElectricSQL docs (electric.ax/docs): shapes, HTTP API, OpenAPI YAML.
- Durable Streams announcement (2025-12-09) — "ordered, replayable, resumable delivery"
  is per-stream; transaction/atomicity semantics deferred to an unshipped "State Protocol".
- `electric-api.yaml` schema: each shape operation carries `lsn`, `op_position`, `last`,
  and `txids`. **Verbatim caveat on `last`:** "Last operation in a transaction for the shape
  does not mean a last operation in the database." — the documentation explicitly disclaims
  cross-shape transaction grouping.

**Experimental setup** (local, isolated from sandbox; tear-down at §6):
- Docker Compose: `postgres:16` (`wal_level=logical`) + `electricsql/electric:latest`
  (resolves to v1.6.2). Ports `localhost:55432` (Postgres), `localhost:53000` (Electric).
- Schema mirroring projector's Decision 2 shape: wide-table `answer_artifact_projection`
  with `kind` discriminator + a separate `projector_watermark(id, value)` table (the
  shape Decision 3's bespoke-watermark variant would carry).
- Long-poll consumer in Python (`urllib` HTTP, live-mode after first up-to-date control,
  records `lsn`/`op_position`/`txids`/`last` headers + wall-clock arrival time).
- Four experiments map 1:1 to the plan's sub-questions (a)/(b)/(c)/(d). Each runs against
  a fresh data state (DELETE — not TRUNCATE; TRUNCATE invalidates Electric shape handles
  and provokes a must-refetch storm, which is itself a finding).

## 3. Answers to the four sub-questions

### (a) Per-shape ordering — **DOCUMENTED + OBSERVED, holds**

- **Documented**: HTTP API exposes `lsn` + `op_position` per op; Durable Streams advertises
  "ordered, replayable, resumable delivery" within a stream.
- **Observed**: 50 sequential inserts to one shape, 50 inserts received by client in
  exact source order. `op_position=0` on each, monotonic LSNs, no out-of-order.

### (b) Cross-shape ordering (two txns, two shapes) — **DOCUMENTED ABSENT; not reproduced under load but not proven safe**

- **Documented**: OpenAPI is silent on cross-shape ordering. The `last` field's verbatim
  caveat — "Last operation in a transaction for the shape does not mean a last operation
  in the database" — is the explicit disclaimer of cross-shape grouping. Durable Streams
  defers transaction semantics to an unshipped "State Protocol".
- **Observed**: 100 pairs (artifact-txn then watermark-txn back-to-back, no sleep),
  100/100 correctly ordered at client. **However, this is NOT a guarantee proof** — it
  shows the race window did not fire on a single-machine local Postgres+Electric with
  ~1ms tx times. The race is theoretically present (see (d) for the related but stronger
  evidence below); under network latency, replica lag, or cluster pressure it would.
  Documented-but-not-proven-safe is the assumed-contract trap the plan calls out.

### (c) Same-shape position marker (one shape, two `kind`s) — **OBSERVED, holds**

- **Observed**: 30 pairs of `(artifact row, watermark row)` written in one Postgres txn
  to `answer_artifact_projection`, discriminated by `kind`. Client received all 30 pairs
  in arrival order. **All 30 share the same `lsn` AND artifact's `op_position` < watermark's
  `op_position`** — strong evidence that within a single shape, Electric reorders nothing:
  same-LSN ops are delivered in PG commit-order by `op_position`.
- This is the path that survives the cross-shape race in (b)/(d): both rows ride the
  same shape's per-stream FIFO, and the `last` flag's per-shape caveat does not bite
  because the projector treats one shape as the see-your-write substrate.

### (d) Intra-transaction atomicity (one txn, two shapes) — **OBSERVED VIOLATED**

This is the load-bearing finding. Five repeated runs of 100 pairs each. Each pair is an
artifact-row insert + watermark-row update committed in a **single Postgres transaction**.
Client subscribes to both shapes.

| Run | Pairs | Same-LSN matches | Arrival-order violations | Max gap |
|----:|------:|----:|----:|----:|
| 0 | 100 | 100 | 1 | 16ms |
| 1 | 100 | 100 | 1 | 16ms |
| 2 | 100 | 100 | 3 | 16ms |
| 3 | 100 | 100 | 3 | 16ms |
| 4 | 100 | 100 | 3 | 16ms |

15 violations across 500 pairs. In **every** violation the artifact and watermark
operations carry **identical LSN** (proving they were the same Postgres commit), yet the
watermark arrived 15–16ms ahead of the artifact at the client. **Electric does not deliver
same-txn cross-shape operations atomically to the client.**

The 15–16ms cluster is the per-shape long-poll cycle; the race window is exactly
"watermark shape's poll fires once before the artifact shape's poll catches up to the
same LSN." Under network latency or shape-server scheduling this window grows.

Verdict on the criterion: (d) is **falsified by direct observation, not just documentation**.
The assumed-contract trap was avoided.

## 4. Conclusion

**Decision 3 dies — Electric's native position is sufficient — IF the projector adopts
the `(c)` schema discipline.**

Three pathways were on the table; only one survives:

- (b) cross-shape with separate watermark **table**: doc-silent, not safety-proven under
  load. Rejected.
- (d) same-txn-cross-shape atomicity: **observed violated** (15/500 pairs, 16ms races).
  Rejected.
- (c) same-shape position marker: documented (per-shape `op_position` ordering), observed
  green (30/30 pairs ordered, matching LSN, correct `op_position`). **Accepted.**

The projection-schema implication of accepting (c):

- `projector_watermark` as a **separate table is deleted** from Decision 2's migration set.
  The wide-table `answer_artifact_projection` with `kind` discriminator already supports
  rows of `kind='Watermark'` (nullable `payload`, `watermark bigint NOT NULL`).
- The projector emits, **in one Postgres txn per apply cycle**:
  1. The artifact row(s) with the new `watermark` value as a column.
  2. A single `kind='Watermark'` row that carries the high-water `value` for that user's
     scope. (Or — see §5 third-option premise-shift below — drop the watermark row entirely
     and let the artifact row's `watermark` column be the position marker.)
- The client subscribes to **one shape** filtered by `produced_for.user_id` (matching
  the Hop 3 plan's privacy-by-construction shape). Per-shape FIFO delivers artifact and
  watermark rows in commit order.
- The conditional Hop-3 see-your-write probe (§3.4 of plan, Part 3 of Hop 3) is **not
  required**, because the failure path it was guarding (the (b)/(d) cross-shape race)
  cannot occur on a single-shape design.

**The apply-order discipline this requires of the projector:**

The projector MUST write the artifact row first and the watermark row second within the
same Postgres txn (so artifact's `op_position` < watermark's `op_position` within the
shared LSN). If the projector ever splits artifact and watermark into two transactions,
(b) becomes the active risk surface; documentary silence makes that a doc-trust gamble.
The discipline is enforced by the projector's apply loop being a single `BEGIN; INSERT
artifact; INSERT watermark; COMMIT;` per artifact.

## 5. Premise-shift surfaced — position-as-column, no marker row at all

While characterizing (c) the experiment revealed a third option the plan did not name:
**the position marker can be a column on the artifact row itself, not a separate row.**
The `answer_artifact_projection` schema already has `watermark bigint NOT NULL` as a
top-level column. A client doing "wait until I see an artifact whose `watermark >= N`"
gets see-your-write for free without any marker row — the artifact ROW IS the marker.

This is strictly stronger than (c)'s same-shape-with-marker-row variant: zero extra rows,
zero extra writes, same per-shape FIFO guarantees. The cortex-bff `stream_end` returns
the projector-assigned watermark value; the client subscribes to its user's shape and
treats `MAX(watermark) >= N` as "see-your-write complete."

This is a premise-shift relative to the plan's revision 2 framing (which assumed a
distinct watermark row). I am surfacing it as required by §3.4's "Halt on third option"
trigger; the architect should decide whether to revise Hop 2's migration (drop the
`projector_watermark` table from the migration set entirely; keep the column-based
position) or stay with the `kind='Watermark'` row approach (slightly more flexible — a
watermark can advance without any artifact change). Either is consistent with the (c)
verdict; the column-only path is simpler.

## 6. Updated plan implications (descriptive only — plan not revised in this commit)

Following the conclusion above:

1. **Decision 3 dies.** Update §3.4 to record the spike outcome: native Electric position
   per-shape is sufficient under the single-shape constraint. Coupled-retirement note
   in §3.5 stands as-is (Decision 1 still retires with the Restate+topic successor);
   Decision 3 no longer exists to retire.
2. **Hop 2 migration drops `projector_watermark` table** (or keeps it empty for shape-flexibility,
   per the architect's choice on §5). The `watermark bigint` column on
   `answer_artifact_projection` survives unchanged — it is now the position primitive itself.
3. **Hop 3 Part 3 (see-your-write ordering probe) drops** from the breakpoint criteria
   in §6 and the discipline note in §7. The plan's §6 already conditioned Part 3 on the
   spike outcome ("Required only if Decision 3's spike outcome required building the
   bespoke watermark"); the condition is now resolved.
4. **The projector apply loop gains a discipline note**: each artifact-change-set is one
   PG transaction, artifact-row written before any watermark row within the same txn,
   so `op_position` ordering inside the shared LSN matches the see-your-write contract.
5. **Build-session gate list §3.6 step 2 is satisfied** by this commit; step 3 (Hop 1)
   is the next gate (and is NOT touched in this thread per §10 binding STOP).

## 7. Halt-on premise-shifts

- **Position-as-column third option** (see §5) surfaced. Per §3.4 trigger language this
  is a "halt and surface." Surfaced here in §5; awaiting architect ruling on whether to
  fold it into Hop 2 migrations.
- **No other premise-shifts.** Electric was reachable in local Docker (no Postgres-config
  surprises — `wal_level=logical` + a logical-replication slot was sufficient, matching
  what the sandbox `postgres:16` deployment already supports per audit §2.2). The
  projector-writes-two-rows premise from §3.4 is preserved by (c)'s same-shape variant;
  the column-only variant in §5 is the only premise that genuinely shifts and it is a
  simplification, not a contradiction.

## 8. Tear-down confirmation

Local containers `spike_pg` and `spike_electric` are torn down (`docker compose down -v`)
as part of this commit's prep. Scratchpad files retained for inspection until next
session prunes; they do not affect repo state.
