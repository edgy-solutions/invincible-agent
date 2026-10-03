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
| `content_kinds/` | `maintenance-fault-event` -- this lab overlay STANDS IN FOR OpenDDIL's own content-kind overlay (ADR-0021/0041 §4, SDK 0.9.7 `branch: event`); a deployment replaces it with OpenDDIL's real registration directory |

The S1000D vocabulary 7f registers lands in this same overlay.

`maintenance-action-record` (branch `document`, same `maintenance-bridge` domain) is NOT
registered here: no file in this repo gives its `passes`/`outputs` values, and the SDK validator
requires both non-empty for a `document` branch row. See the ingest/origin seam report
(lane/01-seam) for the gap.
