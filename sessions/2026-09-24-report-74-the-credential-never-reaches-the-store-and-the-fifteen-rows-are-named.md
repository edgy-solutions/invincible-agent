---
to: ia-01/lane/01
from: ia-74/lane/74
cc: architect, Chris
date: 2026-09-24
subject: the scrub is built and sealed (10/10 mutations, two of my own arms were worthless and I found out by mutating), the fifteen rows are named, and every thread in the store is one of them
---

# 74 — identity never reaches the checkpoint store

**Built on the lane. No store writes: the purge below is Chris's and I have not run any part of
it.** Reads against the sandbox Postgres were done under the grant Chris gave in-session.

| what | where |
| --- | --- |
| the scrub | `agent_fleet/graph_host/identity_scrub.py` (new) |
| the wiring | `agent_fleet/graph_host/main.py` — 5 edits |
| the seal | `tests/graph_host/test_the_checkpointer_never_stores_the_credential.py` — 12 arms |
| suites | `tests/graph_host tests/identity tests/security` → **195 passed, 10 skipped, exit 0** |
| mutation | **10 mutations, 10 killed, 0 survivors** — after I closed two that survived |

---

## 1 · The mechanism, and the one thing it must not do

`put` is handed the live checkpoint of a run that is **still executing**, and `channel_values`
holds the same dict object the next node will read. So the scrub **copies**; a redaction in place
would strip the credential out from under node 2 and turn a storage fix into a mid-run
authorization failure — a graph that works at node 1 and refuses at node 2, which is a worse
defect than the one being fixed and would look like an authorization bug anywhere but here.

A **subclass** of the concrete saver, not a wrapper: LangGraph isinstance-checks the checkpointer.
Measured before choosing — a `__getattr__`-delegating wrapper is refused by `compile()` with
*"Expected an instance of BaseCheckpointSaver … Received Wrapper"*. Subclassing is safe because
`from_conn_string` yields `cls(conn=conn, serde=serde)`, and the seal pins that construct in the
library's own source: with a hard-coded `AsyncPostgresSaver(...)` the subclass would be silently
discarded and the scrub would vanish with it.

**Two predicates, because a key list is a sample.** Redaction fires on the declared identity
carriers *and* on anything JWT-shaped anywhere. The finding's second site was the `__start__`
channel — a name no identity key list would ever have contained.

**Both savers scrub**, the durable one and the in-process fallback. Not because process memory is
a disclosure, but because a scrub you lose by unsetting an environment variable is one where every
offline test exercises an unscrubbed saver while reporting coverage of the scrubbed one.

**One mirror removed rather than added.** `identity_scrub` now *owns* `IDENTITY_HEADERS` and
`IDENTITY_CHANNEL`; `main.py` imports both. The host accepting a header the scrub does not redact
is an invariant *between* two files, which no per-file check can see — a fourth identity header
added to one of them would forward a credential the store then keeps, with every arm green. The
seal asserts `is`, not `==`.

---

## 2 · Two of my own arms were worthless, and mutation is what said so

This is the part worth your time. The first pass was 10 arms, all green, and the mutation run
produced **two survivors**:

**M9 — stripping the wrapping out of `_open_saver` killed nothing.** That is the *only* place the
wrapping matters and the *only* path production takes. My arm had built
`scrubbing_saver_class(AsyncPostgresSaver)` in the test body and asserted `issubclass` — it
constructed its own subject and then verified it. A precondition checked on the wrong subject is
true on both sides of the change. Replaced by an arm that invokes `_open_saver` for real with a
DSN set and a stand-in saver, and asserts on **the saver the host assigned**. It asserts
`open_error is None` first, because `_open_saver` swallows failure into `open_error` and sets
`_SAVER = None` — without that, a broken double reds the arm naming the scrub, for a reason that
is not the subject.

**M3b — removing the scrub from `aput_writes` killed nothing.** `InMemorySaver.aput_writes`
delegates to the sync `put_writes`, which the subclass has already overridden, so the async
override was **unreachable in every offline arm while being the only one `AsyncPostgresSaver`
calls**. A guard covered solely by a path that cannot reach it is a guard nothing tests. Closed by
driving all four entry points directly against a bare recorder, and comparing the exercised set
against the write surface **derived** from `BaseCheckpointSaver` — so a fifth write method in a
future upgrade reds the arm for being unexercised rather than opening a path around the scrub.

Both were green arms over healthy code. Neither is visible by reading.

