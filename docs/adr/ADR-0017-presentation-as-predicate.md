---
status: Proposed
date: 2026-06-03
deciders: Platform team
supersedes: ADR-0012
---

# ADR-0017 — Presentation-as-Predicate (and the end of generic `output_uri`)

## Status

Proposed (2026-06-03). Supersedes [ADR-0012](ADR-0012-ui-archetype-rigidity.md).

## Related

- [ADR-0004 — Predicate-graph routing](ADR-0004-predicate-graph-routing.md):
  the substrate this ADR reuses. Engine selection is already a
  `/search_predicates` lookup against `(verb, input_uri, output_uri,
  domain, persona)`. This ADR adds a *second* lookup of the same shape
  for presentation selection.
- [ADR-0005 — Verb and concept namespaces](ADR-0005-verb-and-concept-namespaces.md):
  defines the `mesh:` IRI scheme that the new output-shape vocabulary
  inherits.
- [ADR-0006 — Verb registry location](ADR-0006-verb-registry-location.md):
  DataHub is the inbox; the doc-tools sensor materializes registrations
  into the Weaviate Predicate collection. Presentation registrations
  ride the same pipeline.
- [ADR-0009 — Sunset classification axes](ADR-0009-sunset-classification-axes.md):
  `domains` is a scope filter, `persona` splits into user-side and
  answerer-side. The presentation lookup uses the user-side persona;
  the engine lookup keeps using the answerer-side persona.
- [ADR-0012 — UI archetype rigidity](ADR-0012-ui-archetype-rigidity.md):
  this ADR's predecessor. ADR-0012 named the symptom (six fixed
  archetypes hardcoded in BAML, one LLM picking among them on every
  request). This ADR removes the cause: the BAML LLM was picking
  because nothing in the contract told it what shape it was looking
  at. Once `output_uri` is explicit, the pick becomes a deterministic
  predicate lookup.
- [ADR-0015 — Router regression L1](ADR-0015-router-regression-L1.md):
  the routing-decisions audit table extends to presentation
  decisions. Same row shape, same drift detection.
- [ADR-0013 — Engine D capability surface](ADR-0013-engine-d-capability-surface.md):
  same disease (one fuzzy verb hiding many capabilities). This ADR is
  the cure applied to Engine A; ADR-0013 was the cure applied to
  Engine D.

## Context

### The wrong assumption

Today Engine A registers one verb:

```python
register_engine_to_mesh(
    name="engine_a_restate_analyst",
    verb="mesh:analyzeWithCodeAgent",
    input_uri="mesh:AgentTask",
    output_uri="mesh:AgentResponse",
    ...
)
```

Engine DA and Engine W register specific verbs with specific I/O:

```python
# Engine DA
verb="mesh:analyzeDataset",
input_uri="mesh:DatasetAnalysisRequest",
output_uri="mesh:DatasetAnalysisReport",

# Engine W
verb="mesh:retrieveKnowledge",
input_uri="mesh:KnowledgeQuery",
output_uri="mesh:KnowledgeRetrievalResponse",
```

Engine A is the outlier. It hides at least six distinct question
shapes — ownership lookup, lineage traversal, downstream-impact
assessment, schema inspection, freshness checking, PII-exposure
auditing — behind one verb with one universal output type. The
"universal output type" `mesh:AgentResponse` is not the registry's
intended shape; it's an artifact of pretending one verb covers
everything.

The downstream consequence shows up at the presentation boundary.
Engine F (`agent_fleet/presentation_agent/`) receives the agent's
response JSON and a persona, then calls `b.DesignUI(raw_data,
persona)` — a BAML prompt that asks an LLM to pick one of six
archetypes (`KNOWLEDGE_DOCUMENT`, `ASSET_STATE_METRIC`,
`PROCESS_TOPOLOGY`, `HAZARD_DECLARATION`, `CHART_WIDGET`,
`DIGITAL_TWIN_3D`) based purely on the shape of the data and a
persona hint. The contract carries no `output_uri`, so the LLM has
nothing to constrain its choice. It guesses every time, and the
guesses drift.

### What the guesses cost us

