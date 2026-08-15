# Telemetry standard — build plan (ADR-0038)

Implements [ADR-0038](../../adr/ADR-0038-telemetry-as-provenance-projection-langfuse-standard.md) (extends [ADR-0010](../../adr/ADR-0010-distributed-tracing-strategy.md)). The standard is a **projection of the provenance doctrine into Langfuse** — the code is a generic leaf engine + ratifiable mapping config, not per-project telemetry calls. Phases 2 seals gate everything else.

## Phase 0 — prerequisites (CONFIRMED 2026-08-03)

- **Sensor artifact identity = `request_key = "{ETag}-{Key}"`** — `src/iagent/defs/extraction_review_sensor.py:398` (content hash + object key), and it is **already** carried into the `start_review` payload (`build_start_review_payload(request_key=…)`, line 161). → **Phase 3 trace id**: the Restate `start_review` handler adopts `payload["request_key"]` as the Langfuse trace id for pipeline-originated flow (a re-extraction is a new trace, a retry attaches — the idempotency mirror). *ETag caveat (declared, line 389):* single-part upload → ETag is content-MD5; a multipart producer would make ETag upload-shaped and re-fire — degradation in the **safe** direction (absorbed by the per-notice fingerprint idempotency).
- **LiteLLM → Langfuse mechanism:** the callback is configured via `.Values.litellm.config` (`success_callback`) + a `langfuse-creds` Secret, and it reads trace context from the **request `metadata` dict**. Nesting a generation under our trace requires passing `metadata={"existing_trace_id": <trace_id>, "trace_user_id": <authz_id>, "session_id": …, "tags": […]}` on the completion call. **iagent does not pass this today** → the trace-context injection is the one piece of genuine plumbing (prove-can-fail: without it, LiteLLM generations orphan under their own trace). **Sandbox runs direct Ollama (litellm OFF)** — so the litellm-nesting path is the **work** path; on sandbox / any direct-provider call, the leaf must emit **explicit spans** around the LLM call itself.
- **Build on Langfuse v2 now** (helper + env are API-compatible); v3/OTEL is Phase 5.

## Phase 1 — ADR (done, `1d4f842`)

## Phase 2 — leaf + helper + wiring **(this week — the foundation; unblocks all else)**

**Leaf package `provenance-telemetry`** (new repo, published to the internal index):
- `pyproject`: deps = `langfuse` + `opentelemetry-api` + `pydantic`/`pyyaml` (config) — **nothing else** (the dependency list is the adoption pitch).
- **README = the birth certificate** — opens with the ADR's one-sentence model *and* the "the dependency list *is* the pitch" line. A work-side security review reads the `README` + `pyproject` first, and this package's entire adoption argument is visible in those two files: four dependencies, one doctrine, config-governed vocabulary.
- **Mapping-config schema** — provenance-field → Langfuse-slot, `doc_kind`, content-bearing flags; **validates at load** (unknown slot → refuse; the `validate_ruleset` discipline for shape).
- **`set_trace_standard(...)`** — the fail-soft emitter (moved + generalized from `baml_shared/telemetry.py`): sets trace-id / user_id / session_id / tags / metadata / scores from the config; `try/except` + miss-counter, **never raises** (witness-channel axiom).
- **Explicit-span helper** for direct-provider calls (sandbox path) + a **litellm-metadata injector** (`existing_trace_id`/`trace_user_id`/`session_id`/`tags`) for the work path.
- **Redaction hooks** — declare content-bearing fields; default behavior **hash-don't-drop** (`sha1(value)` stays on the trace → a redacted trace remains *joinable* for debugging without exposing content — the provenance-without-disclosure shape the audit trail already uses).
- *Leaf seals (red-first):* shape-validator refuses an unknown slot; Langfuse-down → no exception, miss counted; **no mesh vocabulary appears in the leaf's source** (the generic-at-birth deletion test — grep the leaf for `resolved_via`/`ruleset_ref`/etc. → zero hits; the vocabulary lives only in the mesh's seed mapping).

