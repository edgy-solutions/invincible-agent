to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-10
re: #336 opens the walker fix; #329 merged master and moved to 0.4.85; the workflows question is closed
supersedes: 2026-11-10-handoff-lane-gov-329-pins-v0-9-17-attestation-waits-on-0-9-18-and-a-question.md

## Next step

1. Both PRs are approved (the architect, 11-10: "#336 and #329 are good. Topaz sync for the two walkers happens before 0.4.85 rolls (Chris)."). Merging is not gov's. Once each merges, remove its worktree.
   - **#336** (walker fix): head `a616770f`, worktree `C:\Users\cnogr\git\wt\gov\walker-deciders`, branch `lane/gov-walker-deciders`. CI: 20 passed, 3 skipped. That count includes one cortex-bff job that failed on a ghcr push error and passed on re-run.
   - **#329** (v0.9.17 pin): head `54c161c0`, worktree `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-17`. CI: 21 passed, 3 skipped.
   - Master opened its own 0.4.85 list (#335, #338). Both PRs merged master in and are now one bullet each at the end of that list. They append at the same place, so whichever merges second has a one-hunk changelog conflict. #329's root lock merged textually; `uv lock --check` passes, and it still differs from master by 4+4 lines.
2. Check for v0.9.18 and whether it carries the field:
   `git -C C:/Users/cnogr/git/iagent-mesh-sdk ls-remote --tags origin 'v0.9.1*'`, then
   `git -C C:/Users/cnogr/git/iagent-mesh-sdk grep -n attestation <tag> -- iagent_mesh/ingest.py`.
   If the tag has the field, open the v0.9.18 pin PR with `attestation: self` on
   `policy/overlays/openddil-lab/content_kinds/pcn.yaml` and `pdn.yaml` **in the same commit** (`extra="forbid"`).

## The dispatch, verbatim (11-10)

"gov: no second SDK field. ADR-0057 and ADR-0062's step-level `excludes:` already is their second-party declaration. `attestation: self` rows for pcn and pdn go in with the v0.9.18 pin. Open the walker fix PR (erin and chris join obsolescence-deciders)."

## #336: the walkers join `obsolescence-deciders`

- **Changes:** erin and chris each gain the group in `policy/users.yaml`. `groups.yaml`'s member note names all three members. The walker seal counts 12 mirrored groups, citing Lane 1's packet's ruling ("the walkers mirror alice"). The chart changelog opens 0.4.85.
- **Tests:** the 29 files that read `users.yaml` or `option_deciders`, plus `test_oidc_broker_chart`, give 841 passed and 1 failed. The failure is environmental: the sibling-SDK check. Control: master's `users.yaml` gives 2 failed (both walker arms).
- **Before the roll:** Chris runs topaz_sync by hand. The PR body says so.
- After it merges, remove the worktree. The precondition is the usual one: `git cherry` shows no `+`, status is clean, and `is-ancestor` holds.

## #329: the v0.9.17 pin

- 0.4.84 was cut (#333) without the pin. Master was merged in at `dcde090c`. The only conflict was the changelog, whose entry now opens 0.4.85.
- After the merge, all 17 locks still name `8d1ee304`, no file names an older tag, and the branch differs from master in 37 files.
- The PR body is updated.
- **Changelog overlap:** #329 and #336 each open a `## 0.4.85 — not yet cut` section. Whichever merges second keeps one heading with both entries. #336's body tells the merger.
- Lane 74's ImpactRow tripwire is still the one red the pin causes. Lane 74 stacks the re-export.

## Closed

- **The "two workflows" question:** the ruling above closes it. `excludes:` is the second-party declaration, and no SDK field is added. Nothing for gov to do on workflows.
- **Lane 1's `viewer_may_attest`-withdrawn packet:** read. It is already superseded: the content-kind row was accepted.

## Still open from 11-09

- Board item `01M6A9QDN1QSSWQ74F6JV74W0B` is still `blocked` on the architect's call on the four held kind rows and the work-instruction card.
- `test_a_finished_run_with_no_leaf_waits_for_a_kind.py` has 2 pre-existing failures, reported to Lane 1.
