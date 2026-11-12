---
from: invincible-agent/lane/01
to: invincible-agent/lane/01
date: 2026-11-12, 14:36Z
supersedes: 2026-11-12-handoff-lane-01-0-4-87-merged-cut-not-rolled-tag-blocks-release.md
---

# Handoff: 0.4.87 is rolled. Live is revision 234, all five of Chris's checks pass, and the lock is free.

## The exact next step
**0.4.88.** Open the train with the per-viewer PR first. Then the drift order:
1. DENIED_USER_SUBS readers;
2. ENABLE_DISPOSITION_AUTHZ;
3. MEM0→LiteLLM, plus the direct Ollama callers;
4. the inventory of redis, clickhouse, minio and redpanda, including the ClickHouse version for dag-tools Q13.

Then #327, #357, #360, #362, #365 and saf's export-by-range. The 0.4.88 packet must say:
- the export grants go to the reviewing group;
- the Promote reviewers' group needs `ingest:exportBatch` and the work profile's `can_export`, or the button stays hidden.

**Fri 11-13:** the mfg-trace ADR. Take the next free number, status Proposed, with `children_withheld: true`.

## What happened (11-12)
- **Release.** Chris deleted my hand-pushed tag and re-ran the release job. Attempt 2 published at 14:02Z: 3 assets, 19 of 19 images.
- **Before the roll.** The values diff against 233 showed only digests and the overlay key, and the dry run was clean.
- **Roll.** Chris said "Roll now". helm ran 14:12:10–14:32:14Z, and revision 234 is deployed. The second rollout finished at 14:33:23Z, and I released the lock at 14:34:05Z.
- **The first roll attempt refused before helm ran.** `upgrade-sandbox.sh` needs `ROLL_LANE=invincible-agent/lane/01` from a detached tag worktree, not just `HELM_KUBECONTEXT`.
- **Checks:**
  - realm reconcile OK, 51 rows ok;
  - task-grant-sync: 8 applied, 0 refused, 52 grants, +3 relations;
  - Topaz read shows alice and bob each hold all three grants;
  - 15 of 15 `/health` return 200, with engine-f on `be3d15fa`;
  - central-gateway logs `enforce_ready=yes`;
  - `telemetry_misses` 0 where configured;
  - cortex-ui runs `37d6e016`.
- **Placed in the master tree's `sessions/`:**
  - `2026-11-12-report-lane-01-to-chris-0-4-87-rolled-rev-234-all-checks-green.md`;
  - a pointer to it at the top of the morning report;
  - the perf packet `2026-11-12-packet-to-perf-from-lane-01-0-4-87-rolled-engine-f-fixed-lock-free.md`.
- **perf** holds its answer run until Chris says the demo is finished (architect's ruling).

## Still carried
- Never signal WorkflowRunner `9062f943-…` `run` or `~5`.
- INTERNAL_DOOR_POSTURE stays observe; D1 waits for "D1 moves to Wednesday".
- Chris's hand delete: `secret/iagent-engine-da-m2m`.
- After OpenDDIL's walk: their door-side read and the ActionRecord comparison.
- After Chris's Topaz seed: fin's URN re-read.
- The demo clicks still come from code, not a click-through. If Chris reports a step that differs, ask cortex to correct it.
- The tag worktree `wt\01\tag0487` can be removed once nothing needs it. It holds a secret copy.
