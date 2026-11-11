to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-11
re: #342, #343, #351 and #353 (v0.9.19) are merged; lane 74's provenance tripwire is red on master; next is ca's v0.9.20
supersedes: 2026-11-10-handoff-lane-gov-342-fin-dag-tools-343-sdk-v0-9-18-attestation.md

## Next step

1. **Watch for v0.9.20** (ca's token-validation release):
   `git -C C:/Users/cnogr/git/iagent-mesh-sdk ls-remote --tags origin 'v0.9.20*'`.
   - When it is tagged, run `git diff --stat v0.9.19 v0.9.20` and read what it carries.
   - Open its pin move the same way as #353, on a branch off `origin/master`: 17 pyprojects, 17 locks (iagent-mesh alone), `meshSdkVersion` and its comment, the `option_deciders.yaml` note, and a changelog bullet.
   - Run its tests before asking for the merge.
   - **On the train only if it lands before Thursday 2026-11-12 12:00Z.** Lane 1 needs it for the engines' refusal branch.
2. **All four PRs merged on 11-11:**
   - #343 at `8987d487` (03:57Z)
   - #351 at `a74b927a` (04:01Z)
   - #342 at `c46c38e0` (04:05Z)
   - #353 at `2f978413` (04:19Z)
   Master pins v0.9.19 in 17 pyprojects. Lane 74's tripwire red rides along (see Tests); watch for 74's answer.
3. **Remove the worktrees** (status clean, `git cherry` shows no `+`, `is-ancestor` holds), with `git worktree remove --force` in the background. `pin-mesh-v0-9-19` is detached at master for the confirming run; reattach it or remove it.
   - #342: `C:\Users\cnogr\git\wt\gov\fin-dag-tools`
   - #343: `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-18`
   - #351: `C:\Users\cnogr\git\wt\gov\course-drift`
   - #353: `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-19`
   - The doc-tools detached worktrees `wt\gov\dt-pin` and `wt\gov\dt-main`: remove them with `git -C C:/Users/cnogr/git/doc-tools worktree remove`.

## The dispatches, verbatim (11-11)

- "gov: #342 and #343 accepted; Lane 1 merges both. The course drift is yours, on the 0.4.85 train, one PR: 1. Bump .github/doc-tools.ref to the doc-tools commit that sandbox actually runs, read from helm (the deployed image's source sha), not to doc-tools main. 2. Update the course overlay row to match that commit's served declaration, including ExtractSectionConcepts and concepts.normalise, in the same commit. 3. The drift leg against the pinned ref passes. If main has moved past the deployed commit, the main leg may stay red; say what remains. Then the v0.9.19 pin move once ca tags it."
- "gov, tonight: 1. #342: merge master in, keep both CHANGELOG entries. 2. v0.9.19 pin move on the 0.4.85 train, now (tagged). 3. When ca tags v0.9.20: its pin move, on the train if it lands before Thursday 12:00Z; Lane 1 needs it for the engines' refusal branch."

## Heads

| PR | branch | head | `^2` |
| --- | --- | --- | --- |
| #342 fin dag-tools v0.13.0 | `lane/gov-fin-dag-tools-v0-13-0` | `30e95c52` | `a02cfda3` |
| #343 SDK v0.9.18 + `attestation: self` | `lane/gov-pin-mesh-v0-9-18` | `b923efbf` | `a02cfda3` |
| #351 course drift | `lane/gov-course-drift-doc-tools-728afaf` | `6172933d` | `a02cfda3` |
| #353 SDK v0.9.19 | `lane/gov-pin-mesh-v0-9-19` | `c8db590a` | built on #343's head |

## #351: course drift

- `.github/doc-tools.ref` moves to `728afaf5`, the commit the sandbox runs. I read it from the deployed doc-tools image's `org.opencontainers.image.revision` label with `crane config`, not from doc-tools main.
- The course row's passes gain `training.baml::ExtractSectionConcepts` and `concepts.normalise`, in the same commit.
- **Local drift runs:**
  - Pin leg: 17 passed. Main leg (`0f0e3db`): 17 passed.
  - Control (master's row at the pin): 1 failed.
  - The content_kinds tests: 799 passed.
- **What remains on the main leg:** nothing today. It goes red again if doc-tools main changes a shared kind before the sandbox rolls. When doc-tools tags a release, move the ref onto it.

## #353: v0.9.19

- **Tag:** object `b3c845fb`, peeling to `ef7a6f35`; its pyproject reads 0.9.19.
- **What it carries:**
  - `WorkOrder.option`/`readiness` and `ActionProvenance.case_definition`/`case_id`/`emitted_by`
  - `ACTION_CONTRACT_VERSION = "2"`
  - `DataProvenance.dataset_urn`/`ticket_id` become optional; `as_of` stays required.
- **Not in it:** multi-provenance per ImpactRow (unruled).
- **Opened ahead of its local tests,** per the architect's "now". Lane 1's ActionRecord seal (#344) tightens with no edit. If it goes red, the red goes to Lane 1; do not loosen the seal.
- The pcn/pdn comments citing "SDK v0.9.18" stay; they are historical.

## Tests

- **#343's merged head `b923efbf`, 35 files: green.** 1576 passed, 1 skipped (cortex-ui is not checked out in the worktree), 3 xfailed.
- **#353's head `c8db590a`, 17 files: one red.** 310 passed, 1 failed.
  - The failure is lane 74's `test_TRIPWIRE_THE_SDKS_PROVENANCE_IS_STILL_THE_ONE_THAT_CANNOT_SAY_ABSENT`, which fires on any change to v0.9.17's `DataProvenance`. It fired as designed.
  - Its sibling, `…_CANNOT_CARRY_A_SERVED_ROW…`, stays green: the SDK's ImpactRow still refuses a served row, and only in `data_provenance`. My reading is that this is multi-provenance, which is unruled.
  - Lane 1's ActionRecord seal is green on v0.9.19.
- **The red is on master.** #353 merged at `2f978413` (04:19Z) before the run reported. The PR was opened on the architect's "now" with its tests marked pending, and CI runs no pytest. Rerun on master: `2f978413`, the file alone: 1 failed, 5 passed (iagent-mesh 0.9.19).
- **Reported, file not touched:** `sessions/2026-11-11-packet-to-lane-74-from-gov-v0-9-19-is-on-master-your-provenance-tripwire-fired.md`, cc Lane 1 and the architect. The re-export, or a ruling that it waits on multi-provenance, belongs to 74 and the architect.
- **Lesson:** a pin move opened ahead of its tests merges on green CI, and CI runs no pytest here. Next time, put "do not merge before the count" at the top of the PR body, or hold the PR as a draft until the count is in.

## Still open

- `promotion._declared_attestation` still returns `None`, so the pcn/pdn `attestation: self` rows are not yet read. Wiring it is Lane 1's.
- Board item `01M6A9QDN1QSSWQ74F6JV74W0B` is still `blocked` on the architect's call on the four held kind rows and the work-instruction card.
- `test_a_finished_run_with_no_leaf_waits_for_a_kind.py` has 2 pre-existing failures, reported to Lane 1.
