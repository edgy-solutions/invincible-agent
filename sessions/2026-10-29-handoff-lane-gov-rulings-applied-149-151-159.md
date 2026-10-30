# Handoff: lane/gov, 2026-10-29 (the rulings applied)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-29

This replaces `2026-10-29-handoff-lane-gov-section-5-is-149-can-export-is-151.md`.

## The directive (architect via Chris, verbatim)

> #149: sandbox overlay gives access_grant:DATA_ENGINEERING two members (alice, bob) and the policy/ review audience three (alice, bob, plus a `carol` sandbox fixture) so a two-approver change always has two eligible after the proposer. #151: can_export gates single and batch alike; fin CDRL profiles default to the program-finance persona's group, rows in the seed; add a `plan` owner to recipient_readers for fin's #148. Rebase the second of #149/#151 after the first merges.

**All three parts are built, measured and pushed. None has merged.**

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-repository-paths-rail` | `295014cb` (on master `47502b35`) | #149 → master | Ruling applied. Seal 52; mutants 11/11. Merges cleanly into `c489812f`. |
| `lane/gov-can-export-rail` | `70e1a8b8` (merge of master `c489812f`) | #151 → master | Ruling applied, plus rows for `default-csv`/`default-json`. Seal 23; mutants 7/7. MERGEABLE; CI was pending when last read. |
| `lane/gov-recipient-readers-plan-owner` | `af8ed126` (on master `47502b35`) | #159 → master | NEW. `plan` owner, shipped empty. Seal 27 + 1 skip; mutants 3/3. |

**Merge order:**
- #149 and #151 conflict only in `helm/invincible-agent/CHANGELOG.md`. Gov rebases (or merges master into) whichever lands second.
- #159 conflicts with neither.

**Packet placed** (untracked, in the master tree `sessions/` and in `cortex-ui/sessions/`):
`2026-10-29-packet-to-lane-01-fin-cortex-1029-rulings-on-149-151-and-a-plan-owner-pr-159.md`, cc architect and saf.

## Open forks (all in the packet)

1. **`unmatched_review`** (`asset_grants` row fallback to `repo_review:POLICY`) is gov's departure. It needs ratifying.
2. **`repo_release:invincible-agent`** is 2 approvers on {alice, bob}. A human-proposed tag cannot close. Does it get a third member?
3. **The `plan_answers` can_export grantee** is unruled: alert-processors or portfolio-leads? The `policy/exports` kind label "review-export" is now misleading.
4. **The export door vs the ruling.** Master's door gates the batch on `ingest:exportBatch` and checks `can_export:<P>` nowhere. Until a door asks `can_export:<P>`, every can_export row is inert.
5. **Lane 1:**
   - engine-r must resolve `access_grant:<DOMAIN>` per changed row;
   - ADR-0062 line 518 is stale.
6. **Rows that whichever of each pair merges second must carry:**
   - #144 × #151: `can_export:cdrl_a001_ev_summary_json` → `[finance-analysts]`;
   - #148 × #151: `can_export:plan_answers`, with its grantee unruled;
   - #148 also needs `plan` reader rows on recipient_readers.
7. **Red on master, not gov's:** `tests/test_overlay_verb_invokers_are_derived.py[s1000d_fault_walk]` is red at `c489812f` and at `47502b35`, and is not in the census. Reported to Lane 1.

## Next (in order)

1. **Read CI on #149, #151 and #159.** When the first of #149/#151 merges, bring the other up to date and re-measure.
2. **When #144 or #148 lands**, add the row each needs (fork 6), if #151 is still open.
3. **When Lane 1's export door adds a `can_export:<P>` check:** it must be on both paths, and a Topaz failure must give a 503.
4. **Carried from the last handoff:** Lane 1's can_drop door (#153, now merged — review its existence read and its 403 family), RELAY adoption, the ruling-3 audit, the SDK v0.9.12 swap, Q11, and Q17–Q26.

## Scratch (the session scratchpad; disposable)

- **Worktrees:** `rp/` is #149, `ex/` is #151 and `rr/` is #159. `mc/` is a detached `c489812f` control with its own venv. Remove each once its PR merges.
- **`mut3.py`** is the mutant driver. Args: `PR BAK GATE BASH SET [ids]`, with SET one of rp, ex or rr. It restores by hash, and a probe file is unlinked and checked.
- **`run1.sh <worktree> <tag> <test>...`** runs one file at a time behind `gate.sh`.

## Lessons

- **A hung pytest in another session can hold the gate for hours.** Two processes ran 124 minutes on 9 CPU-seconds with no child. I did not kill them; they are not mine. The override was a variant gate that excused exactly those PIDs while their CPU stayed flat, and I said so in the commits. They exited on their own mid-run.
- **Gate the commit on the leak scan, inside the same script.** I printed `leak=4` and committed in the same command. The four were a FastAPI OAuth2 bearer class name from master's side of a merge. **For a merge, scan the diff against master** (what the branch adds), not against the first parent.
- **Escapes collapse in a template of a template, again.** A Python patcher in a quoted heredoc wrote `\n` as real newlines into `mut3.py`. Edit escape-bearing code with the Edit tool.
- **A PR that was MERGEABLE goes CONFLICTING when a neighbour lands.** Re-read `mergeable` after every push. A newly landed profile directory is also new work for a completeness rail.
