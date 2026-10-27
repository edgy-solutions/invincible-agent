# Handoff: lane/gov, 2026-10-21

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-withholding-arms-name-their-subject, lane/gov-action-route-seal, lane/gov-q14-unconfigured-topaz)
from: invincible-agent/lane/gov, 2026-10-21

This replaces `2026-10-20-handoff-lane-gov-pair-holds-77-78-open-instance-2-after-23rd.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-withholding-arms-name-their-subject` | `b0d9385b` | #82 → lane/01-202 | open; option 1, waiting on Lane 1's merge |
| `lane/gov-action-route-seal` | `01d8605b` | #77 → lane/01-197 | open; the fix needs the architect's OK (Q17) |
| `lane/gov-q14-unconfigured-topaz` | `3e9b25a9` | #78 → lane/01-197 | open; Q14 as ruled |
| `lane/gov-resolve-instance`, `-enumerate-gate`, `-caller-census`, `-narrow-except` | as on 10-15 | #39, #45, #47, #54 | open, as on 10-15 |

The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-21".

## The directive (10-21, from the architect via Chris), and where each part stands

> to: invincible-agent/lane/gov — Lane 1's 739b0c74 (class-chain read) turns two arms in your withholding test red. Decide today: are the arms wrong given the chain read, or is the read wrong? Reply to Lane 1 by packet. And put Q18–Q20 at the top of a packet to the architect.

- **Decided: the arms were wrong (option 1).** The chain read runs after the visibility filter, matches `OntologyClass` nodes only, and never raises.
  - The seal edit is #82, one file.
  - Before: 2 failed, 14 passed. After: 17 passed, file alone at `6a10a62a`.
  - Mutants: five killed, one equivalent.
- **Reply to Lane 1: PLACED.** It is in master's `sessions/`, cc the architect.
- **Packet to the architect, with Q18–Q20 at the top and then Q17: PLACED.** It is in master's `sessions/`.

## Next

1. **Watch #82.** If Lane 1 merges it into a later head, there is nothing more to do. If the architect rules option 2 instead, close #82 and tell Lane 1 to skip the read.
2. **Watch #77 and #78.** If Q17 rejects #77's fix, revert the four lines on a new commit and xfail the three W1 service arms, with the ruling quoted.
3. **When Q18–Q20 are ruled:**
   - a yes on Q18 or Q20 means a seal, plus a fix if needed, in #77's pattern;
   - Q19 decides the `/source` 404-vs-403 body.
4. **Instance 2 (the stage-enum read)** comes after the 23rd. Find it by grepping lane/01-* for `_delegate_principals` reads added since `b3fdad7f`.
5. **Carried, not re-checked:** Q11; the 422 `no_person` after 188b; #54 onto 74's decide(); the AnswerArtifact origin field.

## Placed (untracked in master's `sessions/`)

- `2026-10-21-packet-to-lane-01-option-1-the-arms-were-wrong-the-chain-read-stands-pr-82.md`
- `2026-10-21-packet-to-architect-gov-q18-q20-open-q17-open-withholding-arms-decided-option-1.md`

## Scratch (the session scratchpad; disposable)

- These worktrees can be removed with `git worktree remove`, never `rm`:
  - `wh/` (#82);
  - `seal/` (#77);
  - `q14/` (#78);
  - `adr/` (#76, closed);
  - `rg/`, which holds the venv the runners use.
- The runners: `run_wh.sh` for `wh/` and `run_q14.sh` for `q14/`. Both take `<log> <file>...`.
- The mutant drivers: `mut_wh.py` (N1–N5, plus `restore`), `mut_wh_n2b.py`, `mut_seal.py` and `mut_q14.py`.

## Lessons

- **A count of sessions is a proxy for whatever was the only caller when the arm was written.** When a second caller arrives, assert on the statement, not the connection. Sort statements by what they match, and keep an unclassified bucket so nothing unnamed passes.
- **A double that rejects a real calling form hides the path it rejects.** The double refused Neo4j's kwargs, so the chain read failed inside the double and its never-raise catch hid that. Match the driver's real signature.
- **A surviving mutant can be meeting a second guard.** N2 flipped the prefix test, but `notice_id_of` refuses a non-notice IRI anyway. Record it as equivalent, with the guard named, and derive a mutant (N2b) that gets past both.