Observed during the 2026-06-03 DataHub query suite re-run:

- **Q2 regression**: Engine A produced a correct ownership answer
  (3/4 fields right), but Engine F's BAML LLM picked
  `ASSET_STATE_METRIC` and emitted an empty metric widget. The agent
  was right; the renderer mis-classified.
- **Q9 archetype quirk**: Engine A produced a correct PII-exposure
  finding, but Engine F picked `ASSET_STATE_METRIC` again instead of
  the more appropriate `HAZARD_DECLARATION`. User-visible answer was
  correct but visually wrong.
- **Q7 partial**: lineage data emitted fine; archetype choice
  acceptable but unstable across reruns.

Each of these is "agent correct, presentation wrong." Each is an LLM
re-deciding from raw data what shape the data has, when the registry
*could* tell it deterministically if the upstream agent had declared
its output shape.

### Why the registry can solve this

The Weaviate Predicate collection (per ADR-0004) already stores
verb-edges with rich metadata: `verb`, `input_uri`, `output_uri`,
`domain_fit`, `persona_fit`, synonyms. The same collection can store
presentation-edges: `subject=output_uri`, `predicate=mesh:rendersAs`,
`object=archetype_uri`, with the same `domain_fit`/`persona_fit`
metadata. The same `/search_predicates` machinery ranks and returns
matches.

So the architecture is already there. What's missing is:

1. Engine A registering specific output URIs (not `mesh:AgentResponse`).
2. Every agent's final_answer echoing its declared `output_uri` so
   downstream consumers can use it without re-classifying.
3. Engine F advertising its presentation capabilities as predicate
   triples instead of hiding them in a BAML LLM prompt.
4. Engine F's `/render_ui` doing a `/search_predicates` lookup
   instead of calling `b.DesignUI`.

## Decision

### 1. Engine A decomposes into one registration per question shape

Same pod, same image, one `register_engine_to_mesh` call per verb,
all pointing at the same endpoint URL:

| Name                              | Verb                       | output_uri                |
|-----------------------------------|----------------------------|---------------------------|
| `engine_a_lookup_ownership`       | `mesh:lookupOwnership`     | `mesh:OwnershipFact`      |
| `engine_a_trace_lineage`          | `mesh:traceLineage`        | `mesh:LineageTopology`    |
| `engine_a_assess_impact`          | `mesh:assessImpact`        | `mesh:ImpactSet`          |
| `engine_a_find_schema`            | `mesh:findSchema`          | `mesh:SchemaDescription`  |
| `engine_a_check_freshness`        | `mesh:checkFreshness`      | `mesh:FreshnessReport`    |
| `engine_a_filter_by_tag`          | `mesh:filterByTag`         | `mesh:TagFilterResult`    |
| `engine_a_describe_asset`         | `mesh:describeAsset`       | `mesh:AssetProfile`       |

`mesh:filterByTag` carries the cross-feature predicate reasoning
pattern (compose tag-match + optional secondary condition like
exposure to a downstream dashboard). PII is one instance — the verb
is general enough to cover any tag-conditional query, not just
PII-exposure audits. `mesh:describeAsset` covers the "tell me about
X" question shape that doesn't fit any single-attribute lookup.

The existing `engine_a_restate_analyst` registration with verb
`mesh:analyzeWithCodeAgent` and output `mesh:AgentResponse` is
**retained as a fallback** for the transition period. Queries that
don't match any specific verb's synonyms still route to it. Once the
specific verbs cover the observed query distribution (validated via
the ADR-0015 audit table), the fallback is removed.

`input_uri` for all six new verbs is `mesh:CatalogAssetQuery` (a new
narrow type — name of the asset plus optional asset class). Agents
that produce CatalogAssetQuery inputs from natural language live in
cortex-bff; that conversion already happens implicitly when the
agent's smolagent loop normalizes the user's question.

### 2. Per-verb prompts in Engine A

Today Engine A has one universal system prompt with a mix of
reasoning patterns layered into it: the recursive-lineage pattern,
the cross-feature-predicate pattern, the anti-pollution rule for
Mem0, the URN-grounding rule. Each pattern fires only on a subset of
questions but lives in the prompt for all questions.

