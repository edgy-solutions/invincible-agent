# Handoff: lane/gov, 2026-10-15

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census, lane/gov-narrow-except, lane/gov-kind-tree-groups)
from: invincible-agent/lane/gov, 2026-10-15

This replaces `2026-10-14-handoff-lane-gov-except-narrowed-pr-54-422-after-188b-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED (in rev 187) |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `bb0b5190` | #47 → lane/gov-enumerate-gate | ACCEPTED; for the 188 landing |
| `lane/gov-narrow-except` | `16aa5450` | #54 → lane/gov-enumerate-gate | APPROVED (2026-10-15) |
| `lane/gov-kind-tree-groups` | `77f5a795` | #56 → **lane/01-rev189** | open; Lane 1's work-instruction row lands behind it |

All six branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-15".

## Rulings (architect)

- **2026-10-14:** "a svc: literal counts as absent in every arm, same as blank; a service identity is never a person." Built at `bb0b5190`.
- **2026-10-14:** "accepted; the engine-side 422 refusing svc: after 188b, as you say."
- **2026-10-15:** "#54 approved. The kind-tree test must count a group grant as a recipient (group → members) — fix the test, Lane 1's work-instruction row lands behind it." Built as #56.

## What #56 is

- **The predicate:** a recipient is a `grant_to` user, or a `users.yaml` member of a `grant_to_groups` group that `groups.yaml` declares. Memberless and undeclared groups reach nobody, as in `validate_policy.unusable_group_audiences`.
- **The arms:**
  - a two-sided control (7 cases);
  - the join with `validate_policy`, over real policy plus a fixture holding one group of each outcome;
  - every `document_promotion` audience reaches someone.
- **Results:** 64 passed; with a stand-in work-instruction row, 74 passed. K1–K3 and V1–V2 are each red on a named arm.

## Placed (untracked in master's `sessions/`)

- `2026-10-15-packet-to-lane-01-kind-tree-seal-counts-group-members-pr-56-your-row-can-land.md`, cc the architect.

## Worktree note

- **`lane/gov-kind-tree-groups` (and anything based on `lane/01-rev189`)** tracks five packets that `lane/gov` leaves untracked. Backups are in the session scratchpad, `untracked-bak2/`.
  - Checking out `lane/gov` removes them; restore them from the backup, then cmp. This was done on 2026-10-15, and all five cmp identical.
- **`lane/gov-caller-census`** has the same dance with three packets, `untracked-bak/`.

## Next

1. **#56 review.** Then Lane 1 commits the row and runs the file again with it in. The stand-in may differ from the real row in its passes and outputs.
2. **Q11 (open): `svc:` group members.** Latent; not built.
3. **The 422 `no_person` on engine O, after 188b lands (RULED 2026-10-14).**
   - Population: rows 13–16.
   - It also refuses `svc:`.
4. **The AnswerArtifact "how resolved" field,** when `test_the_answer_artifact_writer_writes_no_origin_today` goes red.

## Lessons

- **A join arm decided over a population with one outcome cannot see a disagreement.** Real policy has no unusable group, so mutants K2 and K3 left the join green. Give the join a fixture holding every outcome, and assert that both outcomes occur.
- **`Path.read_text()` with no encoding is cp1252 on this box.** A policy file with non-ASCII bytes fails collection, and that crash is not a red.
- **`run_files.sh` exits with its last test, not with pytest's rc.** Read the `rc=` in the log.
