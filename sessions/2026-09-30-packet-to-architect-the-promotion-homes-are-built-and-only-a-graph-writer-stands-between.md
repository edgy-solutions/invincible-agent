# Packet: the ruled promotion homes are built, and one missing writer keeps the act at 503

to: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-09-30
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-09-30-report-74-the-promotion-homes-are-built-and-the-act-still-503s-for-want-of-a-graph-writer.md`

No store writes, no row inserted, no turn fired, nothing live. Both branches are pushed and not merged.

- `lane/74-provenance-floor` `ead2f80d`: the ruled label
  `{obtained_via, ingest_ids, unidentified}`. The `ingest_id` sits in the block. Mutation 15/15.
- `lane/74-promotion-store` `d84ac0ef`, which contains `ead2f80d`: the ledger in the approval
  plane's Postgres (insert-only), the fact triple on the ingest node, and the rejection sweep with
  S3 moved to `rejected/<ingest_id>/` copies-first. A replay of the same decision finishes the
  effect as the original act. Mutation 31/31.
- The consequence set's one red is identical on the baseline.

## The 503 is lifted in code, not in production

`_promotion_stores()` wires the ledger and the S3 quarantine. The graph and the indexes are None,
because no concrete writer exists in this repo or at the SDK pin. Both verbs need the graph, so both
still 503 before any write, naming `graph`. A route arm pins this state.

## To route

1. **Lane 1, the `/ingest` seam.**
   - It writes no ingest node.
   - `make_provenance` (master `gateway.py:8241`) does not pass `ingest_id=`.
   - Until both land, a promotion is refused 409 `ingest_node_absent`, and the sweep finds nothing
     keyed on the block.
2. **Whoever owns the concrete graph and vectors writers.** The adapter needs three things the SDK
   writers lack (measured earlier today):
   - a node-exists read;
   - a delete-by-block-`ingest_id` on the graph;
   - any delete on the vectors writer.

   The shapes to meet are `IngestGraph` and `IngestIndexes` in `src/iagent/promotion.py`.
3. **cortex-ui.** `ProvenanceFloorLabel.tsx:22` banners on `ingest_ids.length` alone, so
   `unidentified: true` with no ids draws no warning.
4. **The chart / bff.** The Electric shape proxy has no table allow-list. `document_decision_record`
   is unexposed only because it lacks `produced_for_user_id`.
5. **Open.** Do extraction outputs outside the seam directory exist? The quarantine moves only
   `ingress-user/<kind>/<hex>/`. HAZ-1003 is still unmeasured.
