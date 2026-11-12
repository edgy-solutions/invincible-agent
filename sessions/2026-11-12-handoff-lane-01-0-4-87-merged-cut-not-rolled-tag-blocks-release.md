---
from: invincible-agent/lane/01
to: invincible-agent/lane/01
date: 2026-11-12, 10:46Z
supersedes: 2026-11-12-handoff-lane-01-0-4-86-rolled-rev-233-0-4-87-queue.md
---

# Handoff: 0.4.87 is merged and cut but NOT released or rolled. Live is still revision 233.

## The exact next step
**Wait for Chris**, who has to do two things:
1. delete the tag and re-run the release job:
   ```
   git push origin :refs/tags/invincible-agent-0.4.87
   gh run rerun 43162370205 --failed -R edgy-solutions/invincible-agent
   ```
2. give a fresh go to roll. The overnight pre-approval covered a roll by 11:00Z only, and that has lapsed.

**Then, in `C:\Users\cnogr\git\wt\01\tag0487`** (detached at `e29f7442`; venv built; secret copy matches, len 3059, sha 30d6452f):
1. `gh release view invincible-agent-0.4.87` should list three assets. Check `images` against `expected` in `image-digests.json`.
2. Diff the values against revision 233 with `valdiff2.py`. Allowed: the 19 repo digests, the cortex digest `37d6e016`, and `agentFleet.env.CAPABILITY_GRANT_OVERLAY_DIRS`. Anything more: stop.
3. Dry run through `dryfilter2.py`. List the STARTED Dagster runs. Take the lock.
4. Roll, then run Chris's checks:
   - realm reconcile OK;
   - task-grant-sync 0 refused, including bob's 3 rows;
   - every `/health` 200, including engine-f;
   - `enforce_ready=yes`;
   - `telemetry_misses` 0.

   Any failure: roll back to 233.
5. Tell perf, and append the outcome to the morning report.

## What happened
**Merged, in the architect's order:**
- #369 `68990cfa` (engine-f);
- #368 `bf2a8eb4` (bob's overlay);
- #370 `b10068fd` (cortex `fb3162a`);
- the cut, #371 `e29f7442`.

**My error:** I pushed the tag by hand. `chart_version_seal.py` read it as "already published", so the release job refused. Auto mode refused my deletion of the tag. Memory: `the-release-job-pushes-the-chart-tag.md`.

**Reports placed in the master tree's `sessions/`:**
- `2026-11-12-report-lane-01-to-chris-0-4-87-is-merged-and-blocked-on-one-tag-step.md`;
- `2026-11-12-morning-report-lane-01-to-chris-0-4-87-merged-not-rolled.md`;
- the perf packet `2026-11-12-packet-to-perf-from-lane-01-no-roll-tonight-lock-is-free.md`.

**Lock:** released 10:45Z.

**Demo clicks:** cortex never sent numbered steps, so the morning report's steps come from the code and are unverified.

## Still carried
- **0.4.88:** the per-viewer PR first, then the drift order, #327, #357, #360, #362, #365 and saf's export-by-range. The 0.4.88 packet must say:
  - the export grants go to the reviewing group;
  - the Promote reviewers' group needs `ingest:exportBatch` and the work profile's `can_export`.
- **mfg-trace ADR on Fri 11-13:** the next free number, status Proposed, `children_withheld: true`.
- Never signal WorkflowRunner `9062f943-…` `run` or `~5`.
- INTERNAL_DOOR_POSTURE stays observe.
- Chris still has to hand-delete `secret/iagent-engine-da-m2m`.
- After their walk: OpenDDIL's door-side read and the ActionRecord comparison.
- After Chris's Topaz seed: fin's URN re-read.
