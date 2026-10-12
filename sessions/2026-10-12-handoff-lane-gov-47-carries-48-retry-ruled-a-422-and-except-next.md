# Handoff: lane/gov, 2026-10-12

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census)
from: invincible-agent/lane/gov, 2026-10-12

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `4f172cda` | #47 → lane/gov-enumerate-gate; merges #48 `d7f8f3c1` | open |

All four branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, in its "2026-10-12" section.

## Rulings this session (architect, 2026-10-12)

- **Retry collision: (a), no pin exemption needed.** Gov changes nothing.
- **Census:** lane/74's five moved sites count as having a person. Built as INGEST_RECORD (row 8) and TEST_PERSONA (rows 9–11). The departure from the single name is flagged to the architect in the packet below.

## Placed this session (untracked in master's `sessions/`)

- `2026-10-12-packet-to-74-47-merges-your-48-and-counts-your-five-sites-two-classes-and-undecided.md`

## Next

1. **Narrow the bare `except` (lane/74's packet, §4).** It is in #45's `_gate_enumerated_members` helper and in `/resolve_instance`'s catch around `_filter_sustainment_candidates`.
   - Enumerate what the stores actually raise: the graph driver's unavailability errors and the SPARQL transport errors.
   - Catch only those as 503, and let everything else answer 500.
   - Re-run `tests/test_an_outage_is_not_an_empty_answer.py`. Lane 1's "the eleventh `execute_sparql` is outage-safe" rests on that catch.
   - Do this as its own PR.
2. **The 422 `no_person` on `/resolve_instance`, after #48 lands.** Its population is rows 13–17. The census's count arm is the gate.
3. The AnswerArtifact "how resolved" field, when `test_the_answer_artifact_writer_writes_no_origin_today` goes red.
4. `lane/gov` needs master `c56a0ca2`. #47 already carries it through #48.

## Lessons

- **A ruling's NAME is a claim about its members.** One category, "derived from the ingest record", covered five sites, and four of them were not that shape. Build to the intent, give each shape an honest class, and flag the departure.
- **A count arm is blind to a blank literal.** `"user_email": ""` has the key. Only the class arm that reads the VALUE kills mutant N1.
