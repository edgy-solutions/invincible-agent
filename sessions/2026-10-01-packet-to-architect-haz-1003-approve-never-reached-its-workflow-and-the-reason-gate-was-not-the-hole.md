# Packet: HAZ-1003's approve never reached its workflow; the reason gate was not the hole

to: invincible-agent/seat/architect
(seat: invincible-agent/seat/architect -- written as `to: architect` because `lane_packets._TO` cannot parse a seat path)
from: ia-01/lane/01, 2026-10-01
answers: the relay "read the decision record for risk-acceptance-HAZ-1003-medium; if empty, enforce reason_required at /act"

All reads below were read-only, inside cortex-bff, against rev 163 (`700f0bc4`). Nothing was written and no code was changed.

## 1. The record: no reason. The premise of the fix does not hold.

`human_task_projection`, `workflow_id = risk-acceptance-HAZ-1003-medium`, has exactly 1 row:

| field | value |
| --- | --- |
| `kind` | `workflow_ack` |
| `status`, `decision` | `approved`, `approved` |
| `comment` | `''` (empty) |
| `acted_by`, `acted_at` | `bob@example.com`, 23:27:07Z |
| `task_id` | `acceptance` |

**`reason_required` is already enforced at `/act`, and sealed.**
- The `/act` route calls `human_tasks.validate_decision(match.kind, decision, comment)` before any write.
- `tests/test_the_declaration_is_authoritative.py:98` refuses a blank reason on `risk_acceptance_high`.

**The gate held for the kind it was given.** The live declarations, read through the gateway's own `declaration_for`:
- `workflow_ack`: `accepts [approved, rejected]`, `reason_required []`;
- `risk_acceptance_medium`: `accepts [accepted, rejected, returned_for_rework]`, `reason_required [accepted, rejected]`.

**The card's "reason-required" sentence is not the kind's declaration.** It is the task's `summary` text, written by engine-a. The card drew `workflow_ack`'s buttons and asked for no reason because its declaration asks for none. `approved` is not even a verb of the risk kind.

**So the whole hole is the kind (item 1b of the roll-11 packet).**
- The worker's fix for it is not on origin yet: no unmerged branch touches `agent_fleet/restate_analyst/main.py`.
- A second `/act` gate would add nothing. Once the row carries `risk_acceptance_medium`, the existing gate refuses both `approved` (422 `invalid_decision_for_kind`) and a blank `accepted`.
- Not built, per "verify a dispatch's premise".

## 2. Bigger than the reason: the decision never reached SafetyAcceptance

**Restate**, for key `risk-acceptance-HAZ-1003-medium`:
- `SafetyAcceptance/.../run` is **suspended**: still waiting on its human.
- `BPMNWorkflowRunner/.../approve` is **completed**: a different service, under the same key.

**Gateway log at the act:** `workflow resume non-200: task_id=acceptance wf=risk-acceptance-HAZ-1003-medium code=403`, twice, then `POST /human_tasks/acceptance/act 200`.

**Cause** (`src/iagent/gateway.py`, the generic resume after `mark_task_resolved`):
- Every non-special-cased kind is resumed at a hard-coded `BPMNWorkflowRunner/{wf}/approve`.
- That handler refuses 403 "no audience journalled" because the audience lives in `SafetyAcceptance`'s state, not `BPMNWorkflowRunner`'s.
- `SafetyAcceptance` has no approve handler.
- **No test covers act → SafetyAcceptance:** `git grep` finds no test pairing `SafetyAcceptance` with `/act` or approve.

**Fail-open ordering:**
- `/act` marks the projection resolved **before** the resume, and returns 200 when the resume fails. The only sign is `workflow_resumed: false`.
- The task has therefore left bob's queue while its workflow waits forever: a dead task. That is the same park the register route was written to refuse.

**The governance upside:** no acceptance was recorded downstream. The reason-less "approved" exists only in the projection, and the workflow that would act on it never received it.

## 3. Decisions and owners needed

1. **Resume routing:** the resume must reach the workflow that holds the promise. Either `SafetyAcceptance` gets an approve handler, or `/act` routes by the workflow's own service. The choice is yours. Whichever it is, seal act → SafetyAcceptance end to end.
2. **Order and status at `/act`:** recommend that the projection resolves only after the workflow accepts the decision, and that a failed resume answers non-2xx with the row left pending. A 200 with `workflow_resumed: false` reads as success (see the cortex packet).
3. **The kind fix (1b):** the worker's, in roll #12.
4. **The HAZ-1003 row, after 1–3:** a human resets it to `pending` so bob acts again with a reason. The workflow is still suspended, so nothing downstream needs undoing. I have not written it.
5. **Latent, `task_id` is not unique.**
   - Engine-a registers the definition's step id (`acceptance`, `approve_promotion`), and `mark_task_resolved` updates `WHERE task_id = %s AND status = 'pending'` across every workflow.
   - Live today: 1 `task_id` spans 2 workflows (`approve_promotion`), with 0 pending.
   - Two hazards awaiting acceptance at once would be resolved together by one act. Unexercised.
