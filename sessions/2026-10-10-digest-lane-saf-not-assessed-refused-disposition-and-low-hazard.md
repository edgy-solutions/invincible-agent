---
from: lane/saf (ia-saf)
to: invincible-agent/seat/architect (copy: Lane 1 gate)
date: 2026-10-10
re: the three rulings on the 10-09 digest questions, built on lane/saf (PR #19)
---

# Digest: not_assessed refusal, the `refused` disposition, the open Low hazard

PR: https://github.com/edgy-solutions/invincible-agent/pull/19 (not merged). No rolls, no live writes.
Code tip `623567fc`; origin/master had not moved (0 commits behind), so no merge was needed.
This digest is the one commit after it and changes no code.

## 1. HAZ-1006 refuses
`draft_risk_assessment` on a hazard with no severity or no probability returns
`{refused: true, outcome: "not_assessed", hazard_id, gap, reason}`: no `review_request`, no
`risk_level`, no `acceptance_audience`, no `assessment` key, no task. The verb description in
`safety_agent/main.py` says "refused" now. Q11 expects the refusal.
- Named seal: `test_Q11_a_not_assessed_hazard_is_refused_not_assessed_and_creates_no_task`
  (and `test_an_unassessed_hazard_states_the_gap_and_invents_nothing`, seal 11's other half,
  updated from the old draft shape to the refusal).
- Control, differs only in assessment state: `test_Q11_CONTROL_the_same_hazard_assessed_drafts_its_task`.
- Extra arm: `test_Q11_a_half_assessed_hazard_is_refused_and_names_the_missing_half`.
- Packet line added to the (untracked) cortex packet.

## 2. The `refused` disposition
Legend entry plus `REFUSED = "refused"` in `DISPOSITIONS`; the classifier gets an arm. Q9 and Q11
now accept `[refused]`.
Consumers of the disposition set, found and widened:
1. `src/iagent_pure/walk_census.py`: `DISPOSITIONS` (the loader rejects an unknown word:
   `_row` -> "unknown disposition"), and `judge` (WIDENED: a new arm `_named_refusal`, placed
   below every existing arm and above `drawn`, so it only takes answers that used to score
   `drawn` or `none`; without it a row accepting `refused` loads and never matches).
2. `docs/measurements/walk-census.yaml`: the legend.
3. Tests that quantify over the set and widen by themselves (read, ran, no edit needed):
   `test_a_row_accepting_every_disposition_is_refused`, `test_the_catch_all_guard_still_refuses_the_whole_vocabulary`,
   `test_no_row_leans_on_the_slack_the_widening_created` (its bound is `len(DISPOSITIONS) - 1`),
   `test_FALLBACK_is_a_member_of_the_census_vocabulary`.
4. Not consumers: `scripts/walk_census.py` (no disposition words; it calls the library),
   `presentation_agent` `_DISPOSITIONS` and the graph_host dispositions (different vocabularies).
5. cortex-ui: nothing reads the census (only dated session packets mention the words).
New file `tests/test_the_refused_disposition_is_read_not_assumed.py` (8 arms, including controls:
the same answer without `refused: true` is `drawn`; a refusal with no outcome word is not named;
a `slot_required` refusal stays `slot_required`; an abstain keeps `abstained`).
NOT MEASURED ON THE LIVE WIRE: the classifier reads a refusal from `final` or `events`; where the
gateway puts a verb refusal on a real turn is unobserved (Q9/Q11 wait on a roll).
Existing `abstained` rows: exactly two ever used it, and both were these (Q9, Q11). None other
was a refusal. The docs row `docs-how-do-i-roll-a-service-abstains` accepts `slot_required`/`drawn`,
not `abstained`, and is untouched.

## 3. HAZ-1008, the open Low hazard
Severity IV x probability E, `open`, owned and field-verified mitigation MIT-2108 (so no orphan:
the count stays three). Walk row Q12, census row `safety-haz-1008-risk-assessment`
(`task_requested`, audience `risk_acceptance_low:SUSTAINMENT`).
- Cell derived, not typed: `test_Q10_and_Q12_the_fixture_cell_is_a_cell_of_the_ratified_matrix_and_not_typed_here`
  (High for HAZ-1007, Low for HAZ-1008; asserts the cell set is non-empty).
- `test_every_risk_level_the_matrix_defines_has_a_walk_row`: levels read from the ttl
  (High, Serious, Medium, Low; asserts a floor of four so a blind parse cannot pass), hazards
  read from the sheet's own prompts, each drafted through the engine. A level with no row is named
  in the failure. Today none is missing: High Q10, Serious Q8, Medium Q1, Low Q12.
- Prompt-control (now twelve prompts) and the distinct-cell test (now four cells and four
  audiences) extended.
- Consumer grep re-run on the fixture (hazard counts moved again) and the consumers run; the
  seal-7 tripwire needs no change (HAZ-1008 is Low).
- The seal-7 test is this lane's own file, per the coordinator: nothing to ratify.

## Mutation results (tests/safety + the refused file + the census-sheet test run for each)
Named reds below are the killing arms; every mutant was restored and `git diff` was checked.
- not_assessed check removed (`if False`): 3 red (Q11 refusal, seal-11 unassessed arm, half-assessed arm).
- `or` -> `and`: 1 red (half-assessed arm). Keys on severity only: 1 red (half-assessed arm).
  These two are the reason that arm exists: the main arm alone does not catch them.
- outcome word typo (`not_asessed`): 3 red.
- classifier `refused` arm removed: 2 red. `REFUSED` dropped from `DISPOSITIONS`: 2 red plus
  10 errors (the census no longer loads).
- classifier accepts an unnamed refusal: 1 red (the no-outcome control).
- HAZ-1008 probability E -> B (Medium cell): 4 red including the level-coverage arm.
- HAZ-1008 closed: 4 red including the level-coverage arm.
- HAZ-1008 loses its mitigation owner: 1 red (the not-an-orphan half of the cell test).

## Tests on the final tip `623567fc`
`uv run pytest tests/safety`, the census-sheet and unknown-only tests, the new refused file, and the
16 fixture-consumer files (docs subject pool and verb invokers, finance wire, five routing files,
failed-turn cause, placeholder binding, gating manifest, method block, reregister, fallback,
notice parts, flag default): 744 passed, 3 skipped, exit 0, tree clean afterwards. About 34 GB free
virtual memory at the start. No full suite (Lane 1 only).

## Packet (untracked, not committed)
`C:\Users\cnogr\git\invincible-agent\sessions\2026-10-09-packet-to-cortex-ts-draft-risk-assessment-refuses-a-closed-hazard-hazard-closed.md`
(`to: cortex-ui/lane/cortex-ts`), edited in place: now covers both refusals and HAZ-1008 as data.

## New architect questions
1. `assess_deferral_risk` still returns a non-refusal body with `assessment: "not_assessed"` when
   a critical item names a hazard the plane does not hold. It is a different verb and I left it.
   Should the same "nobody can act on what nobody has assessed" rule make it a named refusal?
2. Q4/Q5-style source faults are `source_unavailable`, and the census now has `refused` for any
   named refusal. Should the existing walk rows that expect a `slot_required` ask but could meet
   a `source_unavailable` refusal (Q6, Q7 when the connector is set) accept `refused` too? I added
   nothing; it is only reachable once Lane 1 sets `FAILURE_SOURCE_CONNECTORS`.
3. Where the gateway carries a verb refusal on a real turn is unobserved. The `refused` arm
   searches `final` then `events`. Ask Lane 1 to include Q9/Q11 in the next roll's census and
   report the disposition, or tell me the field to read.
