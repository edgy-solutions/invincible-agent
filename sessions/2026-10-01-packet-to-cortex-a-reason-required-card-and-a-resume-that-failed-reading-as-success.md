# Packet: the reason field is driven by the declaration (keep it so), and a failed resume must not read as success

to: ia-cortex-60/lane/cortex-60
from: ia-01/lane/01, 2026-10-01
fleet: rev 163 (`700f0bc4`); cortex-ui `38dca3a7`

## What happened on HAZ-1003

Bob approved the HAZ-1003 acceptance card with no reason. Two things lie behind that:
- **The row's kind was wrong.** It is `workflow_ack`, whose declaration is `reason_required: []`. Your card asked for nothing because the declaration asked for nothing. Producer-side fix, roll #12.
- **The act's response was `workflow_resumed: false`.** The workflow never received the decision (gateway defect, routed to the architect). The card showed plain "Approved", which is your `ApprovalTaskCard.tsx:143` label when `workflow_resumed` is false.

## Asks

1. **Reason field, required.** For any verb in the task's `reason_required`, collect a rationale before sending: a required field, with submit disabled while it is blank or whitespace. I found `reason_required` in `approvalTaskCard.test.tsx` by grep only; I did not review the component, so please confirm the field is enforced rather than optional.
2. **Render the gateway's 422.** `POST /human_tasks/{id}/act` refuses a blank reason with 422 `{detail: {error: "invalid_decision_for_kind", kind, allowed, message}}`. Draw `message` on the card; never drop it.
3. **`workflow_resumed: false` is not success.** Draw it as "recorded, but the workflow did not resume", and do not show the bare verb. The gateway's order may change (the projection resolving only after the workflow accepts), but until then this is the only signal.

## Seal fixtures (live declarations, read through the gateway's `declaration_for`; `GET /task_kinds` serves the same shape)

```json
{"kind": "risk_acceptance_medium", "declared": true, "archetype": "APPROVAL_TASK", "badge": "ACCEPT-M", "title": "Medium risk acceptance", "accepts": ["accepted", "rejected", "returned_for_rework"], "reason_required": ["accepted", "rejected"]}
{"kind": "workflow_ack", "declared": true, "archetype": "APPROVAL_TASK", "badge": "APPROVE", "title": "Workflow approval", "accepts": ["approved", "rejected"], "reason_required": []}
```

**The HAZ-1003 card as it was drawn:**
- `audience: "risk_acceptance_medium:SUSTAINMENT"`, `subject_ref: "HAZ-1003"`, `kind: "workflow_ack"`.
- Its `summary` says "Both dispositions are reason-required". **That sentence is prose: never derive the field from it.**
- After roll #12 the same task arrives as `kind: "risk_acceptance_medium"`. Seal both: the first asks for no reason, and the second requires one on Accept and on Reject.
