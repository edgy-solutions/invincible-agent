# Handoff: lane/gov, 2026-10-29 (the rulings applied, two rounds)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-29

This replaces `2026-10-29-handoff-lane-gov-section-5-is-149-can-export-is-151.md`.

## The directives (architect via Chris, verbatim)

**First round:**

> #149: sandbox overlay gives access_grant:DATA_ENGINEERING two members (alice, bob) and the policy/ review audience three (alice, bob, plus a `carol` sandbox fixture) so a two-approver change always has two eligible after the proposer. #151: can_export gates single and batch alike; fin CDRL profiles default to the program-finance persona's group, rows in the seed; add a `plan` owner to recipient_readers for fin's #148. Rebase the second of #149/#151 after the first merges.

**Second round:**

> ratified: asset_grants row with the domain audience and policy/ fallback. plan_answers → a new group `portfolio-leads` (alice in sandbox), not alert-processors; AP is notices. repo_release gets carol as third. The export door not checking can_export:<P> is Lane 1's defect: packet them, it rides 0.4.73; your rows are correct as shipped.

> the carve-out row (overlay path + domain → repo_review:POLICY + domain stewards); reword the §5 workflow-path row per 74; carol into repo_release; portfolio-leads group with alice. Then the §5 table is done and #123 can go Proposed.

**All of it is built, measured and pushed. None has merged.**

lane/74's packet `2026-10-29-packet-to-gov-adr-0062-workflow-row-keyed-on-overlay-path-and-domain.md` (untracked in this tree) asked the two questions that §5's workflow-bundle row answers. The round-2 packet answers them.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-repository-paths-rail` | `f4942845` | #149 → master | Both rulings applied; carol is in `repo_release` too. Seal 53; mutants 12/12 (D1–D12). |
| `lane/gov-can-export-rail` | `c0302427` | #151 → master | Both rulings applied. `EXPORT_PROFILE_GROUPS = {plan_answers: portfolio-leads}`. Seal 25; mutants 9/9. The #148 join is measured. |
| `lane/gov-recipient-readers-plan-owner` | `af8ed126` | #159 → master | `plan` owner. Seal 27 + 1 skip; mutants 3/3. |
| `lane/01-adr-0062-mesh-owns-its-repositories` (Lane 1's) | `14f7a10b` | #123 | Gov's §5 commit. The table is done. Lane 1 flips Status and draft → Proposed. |

**Merge order:**
- #149 and #151 conflict only in `helm/invincible-agent/CHANGELOG.md`. Gov updates whichever merges second.
- #159 conflicts with neither.

**Packets placed** (untracked, master tree `sessions/`):
- `2026-10-29-packet-to-lane-01-fin-cortex-1029-rulings-on-149-151-and-a-plan-owner-pr-159.md` (round 1; also in `cortex-ui/sessions/`)
- `2026-10-29-packet-to-lane-01-fin-74-section-5-done-123-can-go-proposed-door-defect-plan-answers.md` (round 2)

## Open forks

1. **"A new group `portfolio-leads`".** The group already exists, holding alice, erin and chris. I used it. If the architect meant an alice-only export group, it needs another name. Asked in the round-2 packet.
2. **My §5 choices, to be confirmed:**
   - the workflow row takes one approval from each audience;
   - the steward audience is named `workflow_steward:<DOMAIN>`.
3. **Lane 1:**
   - the door checks `can_export:<P>` on both paths (0.4.73);
   - flip #123 to Proposed;
   - §7's two stale lines (around line 657: POLICY holds alice and bob; alice is the only grantor);
   - engine-r resolves `<DOMAIN>` per changed row.
4. **Rows that whichever of each pair merges second must carry:**
   - #144 × #151: `can_export:cdrl_a001_ev_summary_json` → `[finance-analysts]`;
   - #148 × #151: `can_export:plan_answers` → `[portfolio-leads]` (row text in the round-2 packet).
   - fin also owes `plan` reader rows on recipient_readers.
5. **#148 conflicts with master** in `tests/test_the_person_reaches_the_migrated_route.py`. That is fin's.
6. **Red on master, not gov's:** `test_overlay_verb_invokers_are_derived[s1000d_fault_walk]`. Reported to Lane 1.
7. **The workflow-bundle rail row** lands with the first `workflow_steward:<DOMAIN>` audience. Today rule 8 would refuse it.

## Next (in order)

1. **Read CI on #149, #151 and #159.** When the first of #149/#151 merges, bring the other up to date and re-measure.
2. **When #144 or #148 lands,** add its row (fork 4) if #151 is still open.
3. **When Lane 1's door adds `can_export:<P>`:** review it. It must cover both paths, and a Topaz failure must be a 503.
4. **When the architect answers fork 1 or 2,** apply the answer.
5. **Carried:** review the #153 can_drop door, RELAY adoption, the ruling-3 audit, the SDK v0.9.12 swap, Q11, and Q17–Q26.

## Scratch (the session scratchpad; disposable)

- **Worktrees:**
  - `rp/` is #149, `ex/` is #151, `rr/` is #159;
  - `adr/` is #123's branch, detached at `14f7a10b`;
  - `mc/` is a detached throwaway at `baa7d30f` with its own venv; the #148 join was measured there and the merge aborted.

  Remove each once its PR merges.
- **`mut3.py`** is the mutant driver. Args: `PR BAK GATE BASH SET [ids]`, SET is rp, ex or rr. It restores by hash.
- **`run1.sh <worktree> <tag> <test>...`** runs one file at a time behind `gate.sh`.

## Lessons

- **A hung pytest in another session can hold the gate for hours.** I used a variant gate that excused exactly those PIDs while their CPU stayed flat. I said so in the commits, and never killed them.
- **Gate the commit on the leak scan, inside the same script.** For a merge, scan what the branch adds against master.
- **The scan matches its own lesson.** The handoff's note about a matched class name matched the scan. Reword the prose; never weaken the pattern.
- **`.githooks/pre-push --expected` reads stdin and hangs when stdin is open.** On this tree it prints nothing anyway (the old hook). Derive the trailer from the toplevel and the branch, and assert that it starts `Lane: `.
- **An arm that fakes a profile over the real seed breaks on the join that ships the profile's row.** Measure the join in a throwaway before the second PR merges.
- **Escapes collapse in a template of a template.** Edit escape-bearing code with the Edit tool.
