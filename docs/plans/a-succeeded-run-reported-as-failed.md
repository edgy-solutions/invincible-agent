---
id:         a-succeeded-run-reported-as-failed
status:     open
owner:      lane 1 (supervisor / BFF queue) — HANDED OVER, not diagnosed further
blocked-on: lane 1
repo:       invincible-agent
ruled-by:   ADR-0038 (telemetry as provenance projection)
code-site:  src/iagent/gateway.py (the /interview/stream UI-payload fetch and its budget), src/iagent/defs/dynamic_supervisor.py (supervisor_query_job)
summary:    TWO ITEMS, ONE OBSERVATION, handed to lane 1. (1) A FALSE RED, which is the worse direction: `supervisor_query_job` logged RUN_SUCCESS while the stream had already emitted `pipeline_error dagster_run_failed` and `ui_payload_timeout` to the user. A run that succeeded was reported as failed, so the instrument disagrees with the system in the direction that manufactures phantom bugs. (2) THE LATENCY ITSELF: measured 5m06s, 5m23s and 6m37s for single finance questions, against a BFF budget shorter than any of them. That is the demo's ceiling and nobody has profiled where it goes.
---

# A run that succeeded, reported to the user as failed

## What was measured

2026-09-02, single questions through `/interview/stream` as alice. The stream ended:

```
event: pipeline_error
data: {"message": "Pipeline failed.", "kind": "retrieving", "retryable": false,
       "cause": "dagster_run_failed"}
event: pipeline_error
data: {"message": "Timeout or failed to fetch UI payload.", "kind": "composing",
       "retryable": true, "cause": "ui_payload_timeout"}
```

The same runs, in Dagster:

```
ENGINE_EVENT  Multiprocess executor: parent process exiting after 5m23s
RUN_SUCCESS   Finished execution of run for "supervisor_query_job".
```

```
ENGINE_EVENT  ... after 6m37s      RUN_SUCCESS
ENGINE_EVENT  ... after 5m06s      RUN_SUCCESS
```

**The runs succeeded. The user was told the pipeline failed.**

## (1) The false red is the worse direction, and it is worth stating why

A missed failure costs you an unnoticed bug. **A manufactured failure costs you a search for a bug
that does not exist** — and it spends the credibility of every other signal from the same
instrument. During this session's diagnosis, `dagster_run_failed` was initially read as a genuine
pipeline fault and cost a detour before the logs showed `RUN_SUCCESS`.

Note also that `cause` is asserted with confidence: `dagster_run_failed` is a claim about the run,
not about the fetch. The honest cause for the first event is the same as the second — the client
stopped waiting. **One of these two events is a fact and the other is an inference stated as a
fact**, which is the same shape as `rejected: []` reporting one of two refusal kinds under a name
that reads like both.

## (2) The latency, unprofiled

Three single-question runs: **5m06s, 5m23s, 6m37s.** Known contributors from the same logs, none
measured for share:

* `fill_slots` against engine-o hits its 20s client budget and is abandoned
  (`[[a-mandatory-slot-does-not-refine]]`) — 20s of pure waste on every finance question, and the
  answer arrives anyway, unread.
* `synthesize_stateful` attempts Engine B on every run and fails DNS resolution
  (`iagent-engine-b.sandbox.svc.cluster.local` — the engine is `enabled: false` in sandbox), then
  swallows it by design. Cost unmeasured; it is a resolution failure rather than a connect
  timeout, so probably small — but it is per-run.
* Multiple sequential LLM calls (ground → classify → fill → answer).

**Nobody has profiled it**, and the step timings are already in the Dagster event log, so the
profile is a read rather than an instrumentation project.

## Not diagnosed further here

Both belong to the supervisor/BFF lane. Recorded with the evidence attached so the next person
starts from measurements rather than from the symptom — and specifically so that
`dagster_run_failed` is not trusted as a cause by whoever sees it next.

## Related

* `[[a-mandatory-slot-does-not-refine]]` — the 20s budget, which is both a latency cost and a
  correctness bug.
* `[[a-fallback-that-absorbs-every-failure-reports-none]]` — the other instance this week of a
  surface reporting less than the system knew.
* `[[a-registration-is-not-a-reachable-call]]` — the standing family: a green signal at a layer
  above the one doing the work.
