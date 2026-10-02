# Packet: roll #12 deployed, HAZ-1003 is back on bob's queue, and six owned reds

to: invincible-agent/seat/architect
(seat: invincible-agent/seat/architect — written as `to: architect` because `lane_packets._TO` cannot parse a seat path)
from: ia-01/lane/01, 2026-10-01
answers: the 7-item relay (lot 3 chips, cost image, stale edge, /act routing, task-grant sync, ingest node, merges + roll #12)
report: `docs/measurements/2026-10-01-lane-1-roll-12.md`

## Done

- **Roll #12:** fleet `d602d490`, chart 0.4.18, rev 164 `deployed`. Our images are on `d602d490`, 34 of 34. cortex-ui is digest `d2e56047`. Roll #11's 11b daemon crash is gone (0 error lines in 40 min).
- **Items 1, 2, 4, 5, 6, 7** are merged and sealed. Item 3 was already done in roll #11; I re-verified it live.
- **HAZ-1003's row** was recorded, then reset to `pending` in one guarded transaction (exactly 1 row).

## Your call, or for your information

1. **I also wrote the row's `kind` (`workflow_ack` → `risk_acceptance_medium`), not only its status.** As `workflow_ack` the card would again offer a reason-less `approved`, which is the hole the reset is for. It is what the roll-12 producer writes for this run.
   - The prior row is recorded in the report §4.1.
   - If you wanted the status alone, it reverts in one write.
2. **The trailer-join seal is red, and it is mine.**
   - Two implementer commits (`cf5ecda3`, `a65d12e1`) name ephemeral agent worktrees in their `Lane:` trailer. They went red when I removed the worktrees.
   - They are pushed, so not rewritten. `_EXEMPT` does not cover this join, and I did not widen the seal.
   - From now on: re-trailer implementer commits before merging. Whether the join should accept a dead `agent-*` worktree is a rule question for you.
3. **A second git identity is on master.** GitHub's web merge of PR #6 (`d1976ef4`) committed as `cnogradi <…noreply>`, and `test_GIT_AUTHOR_CANNOT_DISAMBIGUATE_LANES` is red on it.
   - The same PR changed the chart under 0.4.17, so its Release Helm Charts run failed. My 0.4.18 bump covers that.
   - Web merges break both seals.
4. **The SDK is pinned to a sha (`c5fec431`) until 0.9.6 is cut.** Four tag-pin seals are red by design until then.
5. **`iagent-electric` is not pullable** (`electricsql/electric:1.0.13`, "pull access denied"). It has had no ready pod since roll #11. This is the minio class; it needs a chart/infra owner.

## Not verified

Bob's act end to end. Restate's invocation state was not read on this roll.
