# ADR-0009 — Sunset persona / domain / intent as classification axes

**Status:** Proposed
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) (SPO/predicate model;
    this ADR finishes the work ADR-0004 started by removing the
    classification layer the predicate graph was meant to replace)
  - [ADR-0005](ADR-0005-verb-and-concept-namespaces.md) (`mesh:` vs
    domain namespaces; domain-as-scope rests on this)

## Context

ADR-0004 reframed tools as predicates and stood up predicate-graph
routing. But the legacy three-axis classifier — persona × domain ×
intent — still runs in front of it. Engine O's
[`/route_and_plan`](../../agent_fleet/ontology_service/main.py) endpoint
does 6 × 5 × 5 = 150-cell BAML classification per request, the gateway
routes on the resulting `intent`, the supervisor's
[`if domain ==`](../../src/iagent/defs/dynamic_supervisor.py) switch
chooses an engine URL, and engines pick a response shape by `persona`.

The fragility this caused was the explicit motivation for ADR-0004, and
fixing the production duplicate-runs bug (commit 3226da2) made it
unavoidable to confront that the classifier itself is the round-hole
problem — modernizing it (Step E/F as originally drafted) only changes
the *form* of the enums (dynamic, graph-derived) without retiring the
*function* (3-axis classification).

We must reach a verdict on each axis: does it still earn its keep, and
if so, in what role.

### Per-axis verdict

**Intent (5-way enum, classified per request).**
Four of the five values — `DIAGNOSTIC_AND_REPAIR`, `STRUCTURAL_QUERY`,
`KNOWLEDGE_RETRIEVAL`, `SYSTEM_META_AND_REJECTION` — collapse into "the
user query matched predicate X." The predicate-graph match IS the
intent classification at finer resolution. Only `PROCESS_CREATION` is
genuinely different: it's a multi-turn interactive mode (ProcessInterviewer
on Restate), not a one-shot verb invocation. And it won't stay alone —
there's a whole class of conversational engines that aren't BPMN-build
(interview-style data clarification, multi-step troubleshooting,
collaborative authoring) waiting to land.

So intent's real job is **a binary discriminator**: *conversational vs.
one-shot*. Inside the conversational branch we fan out (interviewer,
future conversational engines) using the same predicate-graph mechanism,
just keyed by a different mode hint. There is no useful middle ground;
N-way intent classification is the wrong abstraction.

**Domain (5-way enum, hardcoded routing key).**
Two jobs are conflated in one field:

| Job | Replacement |
|---|---|
| **Routing** — `if domain == "DATA_ENGINEERING"` → Engine DA, `MAINTENANCE/MANUFACTURING` → Engine E, else → Engine A | The `/find_tool` predicate-graph match. Domain is not a routing key; the matched verb's owner is. |
| **Scope / authz** — Engine W's strict per-collection segregation, Engine E's per-tenant graph context | This is real and stays. Domain becomes a **scope filter** on top of predicate match. |

The routing job is the source of the `if/then` exceptions we kept piling
on; the scope job is the legitimate use. **Engine DA must not be a
special case** — `DATA_ENGINEERING` is a domain scope like any other.
Engine DA registers as serving the `DATA_ENGINEERING` domain (and any
other dataset-bearing domain it onboards); `/find_tool` finds it the
same way it finds Engine E or W.

**Persona (6-way enum, classified per request).**
The current code conflates two distinct concepts that we now call
explicitly:

- **User persona** (caller-side) — *who is asking*. Drives entitlements
  (which domains they can scope into), UI preferences, default response
  archetype. **Source: identity provider claims** (PingSSO), not the
  user's query text. Classifying persona from a query is guessing what
  the operator's job is; the JWT already says.
