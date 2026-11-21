# Census: HumanTask producers and where `task_id` comes from (lane/saf, 2026-11-16)

Question: can `task_id` be made required on the ingest `HumanTask` model
(`src/iagent/ingest_api.py:493`, `task_id: str | None`)? Measured on master 55c720ef, `git grep` over
`src/ agent_fleet/ sql/ policy/ helm/`, plus `iagent-mesh-sdk` and `cortex-ui`.

## Verdict

1. `HumanTask` in `ingest_api.py` is a RESPONSE row of the caller's queue (`GET /me/human_tasks`), not a
   producer's input. It is declared only in this repo. `iagent-mesh-sdk`: zero matches for `HumanTask`
   or `task_id`. `cortex-ui`: consumes the generated `src/api/generated/bff.ts`, where `task_id: string`
   (non-null) at every occurrence listed (lines 13, 23, 31, 42, 61, 345, 356, 437). Nothing to hand to the SDK lane.
2. The column cannot hold NULL: `sql/create_human_task_projection.sql:43` `task_id TEXT NOT NULL`.
3. The one write path, `human_tasks.register_task` (`src/iagent/human_tasks.py:624`), takes
   `task_id: str` (keyword-only, required), and the HTTP door's body `HumanTaskRegisterRequest.task_id: str`
   (`src/iagent/gateway.py:1226-1231`) is required too. A request without it is a 422 before any row exists.
4. So every producer below supplies a non-empty string, and `str | None` on the response model is
   looser than every layer under it. Tightening to `task_id: str` loses no row. The one caveat is
   an EMPTY string: nothing checks `min_length`; the sources below are all derived (never user-typed
   empty) except the workflow-definition `task["id"]` (row 9), which is whatever the BPMN/UserTask
   definition names. I did not census the live table; do that (`SELECT count(*) ... WHERE task_id = ''`)
   before the tightening ships if it is to be belt and braces.

## Producers (every caller of `register_task`, and every HTTP poster to it)

In-process, `src/iagent/gateway.py` (all call `human_tasks.register_task`):

| # | site | kind | `task_id` source |
|---|------|------|------------------|
| 1 | gateway.py:1520 (`POST /internal/human_tasks/register`) | request's `req.kind` | `req.task_id`, required `str` in the body model (1226) |
| 2 | gateway.py:1585 (access request) | `access_request` | line 1582: `"access-" + uuid4().hex[:10]` |
| 3 | gateway.py:1689 (triage / extraction refusal) | `extraction_refusal` | line 1682: `req.task_id or ("triage-" + sha1(subject_ref)[:12])` |
| 4 | gateway.py:6421 (extraction defect from a review finding) | `defect["kind"]` | `defect["task_key"]` (derived key; `task_exists(task_key)` checked at 6419) |
| 5 | gateway.py:15616 (document promotion) | `promotion.KIND` | `_promotion_task_id(ingest_id, generation)` (15433): `document_promotion:<id>[:g<n>]` |
| 6 | gateway.py:15702 (empty-extraction confirm) | `EMPTY_CONFIRM_KIND` | line 15694: `_empty_confirm_task_id(ingest_id, attempt)` -> `<kind>:<ingest_id>:a<n>` |
| 7 | gateway.py:15777 (extraction defect, steward says parts exist) | `extraction_defect` | line 15772: `f"extraction-defect:{ingest_id}:empty-a{attempt}"` |

Over HTTP to `/internal/human_tasks/register` (these all land on row 1):

| # | site | `task_id` source |
|---|------|------------------|
| 8 | `agent_fleet/restate_analyst/dispatch_driver.py:240` (pcn dispatch) | payload line 195: `task["task_key"]` (also sent as `task_key`, line 196); key is `resolution.idempotency_key` (`dispatch_plan.py:108`), notice x part |
| 9 | `agent_fleet/restate_analyst/main.py:1761` (`_register_human_task`, user_task / grouped review) | line 1712: `task_id = task["id"]` (the workflow definition's task id); sent as `"task_id"` (1724). KeyError if the task has no `id`, so never None |
| 10 | policy workflow `direct_call` to `publish_endpoint` (`workflow_definition.py:349`; `policy/workflows/promote_answer_artifact.yaml` step `publish_artifact`) | the step's own bound body; the request model requires `task_id`, so a definition that omits it is a 422 at the door (not a row with NULL) |

Not producers: `/internal/human_tasks/expire` (`gateway.py:1553`) takes `task_id: str` and only retires rows;
the sensor in `src/iagent/defs/extraction_review_sensor.py` files through the BFF, not a second writer.

## What I did not do

- No live-table count of empty-string `task_id`s (needs the cluster; Chris's call).
- Row 10 is read from the endpoint config and the request model, not from a run of the workflow.
- The change itself (`task_id: str`, regenerate openapi, cortex-ui types already non-null) is not made;
  it sits with whoever owns `ingest_api.py` (gov / the ingest-v1 lane).
