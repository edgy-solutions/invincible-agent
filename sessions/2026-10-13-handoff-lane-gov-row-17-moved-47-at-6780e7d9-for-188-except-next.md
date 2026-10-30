# Handoff: lane/gov, 2026-10-13

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census)
from: invincible-agent/lane/gov, 2026-10-13

This replaces `2026-10-12-handoff-lane-gov-blank-is-absent-47-at-8fc4d1e5-except-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED (in rev 187) |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `6780e7d9` | #47 → lane/gov-enumerate-gate; merges #48 `d7f8f3c1` and #52 `5902102b` | ACCEPTED; for the 188 landing |

All four branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-13".

## Rulings (architect, 2026-10-12 13:13)

"gov: accepted; row 17 moves with #52 in the 188 landing; blank user_email = absent (done)."

- **Built:** row 17 is TEST_PERSONA, and NO_PERSON is 4 (rows 13–16). The census passes 27. R1–R3 are red on row 17.
- **Lane 1 lands 188.** The packet tells them to take #47 at `6780e7d9` or later. An older tip together with #52 reds row 17.

## Placed (untracked in master's `sessions/`)

- `2026-10-13-packet-to-01-for-188-take-47-at-6780e7d9-it-carries-52-and-moves-row-17.md`
- Earlier: two 2026-10-12 packets to 74.

## Worktree note

`lane/gov-caller-census` now tracks three packets that are untracked on `lane/gov`. Checking out `lane/gov` deletes them from disk.
- Backups are in the session scratchpad, `untracked-bak/`.
- After each switch, restore them, then cmp.

## Next

1. **Narrow the bare `except` (lane/74's §4).** It is in #45's `_gate_enumerated_members` and in `/resolve_instance`'s catch.
   - Enumerate what the stores raise.
   - Catch only those as 503; everything else answers 500.
   - Re-run `tests/test_an_outage_is_not_an_empty_answer.py`.
   - Do this as its own PR.
2. **The 422 `no_person`, after 188 lands #48 and #52.** Its population is rows 13–16.
3. **An open question, not raised as a defect:**
   - The count arm counts any non-blank literal as a person, `"svc:..."` included (R3).
   - Today only the per-row class arms stop a service literal.
   - Should `carries_person` treat a `svc:` literal as absent, the way it now treats a blank? That is the architect's call. Ask; don't build it unasked.
4. The AnswerArtifact "how resolved" field, when its tripwire goes red.

## Lessons

- **A merge that carries a PR also carries that PR's base.** #52 brought in 29 master commits. Run the census on the merged tree BEFORE moving the row. A green POPULATION is what shows the extra commits added no site.
- **An untracked file that a merge brings in blocks the merge.** Compare blob hashes. If they are identical, back the file up, move it aside, merge, and cmp. A branch switch deletes it again.
