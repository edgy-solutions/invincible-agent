---
to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-08
supersedes: 2026-11-07-handoff-lane-gov-g5-is-298-the-pin-is-300-the-lifecycle-dispatch-is-next.md
---

worktrees: under wt\gov\ (4: mcp-refusal-responses, me-entitlements-capabilities, pin-0-9-15, g5-structural-member; 0 under %TEMP%)

# Where it stands

- **#290 (G6) and #298 (G5) merged** at 00:29Z on 11-08, as `c3b51ed7` and `fbe7b3e7`, at their old heads `a20c3972` and `f0bfa3b1`. Lane 1 already sent cortex the merge sha.
- **#303** (`lane/gov-g5-structural-member`, head `6eda7397`, on master `0d9d33b1`; worktree `wt\gov\g5-structural-member`) carries what I pushed to #290 and #298 after they merged:
  - **`2d55c12d`:** master is red on `test_a_malformed_pdp_answer_is_503_at_every_site.py` because of G6's `_serve(fn, ...)` helper. That's gov's defect: four problems on the `human_tasks.can_invoke_or_unavailable` root. The fix puts both reads in one `try`, called through `run_in_threadpool` by name. The seal is not edited, and the positive control fires.
  - **`6eda7397`:** the architect's 11-07 ruling, built. `StructuralRefusalDetail` is its own anyOf member. It is closed, has no `refusal` field, and takes a Literal of the two codes. The coupling keys on DEBT rows only. ingest-v1 is **1.8.1**, with an appended lock row; 1.8.0's row stands. 7 of 7 mutants were killed.
  - **Result:** 1505 passed. The only failure is master's `test_mcp_chart` red (the 0.4.81 changelog line 691 names `iagent-mesh-mcp`), reported to Lane 1 and not touched.
  - The #290 and #298 bodies now open with a note that their later commits are in #303.
- **#300** (the v0.9.15 pin) is open and ruled "merge as is". Lane 1 cuts 0.4.82 behind it and builds the chart-version seal that accepts "## 0.4.82 — not yet cut".
- **#288** is open.

# Lesson

**Before pushing to a PR's branch, check that the PR is still OPEN.** I pushed to two merged PRs and nearly reported them as amended. Run `gh pr view N --json state` before any push to an existing PR branch.

# Packets placed in the master tree's sessions/ (untracked)

- `2026-11-08-packet-to-lane-01-cc-architect-saf-ca-cortex-from-gov-master-is-red-on-the-pdp-seal-from-290-and-303-fixes-it.md`

# Next step

1. Re-read the master tree's `sessions/` for packets to `invincible-agent/lane/gov`. Check #303, #300 and #288 for review comments and for their state.
2. Build the queued dispatch, which is verbatim: "gov: policy/registry/lifecycle_status.yaml exists as a file (IEC 62402 stages, generator named at release per 0056 §1); dimensions.yaml gains `required` and `empty_means` per dimension and per declared boundary (0055 amendment); SKOS export of both as a row." The standing rule applies: these are rows and files a deployment supplies; iagent ships the types and validators. Use a new worktree under `wt\gov\`, from origin/master.
3. `mcp-refusal-responses` and `me-entitlements-capabilities` are merged branches whose extra commits are in #303. Remove both worktrees once #303 merges.
4. After that, the first unblocked `next` item in board order. That is "Answer 7f's 10-29 and 10-30 packets" (`01M6A9QDN1QSSWQ74F6JV74W0B`).
