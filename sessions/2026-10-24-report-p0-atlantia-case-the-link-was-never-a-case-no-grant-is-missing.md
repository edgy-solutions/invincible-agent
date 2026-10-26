to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-24
re: P0, operator.atlantia "no case that you can see" on /case/d1a7ee0b-040f-5eab-b573-0aab1d245abc
relay: Chris

This report carries no secret and no infra detail.

# The link was never a case, and no grant is missing. The fix is a fresh case from OpenDDIL's intake, on another asset or fault

Chris approved four live reads tonight: the task projection rows, Topaz, one runner read, and a brokered login as atlantia. Each ran once. No writes.

## 1. The case's tasks
- **`d1a7ee0b-040f-5eab-b573-0aab1d245abc` does not exist.** It has zero task rows, no runner state, and no `run` invocation. Its only invocations are two `case` reads at 03:35Z and 03:37Z on 10-24, which match the BFF's two 404s on that path.
- The id is spliced. `d1a7ee0b` is the first group of the real case. `040f-5eab-b573-0aab1d245abc` is the tail of `c18ecb64-040f-5eab-b573-0aab1d245abc`, an id OpenDDIL's poller sends to `/cases/{id}/action` (116 requests in 72 h, all 403).
- **The real case is `d1a7ee0b-01f1-5028-9ffe-876d6e8f02d2`.** It is 1008 / tr_module / MRAD-ARR-0417, opened 2026-10-20 04:37Z, state `maint_fault_escalate`, `terminal: null`. Its tasks:

| task | audience | recipients | status | acted |
| --- | --- | --- | --- | --- |
| `~1:decide` (maint_fault_approval) | `maint_fault_approval:edge-01` | bob only | pending | nobody |
| `~2:escalation` (maint_escalation) | `maint_escalation:edge-01` | bob only | pending | nobody |

- **Not decided. Escalated by its 4-hour deadline at 08:37Z on 10-20, not by a walk.** No walk this week acted on it.

## 2. atlantia's groups and the grant
- She is a member of `maint-approvers-edge-01` and `openddil-maintainers`, and holds the `mesh:s1000dFaultWalk` invoker capability.
- **The group exists as `maint-approvers-edge-01`, not `maint-approvers`.** It is the only group granted `maint_fault_approval:edge-01`.
- The audience resolves today to her, liaison and bob. `can_act` for her is True.
- **Her identity matches.** I signed in as her through the broker, and `/me/entitlements` gave `authz_id` `11111111-1111-4111-8111-111111111111`, the id every grant names. She is offered MECHANIC·MAINTENANCE.
- **Nothing to fix in the grant.**

## 3. The visibility rule
- **"Holder" includes a pending task she has not opened.** `holds_task_on_case` matches any row with her `recipient_id` and that `case_id`, at any status. That is the rule as you require it.
- **But the rows are written once, when the task is filed, for whoever is in the audience at that moment.** On 10-20 the audience was bob alone. Her membership arrived between 10-20 08:37Z and 10-22 03:43Z: our own test cases filed on 10-22 already list her. So on `d1a7ee0b-01f1` she holds no row, and the case read is a 404 for her too. I measured this through the broker: both ids answer 404.
- **This is a gap in the rule, not in this case.** A grant added after a task is filed never reaches that task: not its queue, and not the case view. That is for you to rule on. I have built nothing for it.
  - Option A: `holds_task_on_case` also admits a current `can_act` on the audience of any open task on the case.
  - Option B: a re-resolve step writes the missing recipient rows when an audience's membership changes.

## 4. What I did
- **A fresh case. Not a grant fix, and not a re-send of 1008.**
  - The trigger dedupes on `event_id`, and it attaches any event with the same `[asset_id, fault.item, fault.fault_code]` to the open case (`policy/overlays/openddil-lab/triggers/maintenance_fault.yaml:9-14`).
  - So a re-send of 1008, or a new event for the same asset and fault, lands on `d1a7ee0b-01f1`: the case she cannot see.
- **The packet to OpenDDIL** asks for a fresh event with a new `event_id`, on an asset or fault code with no open case. The case id is that `event_id`. `sessions/2026-10-24-packet-to-openddil-the-link-is-not-a-case-send-a-fresh-event-on-another-asset.md`.
- **No roll was needed.** By noon, the deliverable is the fresh case id, once OpenDDIL sends it.

## 5. Seen on the way, not acted on
- **`d1a7ee0b-01f1~1:decide` is still `pending` in bob's queue,** although its instance timed out and the case moved to escalation. A queue entry that cannot be acted on.
- **OpenDDIL polls `/cases/d1a7ee0b-01f1-…/action`:** 1673 requests in 72 h, all 404 `no_action_record`. That answer is correct until the case is released.
- **The open case blocks a clean case on 1008 / MRAD-ARR-0417 until it is closed.** Closing it is acting on d1a7ee0b, and I have not.
