# ADR-0038 — Telemetry as provenance projection: the Langfuse observability standard (extends ADR-0010)

**Status:** Proposed — standard defined; rollout staged (helper + env on v2 this week; doc-tools artifact-keyed tracing; prompt-hash; v3/OTEL migration), each sealed.
**Date:** 2026-08-03
**Deciders:** Platform team
**Related:**
  - [ADR-0010](ADR-0010-distributed-tracing-strategy.md) — this **extends** it. 0010 established `X-Trace-Id` propagation at the HTTP boundary; this defines the full metadata *standard* carried on top.
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) — decision records, `ruleset_ref`, the format×pipeline-version promotion key, and the **witness-channel fail-soft** ruling the telemetry emitter inherits.
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — the field-mapping is **ratifiable config** (seed/overlay), not a code convention.
  - [ADR-0031](ADR-0031-instance-resolution-ladder.md) — `resolved_via` tiers (a span attribute, verbatim).
  - The provenance doctrine (`obtained_via`, `admitted_by`, `era`, `requested_by`, `authz_id`, `doc_ref`) and the derived-value / artifact-identity rules the trace-id convention reuses.

## Context

We want to standardize Langfuse telemetry across **iagent / cortex-ui / doc-tools** and **publish the standard through the SDK** so work-side adopters inherit it. Audit of today (see the gap table below): the trace-id chain works iagent-side (cortex-ui mints `X-Trace-Id` → engines adopt + forward), but it's thin — spans carry only `name` + input/output + the trace_id; **no environment, version, user/session, tags, metadata, or scores**. doc-tools is effectively **untraced** (only opt-in prompt-fetching; its BAML `Collector` captures events locally and sends them nowhere). Both repos are on **Langfuse v2** (`langfuse.decorators`). LiteLLM's Langfuse callback exists but is unverified and dormant in sandbox (direct Ollama).

**The reframe — the design question is not Langfuse-shaped.** Telemetry is **provenance emission**, and we already have a provenance doctrine. The risk in "maximize what we send" is building a **second, parallel vocabulary** for describing what the system did — trace names, span attributes, metadata keys invented per project — when the system already describes what it did in **ratified terms**: `resolved_via`, `ruleset_ref`, `doc_ref`, `admitted_by`, `requested_by`, `era`, trust rungs, decision-record verdicts. The standard worth publishing is not "how to call Langfuse" but **which of the system's existing provenance fields map onto Langfuse's observability primitives, uniformly** — so a trace in Langfuse and a decision record in the graph tell the same story *in the same words*, and an SDK adopter inherits the **vocabulary, not just the plumbing**.

### The gap (current state, from the audit)
| Goal | Status |
|---|---|
| e2e tracing | ✓ iagent (UI→engines, ADR-0010); ✗ **doc-tools not linked** — and it's the pipeline's *first half* |
| prod/test/dev | ✗ not set |
| version | ✗ no `LANGFUSE_RELEASE` |
| prompt version | ✗ fetched (dev-only), never linked; prod uses *file* prompts, unversioned |
| user / session | ✗ `authz_id` available at the boundary, not emitted |
| tags / metadata / scores | ✗ none |

## Decision

**Telemetry is a projection of the provenance doctrine into an observability backend. The projection rules are the standard.** Never invent a parallel vocabulary; map existing ratified fields onto Langfuse primitives, verbatim.

### The mapping (Langfuse primitive ← existing, ratified source)
Langfuse's model: **traces** (a request/workflow) → **observations** (spans/generations/events) → **scores**, plus **sessions** and **user** attribution. Each slot has a natural tenant already in the stack:

| Langfuse slot | Source (existing) | Rule |
|---|---|---|
| **trace identity** | artifact-derived keys we already mint — notice fingerprint, ingress `request_key`, `workflow_id` (content+location identity) | **never LLM-derived** — the derived-value rule applied to trace ids: a re-extraction is a *new* trace, a retry *attaches*, mirroring ingress idempotency semantics exactly |
| **user_id / session_id** | `authz_id` verbatim; session = the UI's conversation identity (`X-Session-Id`) | service identities surface as `svc:review-starter` — the *same* string as in `requested_by`, one identity plane. Flip-rider: at work these become employee-ids |
| **span attributes** | the provenance-block fields **by their existing names** — `resolved_via`, `ruleset_ref`, `admitted_by`, `era`, `obtained_via` | **never renamed for Langfuse** → grep and dashboard speak one language |
| **scores** | the honest-degradation signals — confidence tiers, `needs_review` rate, coherence verdicts, crops-failed counts | Langfuse scores are the right home for *"how honest was this answer"* — and they make the **trust lifecycle's promotion evidence dashboardable** |
| **metadata** | pipeline version + content hashes | version-stamp **every** trace → *"did behavior change at deploy X"* becomes a query (traces are our only cross-service view today) |

### Structural decisions

