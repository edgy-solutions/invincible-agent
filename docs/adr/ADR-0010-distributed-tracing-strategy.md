# ADR-0010 — Distributed tracing strategy (OpenTelemetry at the HTTP boundary)

**Status:** Proposed
**Date:** 2026-05-30
**Deciders:** Platform team
**Related:**
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — uses structured
    logs for counter/histogram telemetry; this ADR explains why those
    don't get folded into OTel metrics on day one and what the path
    to migration looks like.
  - [ADR-0003](ADR-0003-llm-rightsizing.md) — LLM workload classes
    are already exposed through Langfuse; this ADR keeps that
    division clean.

## Context

A single user query fans out through the mesh roughly as:

```
gateway → /route_intent          → Engine O   → BAML ExtractIntent (LLM)
        → /search_predicates     → Engine O   → Weaviate hybrid
        → Dagster supervisor_query_job
            → /plan              → Engine O   → BAML DecomposeQuery (LLM)
            → execute_subtask × N
                → /search_predicates → Engine O → Weaviate hybrid
                → matched engine
                    → Engine E   → /resolve + Neo4j Cypher + mem0 + BAML
                    → Engine A   → /resolve + DataHub HTTP + LLM tool loop
                    → Engine W   → Weaviate hybrid + LLM
            → Engine F           → BAML DesignUI (LLM)
```

Today, four observability tools cover non-overlapping slices:

| Tool | Owns | Where it shines |
|---|---|---|
| **Dagster** | Op-level orchestration, materializations, asset lineage | Op fan-out, retry state, materialization graph |
| **Langfuse** | LLM call traces — prompt, response, tokens, cost, eval | Per-prompt cost, latency, semantic eval |
| **DataHub** | Data lineage, schema | Asset-to-asset lineage, schema evolution |
| **Structured logs** | Counters + histograms (ADR-0008) | Routing fallback rate, score distribution |

**What none of them own is the inter-service HTTP graph.** When a
user-facing query takes 90 seconds, "where did the time go?" today
requires correlating Dagster op timings + Langfuse traces + a manual
grep through every service's logs for the same `X-Trace-Id`. The
mesh already passes a `X-Trace-Id` header end-to-end and stuffs a
`LANGFUSE_TRACE_ID` env var into the smolagents loop — both of these
are partial implementations of a thing OpenTelemetry's W3C
`traceparent` does properly and automatically.

The question this ADR answers is: **where, specifically, does
OpenTelemetry earn its keep without duplicating the four tools above?**

## Decision

We adopt OpenTelemetry for **distributed HTTP and DB tracing across
service boundaries** — and only that. The strategy is opinionated about
non-goals so OTel does not creep into the layers that Dagster, Langfuse,
and DataHub already own.

### Where we instrument

1. **FastAPI entry points** — gateway, every engine
   (`opentelemetry-instrumentation-fastapi`).
2. **httpx / requests clients** — gateway → engines, supervisor →
   engines, engines → other engines, engines → Restate ingress
   (`opentelemetry-instrumentation-httpx`,
   `opentelemetry-instrumentation-requests`).
3. **Vector store and graph DB clients**:
   - Weaviate (via the official Weaviate OTel hook or a thin manual
     span around the `hybrid()` call if the contrib library lags).
   - Neo4j (`opentelemetry-instrumentation-neo4j`).
4. **SQL backends in Engine DA** — DuckDB / DataHub-fed datasets
   wrapped via DB-API instrumentation
   (`opentelemetry-instrumentation-dbapi`).
5. **One manual root span per user request** at the gateway's
   `/orchestrate` entry point so the whole fan-out is one trace tree
   with the user's query as the root attribute.

### Where we do **not** instrument

These are explicit non-goals, not "we'll get to them later":

1. **Dagster op bodies.** Dagster's UI already shows op timing,
   status, and the fan-out tree. Wrapping op bodies in OTel spans
   adds a second telemetry source for the same data — one of them
   would inevitably drift. Op-level observability stays with Dagster.
2. **BAML / smolagents loops.** Langfuse is purpose-built for LLM
   trace anatomy: prompt, response, tokens, cost, eval. OTel can
   carry spans through these calls, but the *interpretation* of an
   LLM span is Langfuse's job. We keep Langfuse as the LLM tracer.
3. **Pure compute / business logic.** Tracing every function call
   is profiling, not observability. If a non-IO function is slow,
   profile it; don't add an OTel span.
