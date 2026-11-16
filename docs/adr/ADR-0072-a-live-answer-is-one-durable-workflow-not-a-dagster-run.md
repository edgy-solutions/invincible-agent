# ADR-0072 — A live answer is one durable workflow, not a Dagster run

**Status:** Proposed (Lane 1 and lane/perf, 2026-11-14). The prototype is #396, behind a flag that
defaults to today's path. Nothing is rolled, and no answer has run on the new path.
Sections 3 and 8.1 were ruled by the architect on 2026-11-15 (via Chris); the rest is still proposed.
**Date:** 2026-11-14
**Deciders:**
- the architect, for the decision and the open questions in section 8;
- Chris, for the measurement window and the roll;
- lane/perf, who wrote the design and the prototype; Lane 1, who owns the chart half.

**Related:**
- ADR-0071 (#384, Proposed, not yet on master): a directory client is built once per process.
  The BFF's CPU budget is the reason the new service does not run inside the BFF (section 3).
- [ADR-0038](ADR-0038-telemetry-as-provenance-projection-langfuse-standard.md): telemetry as a
  provenance projection. The trace is the run record here.
- #391: the Dagster run limits. Their `iagent` tag row today counts answers and ingest together
  (section 7).
- #388: the failed-run card bug. Section 8.1 records its ruling.

## Context

Each live answer is one `supervisor_query_job` run on Dagster today:
1. The BFF's `/interview/stream` asks engine-o to route the question.
2. It launches the run through Restate's `DagsterRunTracker` and GraphQL `launchRun`.
3. The run waits in the run queue, then a fresh run-worker process starts.
4. Each step forks its own process: `create_task_plan`, then `execute_subtask` once per engine,
   then `synthesize_stateful`, `generate_ui_payload` and `assert_every_engine_answered`.
5. The BFF polls the run and its events once a second, and reads the card from
   `generate_ui_payload`'s output metadata.

**Measured on 0.4.88**: ten sequential answers to one question, by lane/perf on 2026-11-15, from
logs, because the 0.4.88 spans did not export.

| stage | median (s) |
| --- | ---: |
| queued (run created → run started) | 9.5 |
| launch (started → first step) | 6.3 |
| gaps between steps | 8.0 |
| engine time (spans) | 34.8 |
| **total** | **78.3** |

So the run queue, the launch and the gaps take about 24 s of a 78 s answer, and none of it is
engine work. The queue is also shared: Dagster's `max_concurrent_runs` is global, so an ingest
holds a slot that an answer then waits for.

## Decision

### 1. Scope
**Only live answers leave Dagster.** `supervisor_query_job` stops being the live answer path.
Ingestion, ontology loads, assets, batch, `start_review_job` and the BPMN jobs stay on Dagster.

### 2. One answer is one Restate workflow
- **The workflow** is `SupervisorAnswer`, keyed by an `answer_id` the BFF mints. `answer_id`
  takes the place of `run_id` everywhere an answer is keyed: the identity vault, the token
  redemption, logs and spans.
- **Its `run` handler** runs the five supervisor ops **unchanged**, in Dagster's stage order. The
  subtasks run in parallel, and so do synthesis and rendering. Each step is a `ctx.run` with one
  attempt, matching Dagster's no-retry.
- **A shared `snapshot` handler** serves status, events, step statistics and the payload in one
  read, while `run` is in flight.
- **The ops are not rewritten.** A context adapter, `RunlessOpContext`, gives them what they use
  from Dagster's context: the step key, the mapping key, `run_id`, `log_event` and
  `add_output_metadata`. It records materializations in the shape the BFF already projects, so
  cortex sees the same SSE events.

### 3. It runs as its own Deployment
**Ruled 2026-11-15:** the answer service is hosted as its own Deployment in the chart.
- **The Deployment** is `iagent-supervisor`, on the control-plane image that cortex-bff runs, with
  one replica. It is behind `supervisorService.enabled`, and it registers with the Restate admin
  the way the engines do.
- **Its env** is dagster user-code's, since it runs the same ops.
- **Why not inside the BFF:** the BFF's CPU is already the entitlements bottleneck (ADR-0071), and
  an answer that crashes or runs out of memory would take the door down with it.
- **Why not inside engine-a:** a different image and dependency set.
- **What it saves:** the service imports once at pod start. The per-run import (about 3.6 s) and
  the per-step fork go away.

### 4. The BFF chooses the path per request
- **The flag** is `IAGENT_ANSWER_PATH`, `dagster` (the default) or `durable`. It is read per
  request, so a values change switches it with no image change. Any other value logs a warning
  and answers on `dagster`.
- **On `durable`,** the BFF sends `run/send` and reads one `snapshot` every 0.25 s, with the same
  15-minute ceiling. Today it makes two GraphQL reads a second.

### 5. Backpressure moves into the service, and it is a condition of the default
The run queue is today's only limit on concurrent answers. Restate does not limit concurrent
invocations of a service for us, so on `durable` nothing does.

**The rule:**
- `durable` may run **only in a declared measurement window**, one answer at a time, until the
  service has an admission limit.
- The limit is a FIFO semaphore of K concurrent answers. K starts at 2, the `iagent` tag row's
  value. Past a wait ceiling, the service answers "busy", and the BFF emits it as an error event.
- **The limit counts once per replica,** so the one-replica rule in section 3 is part of it.
- **#396 does not have it.** It is the change that must land before `durable` becomes a default.

### 6. The trace is the run record
- The spans are the ones `step_spanned` emits on Dagster, with `supervisor.run` as their parent.
- A retried step emits a second span with its attempt number, so the trace shows retries.
- **The Decision Map is drawn from the span tree** that the workflow holds in its state, served by
  the BFF. It is not read back from the trace store: export there is asynchronous, and work's UI
  may not reach the store. Both share span ids, so they agree. The map change belongs to cortex.

### 7. What is lost, and what replaces it
| lost | replaced by | gap |
| --- | --- | --- |
| Dagster's run page: timeline, step logs, materializations | the trace; the Restate invocation journal; pod logs tagged `answer_id` and `trace_id` | no one page shows logs and materializations together |
| re-execute from the UI | a re-ask, under a new `answer_id` | **re-execute from a chosen step is not replaced** |
| the run queue as backpressure | the admission limit (section 5) | none, once it is built |
| run monitoring (start timeout, max runtime) | the service's timeouts and the BFF's 15-minute ceiling | none |
| run history, searchable by tag | the trace store, by user, session and tag; Restate's retention | retention follows Restate and the trace store, not Dagster |
| the `pipeline_stage` HUD from step stats | the adapter's step records, with the same step keys | none |

**#391's `iagent` tag row** then counts ingest only. Its value is re-read after the measurement,
not before.

## Consequences
- **One more Deployment and one more Restate registration.** They roll on their own, and never
  roll the fleet.
- **`restate-sdk` moves into the main dependencies**, because the control-plane image installs no
  extras. That needs an image rebuild.
- **An answer is no longer visible in Dagster.** Section 8 asks whether a completion event should
  be recorded there.
- **The flag defaults to today's path.** Merging #396 and rolling the chart changes nothing until
  the flag is set.

## The measurement that decides it
- **Set `durable`** on cortex-bff for one declared window, under the roll lock.
- **Run** the ten questions of the 0.4.88 pass, sequentially, measuring the same stages:

  | stage | Dagster | durable |
  | --- | --- | --- |
  | queued → started | run created → `RUN_START` | `run/send` accepted → the handler's first line |
  | started → first step | `RUN_START` → `create_task_plan` | handler start → `create_task_plan` |
  | gaps | step stats | the adapter's step records |

- **Then set it back to `dagster`,** unless the architect rules otherwise.
- **Verify the two points the prototype could only infer:**
  1. that `snapshot` serves the live view while `run` is in flight;
  2. that one replica holds the live view.
- **Estimate the work cluster** from Chris's three work timings substituted into this breakdown.
  Label it an estimate, with its assumptions stated. Report any concurrency result separately.

The decision to make `durable` the default rests on that report and on section 5's limit.

## 8. Open questions (named, not decided here, except 8.1)
1. **The failed-run card (#388). RULED 2026-11-15:** "On a failed run the BFF delivers a failure
   card naming the step and the trace id; it never stays silent."
   - **The defect it closes:** `assert_every_engine_answered`'s docstring says the BFF still
     delivers the card on a failed run. It does not: the stream stops on `FAILURE` and never
     fetches the card. The durable path keeps the card on a failed snapshot.
   - **What the ruling requires, on both paths:** the card names the step that failed and the
     run's trace id (section 6: the trace is the run record).
   - **What it forbids:** a failed run that ends the stream with no card.
   - **The seal it needs:** a run made to fail at a named step yields a card carrying that step
     and the trace id. A control is the same run succeeding. Mutation: drop the card on `FAILURE`,
     and the seal fails.
2. **A completion event in Dagster.** The workflow could report one runless `answer_record` asset
   event when an answer completes, off the critical path. Whether Dagster 1.12.20 accepts an
   asset outside the code location's graph is unverified. Wanted, or not?
3. **A replay endpoint.** It would resubmit a stored config under a new `answer_id`. Wanted now,
   or only when someone needs it?

## Alternatives considered (rejected)
- **Keep Dagster and tune it** (more run slots, a warm run worker, an in-process executor). That
  leaves the queue shared with ingest, and the launch still costs a process.
- **Run the supervisor inside the BFF.** Rejected in section 3.
- **Rewrite the ops without Dagster's context.** It is the larger change and the riskier one; the
  adapter keeps the op bodies byte-identical.