**Mesh side (`invincible-agent`):**
- add `provenance-telemetry` dep; `baml_shared/telemetry.py` → **re-export shim** (removal marker: "all three repos on the leaf").
- ship the mesh **seed mapping** (`resolved_via`/`ruleset_ref`/`admitted_by`/`era`/`obtained_via`/`authz_id` → slots) as ADR-0036 seed config.
- **mesh-repo CI truth-check** — every mapped field exists in the mesh's provenance contracts (red-first; the "vocabulary owner validates truth" tier).
- call `set_trace_standard(...)` at the boundary — `agent_fleet/restate_analyst/main.py:~553` (where `current_trace_id.set()` runs) — user=`authz_id`, session (from `X-Session-Id`), tags=[engine,verb,domain], metadata={subject_class, resolved_via, chart_version}.
- inject litellm metadata at the LLM call for the work path; wrap direct-Ollama calls in explicit spans for sandbox.

**cortex-ui** (`src/api/client.ts`) — add a stable **`X-Session-Id`** in the same interceptor as `X-Trace-Id` (per-conversation, not per-request).

**Charts** (both `values.yaml`) — `LANGFUSE_RELEASE` (git SHA, baked in CI) + environment (sandbox→`dev`, work→`production`).

**Phase seal:** a trace carries the full standard shape (env/release/user/session/tags/metadata); shape refuses unknown slot; mesh truth-check reddens on a nonexistent mapped field; fail-soft proven (Langfuse down → review still starts, miss counted); **path-equivalence** — the sandbox explicit-span helper and the work litellm-injector, given the *same logical operation*, emit the **same span shape** (name grammar, attributes, nesting depth), differing only in transport. One fixture-driven comparison test, red-first — so the dual path is **one standard with two carriers**, not two standards under one name (the classic dual-emission drift, closed at exactly the environment boundary where comparison matters most).

## Phase 3 — doc-tools tracing, artifact-keyed

- doc-tools deps on `provenance-telemetry`.
- Restate `start_review` adopts `payload["request_key"]` (ETag+Key) as the trace id → the pipeline and the review share one trace.
- wrap doc-tools BAML extraction (`doc_tools/plugins/sustainment.py`, the vision `Collector`) in leaf spans — "extract table crop 3/5 for notice X" with the generation *inside*.
- **Seal:** drop a PDF → **one trace bucket→queue**; re-extraction = new trace, retry attaches.

## Phase 4 — prompt-hash linkage

- `doc_tools/plugins/base.py`: file mode → content-hash the canonical prompt → `prompt@<12-hex>` into span metadata; langfuse mode → link the `langfuse_prompt` object to the generation. Same for any iagent file prompts.
- **Seal:** a trace names the prompt version that produced an extraction.

## Phase 5 — v3 / OTEL migration (own increment)

- bump leaf `langfuse` v2→v3 (OTEL-based); migrate decorator/callback APIs; native `environment` field (`LANGFUSE_TRACING_ENVIRONMENT`); OTEL context propagation (interop with work's APM/collectors).
- **Seal:** before/after trace-shape comparison — **no silent span drops**.

## Critical path

```
Phase 0 (confirmed) ─┬─→ Phase 2 (leaf + helper + wiring) ─┬─→ Phase 3 (doc-tools artifact-keyed)
                     │                                     ├─→ Phase 4 (prompt-hash)
                     └────────────────────────────────────→└─→ Phase 5 (v3 / OTEL)
```
Phase 2 is the unblocker; 3/4/5 parallelize once it lands. First two phases this week.

## Dispositions (settled in review — Phase 2 doesn't stall on them)

- **Score taxonomy — derived, not designed.** The honest-degradation signals already have canonical homes/encodings in the **decision-record schema**; the Langfuse scores are a *projection of that schema* (the ADR's own doctrine). So the question reduces to "which decision-record fields project, at what encoding" — a mapping-config entry per the ratifiable-config rule, **seeded with the obvious four**: confidence tier (ordinal), `needs_review` rate (fraction), coherence (binary-per-join), crops-failed (count/total). Extended through governance. No design session for what the schema already decided.
- **Redaction-class list — the fields the standard already names.** `content_bearing: true` on **MPNs, notice ids, document snippets, matched-text verbatims, and override reasons** — that last is the sleeper: `'sasa'` was harmless, but real override reasons carry engineering judgment about specific parts. Default hook = **hash-don't-drop** (above). Both land as **seed-mapping content**, extendable by work's overlay; neither blocks the leaf stand-up.
- (LiteLLM metadata keys — resolved in Phase 0 above; v3 timing — after v2 proves out.)
