# Census: every site that serves a person a task, on master 4fe860a3

Built against ADR-0068 as drafted on PR #347 at sha e2ae0272 (Status: Proposed). The ADR's build
list says it takes effect after ratification; the architect dispatched this build anyway.

Where recipients are expanded today: once, at registration. `_resolve_audience_actors`
(`src/iagent/human_tasks.py:168`) resolves direct `user` grants and `group#member` members one
level deep, and `register_task` calls it (`human_tasks.py:624`, `:699`), writing one
`human_task_projection` row per recipient. After that, nothing re-reads policy: a grant added later
reached no queue, and a revoked recipient kept the row.

After this PR the match runs at READ time in `human_tasks.viewer_tasks`: every stored row is a row
expanded from an audience (none is "named directly" outside policy), so each is re-checked with
`can_act_or_unavailable(audience, viewer)` on the read; capability holders are added from open tasks
that carry `excludes`. Rows with no recorded `excludes` (written before this change) are never
matched by capability and are re-checked like any expanded row.

## Fixed

| master file:line | site | now |
| --- | --- | --- |
| `gateway.py:1768` | `GET /me/human_tasks` (`list_tasks_for`) | `viewer_tasks`, label-scoped |
| `gateway.py:2232` | `get_review_batch` (`list_tasks_for`) | `viewer_tasks` via `_pending_for_actor`, label-scoped |
| `gateway.py:5876` | `_admit_named_on_case` task_holder (`holds_task_on_case`) | `viewer_tasks` + label gate on the NAMED person's cells |
| `gateway.py:6017` | act match (`list_tasks_for`) | `_pending_for_actor` |
| `gateway.py:6033` | act settled fallback (`get_task_resolution`) | same label gate; a failing label is the same 404 as no row |
| `gateway.py:12975` | `_load_viewable_case` holder admission | label-gated; a holder without the case's labels is refused |
| `gateway.py:13013` | `get_case` `approvals[].task` | fed by the viewer's own rows, label-scoped |
| `gateway.py:14052` | notice status read | answers anyone `_ingest_review_access` admits |
| new | `GET /me/queue`, `GET /me/needs_you` | viewer queue and counts, `on_behalf_of` by policy row |

## Unchanged, with the reason

| master file:line | site | reason |
| --- | --- | --- |
| `gateway.py:13013` (`list_tasks_for_workflows`) | chain status (decided_by, status) behind the case gate | supplies status only; the task payload comes from viewer rows |
| `gateway.py:5971, 14128, 14533, 15677, 15903, 16829` | `get_task_open_state` | reads by task id; serves no viewer's task |
| `gateway.py:6620, 6774` | `get_task_resolution` after the act gate | downstream of the act gate in the same request |
| `gateway.py:14128, 14533` | `_ingest_review_access` task_holder | already a read-time capability check; flagged to gov |
| `gateway.py:13881, 15123` | `ingest_status.get_status_for` (duplicate_of, submitter reads) | submitter-scoped ingest reads, not task reads |
| `gateway.py:~17735` | Electric shape | a shape predicate cannot evaluate labels; see PR body |
| `check_can_act` at act time | the act gate | still runs; the read-time re-check now also drops a revoked recipient from the list |

## Undecided

None.