**The ten, after closing those two:** scrub mutates in place → 2 red · shape predicate removed → 6
· `put_writes` unscrubbed → 3 · `aput_writes` unscrubbed → 1 · `channel_values` left alone → 4 ·
marker itself carries the tell → 7 · host writes the channel by literal → 1 · host respells the
header set → 1 · fallback unscrubbed → 1 · durable saver unscrubbed → 1. Every restore verified
**byte-exact by sha256** against bytes read before the first mutation, never by `git checkout --`,
which would have deleted the uncommitted work under test. The suite was re-run green after all
restores.

**The positive control is the file's first arm and it is not a courtesy.** Every other arm asserts
an absence, and a fixture whose graph never carried a token, a matcher with a typo, and a run that
silently did nothing all produce a clean scan indistinguishable from a working scrub. The same
graph, token and matcher through a saver differing in one thing **must** find `eyJ`; if it ever
stops, nothing below it in that file means anything, and the file says so.

**Where the seal stops, stated rather than implied.** It asserts what the saver is *handed*, plus
what an in-process saver reads back. The step from "the argument is clean" to "the Postgres row is
clean" is the saver's own serialization, which no in-process double executes — the same gap the
referent seal names for Cypher's null semantics. The live half of the claim is §4's census and the
re-census owed after the purge.

### One red I caused and corrected

I first wrote the sibling import **package-first**, to guarantee one module object. Package-first
is exactly what `test_no_module_imports_agent_fleet_OUTSIDE_a_flat_first_fallback` forbids, and it
is right: `agent_fleet` does not exist in this engine's image, so package-first takes the `except`
arm on every real import — handling the fork on the only path that matters rather than taking the
one that works. Corrected to flat-first. The identity concern does not disappear, it moves: two
module objects are possible only if `graph_host/` is itself on `sys.path`, and that is a situation
to **detect**, which is why the declaration arm asserts `is`.

---

## 3 · Item 3's open contract gap, in one line, for your ruling

> When a `_SCOPED_BY_SLOT` class is enumerated with its scoping slot **absent or bound to an
> unknown lot**, engine-cost still answers class-wide, because the honest answer needs an
> `outcome` the enumeration contract does not have — `too_many` would assert a false cardinality
> reason (twelve against a bound of twenty-five), and a new outcome files under engine-o's
> else-arm as "no provider holds this class".

---

## 4 · The fifteen rows, named — and every thread in the store is one of them

Read today against the checkpoint database. Predicate
`position(convert_to('eyJ','UTF8') in blob) > 0` — **bytea-to-bytea, deliberately**: the blobs are
msgpack, so `convert_from(blob,'UTF8')` raises on the first invalid byte and takes the whole query
with it. Its two controls returned **3** and **0** in the same session, so the zeros below are
worth something.

**`checkpoint_blobs`** — PK `(thread_id, checkpoint_ns, channel, version)`; `checkpoint_ns` is `''`
for all fifteen.

| thread_id | channel | version | bytes |
| --- | --- | --- | --- |
| `6181bbf7-b949-41d4-8efc-d874d9ccbeab` | `identity` | `00000000000000000000000000000002.0.3605265880875713` | 1386 |
| `6181bbf7-b949-41d4-8efc-d874d9ccbeab` | `__start__` | `00000000000000000000000000000001.0.11598450424908247` | 1419 |
| `e6c78f0a-f6a1-4546-832a-5176c00fa166` | `identity` | `00000000000000000000000000000002.0.6789108351218356` | 1386 |
| `e6c78f0a-f6a1-4546-832a-5176c00fa166` | `__start__` | `00000000000000000000000000000001.0.9976753604067878` | 1419 |
| `ede7dc01-63fe-4093-bcd2-e9b2d1fc1e1c` | `identity` | `00000000000000000000000000000002.0.22457060563769005` | 1386 |
| `ede7dc01-63fe-4093-bcd2-e9b2d1fc1e1c` | `__start__` | `00000000000000000000000000000001.0.16571581896572174` | 1419 |
| `lane32-ledger-probe-2026-09-19` | `identity` | `00000000000000000000000000000002.0.9770249089831635` | 1387 |
| `lane32-ledger-probe-2026-09-19` | `__start__` | `00000000000000000000000000000001.0.1841011220320221` | 1420 |
| `run-594daac5907b487581b95833ec8c1b8b` | `identity` | `00000000000000000000000000000002.0.6227388750431676` | 1427 |
| `run-594daac5907b487581b95833ec8c1b8b` | `__start__` | `00000000000000000000000000000001.0.38002582223246695` | 1460 |

**`checkpoint_writes`** — PK `(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)`; all
`channel = identity`, all `idx = 1`.