1. **LiteLLM is the bottom layer, not a peer.** Its auto-instrumentation gives *generations, not meaning*. **Read the pipe** — verify what its callback actually sends — then **nest it**: a Gemma vision call must appear *inside* "extract table crop 3/5 for notice X," not as an orphan generation with a bare prompt. **Trace-context propagation** (passing trace/span IDs into LiteLLM's callback via its metadata mechanism) is the one piece of genuine plumbing this standard needs, and it is the piece to **prove-can-fail first** — two independent trace-creators produce two half-stories per request.

2. **doc-tools is the pipeline's *first half* — instrument it second (right behind the helper), not "later."** The value proposition is end-to-end observability, and the actual *end* is a PDF landing in MinIO → extraction → vision calls → the sensor tick → ingress. Today a trace begins at a UI click or a `start_review`, which means the 173-second compositions, the vision runaways, the crop failures — **the incidents this arc actually debugged** — are exactly the spans the standard would not cover. The chain design already solved the hard part: **the sensor mints identity from ETag+Key**, and that content+location identity should *be* the trace id for the pipeline-originated flow (derived-value rule → re-extraction is a new trace, a retry attaches). The sensor→`start_review` POST carries `X-Trace-Id` so the Restate side **joins** the pipeline's trace rather than minting its own. *"Drop a PDF, watch one trace from bucket to bob's queue"* is the standard's demo — worth more than every metadata field combined.

3. **Take the v3 / OTEL bump — in its own increment.** The tactical argument (native `environment` field vs. tag-encoding) is minor; the strategic one decides it: **v3 is OTEL-based, and OTEL is the interchange standard for the very thing we're standardizing.** Publishing an SDK telemetry standard to work-side teams on v2's bespoke decorators is publishing onto a foundation Langfuse itself is migrating off — and OTEL context propagation is *also* how our trace ids would interop with anything else work runs (their APM, their collectors), which a work-published standard must anticipate (the adopt-interchange-standards-at-the-boundary posture, applied to observability as it was to ODCS). **Sequence honestly:** the helper + env vars land on **v2 now** (API-compatible; the fields are the urgent gap); v3 migration is **increment three with its own seal** — an OTEL rebase mid-standard is exactly the change that silently drops spans, so the seal is a **before/after trace-shape comparison**, not upgrade-and-hope.

4. **Prompt versioning in file mode = `ruleset_ref` for prompts.** A file-sourced prompt stamped with its content hash — `prompt@<12-hex>` — is the same pattern we already own: stable under co-tenancy, changes when meaning changes, and lets a decision record or trace say *which* prompt produced an extraction. The trust lifecycle's **format×pipeline-version** key genuinely needs it — **prompt changes are pipeline-version changes for promotion purposes**, and today they are invisible. This is not optional polish: **an unversioned prompt is an unversioned pipeline component vouching for trusted vendors.**

### Doctrine (what makes this SDK-publishable, not just internal)

- **The field-mapping is ratifiable config, not a code convention.** Which provenance keys map to which Langfuse slots, which events emit spans, the naming grammar — a small **versioned schema the SDK reads**, seed/overlay per ADR-0036. Work-side teams extend the vocabulary through the *same governance* as everything else, rather than inventing keys (the `taskKindLabel` lesson, pre-empted at the observability layer).
- **Emission fails soft-and-countable, never loud** (witness-channel axiom). A Langfuse outage must **not** stop a review from starting — the decision-record writer already established this exact ruling (ADR-0034); the telemetry emitter inherits it, misses logged and counted.
- **Content-bearing fields are declared for redaction-by-class.** Traces will carry MPNs, notice IDs, and document snippets — fine for work's own Langfuse, but the standard **declares which fields are content-bearing** so a deployment can redact by class, and the **open-side SDK ships the redaction hooks** even if sandbox never uses them.

### The helper is derived *from* this ADR
A single `set_trace_standard(...)` in the standalone `provenance-telemetry` leaf (see **Package boundary** below), called once at each entry boundary (right where `current_trace_id.set(...)` already runs). Its field list is **derived from the mapping above, not invented** — one boundary, one shape, one file to extend. It is the *implementation* of the standard, not its source of truth.

### Package boundary — where the standard lives (a standalone leaf)

**Decision: a standalone leaf package, `provenance-telemetry`** — not inside `invincible-agent`, not inside `iagent_mesh`. Two independent arguments force it:

- **The ADR's own doctrine.** "The field-mapping is ratifiable config, not code" means the emission engine is **vocabulary-agnostic by design commitment.** A vocabulary-agnostic engine living inside `iagent_mesh` would contradict its own ADR one directory over.
- **The dependency list *is* the adoption pitch.** "Publish the standard to other teams" and "importing it drags in `fastapi`/`mcp`/`acryl-datahub`" cannot both be true. A finance team should install a package whose dependency list *is* the standard's footprint — `langfuse`/`opentelemetry` + a config loader, nothing else. Heavy transitive deps are how internal standards die at other teams' security reviews.

**Not circular — two graphs, only one matters:**

| Graph | Relationship | Cyclic? |
|---|---|---|
| **Code / import** (build-time) | `invincible-agent`, `doc-tools`, `iagent_mesh`, any company tool → **`provenance-telemetry`** (all depend *down*) | **Acyclic ✓** |
| **Runtime / protocol** | `MeshClient` (in `iagent_mesh`) → the running mesh over HTTP `/v1/register` + DataHub emit | not a code dep at all |

`iagent_mesh` is a verified zero-iagent-imports leaf, so the "SDK depends on iagent" fear was a **naming illusion** — and that same illusion is why the telemetry package is named for **what it does, not who built it**: `provenance-telemetry`, not `iagent-telemetry`. A mesh-flavored name reads as *their* library to every other team — adoption friction measured in org-chart units.

**Two-tier validation (the safety story for string-reference decoupling).** The engine references provenance fields *by string via config* (so it needs no dependency on `iagent_mesh`) — which reopens the exact gap `validate_ruleset` closes for rules: a mapping naming `resolved_vai` (typo) or a retired field would emit nothing, silently, forever. The fix is the split every ratified config already uses:
- **The leaf validates *shape*** — the mapping schema validates at load (unknown Langfuse slot refused; the schema-drift discipline). Vocabulary-agnostic.
- **The vocabulary owner validates *truth*** — the mesh-side seed mapping gets a CI check **in the mesh repo** asserting every mapped field name exists in the mesh's provenance contracts. Validation lives with whoever owns the vocabulary. This is what lets a finance team's mapping name fields the mesh never heard of without anything breaking — *their* repo owns *their* truth-check.

**The seed mapping is ADR-0036 seed content.** The mesh's provenance→Langfuse mapping ships as seed config (in the mesh repo, with the truth-check above); work's overlay adds/shadows; a non-mesh adopter supplies its own. The leaf ships **no vocabulary** — only the engine and the shape-schema.

**Relocation is expand/contract, not a hard move.** `baml_shared/telemetry.py` moves into the leaf; the mesh's imports of the old path keep working through a **re-export shim** during the interval. The shim carries a removal marker naming its condition — *all three repos on the leaf* — and the contract phase deletes it. A hard move would break doc-tools' adoption ordering for no reason.

## Rollout (staged, each sealed; first two this week)

1. **This ADR** — the projection doctrine + mapping.
2. **Helper + env vars (v2) — landing in the new `provenance-telemetry` leaf.** `set_trace_standard` (user_id=`authz_id`, session_id, tags, metadata from the mapping) + the shape-schema validator + `LANGFUSE_RELEASE` (git SHA) + environment (v2: tag/metadata), wired per-deployment in both charts; `baml_shared/telemetry.py` becomes a **re-export shim** (marked for removal when all three repos are on the leaf). Mesh-side seed mapping + its **mesh-repo truth-check** land here. **Seal:** a trace carries the standard shape; the shape-schema **refuses an unknown slot**; the truth-check **reddens on a mapped-but-nonexistent field**; and **fail-soft proven** (Langfuse down → the review still starts, the miss is counted).
3. **doc-tools tracing, artifact-keyed.** Sensor mints the trace id from ETag+Key; sensor→`start_review` forwards `X-Trace-Id`; BAML spans nest under it. **Seal:** drop a PDF → one trace bucket→queue; re-extraction = new trace, retry attaches.
4. **Prompt-hash linkage.** `prompt@<hash>` for file prompts + `langfuse_prompt` link for GUI prompts, into span metadata. **Seal:** a trace names the prompt version that produced an extraction.
5. **v3 / OTEL migration.** **Seal:** before/after trace-shape comparison — no silent span drops.

## Consequences

- **One vocabulary across graph and traces** — a trace and a decision record describe the same event in the same words; grep, dashboard, and audit agree by construction.
- **The trust corpus becomes dashboardable** — scores carry the honest-degradation signals, so promotion evidence is a Langfuse view.
- **"Did behavior change at deploy X" is a query** — every trace is version- and hash-stamped.
- **Work-side adopters inherit the doctrine** — the SDK publishes the mapping (ratifiable config), not a pile of `langfuse.observe(...)` calls to copy.
- **The full pipeline is observable** — with doc-tools instrumented on artifact identity, a work trace starts at the PDF, not mid-story.

## Non-goals

- A new metadata vocabulary invented for Langfuse (the whole point is to *reuse* the provenance names).
- Loud telemetry (emission never blocks the request path).
- Instrumenting every function — spans are for **provenance-bearing operations**, not call-graph completeness.
- Committing to a specific score set/scale or the v3 migration date here (open questions below).

## Open questions

1. **Score taxonomy + scales** — the exact honest-degradation signals promoted to Langfuse scores (confidence tier, `needs_review`, coherence verdict, crops-failed) and their numeric encoding.
2. **LiteLLM metadata mechanism** — the concrete way trace/span context is threaded into its callback (read the pipe; confirm before building on it).
3. **Redaction-class list** — which fields are declared content-bearing, and the default redaction hook behavior in the open SDK.
4. **v3 migration timing** — after the v2 fields prove out; gated on a trace-shape before/after seal.

## The one-sentence model

Telemetry is the provenance doctrine projected into an observability backend: trace identity from artifact keys (never LLM-derived), user/session from `authz_id`, span attributes and scores from the fields the graph already uses — so the standard we publish is a *projection*, and adopters inherit the vocabulary, not just the plumbing.
