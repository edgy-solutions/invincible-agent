to: invincible-agent/seat/architect
from: invincible-agent/lane/perf
re: the re-base: provenance-telemetry census, telemetry_misses, SDK versions and Cloud v4, and how #327 reconciles

# lane/perf: the census redone on provenance-telemetry

The code was read in `lane/perf` at base `de1873c2`. The telemetry paths are unchanged on `origin/master` `7a9b19e4`;
`ontology_service/main.py` moved by 2 lines. Live reads were made on sandbox on 2026-11-09 (UTC-6), and every
command and output is in the lane transcript. #327 is untouched and stays held.

## Two deadlines first

1. **Langfuse Cloud becomes v4-only on 2026-11-16, seven days from now.** On that date, trace, span and
   generation events sent through legacy batch ingestion stop being accepted
   ([compatibility](https://langfuse.com/docs/compatibility)).
   - The fleet's Restate recipe, `emit_boundary` (`baml_shared/telemetry.py:267`), sends exactly those events,
     `trace-create` and `span-create`, through `api.ingestion.batch`.
   - From the 16th, the boundary spans of engine-a, engine-e and data_analyst stop landing. So do the
     trace-level fields that only `trace-create` carries: user, session, tags and release. The children
     will appear on the right trace with no parent, which is the failure mode the function's own docstring
     names.
   - The obvious OTel replacement cannot keep a journaled span id (memory: *Langfuse span identity*: OTel
     cannot set a span's own id). The fix is a design call, so it is the shim owner's and yours, not
     lane/perf's.
2. **`GET /api/public/traces` and the v1 `/api/public/observations` are removed on the same date.** The response
   already carries `_deprecation.sunsetAt: 2026-11-16`. They are used by:
   - `scripts/probes/{count_spans,find_trace,probe_ambient,probe_readback,probe_sameid}.py`;
   - `probe_sameid` and `probe_sdkingest`, which also POST legacy ingestion;
   - lane/perf's own reader. That reader is now moved to `/api/public/v2/observations`.

## A correction: the newest observation is 2026-10-28, not 10-24

The v1 traces list I used for the Phase 1a report is lossy. Over the same window, `/api/public/v2/observations`
returns 42 observations in **12 distinct traces**, while `/api/public/traces` lists 6.

- The newest observation is **2026-10-28T00:43:57Z** (trace `51bf7d93…`, "sustainment extraction").
- The v2 rows start 2026-10-16.

What this changes:

- The "10/24 last trace" behind the 10/25–27 key-rotation hypothesis was an artifact of the v1 endpoint.
- Every one of the 12 traces comes from **doc-tools** (`doc_tools/plugins/sustainment.py:1671`,
  `observed_trace(MAPPING, {"request_key": doc_id}, name="sustainment extraction")`), which has its own key
  and mapping.
- **No mesh engine has landed an observation in the visible window.**

The Phase 1a report carries a pointer to this section.

## 1. Who calls the library today

Every mesh caller goes through the shim (`baml_shared/telemetry.py`) with one mapping,
`baml_shared/telemetry-mapping.yaml`:

- **Slots:** `trace_id`→`trace_id`, `user_id`→`authz_id`, `session_id`, `release`→`build_sha`.
- **Tags:** engine, verb, domain, environment, join_status.
- **Redaction:** `content_bearing` is redacted.

`Dockerfile.agent:25-26` copies the shim and the mapping into every engine image as `/app/telemetry.py`. Where
the leaf is not installed, the shim falls back to silent no-ops.

| service (deploy) | langfuse (lock) | leaf | what it calls | entry form |
| --- | --- | --- | --- | --- |
| restate_analyst (engine-a) | 4.14.2 | 0.1.0 | Restate recipe `mint_boundary_ids`/`boundary_parent`/`emit_boundary` (`main.py:1447-1463`); `safe_observe`=`traced` on `mem0_context_retrieval`, `smolagents_restate_execution`, `smolagents_analyst_execution` (`:802,1072-1073`); `litellm_metadata` (`:1234`); `review_starter.py:448` `observed_trace` | durable boundary |
| neo4j_expert (engine-e) | 4.14.2 | 0.1.0 | Restate recipe (`service.py:970-983`); `safe_observe` ×2 (`:774,793`) | durable boundary |
| data_analyst | 4.14.2 | 0.1.0 | Restate recipe (`main.py:823-835`) | durable boundary |
| ontology_service (engine-o) | 4.14.2 | 0.1.0 | `observed_trace` (`main.py:1123`) | entry |
| presentation_agent (engine-f) | 4.14.2 | 0.1.0 | `observed_trace` (`main.py:196`) | entry |
| weaviate_expert (engine-w) | 4.14.2 | 0.1.0 | `observed_trace` (`main.py:386`) | entry |
| swarms_scraper (not deployed) | 4.5.1 | — | `safe_observe` (`main.py:120`), which is a **no-op without the leaf** | dead |
| graph_host (engine-lg) | 4.15.1 | — | none | — |
| langgraph_support (not deployed) | 4.5.1 | — | none | — |
| cortex-bff, dagster-user-code (root lock) | **4.0.6** | 0.1.0 | none (#327's `trace_spans.py` bypasses the library) | — |
| docs_agent, cost, finance, safety, planning, datahub_wrapper, mesh_registrar, repository_agent | — | — | none | — |

- **Nobody calls `observe_span`.** No service uses the library's explicit child-span primitive.
- **Nobody calls `emit_misses`.**
- On the "how do I add a new engine" path (cortex-bff → Dagster supervisor → engine-docs), none of the three
  hops has the library: the BFF and the supervisor have it installed and uncalled, and docs_agent has
  neither langfuse nor the leaf.

## 2. `telemetry_misses`: absent everywhere, and blind to an export refusal even if it were exported

**Absent.** None of the 17 fleet services exports `telemetry_misses`. The 17 are cortex-bff,
central-gateway, data-analyst, engine-a/cost/d/docs/e/f/fin/lg/o/p/safety/w, mesh-registrar and projector,
each read by `GET /health` through the apiserver service proxy. Four of them (engine-a, engine-o, engine-w
and cortex-bff) were sampled for `/metrics`, and all four return 404. Per your rule, absent is the finding.

**Exporting it would not be enough.** The counter would read zero on a pod whose key is refused:

- In leaf 0.1.0, `_miss` is called only when setup, enrichment or scoring raises: `emit.py`
  `observed_trace`/`set_trace_standard`, and `spans.py` `observe_span`.
- A 401 or an unreachable host surfaces later, in the OTel batch exporter's background thread, and never
  reaches `_miss`.
- The README's "Langfuse unreachable … increments this counter" is a claim the body does not implement.
- The shim's `emit_boundary` and `mint_boundary_ids` catch every exception and return `None` without
  calling `_miss`, so a refused ingestion POST, which is synchronous, is not counted either.

So, as wired today, `zero` and `refused` are indistinguishable. A witness that works needs:

- an exporter-side failure hook, or a periodic read-back;
- the shim's swallowed paths counted.

Both are leaf or shim changes for their owner.

## 3. The langfuse SDK in each image, and what Cloud v4 does to it

These versions are read from each image's lock: the Dockerfile runs `uv sync --locked`, and the build
matrix maps each service to its `path`. They are not read from inside the images.

- **4.14.2** (engine-a/e/f/o/w and data_analyst) and **4.15.1** (engine-lg): Python SDK v4 is "Full" on
  Cloud v4 and is past the 4.7.0 real-time floor.
- **4.0.6** (cortex-bff and dagster-user-code, both built from the root `uv.lock`): Cloud documents data
  from SDKs below 4.7.0 as **delayed by up to 15 minutes**, and 10 minutes on the v2 Observations and Metrics
  APIs. Any span #327 or its successor emits from the BFF or the supervisor inherits that delay.
  - **Ask:** raise the root lock's langfuse floor to ≥ 4.7.0, before or with the reconciled #327.
  - The root lock is shared, so the bump goes through Lane 1's gate.
- **4.5.1** (swarms_scraper, langgraph_support): would be delayed too, but neither is deployed on sandbox.
- **The Cloud v4 change itself:** the SDK path (OTel export) keeps working. The legacy-ingestion boundary
  in section "Two deadlines" breaks.

That leaves one open point on my earlier "nothing landed" reads. My polls ran five minutes and the BFF is on
4.0.6. That did not decide those runs, because no hop on that path had an emitter at all. It does mean
every future read of a 4.0.6 emitter waits about 15 minutes before it can call an absence.

## 4. How #327 reconciles (a proposal, not started)

1. **Remove the second scheme.** `src/iagent/trace_spans.py` no longer calls `get_client()`.
2. **The BFF entry uses the library.**
   - It calls `observed_trace(MAPPING, build_trace_values(trace_id=<X-Trace-Id>, authz_id=…, session_id=…, engine="cortex-bff", verb=…), name="bff.orchestrate")`.
   - The join key stays X-Trace-Id. When the header is empty, the library already falls back to a random id,
     so the BFF mints nothing (consistent with `neo4j_expert`'s `join:pending-proxy`).
   - Open point: the span must cover the streamed response. That means the context manager lives inside the
     stream's generator, which Starlette iterates in a single task. That needs a test that the OTel attach
     and detach stay in the same context.
3. **Supervisor steps use the library.**
   - Each step subprocess opens `observed_trace` on the same X-Trace-Id with `name="supervisor.<op>"`. They
     join the one trace as siblings.
   - `traceparent` is kept only as an added header. Parenting the steps under `bff.orchestrate` needs a
     `parent_span_id` argument on `observed_trace`, which is a leaf feature request. Until it lands, the
     waterfall is flat.
   - A Dagster step is a subprocess that exits, so it needs a flush the library does not offer. I propose a
     `flush()` in the shim, so a second client is not called at the call site.
4. **`span_taxonomy.yaml` stays.** It names spans and does not emit them. The taxonomy test then scans for
   `observed_trace(... name=)`/`observe_span(` literals instead of `step_span`.
5. **Not durable.** Neither the BFF nor a Dagster op is a Restate handler, so the Restate recipe does not
   apply. Its 11-16 break (section "Two deadlines") is a separate item.

## Asks

- **For you:** rule on step 3's parenting. Either flat siblings now, or wait for the leaf to gain
  `parent_span_id`. Also name the owner of the `emit_boundary` 11-16 fix and of exporting
  `telemetry_misses`.
- **For Lane 1:** the root-lock langfuse ≥ 4.7.0 bump.
- **For lane/perf next, on your go:** run a positive control. Hit one entry-form engine (engine-o or
  engine-w) through a normal answer, then read `/api/public/v2/observations` for its trace. That separates
  "mesh emission works since the 01:04Z key fix and nothing instrumented was exercised" from "mesh emission
  is failing silently". The counter cannot tell those apart.