- **Answerer persona** (engine-side) — *what voice/shape the engine
  uses to respond*. Engine E returns `MechanicResponse |
  AuthoringResponse | LogisticsResponse | AuditResponse | DataStewardResponse`
  (BAML union at
  [contracts.baml:159-199](../../baml_shared/baml_src/contracts.baml));
  Engine F renders persona-specific UI components. This stays —
  per-engine output polymorphism is a real feature. **Source: the
  matched predicate** (`owner_persona`, already on every engine
  registration) or the caller's identity-derived persona, in that order.

The current classifier predominantly drives the answerer persona but
treats it as if it were the user persona. This was the source of
confusion in past sessions; this ADR makes the two distinct.

## Decision

The persona / domain / intent classification axes are retired as a
routing primitive. The replacements:

1. **Intent becomes a binary `mode`**: `one_shot` (default) or
   `conversational`. Engine O publishes this; the gateway uses it as a
   path discriminator (predicate-graph vs. ProcessInterviewer-style
   handler). Adding a new conversational engine is a registration —
   not a code edit to a 5-value enum.

2. **Domain becomes a scope, not a routing key.** Engines declare their
   served domain(s) on registration (already true via
   `mesh_registration.py`). `/find_tool` filters predicate matches by
   the user's entitled domains. Engine DA registers as a normal domain
   citizen; the `if domain == "DATA_ENGINEERING"` branch is deleted.

3. **Persona splits into two named concepts:**
   - **User persona** — sourced from identity-provider claims, surfaced
     through the JWT, available to all engines via `ctx.user`.
   - **Answerer persona** — sourced from the matched predicate's
     `owner_persona` registration field (already in DataHub); falls
     back to the user persona if the predicate is persona-agnostic.

4. **Engine O's `/route_and_plan` is rebuilt** as a verb-extractor +
   predicate-matcher: input → `(candidate_verb, arguments, entity_refs,
   mode)`. No 150-cell classification. The output feeds `/find_tool`
   directly. The legacy `MASTER_PERSONAS` / `MASTER_DOMAINS` /
   `MASTER_INTENTS` dicts in
   [`ontology_service/main.py`](../../agent_fleet/ontology_service/main.py)
   are deleted; **personas and domains become graph view-functions** —
   Cypher reads against the predicate registry, not Python constants.

5. **The `domain ==` switch at
   [`dynamic_supervisor.py:143-175`](../../src/iagent/defs/dynamic_supervisor.py)
   is replaced** with `/find_path` calls + a step iterator (this
   subsumes the originally-planned Step D.2).

## Consequences

**Wins:**

- One routing mechanism. Adding an engine no longer requires editing
  three different Python dicts and a `if/elif` chain.
- Engine DA stops being a special case. New "domains" can be
  onboarded by registering a domain-scoped engine, period.
- "Conversational" becomes a real, extensible engine class — the
  BPMN interviewer is the first of several planned, not the only
  exception in an N-way enum.
- Persona-from-identity is auditable: a MECHANIC viewing AUDITOR
  output is now a deliberate elevation, not a query-classifier
  mistake.
- Engine O's classification latency disappears; verb extraction is a
  smaller LLM job than 6 × 5 × 5 axis labeling.

**Costs:**

- Engine O's `RouteAndPlan` BAML function needs a rewrite. The
  existing function and the `MeshRoutingDecision` schema are removed.
- Identity-provider claims must carry at least the user's persona
  (and ideally entitled domains). **Current PingSSO claims are
  insufficient** — see *Open dependencies*. Until claim expansion
  lands, user persona falls back to a default and answerer persona is
  driven by the matched predicate's `owner_persona` alone.
- Engines that read `persona` from the request payload today
  (Engine E, Engine F) must accept the new split: `user_persona` and
  `answerer_persona`. Internal to each engine; not a wire-format
  break if we keep `persona` as an alias to `answerer_persona` during
  migration.
- ADR-0004's "Step E / Step F" wording in
  [`ADR-0004-predicate-graph-routing.md`](ADR-0004-predicate-graph-routing.md)
  is superseded by the migration steps below. ADR-0004's status is
  unchanged (still Accepted) — this ADR builds on it; the original
  "Step E / Step F" plan was an interim sketch that this ADR refines.

