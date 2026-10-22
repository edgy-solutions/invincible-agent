to: invincible-agent/seat/architect
cc: cortex-ui/master, doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-22
re: "Build today" (the TI silent end): Lane 1's item 1 and cortex's item 2, rolled together
relay: Chris

Committed on lane/01-202. This report carries no secret.

# Rev 214 is live: BFF 206 (`67d6e9f6`) with cortex `c390a03`. Every gate held, so no rollback. The live TI check is Chris's drop, next

## Outcome

| item | result |
| --- | --- |
| roll | helm rev **214**, deployed 17:41Z. 33/33 deployments rolled out. Chart label held at 0.4.61, as Chris chose (same as 213); `Chart.yaml` is restored to 0.4.62 and the tree is clean |
| images | BFF `cortex-bff:67d6e9f6…` (build run 39816142084, green). cortex-ui at `sha256:2359f48e…` = `c390a03` (cortex CI run 39815907710, green); the pod's imageID matches |
| values diff, shown before the roll | **2 of 201 paths**: `global.imageTag` `7bd00941` → `67d6e9f6`, and `cortexUi.image.digest` `c3a2acdd` → `2359f48e`. Chart templates are unchanged since 213 |
| pre-roll gates | inboxes re-read at 16:48Z (cortex's pin packet, then its §6 rewrite at 16:46Z; my digest matches theirs). Dagster: 0 runs queued or in flight. All 7 nodes Ready, worker6 included |
| health | `/health` 3/3 on the BFF and on cortex-ui |
| cortex login | passed (1 test, exit 0) |
| (ii) brokered login, atlantia | passed (1 test, exit 0). Secret presence by length and hash prefix only |
| (iii) release by case id | passed on a **fresh** test case `e2e-mrad-499c254a`: bob decided `replace_now`, alice's `tier_ack` by case id returned 200 `released`, history `received → triaged → maint_fault_propose → maint_release → closed`. d1a7ee0b was not touched |
| rollback | not needed. It would be to 213 (BFF `7bd00941`, cortex `a3cf4d1`) |

## What is now live

**Lane 1, item 1** (`67d6e9f6`, sealed in `tests/test_a_finished_run_with_no_leaf_waits_for_a_kind.py`):
- Every 60 s, the BFF lists leaf-capable rows at `extracting` that have no leaf. When the row's Dagster run has finished (success, failure or cancel), the row goes to `awaiting_kind` with `hold_reason: "kind_not_identified"`. Unreachable Dagster, or a run that is queued or running, leaves the row alone (fail closed).
- If the run left a title read (a manifest `leaf` block), that block is applied as the manifest backstop applies it: a confident title relaunches as the leaf, otherwise the row is held with the candidates.
- The hold is guarded on the run id the pass saw finish, so a relaunch that landed meanwhile wins.
- `hold_reason` is on `/ingest/{id}/status`, the `/ingest/mine` items and the `/leaf` answer. It has a value only at `awaiting_kind`.
- A pick from the hold relaunches exactly as built on 10-21 (sealed: attempt 2, `leaf_applied`, the sidecar rewritten).
- Seal proofs: 16 arms red against the unfixed source and green after. Three mutants (no run-finished check, no run-id guard, `hold_reason` served at every stage) each red a named arm. Every related test file is green, run one at a time.

**Cortex, item 2** (`c390a03`): the amber rail row, `? · couldn't tell — pick one` with PCN/PDN on the card, the header needs-you count, and the toast. **It also brings `9be5963`**, the pin I missed at 213: a null or absent bbox now reads as "no box". **7f may now send `bbox: null`** for a candidate with no box.

## Not yet proven live, and how it gets proven

- **The new pass has not acted yet.** It logs only when it acts, and it logged nothing in the 7 minutes after the roll. So no leafless row was sitting at `extracting` behind a finished run, or the pass is not running; the silence cannot tell which.
- **The proof is the dry-run path check:** Chris drops the TI PDF and picks no kind (cortex's packet §4). Expected:
  - about 3.5 min after the drop the run ends;
  - within about 60 s the BFF logs `ingest_kind_unidentified ... decision=awaiting_kind`;
  - cortex turns the row amber, toasts and counts it;
  - a pick of PCN relaunches. Allow about 3 min of doc-tools sensor lag before the new run exists.
- I'll read the BFF log line and the run ids when Chris has dropped.

## Departures and notes

1. **`hold_reason` is written by every hold**, not only by the new pass. The title-read hold also writes `kind_not_identified`: a title read that named no confident leaf is a kind not identified. One code today; the column admits more later.
2. **One stale red fixed on the way.** `tests/test_ingest_mine_lists_the_callers_own_drops.py` had been red (7 tests) since `a1656098` (10-21): its sqlite fixture predated the leaf columns that `list_mine` selects. It is now green.
3. **A harness defect, not a product one, in gate (iii).** The walk polls `/cases/{id}` every 5.0 s over one kept-alive connection, and 5 s is uvicorn's keep-alive timeout. Through the port-forward the server's close is not passed on, so a reused connection dies ("server disconnected"). The BFF logged every request that reached it as 200.
   - I re-ran the gate with keep-alive off on a scratch copy. It continued the SAME case; no second case was opened.
   - The tracked walk `tests/sandbox_e2e/test_mrad_case_walks_to_closed.py` has the same race. I'll fix it after the dry run (one line: no connection reuse, or a poll that isn't 5 s).
4. **The fbecec9e trace** is in its own report (`21e19cab`): no hop stopped.

## Freeze

This was the last roll before the dry run. **The freeze resumes now.** Queued for after the dry run:
- `retry_reason` on the row-shaped answers;
- chart 0.4.62;
- the replacement work, pending your rulings;
- the walk's keep-alive fix.
