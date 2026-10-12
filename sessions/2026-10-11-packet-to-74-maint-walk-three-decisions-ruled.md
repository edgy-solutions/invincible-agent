# Packet: your three maintenance-walk decisions are ruled. Lane 1 lands the grants; the on_behalf_of code is yours

to: invincible-agent/lane/74
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-11
re: the three decisions you asked for, for the #15 maintenance walks

## The rulings (Chris, 2026-10-11)

**a. Who step 1 runs as.**
- Step 1 runs `on_behalf_of` the event's `dropped_by`.
- For OpenDDIL events, that is the delegate identity of client `iagent-openddil`, whose authz id
  is `svc:openddil`. That identity gets the fault-walk grant.
- **`svc:case-runner` never gets a verb grant.**

**b. Task grants go through groups in policy YAML, tier `edge-01`, and are then synced.**
- bob → maint approvers: `maint_fault_approval:edge-01`
- a sandbox maint persona → tier ack: `maint_tier_ack:edge-01`
- bob → supervisor review: `maint_supervisor_approval:edge-01`

**c. Test-persona tokens.**
- You may mint sandbox test-persona tokens from the demo passwords for the walk.
- Reports show a token's length and a hash prefix only.

## Who does what

**Lane 1: the YAML for (a) and (b),** on `lane/01-maint-walk-grants`, going into rev 187 before
the roll:
- `svc:openddil` is declared in users.yaml with no groups, and added to
  `mesh:s1000dFaultWalk`'s `grant_to`.
  - The derived-invokers seal allows it as a ruled service invoker.
  - That allowance is guarded: the invoker must be a service with no cell, it must actually be
    granted, and `svc:case-runner` must hold no `mesh:` grant.
- Three new actor groups:
  - `maint-approvers-edge-01` (bob)
  - `maint-tier-ack-edge-01`: alice, the MECHANIC/MAINTENANCE fixture user, as the sandbox maint
    persona. Erin and chris join it too, because the walkers must hold exactly alice's groups.
  - `maint-supervisors-edge-01` (bob)
- Three `task_grants` entries keyed `…:edge-01` that name those groups.
- The existing `…:ORG` entries are left in place.

After the roll, Lane 1 runs the grant sync.

**74: the code half of (a).**
- The case runner's step 1 must carry the event's `dropped_by` as `on_behalf_of`, and act as
  that identity's grant, not as `svc:case-runner`.
- I have not read your runner for this. If it already does so, tell me and this item closes.

## Two things to confirm before you walk

1. **The tier string.** The workflow audiences are `…:{trigger.owning_tier}`. The ruling names
   `edge-01`, and every grant before today names `ORG`. Before you count a refusal as a
   regression, check that the OpenDDIL events you walk carry `owning_tier: edge-01`.
2. **Alice as the tier-ack persona** is my choice, not the ruling's. The ruling says "a sandbox
   maint persona". If you had a different user in mind, say which.
