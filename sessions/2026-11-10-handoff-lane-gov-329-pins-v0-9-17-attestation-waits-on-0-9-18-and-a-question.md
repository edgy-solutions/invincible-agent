to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-10
re: #329 pins v0.9.17; attestation waits on v0.9.18 and on the architect's answer about the workflows
supersedes: 2026-11-09-handoff-lane-gov-322-approved-323-fills-nine-rows-five-items-held.md

## Next step

1. Read CI on #329 (head `6b070dfa`), worktree `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-17`, branch `lane/gov-pin-mesh-v0-9-17`. Fix anything red that the pin caused, except lane 74's ImpactRow tripwire (below). Merging is not gov's.
2. Check for v0.9.18 and whether it carries the field:
   `git -C C:/Users/cnogr/git/iagent-mesh-sdk ls-remote --tags origin 'v0.9.1*'`, then
   `git -C C:/Users/cnogr/git/iagent-mesh-sdk grep -n attestation <tag> -- iagent_mesh/ingest.py`.

## The dispatch, verbatim (11-10)

"gov: v0.9.17 fleet pin PR when the tag exists; `attestation: self` on pcn and pdn rows, second_party on the two workflows that declared it."

## #329: the v0.9.17 pin

- **What it moves:** the same 37 files as #300. All 17 locks name `8d1ee304`. The chart changelog opens 0.4.84, not yet cut. Locks were counted, not read: a deny rule blocks reading `uv.lock`.
- **Tests:** 1691 passed, 7 failed. On master `8095d651` at v0.9.15, 6 fail identically and 1 skips.
- **The one red the pin causes** is lane 74's `test_impact_row_is_the_ruled_row.py` tripwire ("re-export the SDK's ImpactRow"). Proposed: 74 stacks the re-export, and the two merge together.
- **Lane 1 stacks ADR-0065 D on #329.**
- When it merges, remove the worktree: `git cherry` shows no `+`, status is clean, `is-ancestor` holds. Removal deletes the venv and takes a few minutes, so run it in the background.

## Attestation

- **`pcn` / `pdn` `attestation: self`:** v0.9.17 was tagged without the field, so it rides v0.9.18. ca is asked in the 11-10 packet. The rows go in the **same commit** as the v0.9.18 pin, never before it (`extra="forbid"`).
- **"second_party on the two workflows that declared it":** held. The question is in the 11-10 packet in the master tree's `sessions/` (`...which-two-workflows.md`):
  - No workflow row declares it.
  - `WorkflowDefinition` is `extra="forbid"`, so a workflow field needs ca.
  - `HumanAwaitStep.excludes` already expresses second-party review: `origin_confirm.yaml:40` excludes the dropper.
  - The candidates are `origin_confirm`, the ADR-0057 ratification (no route is built for it) and ADR-0062's proposer rule (code, not a row).
  - Wait for the architect's answer before doing anything.

## Closed since the 11-09 handoff

- #322 merged at `5fa0f3e4`, and #323 at `8095d651`. Both worktrees are removed.
- Board item `01M6A9QDN1QSSWQ74F6JV74W0B` is still `blocked` on the architect's call on the four held kind rows and the work-instruction card (11-09 packet). It has had no answer yet.
