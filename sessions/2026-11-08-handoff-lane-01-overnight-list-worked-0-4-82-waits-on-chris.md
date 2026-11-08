to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-08 (05:20Z)
supersedes: 2026-11-07-handoff-lane-01-0-4-81-rolled-rev-228-fin-live-check-under-the-lock.md

# The overnight list is worked; 0.4.82 waits on Chris's word

## NOW

**Nothing rolls until Chris says so.** Sunday's order, from the architect:
1. 7f's doc-tools roll. It is one roll in two applies. It is not finished until 7f's
   `expectImage` write lands; see doc-tools `sessions/2026-11-08-placed-for-chris-the-ca3e7d83-…`.
2. tr's re-ingest hour.
3. 0.4.82.

**For the 0.4.82 roll, on Chris's word:**
- Re-render the values diff in `wt\01\cut0482` and show it.
- Take the roll lock.
- List STARTED runs, avoid 07:00Z, and re-read every inbox.
- Remove the copied secret overlay from `wt\01\rel482` after the roll.

0.4.82's Topaz sync carries no new group. That is confirmed in the roll file.

## Open PRs (green and held unless noted)

| PR | branch | what | state |
| --- | --- | --- | --- |
| #309 | attach fix | `delegate_not_seeder` | green `36fd0b8c`, held |
| #313 | `wt\01\taskid` | The runner fills `task_id`; it also carries #301's lost content | green `e491dcad`, held. saf's test follows it |
| #317 | `lane/01-adr-0065-c-the-ontology-slice` (`wt\01\ontology`) | ADR-0065 C | green `032b11ad`, held. The LTB fields follow iagent-mesh v0.9.16 |
| #318 | `lane/01-board-sweep-11-08` (`wt\01\sweep`) | Board sweep | Board-only: merge on green with `train-one2.sh 318` |

## Done this window

- **The board sweep (#318).**
  - Two Lane 1 items are done.
  - The pause-record item (live read owed) and the acryl item (done-when 3 owed) stay in review.
  - C is in review. D is blocked.
  - Cortex's export item: its capabilities half moves to open (no PR, so not review).
  - `SWEEP.md` has 77 rows.
- **The Monday rulings packet** is placed in the master tree:
  `sessions/2026-11-08-packet-to-architect-from-lane-01-the-monday-rulings-in-one-list.md`.
  It has A1–A5 (the five named items) and B1–B7:
  - D's three blockers;
  - gov's four #314 questions;
  - #314's new Topaz group;
  - LTB scope, SDK vs ADR;
  - the `iof:` prefix finding;
  - Cortex's item 3, where Lane 1 withdrew its 11-07 statement;
  - the on_behalf_of ruling vs the code.
- **OpenDDIL's sample event** validates against ingest-v1's schema at 0.4.81, and an offline replay
  of the door routes it. The reply packet is placed.

## Blocked: ADR-0065 D (item `01M6W93W013YFR30HE67S3VF8B`)

D waits on three things, all on the Monday packet's B1:
- the v0.9.16 pin, whose mover is unruled;
- gov's #314, which already seeds the registry;
- the dispatching-disposition trigger, which overlaps 74's `01M6QHKVK50KZ10GJM77T5051F`.

Do not build around any of them.

## Queued, unchanged

- The FLOW_DECOMPOSITION projector row (`wt\01\flowrow`). It waits for fin's `menu:` block.
- ADR-0063 §2–§4 from 7f, as a docs PR.
- ADR-0067: wait for OpenDDIL's draft.
- Forks 1+3 (`01M6KF81WMJJXVKQAP12M0QTMY`), and ADR A–E.
- The alice Topaz delete, which goes to Chris.
- NetworkPolicy: Jena → Weaviate → Neo4j, by 12-01.
- Items `01M6QGKGVF12QW1REN9K0K1HMB` and `01M6QGKFTKSD18ZAPMA285F25X`.

## Worktrees

All of Lane 1's worktrees live under `C:\Users\cnogr\git\wt\01\`:
- `cut0482`
- `dag-tools-internal-doors`
- `doc-tools-pin`
- `flowrow`
- `ontology`
- `rel482`
- `sweep`
- `taskid`
- `tasking`
- `train`

## Notes

The master tree has two untracked board items. Both are already on origin/master:
- `01M6T3M9…`: the master tree's copy is the older one.
- `01M6W1Y0…`: identical to origin/master.

Leave them for the tree's owner.
