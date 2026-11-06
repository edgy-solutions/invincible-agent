# Handoff: lane/gov, 2026-11-06 (#276 merged; #282 is the dimensions ruling; two SDK fields asked)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-06

This supersedes `2026-11-06-handoff-lane-gov-276-can-decide-rail-four-forks-with-the-architect.md`. Its "Carried over" row still stands except where this file changes it.

## The rulings since (via Chris, verbatim)

On #276's four forks (architect):

> "1. Two different acts, two rails: option_deciders.yaml says who may choose an option at a decide step; task_grants' approver audience says who may approve. A workflow row references both by name; neither derives from the other. 2. Key per workflow now, not later: `<workflow_id>.<option>`. A generic option (archive) gets one row per workflow that offers it. Nothing reads the file yet, so there is no cost. 3. Options live on the decide step of the workflow definition (`steps[id=…].options`, the SDK's WorkflowDefinition). The three hard-coded option lists retire when the runner reads the step — item for 74, after the Socratic bar work. 4. Contracts use `level:` (per column, plus `max_level` on the dataset), the levels.yaml vocabulary; `classification` stays the compartment word on workflow rows. The three red runbook-page tests on master: Lane 1 triages and names an owner in the sweep; they predate everything tonight."

On dimensions (Chris):

> "gov: policy/classification/levels.yaml → dimensions.yaml (name, type, vocabulary, owner); `cleared_for:<level>` stays for the hierarchical dimension; `holds:<dimension>:<value>` rail for set dimensions; validator refuses a value outside the vocabulary. Still validator-only. #268's seal updates."

## State

- **#276 merged** as `a20770eb`, with rulings 1 to 3 applied. The rail item `01M6QDH5GS5KRZXF05P5BYGJ2V` is set to done on #282's branch.
- **#282 is open and MERGEABLE.** Branch `lane/gov-classification-dimensions`, head `514aaec0`, master `a20770eb` merged in at `5c8d57a1`.
  - It renames `levels.yaml` to `policy/classification/dimensions.yaml` and adds the `holds:` rail `policy/dimension_holders.yaml` (family `dimension_holders`, object_scoped). `cleared_for` now reads the hierarchical dimension.
  - Seals: `test_classification_dimensions.py`, `test_dimension_holders_rail.py`, and the updated `test_level_readers_rail.py`.
  - What ran: 290 passed on the merged tree, and 24 of 24 mutants were killed.
  - It needs a train the architect orders, or Chris's approval (rule 3: not board-only).
  - Board: `01M6QJN0CFMHH0G58ZTCEKTWV2` (review) is this work.
- **Packets placed** (master tree, untracked):
  - `2026-11-06-packet-to-architect-from-gov-dimensions-built-282-and-two-sdk-fields-the-rulings-need.md`, cc lane/01. It asks for:
    - confirmation of three readings: at most one hierarchical dimension; owner replaces reason and ratified_by; the rail's file name;
    - SDK items for ca, because v0.9.15 has no `options` on any step (only `HumanAwaitStep.chooses_from`) and no `level` or `max_level` on `AssetContractColumn` or `AssetContractDataset`;
    - ADR-0064's stale `levels.yaml` (line 124 and the draft appendix) to be updated.

    It also reports `tests/test_board_drift.py` red on master to Lane 1.
  - `2026-11-06-packet-to-dag-tools-owner-cc-architect-from-gov-the-levels-file-is-now-classification-dimensions-yaml.md`: the new name and shape.
- **Board reassignment.** Lane 1's #279 moved 15 items to gov. None is started. Gov takes one only when the architect assigns it by name.

## Next (in order)

1. Read master, #282 and the inbox in the master tree's `sessions/`.
2. When the architect answers the three readings: rework #282 if it is still open, or file a follow-up item.
3. When the SDK adds `options` on steps: wire option membership into `option_deciders_errors`. Lane 74's `01M6QHKVK50KZ10GJM77T5051F` retires the three option lists.
4. When the SDK adds `level` and `max_level`: build `01M6QDH6G42ETEE4WSG6ZEBQAN` against `contracts/*.yaml` and the hierarchical vocabulary.
5. Carried over: the ConfigMap (`01M6P8PTFES1FTRD1JAKSSVFFC`, blocked on Chris naming the chart version), fork 13, and the v0.9.14 re-pin.

## Scratch (session scratchpad, not durable)

- `dm` (own venv) holds #282. `od` holds the merged #276 and can go.
- The mutant runners are `mut_dm.py` (#282) and `mut_od2.py` (#276). The PR descriptions are `dm_pr_2.md` and `od_pr_4.md`.

## Lessons

- **A commit message's last paragraph is a trailer block if it starts with `Word:`.** "Seal: …" in c2e0ca66 parsed as a trailer. End on prose.
- **Test the board's own validator before staging it.** `status: review` with `pr: []` is refused, and a `pr:` entry is `<repo>#<n>`, not a bare number.
- **A test that writes a tracked file through `write_text` leaves CRLF on Windows.** `git diff` stays clean, so `tr -cd '\r'` the file before trusting a drift check.
- **`gh` outside a repo can fail silently under `| tail`.** Verify a body edit by reading it back.
