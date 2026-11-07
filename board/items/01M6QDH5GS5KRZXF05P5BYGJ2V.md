---
title: The can_decide:<workflow_id>.<option> rail for obsolescence resolution, validator only (ADR-0065 provisional)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#276]
ruling_ref: architect via Chris 11-06 (obsolescence as a process; gov's rails, validator only), and the rulings on #276's forks 1-3 (two rails; key per workflow; options on the decide step)
updated: 2026-11-06
---

The brief, verbatim: "Rails for obsolescence_resolution: roles (who may approve LTB / redesign) as groups + capability rows; `can_decide: <option>` rail with ratified_by: owner; contract files get a `classification` field validated against levels.yaml. Validator only until Lane 1's workflow row lands."

The rulings on #276's forks, verbatim:

1. "Two different acts, two rails: option_deciders.yaml says who may choose an option at a decide step; task_grants' approver audience says who may approve. A workflow row references both by name; neither derives from the other."
2. "Key per workflow now, not later: `<workflow_id>.<option>`. A generic option (archive) gets one row per workflow that offers it. Nothing reads the file yet, so there is no cost."
3. "Options live on the decide step of the workflow definition (`steps[id=…].options`, the SDK's WorkflowDefinition). The three hard-coded option lists retire when the runner reads the step — item for 74, after the Socratic bar work."

This item is the rail. It is modelled on the level rail (#268):

- `policy/option_deciders.yaml` has one row per workflow and option. Each row has `workflow`, `option`, `grant_to_groups`, `granted_by`, `reason` and `ratified_by` (a seat). The key is `<workflow_id>.<option>`.
- It ships empty. No workflow or option is named in code or in the seed.
- The grantor seed is `policy/grantors/option_deciders.yaml`.
- `validate_policy` checks the rail when it is present. It also refuses a `can_decide:` capability row, so the rail is the one home.
- Approvers stay on their own rail, the `task_grants.yaml` audience. Neither rail is read from the other.

What waits for a decide step that carries its options: checking that each option is one of its workflow's options, and one row per offered option. The pinned SDK's steps have no `options` field yet. Lane 74's part is item `01M6QHKVK50KZ10GJM77T5051F`.
