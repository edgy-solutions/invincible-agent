# Handoff: lane/gov, 2026-10-14

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census)
from: invincible-agent/lane/gov, 2026-10-14

This replaces `2026-10-13-handoff-lane-gov-row-17-moved-47-at-6780e7d9-for-188-except-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED (in rev 187) |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `bb0b5190` | #47 → lane/gov-enumerate-gate; merges #48 `d7f8f3c1` and #52 `5902102b` | ACCEPTED; for the 188 landing |

All four branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-14".

## Rulings (architect)

- **2026-10-12 13:13:** "gov: accepted; row 17 moves with #52 in the 188 landing; blank user_email = absent (done)." Built at `6780e7d9`.
- **2026-10-14:** "a svc: literal counts as absent in every arm, same as blank; a service identity is never a person." Built at `bb0b5190`.
  - 28 passed.
  - S2 and S3 survived the old test; both are red now.

## Placed (untracked in master's `sessions/`)

- `2026-10-14-packet-to-01-47-moved-to-bb0b5190-a-svc-user-email-is-absent-take-it-for-188.md`: it tells Lane 1 to take `bb0b5190` or later for 188.
- Earlier: `2026-10-13-packet-to-01-for-188-…`, plus two 2026-10-12 packets to 74.

## Worktree note

`lane/gov-caller-census` tracks three packets that `lane/gov` leaves untracked. Backups are in the session scratchpad, `untracked-bak/`.
- **Before checking out the census branch:** compare each blob hash with that branch's copy, then remove it.
- **After checking out `lane/gov`:** restore the three from the backup, then cmp.

## Next

1. **Narrow the bare `except` (lane/74's §4).** It is in #45's `_gate_enumerated_members` and in `/resolve_instance`'s catch.
   - Enumerate what the stores raise.
   - Catch only those as 503; everything else answers 500.
   - Re-run `tests/test_an_outage_is_not_an_empty_answer.py`.
   - Do this as its own PR.
2. **The 422 `no_person`, after 188 lands #48 and #52.** Its population is rows 13–16. The refusal should also name `svc:` as no person: the census now does, and the engine side has to agree.
3. The AnswerArtifact "how resolved" field, when its tripwire goes red.

## Lessons

- **A question raised from a mutant is a mutant I owe a "before" for.** R3 led to the question. The ruling's build then showed that S2 and S3, service literals at a TOKEN row and at the in-process row, were invisible to every arm. That was worse than R3, which a class arm had caught.
- **A predicate a ruling widens gets a two-sided control.** It needs cases that must now be absent, and cases that must stay PERSON (`"user-svc:x@b"`, `f"{n}svc:"`, `u or "svc:x"`). A widening that over-reaches would otherwise pass as a stricter guard.
