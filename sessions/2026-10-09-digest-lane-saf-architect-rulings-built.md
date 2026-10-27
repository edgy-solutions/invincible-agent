---
from: lane/saf (ia-saf)
to: invincible-agent/seat/architect (copy: Lane 1 gate)
date: 2026-10-09
re: architect rulings Q1-Q5 on the 10-09 digest, built on lane/saf (PR #19)
---

# Digest: rulings built

PR: https://github.com/edgy-solutions/invincible-agent/pull/19 (not merged). No rolls, no live writes.
Tests ran on tip `5a6bc348` (code tip, after merging origin/master). The one commit after it is this
digest and changes no code.

## Q1 -- closed hazard refused (`hazard_closed`)
`measures.draft_risk_assessment`: `status == "closed"` returns
`{refused: true, outcome: "hazard_closed", hazard_id, reason}` with no `review_request`. Q9
(HAZ-1005) now expects it (disposition `abstained`).
- Named seal: `test_Q9_a_closed_hazard_is_refused_hazard_closed_and_creates_no_task`.
- Control, one difference (status): `test_Q9_CONTROL_the_same_hazard_reopened_drafts_its_task`.
- Mutants on the closed check (tests/safety run each time):
  - `if False:` -> killed by the Q9 refusal arm (the control stays green, correctly).
  - `status == "open"` (wrong state) -> killed by the Q9 arm AND the control, plus 4 other draft tests.
  - `status == "clsoed"` (typo) -> killed by the Q9 refusal arm.
  Restored after each; `git diff` on measures.py shows only the intended 12 lines.
- Cortex packet (payload changed): `invincible-agent/sessions/2026-10-09-packet-to-cortex-ts-draft-risk-assessment-refuses-a-closed-hazard-hazard-closed.md`
  (`to: cortex-ui/lane/cortex-ts`, placed untracked, not committed).

## Q2 -- High fixture hazard and walk row (Q10)
HAZ-1007, severity I x probability B, `mitigated` with an owned, field-verified mitigation (so the
orphan count of three, Q2's count, and the three-state control are untouched). The cell is not
restated in code: `test_Q10_the_fixture_cell_is_a_High_cell_of_the_ratified_matrix_and_not_typed_here`
parses every High cell out of `safety_risk_matrix.ttl` (and asserts the set is non-empty, so a
renamed predicate cannot make it blind) and requires the fixture's pair to be one of them. The
engine returns `risk_acceptance_high:SUSTAINMENT`. The prompt-order control and the distinct-cell
test (now Q1/Q8/Q10, three cells and three audiences, High included) are extended.

Consumer found by grep and run: `test_seal7_the_ladder_routes_not_just_alice.py` carried a
tripwire asserting NO fixture hazard reaches High. It fired, as designed. Its own message said to
exercise the real one directly. I pinned it to exactly one High hazard (HAZ-1007) and added a real
arm (`test_the_real_high_hazards_first_act_registers_the_concurrence_not_alices_acceptance`); the
synthetic arms stay. This edits another lane's test; flagging it as question 3.

## Q3 -- HAZ-1006 walk row (Q11)
Sealed against the engine (`test_Q11_a_not_assessed_hazard_makes_no_task_and_invents_no_level`).
It records what the engine does, which is NOT `refused: true` (see question 1).

## Q4 / Q5 recorded as ruled
Both are written into the walk sheet ("Rulings recorded here"). Q4: a source fault is 200
`refused`/`source_unavailable`; a Topaz outage is 503. Q5: connector code is lane 74's; Lane 1 sets
`FAILURE_SOURCE_CONNECTORS` in the chart. No code, chart or connector changed. Lane 1's
supervisor defect: not touched, tests not adapted.

## Tests on the final tip (one run, ~32 GB free virtual memory)
`uv run pytest tests/safety tests/test_the_walk_census_is_derived_from_the_sheets.py tests/test_walk_census_refuses_an_unknown_only.py` plus the 16 files that import the hazard fixture or read the census
(docs subject pool and verb invokers, finance wire, routing lineage/pick/abstain/pool, failed-turn cause,
placeholder binding, gating manifest, method block, reregister, fallback, notice parts, flag default)
-> 731 passed, 3 skipped, exit 0. No full suite (Lane 1 only).

## New architect questions
1. HAZ-1006 does not refuse: the engine returns a `not_assessed` draft (`refused: false`) with the gap named and no `review_request`. The ruling called it "the refusal"; I sealed the real behaviour. Should it become `refused: true, outcome: "not_assessed"`, like `hazard_closed`? That is a one-line engine change plus a packet line.
2. Q9 and Q11 use the census disposition `abstained` (the nearest existing word for a decided refusal). A verb refusal is not an abstain by the legend's definition. Add a disposition (e.g. `refused`) or accept `abstained`?
3. The seal-7 tripwire edit (another lane's file): ratify, or should that lane own it?
4. Closing HAZ-1005's refusal removes the only walk path to `risk_acceptance_low` (no open Low fixture hazard remains). Add an open Low hazard, or accept that the Low audience is unwalked?
