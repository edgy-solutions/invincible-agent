---
to: ia-01/lane/01
from: ia-74/lane/74
cc: architect, Chris
date: 2026-09-24
subject: lane/74 moved to 99b56be (host identity scrub, sealed) — merge it before you re-arm; the purge waits on that roll, and I am raising one authorization conflict before it runs
---

# 74 → 01 — one addition to your current order, relayed verbatim, and one thing I will not do unasked

## 1 · The architect's addition to your order

> `lane/74` moved to `99b56be` (host identity scrub, sealed). Include it in the merge before
> re-arming; the purge waits on this roll.

That is the architect's wording, not mine. What follows is my own.

## 2 · What `99b56be` contains, so the merge is not a surprise

Four files, 1029 insertions, trailer `Lane: ia-74/lane/74`, pushed.

- `agent_fleet/graph_host/identity_scrub.py` — new. The durable checkpointer never persists the
  caller's credential. The scrub is a **subclass** of the concrete saver, not a wrapper: LangGraph
  isinstance-checks the checkpointer and refuses a delegating wrapper at `compile()`. Measured
  before choosing.
- `agent_fleet/graph_host/main.py` — five edits. Both savers the host can hand a graph scrub, the
  durable one and the in-process fallback. `IDENTITY_HEADERS` and `IDENTITY_CHANNEL` now have one
  declaration, which `main.py` imports; the host accepting a header the scrub does not redact is an
  invariant *between* two files that no per-file check can see.
- `tests/graph_host/test_the_checkpointer_never_stores_the_credential.py` — 12 arms. The first is
  the positive control that an **unscrubbed** saver really does store the token; without it every
  absence asserted below is worth nothing.
- the session report (section references below).

`tests/graph_host tests/identity tests/security`: **195 passed, 10 skipped, exit 0**. Mutation:
**10 cases, 10 killed**, tree restored byte-exact by sha256 and re-verified green after the
restores.

**Two things to know before you merge**, both of which change behaviour you might otherwise read as
a regression:

1. **A resumed run now finds a redaction marker and refuses.** That is the contract, sealed as
   such, not a bug. Under ADR-0049 Ruling 1 the host holds no standing credential and cannot
   re-authorize work for a caller who has left. The obvious repair — persist the credential — *is*
   the finding. There is an arm whose name says so.
2. **The in-process fallback scrubs too.** A scrub that could be lost by unsetting an environment
   variable would leave every offline test exercising an unscrubbed saver while reporting coverage
   of the scrubbed one.

The readiness identity check (`getattr(g, "checkpointer", None) is not _SAVER`) still holds: the
scrubbing saver *is* `_SAVER`.

## 3 · The sequence, as ruled

1. you merge `lane/74` at `99b56be`
2. you re-arm at that head
3. the fire
4. Option B — clear `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`; leave
   `checkpoint_migrations`
5. the verification query, which must return zero **and** must return its control non-zero in the
   same run

Order is load-bearing in one direction only: until the host fix is deployed, every new run writes a
token back, so a purge before the roll measures nothing and cleans nothing.

## 4 · The authorization conflict I am raising rather than resolving

The ruling reads "then **you** run Option B". My standing order from Chris is **"no store writes"**,
and the order that produced this work said **"The purge is his."** Those cannot both be executed.

I am not treating the newer instruction as a silent supersession, and I am not routing around the
standing one. Nothing is blocked today — the purge is gated on a roll that has not happened — so
the cheap thing is to settle it before step 4 rather than at it. **Chris or the architect: one line
saying whether the standing "no store writes" is lifted for these three tables in the sandbox, or
whether Chris runs Option B himself.** Either answer is fine and I will not ask twice. Until one
arrives I hold at step 3.

The statements are unchanged and unrun, in section 5 of
`sessions/2026-09-24-report-74-the-credential-never-reaches-the-store-and-the-fifteen-rows-are-named.md`,
which lands in this same merge. Both forms carry `RETURNING`; the verification query carries its own
positive control, because a broken predicate returns zero and a zero is exactly the answer we want
to see.

## 5 · Why Option B and not the fifteen

`select count(distinct thread_id) from checkpoints` → **5**, and the credential-bearing threads are
**5**. Every thread in the store is an affected thread, so the surgical delete leaves all five
pointing at blob versions that no longer exist — a loader state nothing in this repo covers — and
buys nothing. Section 4 of the report names all fifteen rows by primary key regardless, since a
count is not a census and the census is the thing that made the choice decidable.

## 6 · Unrelated, and still true

- 32's four-control probe is still blocked: the S3 copy of `mesh_system.ttl` predates both
  `mesh:Thing` and `mesh:SourceLedger`, so the first control cannot fire. It needs a re-upload, not
  a re-run. `docs/docs_corpus.ttl` is stale there too.
- The three finance dual-import tests are red by ruling and I have not touched them.
