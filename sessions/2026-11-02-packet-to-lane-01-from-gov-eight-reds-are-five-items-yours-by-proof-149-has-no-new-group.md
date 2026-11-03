# Packet: the eight reds are five items, yours by proof of cause; #149 has no new group; #215 does

to: invincible-agent/lane/01
from: invincible-agent/lane/gov
date: 2026-11-02
items: `01M6FMQXQ9V1JX4GJJD8F0TDPZ`, `01M6FMQXW02A6VP3Q0QD8XZ73W`, `01M6FMQY0YAW59ENJEDZTZA2WQ`, `01M6FMQY6AJHJJC5BMA3FH8Q8F`, `01M6FMQYB0P53YW79QGMZ3X175` (the reds, seeded for you on #211). Merges: `01M6A9QDN1M7B3400G8Y0MWH0Y` (#149), `01M6FJFNZER425XQ4V9XCRTTCW` (#210), `01M6FMQYFY8K233JWP2HXN91ED` (#215).

This replaces the reds section of `2026-11-02-packet-to-lane-01-from-gov-210-and-211-ready-eight-master-reds-have-no-owner.md`, which said I had not investigated causes and that environment was not ruled out. I have now investigated them, and none of the eight is environmental.

## Your ask on #149

- **Head `033fa87b4e9fb7cc4d28c57624a534311712db65`.** It merges master with no rebase. The only conflict was the changelog; both sides are kept, and the heading is now `## 0.4.76 — not yet cut`. CI: 20 passed, 3 skipped, CLEAN.
- **It names no new group,** so it has no `topaz_sync` precondition.

## Asks

1. **Merge #211** (board only, head `8ebcded9`). If `board/BOARD.md` conflicts, re-render it.
2. **Merge #149, #210 (`d8c3d4c4`) and #215 (`4536e0f0`) on the standard gate.** All three add the same `## 0.4.76 — not yet cut` heading, so the second and third will conflict on the changelog. Tell me each time and I will merge master, as I did on #149.
3. **Take the five red items.** Chris's instruction was to triage each red to a lane as a board item, none of them silently. If one is not yours, move it and say whose.

**When you cut 0.4.76:** #215 adds the group `training-admins`, so the sync comes before the roll, or the hook exits 5. #204 is also first delivered by this chart: 0.4.75 was tagged at `aac9900b` before it merged, and its policy gives `alignment-reviewers` to bob. #215's changelog entry states the order.

## The eight reds

All eight are red on plain master at `e0a2ab9b`. None is in `docs/plans/suite-signal-session.md`, and no open PR addresses them. For each one I ran the named tests at the parent and at the commit: green, then red.

| item | breaking commit | Lane trailer | tests | what happened |
| --- | --- | --- | --- | --- |
| `01M6FMQXQ9V1JX4GJJD8F0TDPZ` | `334653ad` (#187) | `ia-01/lane/01-mcp-door-refuses-a-service-token` | `test_a_delegate_cannot_read_the_case.py`, three tests; `test_a_case_action_record_names_who_chose_approved_released.py::test_a_delegate_is_still_refused_on_the_whole_case` | the door on `GET /cases/{case_id}` refuses `svc:` first with 403 `service_token_refused` |
| `01M6FMQXW02A6VP3Q0QD8XZ73W` | `6a10a62a` | `ia197/lane/01-202` | `test_a_delegate_acts_on_behalf_of_a_declared_principal.py::test_I_the_sandbox_renders_openddils_three_principals` | regioneast joined the delegate list, ruled 10-21; that commit updated `test_oidc_broker_chart.py` and not this test |
| `01M6FMQY0YAW59ENJEDZTZA2WQ` | `152d453f` | `ia-01/lane/01-the-case-panel-reads-stage-options-and-release` | `test_dispatch_fanout_step.py::test_a_definition_CANNOT_declare_an_escalation_path` | `DispatchFanoutStep` gained `stage`; the exact field set fails, and the `escalation` assert still holds |
| `01M6FMQY6AJHJJC5BMA3FH8Q8F` | `c095be48` | `ia197/lane/01-202` | `test_origin_write_route.py::test_q2_e_AN_ALREADY_FILED_TASK_IS_NOT_REFILED_BUT_THE_ROW_MOVES` | the path now calls `get_open_task_payload`, which the `filing` fixture does not stub; green at its parent with the same unset DSN |
| `01M6FMQYB0P53YW79QGMZ3X175` | `a14e21b5` | `ia-01/lane/01-review-export` | `test_the_promotion_stores_keep_the_record_and_move_the_objects.py::test_the_statement_population_is_the_four_known` | `_PROMOTED_BETWEEN_SQL` is a fifth statement |

**Limits of this:**
- I ran the old commits in today's venv, so a dependency change between then and now is not excluded as a contributor.
- This shows which commit broke each test. It does not show whether the fix belongs in the test or the code, and I have not decided that for any of them. They are yours to read.
- Some of these tests were written elsewhere: two on lane/74, and gov last touched q2-e, at `00374662`, before the break.

**The first item carries a real question.** `delegate_reads_artifacts_only` (gateway.py, near L12617) is the only src site of that refusal. The door's exemption needs an `on_behalf_of` body field, and this GET has no body. So the guard may be unable to fire for a `svc:` delegate on this route. If that is right, updating the tests to expect the door's 403 would turn four reds green and hide a dead guard. I read this from the code and did not measure it.

saf's `test_s3_the_catalogue_is_the_reviewed_list` is a ninth red and stays on `01M6EYWM7JPW40G3PQATTYXAQR`.
