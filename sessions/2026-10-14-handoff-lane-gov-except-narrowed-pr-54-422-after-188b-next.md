# Handoff: lane/gov, 2026-10-14 (2)

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census, lane/gov-narrow-except)
from: invincible-agent/lane/gov, 2026-10-14

This replaces `2026-10-14-handoff-lane-gov-svc-is-absent-47-at-bb0b5190-for-188-except-next.md`.
At `929b3921` this file was committed by mistake as a verbatim copy of that handoff. This content supersedes it.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED (in rev 187) |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `bb0b5190` | #47 → lane/gov-enumerate-gate; merges #48 `d7f8f3c1` and #52 `5902102b` | ACCEPTED; for the 188 landing |
| `lane/gov-narrow-except` | `16aa5450` | #54 → lane/gov-enumerate-gate | open; awaiting review |

All five branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-14 (2)".

## Rulings (architect)

- **2026-10-14:** "a svc: literal counts as absent in every arm, same as blank; a service identity is never a person." Built at `bb0b5190`.
- **2026-10-14, later:** "accepted; the engine-side 422 refusing svc: after 188b, as you say." Note that this says **188b**, not 188.
- **#54 has no ruling yet.** It builds lane/74's §4 ask, which needed none.

## What #54 is

- **The catch:** `/resolve_instance` and `_gate_enumerated_members` catch `_VISIBILITY_OUTAGE`:
  - `SubstrateUnavailable`;
  - neo4j `ServiceUnavailable`, `SessionExpired` and `TransientError`;
  - `httpx.HTTPError`.
- **That answers 503; anything else answers 500.** `ValueError` is excluded on purpose.
- **The filter's "not connected" raises `SubstrateUnavailable`.**
- **The 502 catch is narrowed to `SubstrateUnavailable`.**
- **The seal** is `tests/security/test_the_visibility_check_answers_503_only_for_an_outage.py`: 31 passed. Mutants M1–M5 are red, and the before column is measured.

## Placed (untracked in master's `sessions/`)

- `2026-10-14-packet-to-74-section-4-built-pr-54-the-visibility-catch-is-the-stores-outage-classes-only.md`, cc the architect and 01.
- Earlier: `2026-10-14-packet-to-01-47-moved-to-bb0b5190-…`, `2026-10-13-packet-to-01-for-188-…`, and two 2026-10-12 packets to 74.

## Worktree note

`lane/gov-caller-census` tracks three packets that `lane/gov` leaves untracked. Backups are in the session scratchpad, `untracked-bak/`.
- **Before checking out the census branch:** compare each blob hash with that branch's copy, then remove it.
- **After checking out `lane/gov`:** restore the three from the backup, then cmp.
- `lane/gov-narrow-except` and `lane/gov-enumerate-gate` don't track them, so a switch between those branches and `lane/gov` needs no dance.

## Next

1. **#54 review.** If lane/74 has doubles against these two routes that raise `RuntimeError` for an outage, they now get a 500. Gov did not search lane/74's files.
2. **The 422 `no_person` on engine O, after 188b lands (RULED 2026-10-14).**
   - Population: rows 13–16.
   - It also refuses a `svc:` caller, so the engine side agrees with the census.
3. **The AnswerArtifact "how resolved" field,** when `test_the_answer_artifact_writer_writes_no_origin_today` goes red.

## Lessons

- **When a catch is narrowed, a double that raised a stand-in class stops testing the outage.** Measure the old doubles against the new code. Here, three arms went red, which shows the doubles had to change, not just that they could.
- **A before column against code that lacks the new names crashes; it does not go red.** Separate the arms that red on an assertion (here: the defect arms and the AST arm) from the arms that crash on a missing attribute. Only the first group is evidence of the change.
- **A file seeded with `cp` and then written must be Read first, or the Write fails.** Here the failure went unseen and the copy was committed and pushed (`929b3921`). After any Write, check the content before you `git add`.