## Cortex-UI consequences

A wire-contract audit of [cortex-ui](../../../cortex-ui) against the
ADR-0009 implementation (commits `24ba480` through `1605190`) confirms
**no breaking changes at the wire boundary**. The UI was written
defensively — no hardcoded `"PROCESS_CREATION"` / `"DATA_ENGINEERING"`
/ mode literals, no `task_plan` / `sub_query` references, no JWT
claim introspection. The switch from `intent` to `mode`, the deletion
of the `if domain ==` switch, and the persona split are all invisible
to the UI.

What still works unchanged:

- **SSE event types** (`status`, `context_update`, `chat_message`,
  `ui_payload`, `final_payload`, `stream_end`) and their payload
  shapes — gateway emits the same shapes after this ADR.
- **`/mesh/config` response shape** (`{personas: {NAME: {label, icon,
  color, bg}}, status}`) — we kept the shape; only the *source*
  changed from the hardcoded `MASTER_PERSONAS` dict to the graph
  view-function.
- **`comp.source_persona` on UI components** — Engine F still sets
  it, the canvas attribution badges in
  [`SemanticInterpreter.tsx`](../../../cortex-ui/src/components/registry/SemanticInterpreter.tsx)
  still read it.
- **BPMN compile flow** (`/workflow/compile` and `CompileRequest`) —
  not touched.
- **JWT consumption** — UI only reads `access_token` for Bearer auth;
  `persona` and `entitled_domains` are backend-internal so adding
  them to the JWT (or not, falling back to defaults per this ADR)
  doesn't surface to the UI.

Three subtle behavior shifts the UI may notice — all expected, none
breaking:

1. **The persona roster the UI shows may be smaller.** Old
   `/mesh/config` always returned all six hardcoded personas; new
   `/mesh/config` returns only personas that *own a registered
   predicate*. With the current engine set (A→DATA_STEWARD,
   E→AUDITOR, DA→DATA_STEWARD, W→TECH_WRITER) that's three distinct
   personas. The remaining three appear when an engine registers
   with them as `owner_persona`. This is the right behavior per the
   ADR's "registry is the source of truth" stance, and it's
   self-consistent: `DecomposeQuery` only generates subtasks for
   *registered* personas (it reads them from the same view-function),
   so the UI never gets a `personas` array referencing a persona
   `/mesh/config` doesn't know about.

2. **The supervisor's fallback path (ADR-0008) is invisible at the
   structured-event level.** When ADR-0008's Engine A generalist
   fallback fires, the UI receives normal `ui_payload` and
   `chat_message` events. The fallback signal is in the *chat
   content* — Engine A's preamble says "I am operating as a
   generalist because …" — but no SSE event carries a `fallback_fired`
   flag the UI could use to render a visual badge. Acceptable for v1;
   the gateway can emit a `status` event with `action="fallback_fired"`
   in a later UI-affordance pass if needed.

3. **The `personas` list in the `active_agent_roster` materialization
   reflects `DecomposeQuery`'s plan, not the actual answerer.** Engine
   selection happens at `execute_subtask` time via `/search_predicates`;
   the predicate's `owner_persona` may differ from the
   `target_persona` Engine O's `DecomposeQuery` assigned. The UI's
   "active personas" chips are a *planning hint*, not ground truth.
   This pre-dates ADR-0009 — the old `if domain ==` switch had the
   same divergence — and is not made worse by this ADR.

One UI-side cache consideration worth flagging (not blocking): the
`/mesh/config` fetch in
[`AgentTeamLoader.tsx`](../../../cortex-ui/src/components/NeuralStream/AgentTeamLoader.tsx)
is a one-shot on mount. If the registry adds an engine mid-session,
the UI's `personaConfig` is stale until reload. Today the registry
rarely changes mid-session so this is a non-issue, but with predicate-
graph routing live and DataHub-fed it's a known limit. Easy fix when
relevant: `refetchInterval` on the React Query.

