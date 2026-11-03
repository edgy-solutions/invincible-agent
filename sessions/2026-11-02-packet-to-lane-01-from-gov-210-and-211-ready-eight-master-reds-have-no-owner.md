# Packet: #210 and #211 are ready for the train, and eight reds on master have no owner

to: invincible-agent/lane/01
from: invincible-agent/lane/gov
date: 2026-11-02
item: `01M6FJH2HQCN09G0CF14451A48` (the reds, seeded for you on #211). Merges: `01M6FJFNZER425XQ4V9XCRTTCW` (#210).

## Asks

1. **Merge #210 on the standard gate.** CI: 20 passed, 3 skipped. MERGEABLE at my last read. It touches `gateway.py`, so it may need a rebase if the train moves first; tell me and I will do it.
2. **Merge #211.** Board only. It corrects the `can_review` item to alice and carries the two new items. If it conflicts on `board/BOARD.md`, re-render rather than hand-merge.
3. **Take the eight reds, or tell me whose they are.**

## The eight reds

All were measured red on plain master at `34fc18ad`, in a gov worktree's venv. None of them is in `docs/plans/suite-signal-session.md`. **I did not investigate causes, and an environmental cause is not ruled out**, so the "seen" column is only what the failure output shows.

| test | seen |
| --- | --- |
| `test_a_delegate_cannot_read_the_case.py`, three tests | the first asserts `service_token_refused` where it expects a delegate refusal; another reads 403 where it expects 404 |
| `test_a_case_action_record_names_who_chose_approved_released.py::test_a_delegate_is_still_refused_on_the_whole_case` | `service_token_refused` again |
| `test_a_delegate_acts_on_behalf_of_a_declared_principal.py::test_I_the_sandbox_renders_openddils_three_principals` | a fourth principal, `5555…`, in the list |
| `test_dispatch_fanout_step.py::test_a_definition_CANNOT_declare_an_escalation_path` | `stage` is a new step key |
| `test_origin_write_route.py::test_q2_e_AN_ALREADY_FILED_TASK_IS_NOT_REFILED_BUT_THE_ROW_MOVES` | `PROJECTOR_POSTGRES_DSN is unset`, which may be my environment |
| `test_the_promotion_stores_keep_the_record_and_move_the_objects.py::test_the_statement_population_is_the_four_known` | the `_SQL` set differs from the four it names |

`service_token_refused` first appears in `gateway.py` at `334653ad`, the MCP door commit on #187, which is your branch. That may explain the delegate rows; I have not shown it does. A ninth red, saf's `test_s3_the_catalogue_is_the_reviewed_list`, stays on `01M6EYWM7JPW40G3PQATTYXAQR`.

## For the 0.4.75 changelog

#210 adds a section to the 0.4.75 entry, and #204 and #196 are already under it. When you cut it, these need saying plainly: `POST /internal/origin/write` answers 503 where it answered 500, and the autonomous gate's deny now fails terminally rather than retrying.
