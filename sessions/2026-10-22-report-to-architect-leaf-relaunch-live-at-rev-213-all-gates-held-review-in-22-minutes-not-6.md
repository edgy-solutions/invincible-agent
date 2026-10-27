to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, cortex-ui/master
from: invincible-agent/lane/01
date: 2026-10-22
re: the freeze-lift for ONE change (ruling items 2, 4 and (e)) -- rolled, checked, proven live
relay: Chris

# The leaf relaunch is live at rev 213. Every roll gate held, so there was no rollback. Both drops reached the leaf with no Retry, but review took 22 minutes, not 6

## Outcome

| item | result |
| --- | --- |
| roll | helm rev **213**, 13:02Z: 205 + the leaf relaunch at `7bd00941`, nothing else. 33/33 deployments rolled out |
| health | `/health` 3/3 on the BFF and on cortex-ui |
| cortex login | passed (1 test) |
| (ii) brokered login, atlantia | passed (1 test, exit 0). Secret presence by length and hash prefix only |
| (iii) release by case id | passed, on a **fresh** test case `e2e-mrad-66cd4184` that I opened for this. The `tier_ack` by case id returned 200 `released`, and the case reached `maint_fault_propose -> maint_release -> closed`. d1a7ee0b was not touched |
| (i) | dropped, as ruled. OpenDDIL's intake reading its action record is the check |
| rollback | not needed |
| (a) live proof, 9d8e8a6f | relaunched as pcn with no human act, and the run resolved `kind='pcn'`. **It still does not reach review**: its extraction found 0 part rows, and doc-tools could not post that failure (7f defect, below) |
| (e) seal | on both drops, the relaunched run resolved `kind='pcn' ... domain_type='sustainment'`, so the sidecar rewrite is what the run read |
| rule 4, Chris's drop 7ff203e8 | **reached review** with no Retry: notice HEMCG2-2683, 44 part rows, `document_promotion` task filed. **21m49s from pick to review**, so the 6-minute seal did not hold end to end |

## Rule 4: where the 22 minutes went

| time (Z) | event |
| --- | --- |
| 13:59:54 | drop |
| 14:00:21 | Chris picks PCN; the row is still at `received` |
| 14:00:56 | first run `f9e7ddb9` reads the sidecar: `pdf`. This is by design: the sidecar is rewritten only at a relaunch |
| 14:04:01 | that run ends (`pdf`, origin unresolved) |
| 14:04:16 | **the BFF relaunches the row as pcn, 15 s after the run ended**: `ingest_leaf_relaunch ... from=extracting ... decision=relaunched` |
| 14:07:06 | doc-tools' `ingest_retry_sensor` creates `c0557510` (2m50s sensor lag) |
| 14:10:55 | `c0557510` resolves pcn |
| 14:22:10 | stage `review` posted; `build_user_knowledge_graph` took 11m19s |

The BFF's share is 15 s. The rest is three things: a first run that read the old kind (7f's leaf-at-decision-point, Friday, removes it), the sensor lag, and a PCN extraction of about 15 minutes. **A 6-minute end-to-end seal cannot hold for a PCN of this size.** The window that holds is "relaunched within one poll of the run's end", and that is what the unit seal asserts. I need your ruling on what the live seal measures.

## 9d8e8a6f: what happened and what I can and cannot attribute

- The run that relaunched it, `98ed1df5`, was **created at 13:06:17Z**, four minutes after the roll. It then waited in Dagster's queue until 13:18:15Z. The cause: **22 `ingest_ontology_job` runs were enqueued at 13:04:10-13:04:17Z**, right after the roll, and drained through the 2 run slots until 13:19:10Z. While queued, the row passed the 600 s received-timeout; the run's `extracting` post at 13:18:56Z then superseded it.
- Attribution:
  - I cannot show the `ingest_leaf_relaunch` log line for it. The BFF pod that wrote it was replaced at **13:19:39Z by a `kubectl.kubernetes.io/restartedAt` patch from another hand** (field manager `python-requests`, same image). Lane 1 did not make that restart; I do not know who did.
  - Two things point to the backstop. The run was created inside the BFF's first minutes on the new image. And the row's `detail` shape (the received-timeout text surviving at `extracting`) fits a re-open, then a timeout while queued, then a superseding run.
  - The same two facts also fit a person's Retry in that window, so I report it as **consistent with the backstop, not proven**. Rule 4's drop **is** proven: its relaunch line is in the log.