## Alternatives considered

- **Keep the three-axis classifier and just dynamic-source the enums
  from the graph (Step E / Step F as originally drafted).** Rejected.
  Modernizes the form without retiring the function; leaves the
  `if domain ==` switch and the persona-as-classifier confusion in
  place. The square-peg verdict.
- **Keep `intent` as a 5-value enum but make Process_Creation a
  special-case flag elsewhere.** Rejected. Same square peg; we'd just
  ship a 4-value enum that still requires a code edit per new
  conversational engine.
- **Source user persona from a separate API rather than identity
  claims.** Rejected as a primary mechanism — claims are the right
  source (auditable, tied to the auth session, no extra round trip).
  A user-preferences API could overlay claims for non-identity
  attributes (UI theme, default domain scope), but it is not the
  source of truth for *who the user is*.
- **No-op (leave the classifier in place).** Rejected. The user has
  confirmed there is no production deployment of the current
  classifier — the duplicate-runs bug fixed in commit 3226da2 was the
  visible symptom; the underlying fragility is exactly what kept
  this from reaching production. The "risk of breaking prod" cost is
  zero; the risk of *not* doing this is permanent technical debt
  guarding a system that never worked.

## Course correction — Step F'.6 (verb vector store)

During implementation, the user flagged a real gap: the initial F'.1
shipped `/search_predicates` doing *exact Cypher match* on `type(r)` /
`r.iri` / `r.synonyms`, with an LLM-extracted `candidate_verb` as the
input. That has two problems:

1. **Cypher exact-match is brittle.** Plural / tense / phrasing variations
   ("diagnose" vs "diagnoses" vs "troubleshoot vibration") all miss
   unless the synonym list happens to enumerate them. The previous
   3-axis `RouteAndPlan` had a constraint property (BAML TypeBuilder
   enums forced the LLM to pick from a known list); dropping it
   without a replacement reintroduced fragility.
2. **`OntologyClass` already has Weaviate hybrid for nouns.** The
   `/resolve` endpoint maps NL → ontology URI by running BM25 + vector
   over the `OntologyClass` collection. There was no analogous
   collection for verbs (predicates), so nouns got semantic matching
   and verbs did not — an inconsistency that wouldn't have survived
   the first real failure.

**Resolution** — Step F'.6 (the "verb vector store"):

* **doc-tools' AITool sync** also mirrors each registered predicate to
  a Weaviate `Predicate` collection. The vectorized text combines
  the humanized verb form ("queryKnowledgeGraph" →
  "query knowledge graph"), the synonym list, and the mlModel
  description. The Weaviate write runs *after* the Neo4j MERGE and
  is fail-soft — Neo4j stays the system of record.
* **Engine O's `/search_predicates`** runs Weaviate hybrid search
  against `Predicate.search_text`, with the entitled-domains filter
  applied at the vector-store layer (OR of
  `domains contains_any [entitled]` and `domains == []` to keep
  domain-agnostic predicates visible to scoped callers). Weaviate is
  treated as **required routing infrastructure** — the endpoint
  returns 503 if the client or `Predicate` collection is unavailable.
  No Cypher exact-match fallback: the synonym list is unlikely to
  catch what hybrid search missed, the fallback would only trigger
  during an outage that already broke routing system-wide, and a
  silent degraded path obscures the real signal operators need.
  Exact `(subject_uri, verb_label)` lookups belong on `/find_tool`.
* **BAML `ExtractIntent`** is simplified to `{mode, entity_refs}` —
  `candidate_verb` is gone. The supervisor passes each subtask's
  raw NL `sub_query` straight to `/search_predicates`, so the LLM
  no longer has to invent a routing token an embedding model could
  have matched directly.

This is the right architecture from the start. The earlier sketch in
the Migration plan that referenced a `candidate_verb` field
(implicit in "verb-extractor + predicate-matcher") underestimated how
much of the matching work the embedding model could do directly. Both
sides — the doc-tools mirror and the Engine O hybrid path — are
captured in the migration plan below.

