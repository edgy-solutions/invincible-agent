# openddil-lab overlay

SAMPLE — OVERLAY layer (ADR-0036). Invented in this repo; a deployment replaces the values.

The maintenance fault workflow for the OpenDDIL bridge (contract:
`sessions/2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md`), expressed as
data on the generic case runner (ADR-0039). Nothing in Python knows the words "fault", "spares"
or "S1000D": the trigger, the selection and chaining tables, the definitions, the option
templates, the task kinds and the stubbed walk verb are all here. The seed is unchanged.

| dir | what |
| --- | --- |
| `triggers/` | `maintenance_fault` -- a MaintenanceEvent opens a case keyed on `event_id` |
| `decisions/` | the selection table and one `after:` chaining table per definition |
| `workflows/` | propose, supervisor review, escalate, park, release |
| `task_kinds/` | the three human queues and their vocabularies |
| `verbs/` | `s1000d_fault_walk`, a declared stub until 7f Phase 2(e) serves the walk |

The S1000D vocabulary 7f registers lands in this same overlay.