4. **DataHub asset lineage.** Lineage is a different graph from
   tracing. They have different vertices (datasets vs operations)
   and different consumers (data engineers vs site reliability).
   OTel never owns lineage.

### Trace ID propagation and tool correlation

The mesh's existing manual trace plumbing is replaced by W3C
`traceparent` automatically:

- The gateway's `/orchestrate` root span generates the trace ID.
- `opentelemetry-instrumentation-httpx` injects `traceparent` into
  every outbound HTTP call.
- `opentelemetry-instrumentation-fastapi` extracts `traceparent` on
  every inbound HTTP call.
- **Langfuse correlation**: `restate_analyst/main.py` today reads
  `LANGFUSE_TRACE_ID` from an env var and calls
  `langfuse_context.update_current_trace(id=trace_id)`. After this
  ADR, the trace ID is read from the active OTel span context;
  Langfuse spans carry the same trace ID as the surrounding HTTP
  spans, and clicking a Langfuse trace pivots to the OTel backend
  for the surrounding context (or vice versa).
- **Dagster correlation**: the supervisor's `requests.post(...)` calls
  inside an op already carry `traceparent` once instrumented; the
  Dagster UI's op log can include the trace ID as a metadata field
  (`MetadataValue.text(trace_id)`) so an op log links out to the
  trace backend with one click. Dagster does not become an OTel
  client; it just surfaces the ID for human navigation.
- **Engine A's existing `X-Trace-Id` header and `LANGFUSE_TRACE_ID`
  env var are retired** once `traceparent` propagation is in place.
  Keeping both would invite drift between the two IDs.

### Backend choice

The ADR does not pick a backend — that's a deployment decision tracked
separately. Constraint: **OTLP-compatible**. Examples that satisfy
the constraint: Tempo + Grafana, Jaeger, Honeycomb, Datadog APM, GCM
Cloud Trace. The OTel exporter (`opentelemetry-exporter-otlp`)
points at a collector; the collector decides where the data lands.
Picking a backend later does not invalidate this ADR.

### Sampling

- **Dev / non-prod**: 100% sampling. Trace volume is small; full
  fidelity helps the trace-driven debugging workflow this ADR exists
  to enable.
- **Prod**: head-based 1% sampling at the gateway's root span; the
  sampling decision propagates through `traceparent` so the whole
  trace is either kept or dropped end-to-end (no half-traces).
  Tunable via the OTel collector if a higher rate is needed for
  incident analysis.

### Relationship to ADR-0008 metrics

ADR-0008's `predicate_fallback_total` counter and
`predicate_routing_score` histogram are **kept as structured logs**
on day one. Reasons:

- Zero new infrastructure: works with the existing log-scrape
  pipeline (Loki / Datadog logs / GCP logging) the operator team
  already has.
- Low volume: one log line per routing decision is cheap to scrape.
- Single source of truth: running both structured-log scraping and
  OTel metrics for the same counter is exactly the kind of duplication
  this ADR is trying to prevent.

**Migration target**: once the OTel collector is deployed for tracing,
the ADR-0008 counters and histogram can be re-emitted as OTel metrics
(`opentelemetry.metrics.Meter.create_counter(...)`) and the structured
log lines deleted. That's a separate ADR amendment when it happens.

## Consequences

**Wins:**

- One trace, one ID, end-to-end. "Where did the 90 seconds go?"
  becomes a span-tree question with a one-click answer.
- Auto-instrumentation: no per-engine code change to get the cross-
  service spans. The instrumentation libraries patch the clients;
  engine code stays clean.
- DB / vector store latency surfaces explicitly. Today a 30-second
  op might be 12s Cypher + 800ms Weaviate + 17s LLM; that's invisible
  outside heavy log diving.
- Langfuse correlation is automatic. The manual `LANGFUSE_TRACE_ID`
  env-var plumbing in Engine A goes away.
- Backend portability. The mesh is OTLP-spec, not vendor-specific.

**Costs:**

- New runtime dependency: `opentelemetry-api`, `-sdk`,
  `-instrumentation-*`, `-exporter-otlp` in every engine image. A few
  MB per image, real but small.
- OTel collector deployment in the cluster (or sidecar-per-pod). One
  more pod / sidecar to operate. Standard Helm chart exists; the cost
  is "we know what running this pod looks like."