Post-ADR-0017, the per-verb prompts contain only the reasoning
patterns relevant to that verb:

- `mesh:traceLineage` prompt: includes the recursive-lineage walking
  pattern; excludes the cross-feature predicate pattern.
- `mesh:auditPIIExposure` prompt: includes the cross-feature
  predicate pattern (must satisfy `tags=pii` AND
  `exposed_to_dashboard`); excludes recursive lineage.
- `mesh:lookupOwnership` prompt: short, focused on ownership field
  lookup. Excludes both.

A small shared header still applies to every verb (URN grounding,
anti-Mem0-pollution from [ADR-0016](ADR-0016-mem0-fact-vs-inference-boundary.md),
tool-use mechanics). Verb-specific prompts compose with the header
at request-handling time.

The inbound mesh task envelope already carries the routed verb (per
ADR-0004's routing contract). Engine A's request handler reads it,
selects the matching prompt block, and runs the smolagent loop.

### 3. Every final_answer echoes its `output_uri`

`AgentFinalResponse` (the inline pydantic schema each engine
declares in its system prompt for the agent to populate via
`final_answer()`) gains an `output_uri` field. During the
transition window the field is **optional** in the wire-level
`AgentResponse` (Engines DA, W, and any future engines may not have
been migrated yet); engines that emit it carry it as an extra key
alongside the canonical `AgentResponse.model_dump()`. Engine F
treats a missing `output_uri` as a signal to fall back to legacy
BAML `DesignUI` for that request (per §6 below), so omission is
recoverable. The field becomes required once every engine in the
fleet has been migrated and the audit table shows no missing
echoes for two consecutive weeks.

```python
# Inline schema in the agent prompt:
class AgentFinalResponse(BaseModel):
    status: str
    summary_text: str
    structured_data: Optional[Dict[str, Any]]
    output_uri: str  # NEW — agent echoes this verb's declared output shape
```

For Engine A, the per-verb prompt instructs the agent to set
`output_uri` to that verb's declared output (the prompt provides the
literal string; the agent just echoes it). For Engine DA, Engine W,
and any other engine, the same pattern when they are migrated: the
prompt instructs the agent to echo the engine's declared
`output_uri` in every final_answer.

The wire-level `AgentResponse` BAML class will eventually grow an
`output_uri string?` field, but that change requires BAML
regeneration touching multiple downstream consumers; the transition
during the ADR-0017 rollout passes `output_uri` as a top-level dict
key on the HTTP response, outside the pydantic-typed payload.
Cortex-bff reads it with `response.get("output_uri")`. When the
BAML migration lands, the dict-key approach becomes
schema-validated automatically without any consumer-side change.

This makes the response **self-describing**. Downstream consumers
(Engine F, the audit table, future engines that chain on this one)
don't need to look up the engine's registration to know what shape
came back — the shape is in the response.

It also makes drift detectable. The routing audit table records
both the declared `output_uri` (from the registration) and the
echoed `output_uri` (from the response). When an engine's code
quietly evolves to return a different shape but the registration
isn't updated, the audit table shows mismatched rows.

### 4. `register_presentation_to_mesh` helper

A new helper in `agent_fleet/utils/mesh_registration.py` mirrors
`register_engine_to_mesh` exactly, with three differences:

- `mesh_tool_kind = "Presentation"` instead of `"Engine"`.
- The semantic fields name an SPO triple, not a verb edge:
  - `mesh_subject_uri` — the output shape this presentation can
    render (e.g. `mesh:OwnershipFact`).
  - `mesh_predicate_iri` — always `mesh:rendersAs`.
  - `mesh_object_uri` — the archetype IRI (e.g. `mesh:KnowledgeDocument`).
  - `mesh_archetype` — the BAML archetype name string (e.g.
    `"KNOWLEDGE_DOCUMENT"`), used by Engine F to hydrate the BAML
    call after lookup.
  - `mesh_expected_fields` — JSON-encoded list of fields the
    presentation expects to find in `structured_data`.
