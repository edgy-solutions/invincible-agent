to: invincible-agent/seat/architect
from: invincible-agent/lane/perf
re: Phase 1a, what the code says about tracing, before any trace has been read

# lane/perf: Phase 1a static census

Read from `origin/master` at `17007300`. **The hop table is a reading of the code, not a
measurement.** No answer trace exists to open (see "Measured 2026-11-09" below), so none of this
counts toward the Phase 1 acceptance, and a "none found" means a grep came back empty. Of the leaf
`provenance_telemetry`, only its flush behaviour was checked.

## Two terms in the brief do not match the code

1. **`hops` is not on `data_provenance`.** `data_provenance` is a banner string
   (`agent_fleet/finance_agent/main.py:901`, `cortex-ui/.../flow-decomposition/contract.ts:110`).
   A grep over `agent_fleet`, `src`, `schemas` and `baml_shared/baml_src` finds no `hops` on it.
2. **The footer's "4 hops" counts artifacts, not engines.** `cortex-ui/src/lib/answerElapsed.ts:67-93`
   walks the artifact lineage chain (capped at 8) and sums each producer's own `duration_ms`.
   So "7m 35s · 4 hops" is four artifacts' summed work. It deliberately excludes the time a person
   spent deciding, so it is not a wall clock.

Both need settling before the taxonomy is written:

- What should `hops` count once it is derived from span names?
- For the ≥95% acceptance on a multi-artifact answer, is the denominator each artifact's own
  duration, or first request to final render?

## Propagation is not `traceparent`

There is no `traceparent` anywhere in `agent_fleet` or `src`. The fleet forwards an `X-Trace-Id`
header, and each engine seeds its Langfuse trace id from it
(`create_trace_id(seed=...)`, `agent_fleet/restate_analyst/main.py:1236`). That puts the spans in
one trace. It carries no parent span id, so a flat waterfall is the expected shape. **That is a
prediction to check on a real trace.**

## Hop by hop

| hop | in the code | status |
| --- | --- | --- |
| cortex request id | the gateway reads `X-Trace-Id` (`src/iagent/gateway.py:11684`) | the minting side in cortex-ui not read |
| BFF | forwards the id; no `@traced` / `observe_span` / `observed_trace` in `gateway.py` | **no span found** |
| supervisor | forwards the id (`src/iagent/defs/dynamic_supervisor.py:1580`); none of those three forms | **no span found** |
| restate_analyst | replay-safe boundary, `smolagents_*_execution`, `mem0_context_retrieval` | spans exist |
| Restate queueing | no span at invocation or journal level | **no span found** |
| discovery tool to engine | forwards the id (`orchestrator/discovery.py:85,130`) | forwarded |
| ontology_service, presentation_agent, weaviate_expert | `observed_trace` boundary | spans exist |
| neo4j_expert | `safe_observe` on execution and mem0 retrieval | spans exist |
| data_analyst | reads `X-Trace-Id` and has telemetry wiring; span form not read | to confirm on a trace |
| finance_agent, cost_agent, safety_agent, planning_agent, repository_agent, graph_host, datahub_wrapper | no span form and no `X-Trace-Id` | **no span found** |
| docs_agent | one `X-Trace-Id` mention, in a docstring (`reads.py:91`); no span form | **no span found** (ask-the-manual path) |
| LLM via smolagents and LiteLLM | `litellm_metadata` joins generations to the trace (`restate_analyst/main.py:1233-1241`) | present for the analyst |
| LLM via BAML | one `baml_py.Collector`, at `neo4j_expert/service.py:1009` | tokens and latency for other BAML calls: **none found** |
| Neo4j, Weaviate, Jena, Postgres, MinIO | the only retrieval spans are the two mem0 ones | **no store span found** |
| broker ticket | not censused; the broker is in dag-tools | not checked |
| render | presentation boundary only; cortex-ui not censused | not checked |
| flush before return | no `.flush()` / `.shutdown()` in `agent_fleet`, `src` or the `provenance_telemetry` leaf | **none found**; export depends on the SDK's background batch. `data_analyst/main.py:228` records a killed pod losing its unflushed batch |

The `0` X-Trace-Id counts behind the engine rows are by file. `src/iagent/direct_dispatch.py`,
`workflow_runner.py`, `dispatch_driver.py` and `socratic_elicitation.py` also show zero. Whether
each sits on an answer path is still to be established.

## LLM endpoint

Sandbox's base values route smolagents straight to Ollama (`SMOLAGENTS_PROVIDER: ollama`, model
`gpt-oss-128k:120b`). The LiteLLM proxy appears only in a rehearsal overlay. A `kubectl get deploy -A`
filter found no Prometheus, Grafana or DCGM deployment; it covered Deployments only.

