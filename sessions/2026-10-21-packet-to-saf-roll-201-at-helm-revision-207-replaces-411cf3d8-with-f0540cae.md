to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect, doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-21
relay: Chris

Placed, not committed. This packet carries no secret.

# Roll 201 (helm revision 207) replaces 411cf3d8 with f0540cae on every iagent image

| what | value |
| --- | --- |
| helm revision 207 | deployed 2026-10-21 at about 03:50Z. This is **roll 201**. Engines re-rolled after the reregister job; all settled by 04:01Z. |
| the image on every iagent container | `f0540caef12fa465f9d20672563b7fedd9c1bf34`. No `411cf3d8` is left. |
| what changed in the code | 4 commits, `411cf3d8..f0540cae` on lane/01-197, none of them on master yet. |
| cortex-ui | unchanged from roll 200 |

**The two code commits:**
- `63c1bab8`, policy only:
  - `policy/users.yaml` gains operator.regioneast, and liaison.coalition joins `maint-approvers-edge-01`.
  - The live Topaz directory does not change until a human runs the apply.
- `f0540cae`:
  - A `promoted` document_promotion act that carries row_edits, or that reconciles edges, writes a correction record to `processing-artifacts` at `corrections/<ingest hex>/<record_id>.json`. If the record is needed and no outbox is configured, the act is refused 503 before the ledger append.
  - `deleted`, `added` and `corrected` row ops take an optional `evidence_ref`. A blank value is a 422.
  - The `extraction_defect` payload now carries `ingest_id`.
  - Files touched: `promotion.py`, `promotion_stores.py`, `gateway.py`, `steward_correction.py` and `extraction_defect.yaml`.

**What it means for your measurements:** anything you measured against roll 200 ran on `411cf3d8`. From now on, anything you measure runs on `f0540cae`.

Health ×3 returned 200 on both the BFF and cortex-ui, and the cortex login passed. Both were measured after the rollout settled.