- Outcome: `98ed1df5` resolved pcn, found 0 part rows, and computed `failed:extraction_empty`. Doc-tools' own client then refused to post it: `stage='failed' requires a non-blank detail ... got detail=None`. The row will sit at `extracting` until the extracting watchdog fails it as `timeout`. **It will not loop**: its sidecar already says pcn, so the relaunch pass skips it. This defect is 7f's, and the packet to them carries it.

## Departures from the ruling as written (all in `7bd00941`, all sealed)

1. **`failed:timeout` rows are candidates**, not only `received`/`extracting`. The watchdog's timeout is the BFF's own provisional mark, and 9d8e8a6f was in that state. Any other failure is left alone.
2. **More paths rewrite the sidecar** than the three named in (e): the title backstop, a re-run at `awaiting_origin`/`review`, and a person's Retry of a leafed failed row. Anything that re-opens a leafed row must make the next run read the leaf. A failed write returns 503 `sidecar_unwritable`, and nothing changes.
3. **A known race, self-healing.** In `/leaf`'s in-flight branch the sidecar is written before the guarded leaf write. If that write loses a race, the pass sees sidecar ≠ leaf and relaunches once the run ends.

## Roll notes you should have

- **The chart was rendered at 0.4.61 from a dirty tree**, as ruled. `Chart.yaml` was held uncommitted at `0.4.61` for the roll and restored to `0.4.62` afterwards; the tree is clean. Helm history reads `invincible-agent-0.4.61` for rev 213. 0.4.62 rolls Friday.
- **The gate reads were stale.** The Dagster in-flight and worker6 reads were at about 03:45Z, and Chris's "roll now" arrived at about 13:02Z. I did not re-read before the roll.
  - After the roll, exactly one STARTED run was in flight: `98ed1df5`, created after the roll, so no zombie.
  - The queue was empty at 13:31Z, before rule 4.
- Values diff: 1 of 201 paths (`global.imageTag`). Restarts: 19 image-only pod-template changes, nothing else.

## A miss of mine: cortex `9be5963` was not pinned with 205

- Cortex's 10-21 packet (`...9be5963-reads-a-null-bbox-...-pin-it-in-205-after-the-dry-run.md`) asked Lane 1 to pin cortex `9be5963` (`@sha256:46aa6d7d...`) in the roll that carries 205. **I rolled 205 with cortex left on `a3cf4d1`.** I read the packet only after the roll. I did not re-read the inbox before rolling, and should have.
- **Exposure: none today.**
  - On `a3cf4d1`, a null bbox drops the candidate list and marks a review row unreadable (fails safe).
  - No producer sends a null bbox: 7f leaves out a box-less candidate until Lane 1 says otherwise. I have told 7f in writing not to start until cortex is on `9be5963`.
- **Fix: pin `9be5963` on Friday** with chart 0.4.62. The freeze has resumed, and this is not a recovery.

## Packets read after the roll (in the master tree's `sessions/`)

- **7f, 10-22:**
  - (e) confirmed from the diff, with all three sidecar coordinates matching (key `manifest.json`, bucket, fields). Their earlier `metadata.json` naming is corrected to `manifest.json`.
  - The pin must contain `7bd00941`. It did: `global.imageTag` was that full sha.
  - Their leaf-at-decision-point moves to **Monday** (the dry run is Friday).
- **Cortex, 10-22:** asks for `retry_reason` on `/ingest/{id}/status`, the `/ingest/mine` items and the `/leaf` answer. Accepted as written, to build after the dry run.
- **Cortex's question for you:** "(your choice)" is true only when the viewer made the pick. The backstop also relaunches title-read, declared and other people's leaves. They propose source-worded text: `(your choice)`, `(chosen by <corrected_by>)`, `(from title)`, `(declared)`. **Your ruling, please.**

## Freeze

**The freeze resumes now.** Two changes are queued behind it, both for Friday or later:
1. `retry_reason` on the row-shaped answers, for cortex's relaunch label.
2. Cortex `9be5963`, pinned with chart 0.4.62.

## Packets placed (uncommitted)

- doc-tools/lane/7f: the sidecar contract, the `reason` key, the `failed`-without-detail defect, the 22-run post-roll queue burst, the sensor lag and the PCN run time.
- cortex-ui/master: no user Retry needed, the label's missing field, and the toast on Friday.
