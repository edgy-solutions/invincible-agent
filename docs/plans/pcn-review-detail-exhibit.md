# PCN grouped-review DETAIL — the reviewer can review (exhibit)

Built 2026-07-24, from a live-UI gap: the inbox card offered only blind Approve/Reject, and a `needs_review`
row makes blind accept-all REFUSE (correctly, forever) — so the one working button deadlocked against the
safety chain the system exists for. The rich `GroupedReviewTable` was already built + sealed; it was
missing three connectors. Now wired: the reviewer opens the batch, sees the parts + the UNVERIFIED badge,
overrides the unverified one with a captured reason, and submits — accept-all-with-exceptions. Beats 2-3.

## The three connectors (each endpoint sealed on at least one side already)
1. **engine-a `PcnGroupedReview.get_batch`** (shared read handler): serves THIS approver's authored
   `batch_items` + notice labels and NOTHING else from workflow state (two-object at birth — the state IS
   the per-approver-filtered batch; a decoy state field is asserted absent from the response, so a
   batch-read can't become the existence oracle Slice 3 closed). `run()` now persists `notice_id`+`doc_type`.
2. **cortex-bff `GET /pcn/reviews/{workflow_id}/batch`**: existence-oracle-safe (404 unless the caller
   holds this grouped task in their OWN queue — same authz_id filter as `/act`), proxies `get_batch`, maps
   to the UI `ReviewBatch` shape.
3. **cortex-ui**: the grouped-review card shows a **Review** action that fetches the batch and opens
   `GroupedReviewTable` in an overlay; its submit goes through `actOnHumanTask(..., overrides)` — the `/act`
   bridge, the SINGLE durable decision path. The dead `/review_batches/{id}/resolve` client call +
   `resolveReviewBatch` stub are DELETED (rider 2 — one decider, not a second route to "fix" later).

## Watched assertion — LIVE GREEN (beats 2-3 through the real API path)
Fresh review with one `needs_review` part (`NSR02F30NXT5G`/`NSR05F20NXT5G`), driven through cortex-bff:

| leg | check | result |
|---|---|---|
| **A see** | `GET /pcn/reviews/{wf}/batch` | batch returns the parts; the unverified part carries `needs_review:true` — the reviewer SEES it |
| **B refuse** | blind `POST /act {approved}` (no overrides) | `accepted:false, still_pending` + reason *"unverified part cannot ride accept-all; handle it with an explicit override"* — the deadlock the UI now avoids |
| **C override** | `POST /act {approved, overrides:{<mpn>:{disposition, reason}}}` | `accepted:true, review_dispatched:true, resolved_count:N` |
| **D provenance** | bob `/me/human_tasks` | the dispatch tasks land in bob's queue, `requested_by:alice@example.com`, and the overridden part carries the `[MPN extraction UNVERIFIED]` marker forward |

Leg B is the point: it exercises the laundering seal + refusal routing through the ACTUAL submission path,
and proves blind-approve is not a viable button for a batch that contains its own reason to exist.

## Offline coverage
`test_pcn_workflow`: `get_batch` serves EXACTLY the authored items (a decoy state field must not leak) +
404 on no active review; the grouped register still carries `workflow_id`. 22/22 green. cortex-ui
`tsc --noEmit` clean.

## Gotchas found live (banked)
- **Restate re-registration:** a NEW handler (`get_batch`) on a rolled engine is NOT routable until the
  deployment is RE-REGISTERED with the Restate server (`POST :9070/deployments {uri, force:true}`) — a
  rolling restart alone leaves the old handler set registered (run/submit_decision worked; get_batch 404'd).
- **No-input handler body:** `get_batch(ctx)` takes no input; Restate 400s on a `{}` body — the BFF must
  POST an EMPTY body (`fix cdecaa0`).

## Honest gap FILED (not papered over) — the override reason is not yet a queryable audit
The capture-why reason is ENFORCED at submit (an override without a reason is rejected) and durably
recorded in the Restate decision journal — but `plan_dispatch` does NOT thread `override_reason` into the
dispatch task or the graph state write (only `dispositionState`/`dispositionRef`/`proposedByRuleset`). So
the needs_review FLAG carries forward to bob's task (the UNVERIFIED marker), but the verifying REASON does
not land on the dispositioned part as a queryable audit field. **Follow-up (the audit-thread completion):**
thread `override_reason` → the dispatch task summary AND a `pcn:dispositionReason` graph triple
(plan_dispatch → plan_to_payload → `_write_disposition_state` body → engine-o `/write_pcn_disposition_state`
→ the SPARQL update). Small per layer, four layers + an engine-a/engine-o roll — a clean standalone window.

## Also filed
- Grouped-review **rejection** still 501 (cancel-on-reject deferred) — the card shows only Review for
  grouped tasks, so reject isn't reachable there; a rejected review needs workflow cancellation.