## Migration plan

The original Step E / Step F from ADR-0004 are superseded by these
named steps. Step D.2 is folded in.

1. **Step E' — Derive personas and domains as graph view-functions.**
   - Replace `MASTER_PERSONAS` / `MASTER_DOMAINS` dicts in
     `ontology_service/main.py` with Cypher queries against the
     predicate registry.
   - `MASTER_INTENTS` is deleted outright (no replacement enum).
   - Engines already publish `owner_persona` and (via SDK extension)
     a `domains` list on registration; the view-functions read those.

2. **Step F' / D.2 merged — Replace 3-axis classifier and supervisor
   switch with predicate-graph routing.**
   - `RouteAndPlan` (3-axis) → `ExtractIntent` (mode + entity_refs).
     `candidate_verb` is intentionally NOT extracted — see Step F'.6.
   - Gateway routes on `mode`:
     - `conversational` → ProcessInterviewer (current) or future
       conversational engines, picked by predicate-graph match within
       the conversational subgraph.
     - `one_shot` → `/search_predicates` → engine.
   - `dynamic_supervisor.py`'s `if/elif` chain replaced with
     `/search_predicates` → cheapest match.
   - The `domain ==` switch is deleted; no engine is a code special-case.

2b. **Step F'.6 — Verb vector store (Weaviate `Predicate` collection).**
   - doc-tools' AITool sync mirrors each predicate to Weaviate after
     the Neo4j MERGE. `search_text` = humanized verb + synonyms +
     description; deterministic UUID = `verb_iri|input_uri` for
     idempotent upserts.
   - Engine O's `/search_predicates` runs Weaviate hybrid (BM25 +
     vector), with domain scoping at the vector layer (OR-filter to
     keep domain-agnostic predicates visible). Weaviate is required
     routing infrastructure; the endpoint returns 503 if it's
     unavailable rather than silently degrading to exact-match.
   - Supervisor passes each subtask's NL `sub_query` straight to
     `/search_predicates` — no intermediate LLM-extracted verb token,
     no fallback verb hint.

3. **Identity work — expand PingSSO claims.**
   - Catalog what claims are available today (under the *Open
     dependencies* section). Identify the minimum delta to carry
     `user_persona` and (ideally) `entitled_domains`.
   - This is a separate workstream that does not block Step E' or
     Step F' — engines fall back to predicate-derived answerer
     persona until claims expand.

4. ~~**ADR-0008 (deferred routing-fallback policy) is folded into
   Step F'.**~~ **Superseded by [ADR-0008](ADR-0008-routing-fallback-policy.md)
   (2026-05-30).** Step F'.6 answered "what does Engine O return on a
   match?" — it did not answer "what does the supervisor do on a
   miss?" That's a real, separate decision (when to fall back, what
   the fallback does, how operators see it firing) and deserves its
   own ADR. Captured in ADR-0008.

## Open dependencies

- **PingSSO claim audit.** We do not yet know which claims are
  available on the user JWT. The fallback path (predicate-derived
  answerer persona, default user persona) works without this, but
  the full design needs at minimum a stable user-persona claim and
  ideally an entitled-domains claim. Tracked as a follow-up; not a
  blocker for Step E' or F'.

## Indicators for revisiting

- If a use case emerges where engine selection is genuinely
  orthogonal to verb match (i.e., the same verb should fan out to
  different engines based on a non-predicate attribute), revisit
  whether a router-side classifier is needed.
- If conversational mode grows enough internal sub-modes (>5–6) that
  a single binary discriminator becomes ambiguous, revisit whether
  `mode` should fan out into a small enum — but driven by registry,
  not Python constants.
- If PingSSO claim expansion turns out to be permanently impossible
  (organization will not provision them), revisit the user-persona
  source of truth (preferences API vs. server-derived heuristic).