- No `endpoint_url` — the presentation isn't a callable peer; it's a
  capability advertised by Engine F (or by any other component that
  can render shapes).

Doc-tools' `aitool_registration_sensor` already filters on
`mesh_is_registration=true` and is indifferent to `mesh_tool_kind`.
Presentation triples flow into Weaviate alongside engine triples.

### 5. Engine F advertises its capabilities at startup

Engine F's FastAPI lifespan calls `register_presentation_to_mesh`
once per capability:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    for subject_uri, archetype_name, fields in PRESENTATION_CAPABILITIES:
        register_presentation_to_mesh(
            name=f"presentation_{archetype_name.lower()}_for_{slug(subject_uri)}",
            description=f"Renders {subject_uri} as {archetype_name}",
            subject_uri=subject_uri,
            object_uri=f"mesh:{pascal_case(archetype_name)}",
            archetype=archetype_name,
            expected_fields=fields,
            persona_fit=PERSONA_FIT[archetype_name],
            domain_fit=DOMAIN_FIT[archetype_name],
        )
    yield
```

The initial capability table covers the nine known shapes:

```
mesh:OwnershipFact              → KNOWLEDGE_DOCUMENT
mesh:LineageTopology            → PROCESS_TOPOLOGY
mesh:ImpactSet                  → KNOWLEDGE_DOCUMENT  (table-flavored)
mesh:SchemaDescription          → KNOWLEDGE_DOCUMENT
mesh:FreshnessReport            → ASSET_STATE_METRIC
mesh:TagFilterResult            → HAZARD_DECLARATION  (default; PII-flavored)
mesh:AssetProfile               → KNOWLEDGE_DOCUMENT
mesh:DatasetAnalysisReport      → CHART_WIDGET        (Engine DA)
mesh:KnowledgeRetrievalResponse → KNOWLEDGE_DOCUMENT  (Engine W)
```

`mesh:TagFilterResult` maps to `HAZARD_DECLARATION` by default to
preserve PII-audit semantics; a future per-persona triple can route
non-sensitive tag filtering to `KNOWLEDGE_DOCUMENT` for the same
output URI (see the persona-scoped renderings open item).

Adding a ninth capability (or remapping `mesh:OwnershipFact` to a
new "OwnershipCard" archetype for the OPS persona) is a registration
change, not a code change.

### 6. `/render_ui` becomes a predicate lookup

The new request shape carries the output URI:

```python
class RenderRequest(BaseModel):
    raw_data: ...
    output_uri: Optional[str] = None  # NEW
    user_persona: Optional[str] = None
    persona: Optional[str] = None      # legacy
    domain: Optional[str] = None       # NEW
```

The handler:

```python
@app.post("/render_ui")
async def render_ui(request: RenderRequest) -> Any:
    if request.output_uri:
        triples = await mesh_search_predicates(
            subject=request.output_uri,
            predicate="mesh:rendersAs",
            persona_hint=request.user_persona,
            domain_hint=request.domain,
            top_k=1,
        )
        if triples:
            chosen = triples[0]
            return await baml_render_constrained(
                archetype=chosen.archetype,
                expected_fields=chosen.expected_fields,
                raw_data=request.raw_data,
            )
    # Fallback: legacy path when output_uri is missing OR no triple matches
    return await b.DesignUI(json.dumps(request.raw_data), effective_persona)
