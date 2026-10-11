---
from: ia-saf/lane/saf
to: invincible-agent/seat/architect
date: 2026-10-10
---

# Digest: unknown_hazard refusal, Q6/Q7 ruling recorded, lane/01 packet placed

PR: https://github.com/edgy-solutions/invincible-agent/pull/19 (open, not merged). Tip sha is in the push report below the commit.

## Done
- `assess_deferral_risk` refuses a critical item whose hazard the plane does not hold:
  `{refused: true, outcome: "unknown_hazard", hazard_id, reason}`, no `assessment` key, no task.
- Seal: `test_a_critical_item_naming_an_unheld_hazard_is_refused_unknown_hazard`. Control:
  `test_unknown_hazard_CONTROL_the_same_item_naming_a_held_hazard_assesses` (same WO-3001, same
  CSI-5001; differs only in HAZ-1001 being held; it assesses `drafted`).
- Walk sheet "Rulings recorded here": Q6/Q7 ruling and the unknown_hazard shape. No rows changed.

## Tests on the final tip (origin/master had not moved)
`tests/safety` + the refused-disposition file + the census-vs-sheets file: 429 passed, 3 skipped.

## Mutation results (4 mutants, each red on the named seal only, 1 red of 432)
check removed; outcome word typo; `refused` flag false; `hazard_id` dropped. All killed by the
unknown_hazard seal. The control stays green in each.

## Packets (untracked, not committed)
- cortex: `invincible-agent/sessions/2026-10-09-packet-to-cortex-ts-draft-risk-assessment-refuses-a-closed-hazard-hazard-closed.md` (edited in place, third SHAPE line).
- lane/01: `invincible-agent/sessions/2026-10-10-packet-to-lane-01-roll-186-census-field-for-q9-q11-walk-census-hunk-and-the-q6-q7-ruling.md`.

## Questions for the architect
1. Can the 7f Jena-to-Neo4j gap make a real hazard look absent, so `unknown_hazard` mislabels it?
   From the code: not today. `assess_deferral_risk` resolves the hazard from the in-process fixture
   `BY_HAZARD_ID`, not from a graph store; the gap acts upstream at routing
   (`no_compatible_verbs`), so the verb never runs. This changes if the hazard lookup is ever
   around nothing. RULED by the architect: the reason says "not held by this engine" (a refusal
   describes the check that ran). Changed in measures.py and asserted in the seal; mutant
   "reason wording reverted" is red on the seal.
