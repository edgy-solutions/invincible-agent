---
title: fromMaintenanceBridge.ts names the case: retire it when a case is served
feature: workflow-socratic
lane: cortex-ui/master
repo: cortex-ui
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: Chris 2026-11-06: board item for fromMaintenanceBridge.ts; architect 10-30 standing rule: code names the mechanism, config names the case
updated: 2026-11-07
---

Cortex's 11-05 check of the case panel (`src/archetypes/workflow-case/`) for ADR-0065's resolution case found the card itself names no case. Options, labels, stages and approvers are all read from the served payload or the task declaration. The one file in the package that does name a case is `fromMaintenanceBridge.ts`:

- At `:26`, `workflow_definition_id === "maint_fault_propose"` attaches the transcribed `MAINT_FAULT_PROPOSE_DEFINITION`, imported at `:12`. That's a branch on a workflow id, where the rule wants a row.
- It projects the `maintenance_bridge` wire (`f2fe2d2`, 2026-10-06) as a stopgap. Its header says to swap to Lane 1's `/cases` route when that is served.
- Only tests reach it. Its two importers are `fromMaintenanceBridge.test.tsx` and `rawFields.test.ts`, and other mentions are comments. No runtime path reaches it, and a served resolution case never passes through it.

**Done when** a case is served on a route the card reads. At that point the file, its fixture `fixtures/maintenanceBridge.ts`, its test and the bridge mirror's parity arms are deleted, or kept only if some served wire still needs them, as a definitions table keyed by id rather than a branch. The parked condition is the served case route. Nothing is drawn wrong today.

The serving side is Lane 1's `GET /cases/{id}`, edgy-solutions/invincible-agent#283. It merged at `de9f5fee` and is in the 0.4.81 cut (`f08217b2`), which is not yet rolled. The item unparks when that route is live in the sandbox.

Lane 1, 2026-11-07: 0.4.81 rolled to the sandbox as `iagent` rev 228, and fin's live check passed at 22:27Z. The route is live, so this item unparks. Its status is cortex's to move.
