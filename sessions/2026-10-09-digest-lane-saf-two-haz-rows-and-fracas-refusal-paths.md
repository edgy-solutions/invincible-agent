---
from: lane/saf (ia-saf)
to: invincible-agent/seat/architect (copy: Lane 1 gate)
date: 2026-10-09
re: 10-09 order -- two more HAZ walk rows, FRACAS refusal paths per connector, cortex packet decision
---

# Digest: lane/saf, 2026-10-09

PRs only, no rolls, no live cluster or Topaz writes. Nothing was walked live.

## Item 1 -- two more HAZ walk-census rows (NOT YET WALKED LIVE)

Picked from `agent_fleet/safety_agent/entities.py`. Level and audience were read from the engine
(which reads `safety_risk_matrix.ttl` and the task grants), not restated.

| row | hazard | cell | level | audience | why |
| --- | --- | --- | --- | --- | --- |
| Q1 (existing) | HAZ-1003 | II x D | Medium | `risk_acceptance_medium:SUSTAINMENT` (bob) | baseline |
| Q8 `safety-haz-1001-risk-assessment` | HAZ-1001 | I x D | **Serious** | `risk_acceptance_serious:SUSTAINMENT` | the cell a walker "corrects" to High; audience flips to the senior authority; no mitigation, so `orphan_reason` is set |
| Q9 `safety-haz-1005-risk-assessment` | HAZ-1005 | IV x E | Low | `risk_acceptance_low:SUSTAINMENT` | the only fixture hazard in Low; CLOSED with a verified mitigation, so the draft-on-closed behaviour is recorded |

Caller is the sheet's: bob, SAFETY_ENGINEER, SUSTAINMENT. Rows are marked "NOT YET WALKED LIVE"
the way Q6/Q7 are. There is no HAZ-1004 census row (HAZ-1004 is the fixture control, not a walk
row), so the Q6/Q7 marking is the precedent. The control list is in step: the sheet now has nine
prompts and `test_the_parser_finds_the_sheets_nine_prompts` lists them in order; the census-vs-sheet
test is green both ways.

New tests (in `tests/safety/test_the_walk_sheet_matches_the_engine.py`):
`test_Q8_and_Q9_captured_level_and_audience_are_what_the_engine_returns` (x2) and
`test_Q1_Q8_Q9_reach_three_DIFFERENT_audiences_and_cells`.

## Item 2 -- FRACAS refusal paths, route level

Before: route-level coverage was mode (b) only; (a) and (c) and multi-connector were `gather`
level. Now, in `tests/safety/test_fracas_source_wiring.py`, one named test per mode, each
parametrized over BOTH verbs and BOTH sandbox connector names (`sor-events-a`, `relyence`), each
with a control that differs only in the fault (same connector healthy -> `failure_count == 1`):

- `test_mode_a_BUILD_a_connector_that_cannot_be_built_is_refused_naming_it`
- `test_mode_a_BUILD_an_unimportable_module_or_missing_callable_is_refused_naming_it`
- `test_mode_b_RAISES_a_connector_that_raises_during_query_is_refused_naming_it`
- `test_mode_c_BAD_RECORD_an_unusable_hit_is_refused_naming_the_connector` (empty required field, missing key, non-mapping)
- `test_multi_connector_one_healthy_one_faulty_refuses_the_WHOLE_answer_naming_the_faulty_one` (3 modes x 2 verbs x faulty first/second; control: both healthy -> 2 records)

The old `test_the_route_refuses_with_source_unavailable_and_the_control_answers` was replaced by
mode (b) (same assertions, wider). Each refusal asserts 200, `refused`, `outcome:
source_unavailable`, `connector`, `fn`, the connector in `reason`, and no `rows`/`failure_count`.

Defect found in my own instrument: the `_Q` double ran `dict(r)` on every row, so the
non-mapping row failed inside the query wrapper and never reached `_missing`. The first mutant of
`_missing`'s non-mapping branch (M6) survived. The control/double was wrong, not the subject; `_Q`
now passes non-mapping rows through, and M6 is killed.

### Mutants (each restored after; tree verified clean of source edits)

| mutant | killed by (named arms) |
| --- | --- |
| M1 build wrapper removed | mode_a (both), multi_connector, bad_entry |
| M2 build fault names wrong connector | mode_a (both), multi_connector |
| M3 query wrapper removed | mode_b, mode_c, multi_connector, one_connector_down |
| M4 query fault names wrong connector | mode_b, mode_c, multi_connector, one_connector_down |
| M5 `_missing` returns [] | mode_c, multi_connector, unusable_hit, missing_KEY |
| M6 non-mapping accepted by `_missing` | mode_c (4 red, only the not-a-mapping ids) |
| M7 missing KEY tolerated | mode_c, missing_KEY |
| M8 empty value tolerated | mode_c, multi_connector, unusable_hit |
| M9 bad-record fault names wrong connector | mode_c, multi_connector |
| M10 raising connector skipped | mode_b, mode_c, multi_connector, one_connector_down |
| M11 bad hit skipped | mode_c, multi_connector, unusable_hit, missing_KEY |
| M12 unbuildable connector skipped | mode_a (both), multi_connector, bad_entry |
| M13 route handler removed | all route arms (36 red) |

Known limit: M10 is also killed by mode_c via the shared chain; the mode_b arm is the one that
names it. Mutants were hand-chosen, 13 of them; not a census of every possible edit.

## Item 3 -- cortex packet: none

No card payload changed and the `source_unavailable` refusal body is byte-identical to yesterday's
(`refused`, `outcome`, `reason`, `connector`, `fn`). Only walk-sheet/census rows and tests changed,
so no new packet; yesterday's stays current.

## Tests and commands

- `uv run pytest tests/safety/test_fracas_source_wiring.py -q -p no:cacheprovider` -> 53 passed
- `uv run pytest tests/safety/test_the_walk_sheet_matches_the_engine.py tests/test_the_walk_census_is_derived_from_the_sheets.py -q -p no:cacheprovider` -> 36 passed
- area: `uv run pytest tests/safety tests/test_the_walk_census_is_derived_from_the_sheets.py tests/test_walk_census_refuses_an_unknown_only.py -q -p no:cacheprovider` -> 411 passed, 3 skipped
- other readers of the census: 7 files (routing, fallback, notice-parts, flag-default, migrated-route) -> 246 passed
- No full suite (Lane 1 only). One suite at a time; free memory about 2.8 GB when run.

## Architect questions

1. Should `draft_risk_assessment` refuse or flag a CLOSED hazard (HAZ-1005 drafts an acceptance task today)? Q9 records the behaviour without endorsing it.
2. The fixture has no hazard in the High cell, so no walk row reaches `risk_acceptance_high`. Add one?
3. HAZ-1006 (not assessed, no task) is refused with no review_request. Does it want a walk row?
4. Carried over: the 200 `refused` vs 503 `authorization_unavailable` split for `source_unavailable` -- confirm that is the intended contract.
5. Carried over: who owns the real `SystemOfRecordQuery` connector classes and the chart value for `FAILURE_SOURCE_CONNECTORS`? The SDK ships none.
