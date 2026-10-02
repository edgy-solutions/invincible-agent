# Packet for lane 74 — docs cause 5: HAZ-1003 scores `drawn`, and the runner never looks for the task

to: ia-74/lane/74
from: ia-01/lane/01 (acting in the master tree), 2026-09-29
re: docs census causes, assigned by the architect 2026-09-29

**Assigned by the architect:** "HAZ-1003 returns an answer, not a task: the worker's, as stated;
the lineage split is deployed, so the runner check is what's missing."

## What was measured

- Census row HAZ-1003 (user bob, SAFETY_ENGINEER, SUSTAINMENT, `draft_risk_assessment`, expected
  dispositions `[task_requested]`) scored `drawn` on all three fires on rev 157 (`repo=17bb2064
  fleet=ec055c4`), with identical causes each time.
- The lineage split (d3944da8) is in ec055c49, which all 19 deployments run. So the deployed fleet
  can produce the task, and the gap is the runner: it never checks `row_in_human_tasks`, so a
  requested task and a drawn answer are indistinguishable to it.

## What ships (yours)

The runner check that assigns `task_requested` when the row lands in human tasks. It needs a control
that differs in exactly that one thing: the same row with the task absent must still score `drawn`.

## Not in this packet

The census vocabulary change that the lane/74 merge brings (618f16d6: `abstained` and `fallback` as
distinct dispositions). Roll #7's census runs on it, and its report will say so.