- Sampling decision is live policy — getting it wrong (too high)
  costs storage; too low and incidents become un-debuggable. Start
  at 1% prod, tune by observation.
- **Restate is not OTel-native.** The trace stops at the Restate
  ingress; the durable execution span tree is opaque to OTel. We
  accept this — Restate has its own observability and our HTTP-layer
  spans bracket the Restate calls correctly. If Restate adds OTel
  later we pick it up free.
- **Smolagents loop interior is not instrumented.** Langfuse owns
  it; the OTel span around the smolagent call shows total LLM time
  but not per-step LLM time. Acceptable — drilling into LLM steps
  goes through Langfuse.

## Alternatives considered

- **Status quo: manual `X-Trace-Id` + `LANGFUSE_TRACE_ID`.** Rejected
  as the not-quite-working state we have today. Every new service
  has to remember to propagate the header; correlation across tools
  is grep-driven; failure modes are silent (one service drops the
  header, the trace fragments).
- **All-in on Langfuse for everything.** Rejected. Langfuse is shaped
  for LLM call anatomy, not HTTP fan-out latency. Forcing HTTP traces
  into Langfuse's prompt/response model loses the actual signal.
- **Direct vendor APM SDK (Datadog APM, New Relic, etc.).** Rejected
  for portability — backend lock-in is unnecessary when OTel +
  Datadog-backend gives the same end state. Same logic for Cloud
  Trace and Application Insights.
- **OTel everywhere, including Dagster ops and BAML loops.** Rejected
  per the non-goals above. Duplicate observability for the same
  events is a maintenance hazard, not redundancy — the two sources
  drift and operators learn to trust one, the other rots.
- **OTel for metrics on day one (re-emit ADR-0008 counters via
  OTel).** Rejected for now to avoid coupling the tracing rollout to
  the metrics rollout. Migration path is documented above.

## Migration plan

Incremental — each step is a small reviewable commit, traces become
useful as soon as the gateway and one engine are instrumented.

1. **Gateway**: add `opentelemetry-{api,sdk,exporter-otlp,instrumentation-fastapi,instrumentation-httpx}` to its pyproject, configure the SDK with OTLP exporter to a collector URL (env-driven), and add the manual root span at `/orchestrate`. Verify a trace shows up end-to-end as soon as the next downstream engine is instrumented.
2. **Engine O** next (it's on every routing path; instrumenting it lets every user query produce a multi-span trace immediately): FastAPI + httpx + Weaviate + Neo4j instrumentation.
3. **Supervisor**: add `opentelemetry-instrumentation-requests` so the `requests.post(...)` calls inside Dagster ops carry `traceparent`. Surface the active trace ID as a Dagster `MetadataValue.text(trace_id)` on each op so the Dagster UI links out to the trace backend.
4. **Engines A, E, DA, W, F**: instrument one per commit. Each adds its DB-client instrumentation alongside the FastAPI/httpx layer (Weaviate for A/E/W, Neo4j for E/O, DuckDB/Postgres for DA).
5. **Langfuse correlation**: switch `restate_analyst/main.py` to read the trace ID from `opentelemetry.trace.get_current_span().get_span_context().trace_id` instead of `LANGFUSE_TRACE_ID`. Retire the env-var fallback in the next release after observation confirms the OTel ID is always present.
6. **Retire manual headers**: delete the `X-Trace-Id` plumbing once `traceparent` propagation is verified end-to-end.

## Indicators for revisiting

- **Trace backend storage or query latency becomes a bottleneck.**
  Re-evaluate sampling rate, span attributes (cardinality), or
  backend sizing. Not an architectural change, but worth a re-read.
- **Restate adopts native OTel.** At that point the trace becomes
  continuous through Restate's durable execution and the "Restate is
  opaque" cost goes away. Update the consequences section.
- **LLM spans want first-class OTel semantics.** OTel has a working
  group on LLM/GenAI semantic conventions; if it matures and tooling
  catches up to Langfuse's depth, the LLM-tracer split here might be
  worth reconsidering. Today Langfuse is decisively better at it.
- **ADR-0008's structured logs become a scraping cost.** If the
  fallback-rate counter volume grows or the log-metrics pipeline is
  retired, switch to OTel metrics per the migration target above.
- **A new service joins the mesh in a language without OTel SDK
  maturity** (e.g. a Rust or Zig component). Revisit whether manual
  span emit is acceptable for that one service.
