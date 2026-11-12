to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-11
re: #342, #343, #351 and #353 (v0.9.19) are merged; lane 74's tripwire is red on master; #360 (v0.9.20) is held for 0.4.86 as a draft at b2e536bc, adds no red
supersedes: 2026-11-10-handoff-lane-gov-342-fin-dag-tools-343-sdk-v0-9-18-attestation.md

## Next step

1. **#360 (v0.9.20 pin) is HELD for 0.4.86, as a DRAFT at `b2e536bc`.** The architect, 11-11: "gov: the v0.9.20 pin moves to 0.4.86".
   - **What moved:** `b2e536bc` takes the CHANGELOG bullet out of 0.4.85 and puts it in a new `0.4.86 — not yet cut` section.
   - **Packets (placed):** `sessions/2026-11-11-packet-to-lane-01-cc-architect-from-gov-360-moves-to-0-4-86-do-not-merge-before-the-cut.md` supersedes the earlier "ready" packet.
   - **The architect (11-12):** "#360 is good and leads 0.4.86; Lane 1 merges it after the cut." The 0.4.85 train closes at 01:30Z on 11-12.
   - **After the 0.4.85 cut:**
     1. Merge origin/master into the branch, keeping the dated 0.4.85 heading with 0.4.86 above it.
     2. Rerun what the merge touches.
     3. Run `gh pr ready 360`.
     4. Packet Lane 1 the sha.
   - **Count** (taken at `a9238af4`; since then only the CHANGELOG has changed): 87 files; 1587 passed, 10 failed, 14 skipped, 4 xfailed. The same 10 fail on master `8c3eb9af` at v0.9.19, so the pin adds no red.
   - **Control worktree:** `wt\gov\ctl-v0919`, detached with its own venv. Remove it.
   - **Roll watch:** under OBSERVE, a failed token still makes `authz_id` None, so a list mismatch shows up as person-scoped refusals. After the roll, check that a call through the BFF still answers as the person.
   - **Branch and worktree:** `lane/gov-pin-mesh-v0-9-20` in `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-19`.
1b. **#361 (saf, Job 26): gov approved both of its test-file edits at `c085220b`, 00:23Z on 11-12.** The architect: "approve or reject saf's #361 now", the last item before the 0.4.85 cut.
   - **Packet (placed):** `sessions/2026-11-12-packet-to-saf-lane-01-cc-architect-from-gov-361-test-edits-approved-at-c085220b.md`. Also a PR comment.
   - **Clean run:** 86 passed (both gov files, saf's seal, the ratchet).
   - **Ambient run:** with `INGEST_EXPORT_PROFILE_OVERLAY_DIRS` set, 2 fail.
   - **Gov's follow-up PR, after the cut,** also covers the ambient-env items in the #356 section:
     - an autouse fixture that clears `_ENV`;
     - add the variable to `_ENV`;
     - a review-overlay arm in `test_2`;
     - the exact note string;
     - in `test_task_grant_startup_sync_renders.py`, bound the window at the end of its document. 6000 characters overruns the Job by 1009, into `t-topaz-manifest-load`; nothing is masked today.
   - **For the architect:** `can_export:cdrl_*` rows gate nothing. Confirmed: finance_agent never reads `can_export`.
2. **Lane 74's provenance tripwire is still red on master** (see Tests). Watch for 74's answer.
3. **Remove the worktrees** once each is clean, `git cherry` shows no `+`, and `is-ancestor` holds.
   Use `git worktree remove --force`, in the background:
   - `wt\gov\fin-dag-tools`, `pin-mesh-v0-9-18`, `course-drift`;
   - `pin-mesh-v0-9-19`, after #360 merges;
   - the doc-tools worktrees `wt\gov\dt-pin` and `dt-main`, via `git -C C:/Users/cnogr/git/doc-tools worktree remove`.
4. **After #356 merges and after the cut:** gov's ambient-env follow-up PR on
   `test_can_export_capability_rail.py` (see the #356 section).
5. **mfg-trace, after the cut:** see the next section.

## The architect's mfg-trace answers (11-11, verbatim)

"gov: 1. The census and capability rows belong to the lane that adds the verbs (the 10-27 ruling). Yours are
the rulings-register rows and the personal-data check. 2. Withholding is built in fin's shared reader. You
confirm that the rail's rows and holds: grant express it, and add the sample overlay's personal-data dimension
row when the reader lands. 3. ADR-0066 is reserved and unwritten (fin drafts it now). ADR-0069 is Lane 1's
pattern draft, not yet in the repo. 4. Approve or reject your edited test in #356 today. Then the v0.9.20 pin
move, as a draft until its test count is in."

- **Gov's part:**
  - the rulings-register rows for the verbs (`docs/rulings/README.md`, R-NNN);
  - the operator-column personal-data check against the dimensions rail.
- **Not gov's:** census and capability rows.
- **When fin's shared reader lands:**
  - confirm that the `policy/classification/dimensions.yaml` rows and the `holds:<dimension>:<value>` grants
    express the withholding;
  - add the sample overlay's personal-data dimension row (a `set` row under `policy/overlays/sample/`).
- **Today:**
  - the base ships `dimensions: []`, `boundaries: []` and `dimension_holders: []`;
  - no code reads the file yet.
- The three questions drafted earlier are answered by this; they were not sent.

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

## #356 (saf's export-profile server): gov's test file approved at `6a4175a2`

- **The packet:** `sessions/2026-11-11-packet-to-saf-cc-architect-from-gov-356-can-export-rail-test-edit-approved.md` (master tree, placed). Lane 1 merges #356 by `6a4175a2` once gov, fin and Lane 1 have approved.
- **Follow-up, gov's own PR, after #356 merges and after the cut:** `tests/security/test_can_export_capability_rail.py` reads ambient environment variables.
  - With `INGEST_EXPORT_PROFILE_OVERLAY_DIRS` set, 9 tests fail. With the answer loader's `EXPORT_PROFILE_OVERLAY_DIRS` set, 6 fail; that variable predates #356.
  - test_4, test_5 and test_9 clear nothing.
  - Fixes:
    - clear `_ENV` for every test in the file (an autouse fixture);
    - add `INGEST_EXPORT_PROFILE_OVERLAY_DIRS` to `_ENV`;
    - add a review-overlay arm to test_2 (the variable is ADDED);
    - restore the exact note string.
  - The seal for the fix is the same ambient run going green, with the unfixed file red as its control.
- **mfg-trace:** answered by the architect; see the section above.