```

`baml_render_constrained` populates a known archetype shape from
`structured_data` without asking the LLM to choose an archetype.
Either it's a direct field-by-field mapping (mechanical) or a tiny
BAML prompt scoped to "fill in the fields of this specific
archetype" (no choice). The architectural LLM call that used to make
the archetype decision is gone.

### 7. cortex-bff threads `output_uri` end-to-end

cortex-bff already collects the agent's final response and forwards
it to Engine F. The change is one extracted field:

```python
# In cortex-bff's orchestration loop, after engine call returns:
output_uri = engine_response.get("output_uri")  # NEW
render_response = await engine_f_client.render_ui(
    raw_data=engine_response,
    output_uri=output_uri,
    user_persona=user_persona,
    domain=task_envelope.domain,
)
```

If a legacy engine doesn't echo `output_uri`, the field is `None`
and Engine F falls back to BAML's DesignUI as before. No breakage.

### 8. The audit table records two decisions per request

Per ADR-0015, the routing-decisions audit table currently records
one row per request: the engine routing decision. Post-ADR-0017 it
records two:

| request_id | step             | input             | declared_uri | echoed_uri | chosen_target |
|------------|------------------|-------------------|--------------|------------|---------------|
| `r-1234`   | engine_routing   | "who owns X?"     | —            | —          | `mesh:lookupOwnership` → `engine_a_lookup_ownership` |
| `r-1234`   | presentation     | `mesh:OwnershipFact` | `mesh:OwnershipFact` | `mesh:OwnershipFact` | `KNOWLEDGE_DOCUMENT` |

The presentation step's `input` is whatever the engine echoed as
`output_uri`. `declared_uri` is the registration value; `echoed_uri`
is the value the engine actually returned. Mismatch is a flag.

The L1 regression canary (per ADR-0015) gains a second axis: for each
canonical question the engine claims to handle, the canary also asks
"and did the presentation we got match the expected archetype?"
Presentation drift becomes detectable on the same cadence as
routing drift.

## What this retires

- **The classifier-as-bootstrap idea floated mid-discussion.** I had
  proposed Engine F LLM-classifying the data shape when no
  `output_uri` is present. That puts inference back into a system
  that's designed for declaration. With every engine declaring its
  `output_uri` and the predicate graph holding the renderings, the
  classifier is unnecessary. The fallback to `b.DesignUI` covers
  legacy callers; the long-term path is no classifier anywhere.
- **`mesh:AgentResponse` as a registry value.** Once Engine A's
  fallback registration is removed, no engine in the fleet declares
  a generic output. The audit table will hard-flag any
  `mesh:AgentResponse` value as a registration that hasn't been
  migrated.
- **`mesh:AgentTask` as a registry value.** Same rationale for
  inputs. Each verb's `input_uri` is specific to its question shape.
  Eight verbs across the fleet, eight specific input types, none
  generic.
- **The BAML LLM's role in archetype selection.** BAML keeps the
  archetype *shapes* (the typed component classes); it stops doing
  the *choosing*. The choosing moves to the predicate graph. BAML's
  remaining job is mechanical: given a chosen archetype and the
  structured data, populate the archetype.

## Alternatives considered

### Keep the generic verb, add a classifier in Engine F (rejected)

The proposal I floated and then walked back. Engine F LLM-inspects
the response data shape and picks an archetype. Same end result —
the LLM is still choosing — just moved one component over. Rejected
because the registry was designed to make this kind of inference
unnecessary; adding it back was reverting to ADR-0012's failure
mode.

### Embed `output_uri` in `structured_data` instead of as a top-level
final_answer field (rejected)

Carry the shape inside the payload (e.g.
`structured_data["@type"] = "mesh:OwnershipFact"`). Less wire-shape
churn — no new pydantic field.

Rejected because the wire-shape churn is trivial (one field on a
class every engine subclasses already), and a top-level field is
inspectable by middleware (cortex-bff, the audit logger, future
schema validators) without parsing the payload. Embedded `@type` is
also easier to forget or mis-emit; a required top-level field fails
the response validation immediately.

### Schema validation of the echoed `structured_data` against
`expected_fields` (deferred)

When Engine F looks up `mesh:OwnershipFact → KNOWLEDGE_DOCUMENT` and
its triple says `expected_fields=["asset_name", "owner_email",
"owner_team", "owner_since"]`, validate that the response actually
contains those fields. Reject or fall back if not.

Deferred because the validation framework crosses into BAML's
territory and we want one architectural change at a time. Phase-2
follow-up: wire a strict-validation mode that the audit table can
turn on for canary requests.

### Materialize presentation triples in a separate Weaviate
collection (rejected)

A `Presentation` collection separate from `Predicate`. Cleaner
namespacing.

Rejected because the whole point is that engine routing and
presentation routing are the same operation against the same store.
Splitting collections requires Engine F to query a different
endpoint and dilutes the "one substrate, many predicates" property
that ADR-0004 was set up to provide. The `mesh_tool_kind` field
provides the namespacing without the split.

## Open items

- **`mesh:CatalogAssetQuery` schema.** The narrow input type for the
  six Engine A verbs needs a concrete pydantic. Probably
  `{asset_name: str, asset_class: Optional[str]}` plus a domain hint.
  Defined in the SDK alongside the output-shape vocabulary.
- **Multi-archetype responses.** Some answers are best presented as
  a combination (a lineage diagram *plus* an ownership card). The
  predicate-graph lookup currently returns one triple; either the
  return shape needs to support N triples and Engine F composes them,
  or we mint composite output URIs like
  `mesh:LineageWithOwnership` that map to a single composite
  archetype. The composite-archetype path is cleaner; deferred for
  the post-MVP iteration.
- **Persona-scoped renderings.** Today the persona influences ranking
  but doesn't change the archetype. Eventually
  `mesh:OwnershipFact` for `DATA_STEWARD` may render differently
  than for `OPS_OPERATOR` — that's two triples competing on the
  same subject with different persona affinities. The lookup already
  supports this; the capability table just needs to be enriched.
- **Removal of the generic Engine A fallback.** When the audit table
  shows the specific verbs cover >95% of routed traffic for two
  consecutive weeks, the `engine_a_restate_analyst /
  mesh:analyzeWithCodeAgent` registration is removed. The threshold
  and observation window are placeholders; finalize once we have a
  week of post-deploy data.
- **Engine W and Engine DA migration.** Both already declare specific
  output URIs in their registrations; they need the
  final_answer-echo change and verification that their declared
  shapes match what they return. Small per-engine PRs, parallelizable.
- **~~Harden the non-document archetype hint into a true constraint.~~ (RESOLVED 2026-06-04)**
  Originally the matched capability's archetype was appended to the
  persona string as `f"{persona}::REQUIRED_ARCHETYPE={archetype}"` —
  a soft prompt bias that the BAML LLM happened to honor in Runs
  7–10 but with no architectural guarantee. **Resolution:** added
  four per-archetype BAML functions —
  `RenderAsTopology(raw_data, persona) -> TopologyUI`,
  `RenderAsHazard(...) -> HazardUI`,
  `RenderAsMetric(...) -> MetricUI`,
  `RenderAsChart(...) -> ChartUI`
  — whose return types ARE the specific archetype class, not the
  `DashboardUI` union. The LLM cannot return a different shape; it
  can only populate fields of the one chosen by the predicate-graph
  lookup. Engine F's `_render_archetype_hardened` dispatches to the
  matching function. Falls back to legacy `DesignUI` for archetypes
  with no hardened function (e.g. `DIGITAL_TWIN_3D` until needed) or
  when no capability triple matches at all.
- **~~Surface which presentation path served each request.~~ (RESOLVED 2026-06-04)**
  Engine F now emits an `X-Presentation-Path` response header on
  every `/render_ui` call with one of four stable values:
  `deterministic-document`, `archetype-hardened`, `fallback-designui`,
  or `fallback-no-output-uri`. Cortex-bff's supervisor reads the
  header and surfaces it in the Dagster `Output.metadata` as
  `presentation_path`, ready to be recorded by the ADR-0015
  `routing_decisions` audit table when it lands. Alerting target:
  `fallback-*` exceeding a threshold indicates capability-coverage
  drift — engines emitting output URIs Engine F doesn't have a
  capability triple for — and is the early-warning signal for ADR-
  0012 regression.

## Out of scope

- The Mem0 fact-vs-inference split ([ADR-0016](ADR-0016-mem0-fact-vs-inference-boundary.md)).
  Orthogonal: presentation drift and memory drift are different
  failure modes; both ADRs proceed independently.
- The router observability layer ([ADR-0015](ADR-0015-router-regression-L1.md)).
  This ADR extends the audit-table schema by one row type; the
  observability and canary machinery stays as-is.
- Frontend chrome (React component library, theming, layout).
  Archetype selection is upstream of those concerns.
