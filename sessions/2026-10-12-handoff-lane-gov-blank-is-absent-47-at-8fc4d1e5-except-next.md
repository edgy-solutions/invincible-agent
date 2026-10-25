# Handoff: lane/gov, 2026-10-12 (2)

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census)
from: invincible-agent/lane/gov, 2026-10-12

This handoff replaces `2026-10-12-handoff-lane-gov-47-carries-48-retry-ruled-a-422-and-except-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `8fc4d1e5` | #47 → lane/gov-enumerate-gate; merges #48 `d7f8f3c1` | open; description updated |

All four branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, sections "2026-10-12" and "2026-10-12 (2)".

## Rulings (architect, 2026-10-12)

- **Retry collision:** (a), no pin exemption needed. Gov changes nothing.
- **Two categories approved:** INGEST_RECORD (row 8) and TEST_PERSONA (rows 9–11). The words of the ruling: "accurately described beats one name".
- **A blank `user_email` is absent.** Built at `8fc4d1e5`: one predicate, `carries_person`, in every arm. 27 passed. N1b, N6 and N7 are each red on their class row and on the count. N6 survived the old test, and that was measured.

## Placed this session (untracked in master's `sessions/`)

- `2026-10-12-packet-to-74-47-merges-your-48-and-counts-your-five-sites-two-classes-and-undecided.md`
- `2026-10-12-packet-to-74-a-blank-user-email-is-now-absent-in-every-census-arm.md`

## Next

1. **Narrow the bare `except` (lane/74's packet, §4).** It is in #45's `_gate_enumerated_members` helper and in `/resolve_instance`'s catch around `_filter_sustainment_candidates`.
   - Enumerate what the stores actually raise: the graph driver's unavailability errors and the SPARQL transport errors.
   - Catch only those as 503, and let everything else answer 500.
   - Re-run `tests/test_an_outage_is_not_an_empty_answer.py`.
   - Do this as its own PR.
2. **The 422 `no_person` on `/resolve_instance`, after #48 lands.** Its population is rows 13–17. The census's count arm is the gate, and it now treats a blank as absent, so a `""` cannot slip a caller past the 422's population.
3. The AnswerArtifact "how resolved" field, when `test_the_answer_artifact_writer_writes_no_origin_today` goes red.

## Lessons

- **Two arms that each read a different surface do not back each other up.** The count arm read the KEY and the class arm read the VALUE. A blank at a TOKEN row (N6) got past both, because the TOKEN class arm only checked that a name appeared in the function. Decide the predicate once and have every arm call it.
- **Measure the "before" column.** I ran N6 against the old test, and it survived (26 passed). That run is what turns "both arms catch it now" from a claim into a result.