| thread_id | checkpoint_id | task_id | bytes |
| --- | --- | --- | --- |
| `6181bbf7-b949-41d4-8efc-d874d9ccbeab` | `1f1b49cd-c1a0-67c3-bfff-4d8759d8ae72` | `3801af3a-0957-1923-08e5-659d4af312aa` | 1386 |
| `e6c78f0a-f6a1-4546-832a-5176c00fa166` | `1f1b4684-40d1-69d3-bfff-43467f67b131` | `e7107489-ad57-9d6c-06a3-5c0125797359` | 1386 |
| `ede7dc01-63fe-4093-bcd2-e9b2d1fc1e1c` | `1f1b4a1d-4f39-665c-bfff-2b2030d33095` | `4ffc0009-5532-244c-d119-2aad3e607c38` | 1386 |
| `lane32-ledger-probe-2026-09-19` | `1f1b4a1a-4a0e-6d26-bfff-1bf3b627242c` | `2a456863-70df-0c66-96bd-a0134dd00d0a` | 1387 |
| `run-594daac5907b487581b95833ec8c1b8b` | `1f1b1608-00d6-6a4c-bfff-ae93a1dbdb46` | `d8be1ba7-d3c9-18a4-0bc1-39684c2409c7` | 1427 |

**`checkpoints` carries none** — 0 of 30, as on 2026-09-23. Table totals are **41 / 66 / 30**,
identical to five days ago: nothing new has landed, and the thread named for 2026-09-19 is still
at rest. There is no TTL.

### The finding that changes the choice: 5 affected threads, and 5 threads exist

`select count(distinct thread_id) from checkpoints` → **5**. Every thread in the store is an
affected thread. So the surgical delete does not preserve a clean remainder — it leaves **all
five** threads with `checkpoints` rows referencing blob versions that no longer exist, a state no
test in this repo covers a loader meeting. **It buys nothing.** Per thread the radius is 6
checkpoints / 9 blobs / 14 writes (the `run-…` thread: 6 / 5 / 10).

---

## 5 · The statements. ACTION: CHRIS — I have run none of them

Both are in a transaction and both `RETURNING` their keys, so **the ids that come back are the
rows actually removed**. That is stronger than checking mine by hand: a transcribed list is a
sample that goes stale the moment a run lands, and the returned keys cannot be stale.

**Option A — exactly the fifteen, as ordered:**

```sql
BEGIN;
DELETE FROM checkpoint_blobs
 WHERE position(convert_to('eyJ','UTF8') in blob) > 0
 RETURNING thread_id, checkpoint_ns, channel, version;      -- expect 10 rows
DELETE FROM checkpoint_writes
 WHERE position(convert_to('eyJ','UTF8') in blob) > 0
 RETURNING thread_id, checkpoint_ns, checkpoint_id, task_id, idx;   -- expect 5 rows
-- 15 total. COMMIT only if both counts match; otherwise ROLLBACK and send me the numbers.
COMMIT;
```

**Option B — the whole checkpoint store, which I recommend** given 5 of 5 threads are affected and
Option A leaves every one of them dangling anyway. These are probe and run threads, the scrub
means no future run recreates the problem, and this is the only option that leaves a coherent
store:

```sql
BEGIN;
DELETE FROM checkpoint_writes;   -- 66
DELETE FROM checkpoint_blobs;    -- 41
DELETE FROM checkpoints;         -- 30
COMMIT;
-- checkpoint_migrations is NOT touched: dropping it makes setup() re-run every migration.
```

**Then verify, and do not accept the zero without its control:**

```sql
SELECT (SELECT count(*) FROM checkpoint_blobs
         WHERE position(convert_to('eyJ','UTF8') in blob) > 0) AS blobs_left,
       (SELECT count(*) FROM checkpoint_writes
         WHERE position(convert_to('eyJ','UTF8') in blob) > 0) AS writes_left,
       position(convert_to('eyJ','UTF8') in convert_to('xxeyJyy','UTF8')) AS control_must_be_3;
```

`blobs_left` and `writes_left` must be 0 **and** `control_must_be_3` must be 3 — a predicate that
has stopped working reports a clean store, and that is how a purge gets believed without having
happened.

---

## 6 · What I did not do

- **No store writes.** The purge is Chris's, above, unrun.
- **No `--apply`, no dispatch.**
- **The credential values are not in this file** and were never printed. Row keys and byte lengths
  only; the connection string is not here either.
- **32's four-control probe is still blocked**, and not on the prime: the `mesh_system.ttl` in S3
  predates both `mesh:Thing` and `mesh:SourceLedger`, so the probe's first control cannot fire.
  It needs an S3 re-upload of the current TTL, not a re-prime. `docs/docs_corpus.ttl` is stale
  there too — same shape, worth one pass.
- **Still red by ruling, unchanged:** the three finance dual-import tests. Not touched here.
