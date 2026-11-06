# Handoff: lane/gov, 2026-11-06 (#270 merged; #276 is the can_decide rail; four forks with the architect)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-06

This supersedes `2026-11-05-handoff-lane-gov-268-merged-with-the-rulings-270-routes-from-dag-tools.md`. Its "Open forks" (12, 13) and its "Waiting on" rows still stand, except where this file changes them.

## The brief since (architect via Chris, 11-06, verbatim)

> "Rails for obsolescence_resolution: roles (who may approve LTB / redesign) as groups + capability rows; `can_decide: <option>` rail with ratified_by: owner; contract files get a `classification` field validated against levels.yaml. Validator only until Lane 1's workflow row lands."

It sits under ADR-0065/0066 (provisional numbers, not written). The standing rule: "kinds, workflows, options, levels, ontology slices, mappings and contracts are rows/files a deployment supplies; dag-tools and iagent ship the types and the validators, never a customer's shape." It queues behind 0.4.80, the finance live leg, the OpenDDIL walk and Socratic.

## State

- **#270 merged** as `cf873ad2`. The gateway door's routes now come from dag-tools 0.11.0. `01M6KF8279KZ843KG5MMM0R3YH` was in review on the branch; confirm it reaches done on master.
- **#276 is open and MERGEABLE.** Branch `lane/gov-option-deciders-rail`, head `3d2d9d86`, base master `db0d547e`. It is the `can_decide:<option>` rail.
  - `policy/option_deciders.yaml` (empty) and the grantor `policy/grantors/option_deciders.yaml` (`object_scoped: false`).
  - `option_deciders_errors`, run when present. A `can_decide:` capability row is refused.
  - The seal is `tests/security/test_option_deciders_rail.py`.
  - What ran: the acceptance run gave 211 passed, and 9 of 9 mutants were killed.
  - The area run gave 1688 passed and 4 failed, none from #276: three docs-gate arms red on master (below), plus the SDK-sibling arm, which fails because the worktree is in a scratchpad.
  - Board: `01M6QDH5GS5KRZXF05P5BYGJ2V` (review) is the rail. `01M6QDH6G42ETEE4WSG6ZEBQAN` (open, later) is the contract classification field. It is not started, because no contract file exists as data.
- **Packet placed** (master tree, untracked): `2026-11-06-packet-to-architect-from-gov-obsolescence-rails-can-decide-built-validator-only-four-forks.md`, cc lane/01. Its four forks:
  1. A role is the rail row, not a second capability family. How does the rail relate to the task_grants audience of a `human_await` step?
  2. Is an option keyed alone, or per workflow? `:` is refused in an option id so either form stays open.
  3. Which workflow-row field carries the options? Do the three option literals retire with it (`review_starter.py:145`, `gateway.py:2495`, `dispatch_plan.py:32`)?
  4. What is the contract field called, given that `classification:` already means a compartment on a workflow row?
- **Red on master, not gov's, not in the census:** `tests/docs/test_the_docs_gate_reads_the_grants_the_sync_writes.py::test_no_verb_bearing_page_is_withheld_from_every_grantee`, for the runbook pages on adding a canvas template, a graph and an engine. It reproduces with #276's files removed. It is reported to Chris on #276, with no owner named.

## Next (in order)

1. Read master, #276 and the inbox in the master tree's `sessions/`.
2. When the architect rules the four forks: rework #276 if it is still open, or file a follow-up item.
3. When Lane 1's `obsolescence_resolution` row lands: wire option membership and one row per option to the field it names.
4. When ADR-0066 defines a contract file: build `01M6QDH6G42ETEE4WSG6ZEBQAN`.
5. Carried over: the levels ConfigMap (`01M6P8PTFES1FTRD1JAKSSVFFC`, waiting on Chris naming the chart version), fork 13, and the v0.9.14 re-pin.

## Scratch (session scratchpad, not durable)

- `od` (own venv) holds #276. `gr` and `lv` hold merged PRs and can go.
- `mut_od.py` is #276's mutant runner, and `od_pr_2.md` is its description.

## Lessons

- **A control run is cheaper than an argument.** To show a red is not yours, remove your files from the worktree (backed up to disk), rerun the failing test, then restore and `cmp`. Here that took three seconds of test time and settled the docs-gate question.
- **A brief can name a field the repo already uses with another meaning.** "`classification`" on contracts would collide with workflow rows' compartment `classification:`. Grep the key before building, and raise the collision as a fork.
