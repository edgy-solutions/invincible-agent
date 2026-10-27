to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-22
re: URGENT trace of ingest fbecec9e (TI PCN20250213001.1), and the addendum on a dropper who is also a steward
relay: Chris

Committed on lane/01-202. This report carries no secret.

# fbecec9e: no hop stopped. The pick relaunched 20 s later. The relaunched run started 3m21s after that, behind doc-tools' sensor floor, and resolved pcn. Bob's dropper-and-steward path is the same code as alice's

Read-only trace: the BFF log, the Dagster run list and the run logs. No writes.

## The four hops you named

| hop | result | evidence (times Z; local is Z-5) |
| --- | --- | --- |
| `/leaf` recorded the pick (row leaf + leaf_source) | **yes** | 16:20:00 `/leaf` by bob: access `reason=dropped_by`, then `ingest_leaf from=None to=pcn stage=extracting`, then `leaf_corrected`, 200 |
| the BFF saw the finished run and wrote a retry row | **yes** | 16:20:20 `ingest_leaf_relaunch ... from=extracting run_id=1344abcd... attempt=1 decision=relaunched` |
| the sidecar was rewritten to pcn | **yes, by consequence** | the code writes the sidecar before `relaunch_as_leaf`, and the relaunched run logged `content_kind resolved: kind='pcn' ... domain_type='sustainment'` at 16:27:35 |
| `ingest_retry_sensor` picked the retry row up | **yes** | 16:23:41 run `b24c7779` created with run_key `<id>-a2`; it started at 16:24:05 and posted its stage at 16:24:24 |

## The whole timeline

| time (Z) | event |
| --- | --- |
| 15:58:41 | run 1 `1344abcd` created |
| 16:02:38 | run 1 ends SUCCESS with no leaf. The row stays at `extracting`. **This is the silent end of your "Build today" note**, and it is item 1 of that build |
| 16:20:00 | bob picks PCN on the chip |
| 16:20:20 | the BFF relaunches (its share: 20 s, inside one 60 s poll) |
| 16:23:41 | doc-tools' sensor creates `b24c7779` (3m21s after the relaunch) |
| 16:27:35 | `b24c7779` resolves `kind='pcn'` |

**Why "no relaunch seen":** for 3m21s after the pick, the row said `received · attempt 2` and no Dagster run existed. That is doc-tools' 300 s sensor floor (2m50s last night, 3m21s today). It is not a stopped hop, so there is nothing to fix in the BFF for this trace.

**Not checked:** whether `b24c7779` reached `review`. At my last read it was STARTED in `build_user_knowledge_graph`. Last night's PCN took 11m19s in that step.

## Addendum: a dropper who is also a steward

- **The code has no role branch on either path.**
  - In `/leaf`, the access gate returns `(row, reason)`. `reason` (`dropped_by` / steward) is never read after the gate. The write, the sidecar rewrite and the answer are the same for both.
  - The relaunch pass never reads who set the leaf (`leaf_set_by` / `corrected_by`). It reads only the leaf, the sidecar kind, the run's status and the attempt.
- **Proven live on this drop:** bob, a steward, dropped it. His pick took the `dropped_by` path (the log line above) and relaunched.
- Every earlier relaunch test was alice's, so this is the first live proof for a steward-dropper. No seal distinguishes the two, because no code distinguishes them. I added none.

## What follows from this

- Item 1 of "Build today" closes the 18-minute silent window this drop sat in: a leafless row whose run has finished goes to `awaiting_kind` with reason `kind_not_identified` within one 60 s poll. It is in build now, with this afternoon's roll as the target if it is green.
- The sensor floor is 7f's. It adds about 3 minutes after every relaunch, and cortex shows `received · attempt 2` for that time. If you want that window shorter before the dry run, it is 7f's sensor interval to rule on.
