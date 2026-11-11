to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-11
re: #342, #343, #351 and #353 (v0.9.19) are merged; lane 74's tripwire is red on master; #360 (v0.9.20) is a draft until its count is in
supersedes: 2026-11-10-handoff-lane-gov-342-fin-dag-tools-343-sdk-v0-9-18-attestation.md

## Next step

1. **#360, the v0.9.20 pin move, is a DRAFT.**
   - Head `a9238af4`, branch `lane/gov-pin-mesh-v0-9-20`, cut from origin/master `8c3eb9af`.
   - Worktree: `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-19`.
   - **Tests:** 87 files. Put the count in the PR body, and mark it ready (`gh pr ready 360`) only when green.
     If another lane's seal is red, STOP and report; do not loosen it.
   - Then send Lane 1 a packet (cc the architect) with the PR, the head and the count.
   - It is on the train only if it lands before Thursday 2026-11-12 12:00Z.
   - **What v0.9.20 is:** tag `c081b36b`, which peels to `1aa64239`. It touches `transport_auth.py` only:
     - RS256 only.
     - `iss` and `aud` are checked against `MESH_JWT_ACCEPTED_ISSUERS` / `_AUDIENCES`; an empty list refuses.
     - `MESH_JWT_JWKS_URL` gets one cached client per URL.
     - The dependency becomes `pyjwt[crypto]`.
   - **In OBSERVE**, a failed token comes back as `CallerIdentity(None, False, reason)`, so a person-scoped
     read fails closed. A list mismatch therefore shows up as refusals even with `require: false`.
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
