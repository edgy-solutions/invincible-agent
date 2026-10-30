# Handoff: lane/gov, 2026-10-30 (the 10-30 ruling applied; #149, #151 and #159 merge-ready)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-30

This replaces `2026-10-29-handoff-lane-gov-rulings-applied-149-151-159.md`. That file's directives are
all done; its open forks 1 and 2 are now ruled.

## The directive (architect via Chris, verbatim)

> to: invincible-agent/lane/gov (cc fin) — (b): can_export is required for answer-export profiles.
> #151 reads policy/exports/answers/ too, re-keyed to `plan-answers`, group `portfolio-leads` as it
> exists (alice, erin, chris is fine). #159 adds alice as a reader of plan:notional-plan-office.
> §5 choices confirmed: one approval from each audience; `workflow_steward:<DOMAIN>`. Then
> #149/#151/#159 are merge-ready.

**All of it is built, measured and pushed. None has merged.**

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-repository-paths-rail` | `f4942845` | #149 → master | Unchanged. Seal 53; mutants 12/12. |
| `lane/gov-can-export-rail` | `57d23439` | #151 → master | Three kinds: review_export (`INGEST_EXPORT_PROFILE_DIR` or `policy/exports`), answer_export (`EXPORT_PROFILE_POLICY_DIR` or `policy/exports/answers`, plus `EXPORT_PROFILE_OVERLAY_DIRS`), and fin_cdrl. `EXPORT_PROFILE_GROUPS = {plan-answers: portfolio-leads}`; answer-export has no kind default. Seal 28 + 1 skip; mutants X1–X15, 15/15. **No `can_export:plan-answers` row.** |
| `lane/gov-recipient-readers-plan-owner` | `ee1c4460` | #159 → master | `plan: notional-plan-office → [alice]`. Seal 28 + 2 skip; mutants P1–P5, 5/5. |
| #123 (Lane 1's) | `14f7a10b` | #123 | §5 already states both confirmed choices as decided. No edit made. |

**Merge-tree onto master `77fb1d73`:**
- each of #149, #151, #159, #148 and #144 merges clean;
- #149 × #151 conflict only in `helm/invincible-agent/CHANGELOG.md`.

**CI on #151 and #159 at the new heads** was still pending at handoff (3 and 2 pass, 17 and 18 pending). Read it first.

**The join**, measured on a throwaway merge of #151 `57d23439` + #148 `c27a6dbf` + #159 `ee1c4460`:
- without the row: red, and the refusal names `[portfolio-leads]`;
- with the row: green (29, 7 and 30 passed, CLI OK), and the join arms run;
- J1–J4 are 4/4 named-red.

**Red that is fin's:** #148's `test_the_shipped_rail_has_no_plan_owner_and_the_feature_is_dark` (any `plan` owner reds it). #148's answers README is stale on the same point. Packeted to fin; not touched.

**Packet placed** (untracked, master tree `sessions/`):
`2026-10-30-packet-to-fin-and-lane-01-from-gov-149-151-159-merge-ready-the-plan-answers-row-rides-the-second.md`
It carries the row text verbatim.

## Open forks

1. **Which of #148 and #151 merges first.** The row rides the second.
   - Gov recommends #148 first; that matches fin's README ("fin adds no row"). Gov then rebases #151 and appends the row.
   - If #151 merges first, #148 must carry the row.
   - The row text is in the packet, and in the session scratch as `plan_answers_row.yaml`.
2. **#144 × #151:** `can_export:cdrl_a001_ev_summary_json` → `[finance-analysts]`, from the second to merge.
3. **The #149 × #151 CHANGELOG conflict.** Gov resolves it on whichever merges second.
4. **Carried for Lane 1:**
   - the review export's door check of `can_export:<P>` (#163);
   - flip #123 to Proposed;
   - §7's stale lines;
   - engine-r resolving `<DOMAIN>` per changed row.
5. **The workflow-bundle rail row** lands with the first `workflow_steward:<DOMAIN>` audience. Its name is now confirmed.
6. **Red on master, not gov's:** `test_overlay_verb_invokers_are_derived[s1000d_fault_walk]` (reported 10-29; not re-checked).

## Next (in order)

1. **Read CI on #149, #151 and #159.**
2. **On the first merge among #148, #149 and #151:**
   - bring the others up to date;
   - when #148 lands before #151, rebase #151 and append the row under `capabilities:`;
   - update the `capability_grants.yaml` header convention to name answer-export (ruled 10-30, no default, `plan-answers` → portfolio-leads);
   - re-run can_export, validate_policy, the CLI and recipient_readers one file at a time;
   - re-run X1–X15.
3. **When #144 lands before #151,** add its row.
4. **When the doors land** (fin's #148 at `c27a6dbf`, lane/01's #163): review them. Each must cover both paths and treat a Topaz failure as 503 (a 404 is a deny).
5. **Carried:** RELAY adoption, the ruling-3 audit, the SDK v0.9.12 swap, Q11, and Q17–Q26.

## Scratch (the session scratchpad; disposable)

- **Worktrees:**
  - `rp/` is #149, `ex/` is #151, `rr/` is #159;
  - `adr/` is #123, detached at `14f7a10b`;
  - `mc/` is a detached throwaway back at clean `baa7d30f`, with its own venv.

  Remove each once its PR merges.
- **`mut3.py`:** sets rp, ex, rr, jx and jr. jx and jr are the J1–J4 join mutants; they need the join tree in mc. It restores by hash.
- **`run1.sh <worktree> <tag> <test>...`** runs one file at a time behind `gate.sh`.
- **`plan_answers_row.yaml`** holds the row to append.

## Lessons

- **In a PR worktree, the hook derives the trailer from the lane, not from the scratch directory's name.**
  - `bash .githooks/pre-push --expected </dev/null` prints `Lane: ia-gov/<branch>` on these branches.
  - The basename of `--show-toplevel` would have given `ex/...` and been refused.
  - Close stdin, or it hangs. In ia-gov itself the old hook still prints nothing.
- **`gh pr edit --body-file` failed with a GraphQL error** on both PRs. Use `gh api -X PATCH repos/{owner}/{repo}/pulls/N -F body=@<file>` (Windows path via `cygpath -m`).
- **Re-read the master tree's `sessions/` right before writing a packet.** Fin's second 10-30 packet arrived mid-session and changed what the packet had to say.
- **A row that names a profile can only ship on a tree that has the profile.** Say which PR carries it in BOTH orders; a single "second carries it" hides that the first one must carry nothing.
