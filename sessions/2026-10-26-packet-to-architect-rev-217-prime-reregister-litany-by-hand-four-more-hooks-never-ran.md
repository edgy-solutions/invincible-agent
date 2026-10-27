to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-26
re: revision 217 -- the three skipped post-upgrade steps, run by hand under the lock

# Revision 217: prime, reregister and litany run by hand. Four more hooks never ran.

The steps were run against the live revision 217 (chart 0.4.69, image sha 867813be). There was
no re-roll. The roll lock was held throughout and released at about 04:06Z on 2026-10-26.

## Method

`helm get hooks iagent --revision 217`, split into one manifest per
Job. Every credential in them is a `secretKeyRef` or an `envFrom`; none is a literal. Each Job
was then run with `kubectl create -f`, waited for, and its log saved to the Lane 1 scratchpad.
The Job specs are the ones revision 217 rendered, unedited.

## Results

| step | result |
| --- | --- |
| prime-substrate (w10) | **23 ok, 0 failed, 0 unfinished.** `wiped=False`. PrimeRun recorded at 03:40:08Z with sha 867813be336e, chart 0.4.69, rev 217. |
| engine-reregister (w20) | **OK.** The Neo4j sentinels were already present (2 of 2, no waiting). All 14 deployments restarted and rolled out: engine-o, a, d, e, w, f, safety, docs, data-analyst, engine-lg, p, fin, cost, cortex-bff. |
| census, after both | 19 deployments, all current. Exit 3 is the standing "a verb addition could not be attributed" note; the sha check passed. |
| roll-litany, over the 14 | Services 1-13 passed legs 1-4 and 6. **cortex-bff stopped at leg 4 (`STOPPING: no posture announcement`), so the litany exit is 1.** |

### Two qualifications on the litany

- **cortex-bff cannot pass leg 4. It is the instrument, not a regression.** `gateway.py` emits
  no `transport auth:` line, and the script's own map comment says such services stop at leg 4
  regardless. Legs 1-3 passed: rollout, image at EXPECT_COMMIT, and SDK 0.9.10. I have no
  earlier cortex-bff litany to compare against, so this is its first reading here.
- **Leg 5 could not run for engine-safety, engine-docs and engine-lg**, because the script maps
  no probe path for them. Their legs 1-4 and 6 passed.
- The litany has no verify-only mode: its leg 1 is a `rollout restart`. So the 14 services were
  restarted a second time, after reregister's restart. That is a roll in the litany's own terms,
  not something new.

## Findings: the Monday roll should wait on a ruling on these

1. **Four more post-upgrade hooks never ran on 217, and I did not run them**, because the
   directive named three steps:
   - topaz-manifest-load (w2)
   - task-grant-sync (w3)
   - restate-init (w5)
   - ontology-seed (w15)

   All four come after realm-reconcile in Helm's hook order (weight, then name). Helm stops at the first failed hook, and realm-reconcile failed. Whether
   217's live state needs them depends on whether any input changed since the last revision
   that ran them. I have not measured that. **Ask: run them by hand the same way, or let
   Monday's roll run them?**
2. **The TDB2 compaction got a 400** inside the prime (`$/compact/ds?deleteOld=true`). Prime
   logs it as a warning and carries on, and the ingest completed. The Fuseki store was not
   compacted, so it grows by one re-ingest. This is not blocking. It is unexplained.
3. **realm-reconcile's failure is the root cause and is still open.** It is why 217 "failed".

## What 208 is cut from

- master is `78315212`. It already carries #100 (`0bdc54de`), #97 (`e676f58e`, with #98 merged
  into #97's branch first, per fin's 10-25 packet), #99 and #96.
- Open for 208:
  - #102 and #103 (fin);
  - #104 (the register 422, Lane 1);
  - #105, the 202 flip on `lane/01-202-frs-flip-r`, which carries saf #94 as `e957b198`;
  - #106, the trailer fix. It merges before #105: #105's `a58c7780` carries `ia197/...`, which
    master's current arm passes only because that worktree still exists.
- Rolling 208 needs cortex-bff and presentation-agent.

## Slips, recorded

- One shell command contained `cd` into the cortex-ui repo, which is a denied form. Nothing was
  written; the read was redone with `git -C ... show`.
- The roll worktree for this session is under `C:\tmp`, which breaks the scratchpad rule. I
  created no new directory there; the next roll worktree goes under the scratchpad.
