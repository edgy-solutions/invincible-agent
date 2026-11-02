to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-10-24 (Saturday, overnight)
re: after roll 207 (rev 215). The doc-tools roll waits on Chris, the workbench stores wait on the architect, 208 is next

# Handoff: 215 is live, and three things wait on someone else

**Read first:** `sessions/2026-10-24-report-to-architect-overnight-p0-roll-207-rev-215-walks-workbench-namespace-adr-0060.md`
(cd1e2956). It holds the measured detail; this file holds only the state still in flight.

## State at handoff

| branch | sha (pushed) | state |
| --- | --- | --- |
| `master` | `b6389518` | 207 merged as `a31b61cb`; the 0.4.66 note and `.github/doc-tools.ref` → `b95a550` |
| `lane/01-ingest-v1` | `cd1e2956` | the worktree `/c/tmp/ia193` sits here. It contains all of `lane/01-208` (`e8b4f346`), plus `ingest-v1.md` and its sample (`1fb9e242`), plus tonight's reports. 11 ahead of master |
| `lane/01-adr-0060` | `7e5074c9` | ADR-0060, Proposed; worktree `$S/wadr`. Not to merge until it is ruled |
| `lane/01-207`, `lane/01-rel-0466` | — | fully in master |

- **The sandbox** runs helm `iagent` revision 215 (chart 0.4.66). The rollback target is 214.
  doc-tools is still v0.2.0.
- **Parked:** bob's queue holds `document_promotion:sha256:7b5e584c…` from the PCN26-207 walk.
  Leave it parked unless the architect says to act on it.
- **The `training` namespace** is hand-made: MinIO user and policy `wb-training-read`, and Secret
  `training/wb-store-read`. No bootstrap reproduces it.

## Waiting on someone else (re-read the inboxes before saying "waiting")

1. **Chris: the doc-tools v0.2.1 roll** (doc-tools PR #159 is open). Chris picks one of options (a), (b) or (c) in the
   report. Never read the doc-tools `*.secret.yaml`: that read is denied, so do not retry it.
2. **The architect:**
   - Neo4j for wb, options (a), (b) or (c), and whether Weaviate's anonymous access is in scope;
   - the classify timeout or GPU-host latency, which failed the docs walk and Q9;
   - the TRAINING reviewer (`bob` is a placeholder);
   - the ADR-0060 rulings (§6);
   - whether `1fb9e242` (ingest-v1.md) goes to master ahead of 208.
3. **ca:** a review of ADR-0060 §5. The packet is in iagent-mesh-sdk `sessions/`.
4. **wb:** whether the packet in their `sessions/` landed. Chris does DNS and the TLS copy for the
   workbench hosts.

## Next, in order (when no ruling is blocking)

1. **208:**
   - cortex's 10-24 packet (master `sessions/2026-10-24-packet-to-lane-01-208-review-task-id-…`).
     `review_task_id` at review on a zero-row notice names a promotion task that was never filed
     (gateway.py around :11756/:11761). Return the open task's id, add a seal, and fix
     `docs/api/ingest-v1.md:279` to match;
   - then the v0.9.11 pin, as in the 10-23 handoff.
2. **Fold the training namespace, the MinIO user and policy, and the Secret into the chart**, next to
   `minio-bucket-init-job.yaml` (hook weight −5, `utilImages.mc`). Owed by this lane.
3. **Follow-ups found and not chased:**
   - the TDB2 compaction 400 in prime;
   - the MinIO root credentials sit as plain env on the StatefulSet;
   - the "Q9" naming collision at `walk-census.yaml:311`;
   - the kinds cad, schematic and engineering-document.

## Scratch still alive

- `$S/wadr` (ADR-0060): keep it.
- `$S/dtpin` (doc-tools worktree, branch `01/pin-v0-2-1-086766d7`, PR #159): pushed and clean. Keep it until the doc-tools roll is done.
- `w207`, `wm207` and `wrel` are removed.
- `$S/wt/ia196c` and `$S/wt-same-actor` are from older work; check them before removing.
- Walk logs and probe scripts are in `$S`, named `walk207-*`, `case207*`, `wbtrain.sh` and `wbprobe-pod.yaml`.
  The persona tokens in `$S/tokens` expired at about 06:39Z.
