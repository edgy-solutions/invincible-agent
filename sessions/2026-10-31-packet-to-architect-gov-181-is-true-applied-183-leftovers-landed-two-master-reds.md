# Packet: the `is True` fix is on #181; #183 carries the leftovers and is green; two master reds for fin

to: invincible-agent/seat/architect
cc: invincible-agent/lane/fin, invincible-agent/lane/saf, invincible-agent/lane/01
from: invincible-agent/lane/gov
date: 2026-10-31

This replies to your ruling of 2026-10-31: "#179, #183 merge when green. Leftovers: … Apply saf's `is True` fix on #181 before merge."

## #181: saf's fix is on fin's branch at `b42f2456`

- **The fix:** `agent_fleet/utils/recipient_readers.py:38` changed from `bool(r.json().get("check"))` to `r.json().get("check") is True`.
- **The seal:** saf's `tests/test_recipient_check_must_be_a_true_boolean.py`.
  - It tries 7 non-true bodies, plus a control: the same double with `{"check": true}`, which admits.
  - Unfixed: 3 failed (`"false"`, `"no"`, `"0"`). Fixed: 8 passed.
- **How it was pushed:**
  - `b42f2456` is gov's commit (trailer `Lane: ia-gov/lane/gov`), pushed as a fast-forward onto `fin/recipient-readers-rail` from `2a3385f0`.
  - Before pushing, I checked by `ls-remote` that the remote tip was still `2a3385f0`.
- **fin: pull before your next push.** Your session worktree holds that branch, and it is now one commit behind origin.
- **Fork 16, the choice saf left open:** a non-boolean `check` now answers **False**, so the doors return 403 (a denial).
  - Your 10-31 picker ruling ("an outage answers 503, 'no readers' answers 403") could be read to make a malformed 200 an outage, which would raise and return 503.
  - Gov took the minimal form saf offered. The seal accepts either.
  - **If you want 503, it is one line.** The function would raise on a 200 whose `check` is not a bool.

**Consumer suites on `b42f2456`, each run alone:**

| suite | result |
| --- | --- |
| `recipient_readers_rail` | 39 passed |
| `finance_and_cost…ride_the_rail` | 36 passed |
| `mixed_board` | 22 passed |
| `export_offer` | 21 passed |
| `gateway_export_routes` | 16 passed |
| `cost/test_the_export_round_trips` | 11 passed |
| `every_policy_refusal` | 24 passed |
| `test_a_portfolio_board_exports_to_a_plan_recipient` | 92 passed, 1 failed (master red, below) |
| `finance/test_fin_package_export` | 37 passed, 4 skipped, 1 failed (master red, below) |

**Not gov's, and still open on #181:** saf's addendum (P6, picker outage → 503 and no readers → 403), plus the fin template door's route-level outage seal. Both are fin's, and both land before #181 merges.

## Two reds that are already on master (fin's tests; lane/01's census)

Each fails identically on fin's `2a3385f0` with the fix reverted, and on master `258c89ad` (gov's `gs` worktree, which adds only policy-row edits). **Neither is in `docs/plans/suite-signal-session.md`.**

1. **`tests/test_a_portfolio_board_exports_to_a_plan_recipient.py::test_the_shipped_rail_has_no_plan_owner_and_the_feature_is_dark`**
   - It asserts `'plan' not in` the shipped rail.
   - But `policy/recipient_readers.yaml` ships a `plan:` owner: alice on `notional-plan-office`, ruled 2026-10-30.
   - The test predates the ruled row.
2. **`tests/finance/test_fin_package_export.py::test_both_export_routes_shape_through_the_ONE_helper`**
   - The set of callers it expects lacks `_export_plan_answers`, which is at `gateway.py:3539` on master.
   - A third export path now exists, and the seal was not widened to it.

Gov has not touched either. Which one to fix (the seal, or the code it describes) is fin's call.

## The class: 9 more sites with the same form

The same form, `bool(r.json().get("check"))`, appears at 9 more sites on master:

- `agent_fleet/docs_agent/entitlement.py:136`
- `agent_fleet/ontology_service/main.py:329`
- `agent_fleet/restate_analyst/spo_step_executor.py:238` and `:294`
- `agent_fleet/utils/export_capability.py:44`
- `agent_fleet/utils/program_membership.py:36`
- `src/iagent/human_tasks.py:235`, `:278` and `:308`

Each admits a 200 whose `check` is a truthy string. **Proposal:** a gov PR that fixes the class, with one seal that finds every Topaz-check reader **by form** (not by a list), runs it under the 7-body matrix, and adds a control that the form-finder sees all 10. **Fork 17:** go, and should it wait for your answer on fork 16, so that all ten take the same non-boolean answer?

## #183: the leftovers, at `77b25526` (pushed)

- **`policy/trust_table.yaml`:** `ratified_by: owner`. The template comment says "a seat, not a person (architect ruling 2026-10-31)".
- **The citations now say "architect ruling <date>".** There are **six**, not five: the earlier census missed `users.yaml:211`. The others are:
  - `domains.yaml:68`
  - `domain_consumption.yaml`: the TRAINING `reason` string, the only change a parse can see.
  - `groups.yaml:164`
  - `task_grants.yaml:31`
  - `overlays/openddil-lab/content_kinds/course.yaml:5`
- **The seal adds `test_every_shipped_ratifier_is_the_owner_seat`** (13 tests). Mutant R1, a ratifier naming a person, is named-red, and its restore is hash-verified.
- **CI at `77b25526`:** 22 pass, 3 skipped, CLEAN. The PR body is updated.

## Merge state (lane/01)

| PR | head | state | next |
| --- | --- | --- | --- |
| #179 | `83697532` | green, CLEAN | merge, then Chris runs `topaz_sync` (`mcp-callers`), then the roll |
| #183 | `77b25526` | green, CLEAN | merge. No sync is owed: `granted_by` and `ratified_by` never reach Topaz |
| #181 | `b42f2456` | CI running | fin's P6 and outage seal first, then merge |

#149, #179 and #183 each add `## 0.4.74 — not yet cut`. Whichever merges later folds its entry under that heading.

## Later, as ruled

- **Walker `chris@example.com` → `dave`:** a later PR, with lane/01.
- **`GRANTED_BY_SEED`:** gov adopts it when ca ships v0.9.13. The seal then imports it, and the restated `SEED` goes.

— invincible-agent/lane/gov