Measured from the engine-a pod on 2026-11-09, one sample, with no answer known to be running:

- Ollama reports version 0.34.2. The configured base URL ends in `/v1`, so the native API is on the
  server root.
- `/api/ps` returns `name`, `model`, `size`, `digest`, `details`, `expires_at`, `size_vram` and
  `context_length` for each loaded model. Both loaded models have `size_vram` equal to `size`.
- `/api/ps` has **no in-flight count and no queue depth**, and no GPU utilisation.
- `/metrics` and `/health` return 404.

Still to check: whether `/api/ps` gains any field while a request is running. Sample it during a
live answer. If it does not, queue depth and GPU utilisation can only come from the GPU host itself.
Host access is not granted, and that decision is held for Phase 2.

## Measured 2026-11-09: no answer trace is reaching Langfuse

> **Corrected 2026-11-09** in `2026-11-09-report-perf-census-redone-on-provenance-telemetry.md`. The v1
> `/api/public/traces` list read here is lossy. `/api/public/v2/observations` shows 12 traces, all from doc-tools,
> and the newest is 2026-10-28T00:43Z, not 10-24. This census also missed the provenance-telemetry leaf's
> callers.

The lane now reads with its own dedicated key (Chris's ruling: exec in engine-a was the stopgap and
is retired). That key authenticates against project `iagent`.

- `/api/public/traces` over the whole project returns **8 traces**, every one named
  `sustainment extraction`, oldest 2026-10-10, newest 2026-10-24.
- None has the name or input of an answer. Neither "add a new engine" nor "p_cage" matches, so
  **the two screenshot traces do not exist in this project**.
- The sandbox engines hold a different key pair, and Langfuse rejects it (below).

Not established:

- When emission stopped. The 2026-10-10 floor may be a retention limit; that is unverified.
- Whether another Langfuse project ever received these traces. The lane's key sees only `iagent`.

Consequence: until the sandbox engines hold a valid key, any trace-based work here has nothing to
read. Phase 1's acceptance cannot start, and the instrumentation PRs cannot show a before/after
waterfall.

## The engines' key, as read from engine-a on 2026-11-09

- `GET /api/public/traces` and `GET /api/public/projects` both return 401, with the message
  "Invalid credentials. Confirm that you've configured the correct host."
- `LANGFUSE_HOST` is `https://cloud.langfuse.com`, and `/api/public/health` returns 200 there.
- Both keys are 42 characters with the expected prefixes and no stray whitespace
  (public `sha8=3b4c09de`, secret `sha8=d323e019`).

The engine-a log over 48 h has 19 lines and none mention the exporter, so a refused export leaves no
visible trace in the pod's log. No other credential or Langfuse region was tried with this key.

## Measured 2026-11-10: the key is fixed, and the answer path is uninstrumented

The architect confirmed the credentials: EU host, 42-byte keys, project `iagent`. Lane 1 restarted
every Deployment between 01:04Z and 01:06Z.

"how do I add a new engine" was asked twice as `agent-user` (domains `DATA_ENGINEERING`, `DOCS`,
`MESH`): sessions `perf-4c5975cd` at 00:50Z (82.5 s) and `perf-2043b0b5` at 01:07Z (75.5 s).
Langfuse received no trace from either, polled for five minutes after each.

The path, read from the pods' timestamped logs for the 01:07Z run:

1. cortex-bff `/orchestrate` launched Dagster run `37f1cfbc` (`supervisor_query_job`) on
   `dagster-user-code`. Each step (`create_task_plan`, `execute_subtask[task_0]`, ...) ran in its
   own subprocess under the multiprocess executor.
2. `execute_subtask` called `engine-docs` `/explain` twice, at 01:08:38Z.
3. engine-a (restate_analyst) logged nothing in the window. **This question never reaches the
   analyst.**

None of the BFF, the supervisor or `docs_agent` has a span (table above), so nothing on this path
could emit. Because each Dagster step is a subprocess that exits, a step span also needs an explicit
flush, or its batch is lost.

Separately, both runs' final payloads carried only "No content available." in `markdown_content`
(21 characters). That is not the 7m35s answer from the screenshot, so these runs are not a timing
baseline. Whether the docs engine returned nothing or the card shape differs is not yet read.

## Next

1. Phase 1b PR 1, reviewed by Lane 1: `baml_shared/span_taxonomy.yaml`, a `bff.orchestrate` root span,
   one `supervisor.<step>` span per op with a flush, and `traceparent` from the BFF through the run
   config to the engine POSTs.
2. PR 2: `docs_agent` reads `traceparent` and opens its `/explain` span.
3. Prove it with one trace in the UI, then fan out to the other four questions' paths.
