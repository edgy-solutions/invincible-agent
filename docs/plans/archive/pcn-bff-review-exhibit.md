# PCN disposition review through cortex-bff — composed-path seal (exhibit)

Ran 2026-07-24 on sandbox `edge` after rolling engine-a + cortex-bff (`f11c495`). Proves the five-beats
spine now flows through the BFF (not the raw Restate ingress): a reviewer starts a review, sees the grouped
task, approves it, and the approval bridges into the durable workflow's `submit_decision` — fanning out to
the qualification queue. Seal script: `tests/sandbox_e2e/_seal_pcn_review_bff.py`.

## The wiring (three changes, one coherent path)
1. **engine-a stamps `workflow_id`** on the grouped-review task (`pcn_workflow.run`: `grouped_task["workflow_id"]
   = ctx.key()`; `pcn_driver._mint_dispatch_task` forwards it). The projection row's `workflow_id` was NULL,
   so `/act` had nothing to address `submit_decision` on — an approved review suspended forever. THE blocker.
2. **cortex-bff `/human_tasks/{id}/act`** bridges `kind == pcn_grouped_review` → `POST
   PcnGroupedReview/{workflow_id}/submit_decision`. Validated FIRST, projection resolved ONLY on acceptance:
   a refused submission stays PENDING, never falsely approved-while-suspended. `rejected` → 501 (grouped
   cancellation is a filed follow-up; refuse loudly, don't mark-and-dangle — suspend-vs-fail).
3. **cortex-bff `POST /pcn/reviews`** proxies `start_review`, stamping `approver` from the authenticated
   `authz_id` (never client-supplied) and forwarding the EXTRACTION-sourced `impacted_parts` verbatim — the
   BFF must not reconstruct them from a graph or the `review_state_is_unsourced` tripwire is defeated.

## Evidence — 5 legs GREEN (live, in-cluster through cortex-bff)

| leg | check | result |
|---|---|---|
| **1 start** | alice `POST /pcn/reviews` (extraction payload, fresh notice `PCNBFFSEAL01`) | `STARTED`, `workflow_id=pcn-review-PCNBFFSEAL01-alice@example.com`, count 3, `rules@2915ddb229e4` |
| **2 workflow_id** | alice `/me/human_tasks` → grouped review row | `workflow_id` PRESENT — and the pre-fix `IPCN25300X` grouped row in the SAME response still shows `workflow_id: null` (the fix biting, side by side) |
| **3 bridge** | alice `POST /human_tasks/{grouped}/act {approved}` | `accepted:true, review_dispatched:true, resolved_count:3` — `submit_decision` called, workflow resumed, fanned out |
| **4 fan-out** | bob `/me/human_tasks` | 3 `pcn_disposition` tasks `PCNBFFSEAL01:{NSR01L30NXT5G,NSR02F30NXT5G,NSR05F20NXT5G}` (qualification queue) |
| **NEG tripwire** | alice `POST /pcn/reviews` with `doc_needs_review:true` and no part carrying it | **HTTP 422 `REVIEW_STATE_UNSOURCED`** — the tripwire fires THROUGH the BFF (BFF forwarded the doc-level flag; start_review caught the unsourced request; BFF mapped to 422) |

Leg 2's side-by-side is the positive control: the old NULL row shows the assertion could fail; the new row
shows the fix. The NEG leg proves the laundering guard survives the new composed path — a request built
from a lossy graph (doc-level flag set, no per-part flag) is refused end to end, not just in the unit.

## Offline coverage
`tests/test_pcn_workflow.py::test_run_registers_task_then_fans_out_on_accept` now asserts the grouped
register body carries `workflow_id == ctx.key()` (20/20 pcn workflow+driver tests green under the frozen
restate-analyst env). `FakeWorkflowContext` gained `key()` for the assertion.

## Residue (rides the pre-rehearsal cleanup)
The seal left `PCNBFFSEAL01`: 3 parts in `dispatchQualification` + 3 pending qualification tasks + a
resolved grouped task. Like the loop-run residue, it is BUILD SUBSTRATE for the dashboard window (more
parts-in-state to render) and joins the NAMED pre-rehearsal cleanup (now covering BOTH `IPCN25300X` and
`PCNBFFSEAL01`) so the demo mints fresh. Fresh notice_id was used precisely so the durable workflow key
didn't collide with the prior `IPCN25300X` run — the residue ruling in practice.

## Follow-ups filed (not M1)
- Grouped-review **rejection** → workflow cancellation (currently 501); wire cancel-on-reject so a rejected
  review releases rather than dangles.
- **STRIKE disposition — "this part isn't in the notice at all" (surfaced 2026-07-25 by the auto-path
  re-ingest).** The first un-hacked producer ingest had the vision model over-generate `NSR02F30NXT5G`
  (an F30 variant present in NEITHER run's tables — the notice has the L-variant). The evidence coherence
  seal correctly refused it a crop (honest not_found), and the review flow correctly forces it to be an
  explicit exception (no automated lane). BUT the reviewer's only outcomes are the ruleset dispositions
  (LTB / qualify / archive) — there is no "this is not a real part, strike it from the batch" outcome, so
  an LLM-hallucinated part has to be dispositioned as if it were real. This is a POLICY addition (a
  rules-TTL / outcome-vocabulary question), NOT UI — the disposition set needs a `strike`/`notInNotice`
  terminal outcome that removes the row without dispatching an action. Fold into the grouped-reject→cancel
  work OR wake on the first reviewer who hits it; the honest UNVERIFIED label covers it for the demo.
- `user_jwt` staleness: the token threaded at start is reused for dispatch mint at approve time; a review
  that sits past token expiry would 401 the mint. Pre-existing design; noted for the approval-latency case.
