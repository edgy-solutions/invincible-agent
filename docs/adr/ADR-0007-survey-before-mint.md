# ADR-0007 — Survey existing ontologies before minting `mesh:` concepts

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) (establishes the
    need for system-level concepts like *aggregated raw data*, *UI
    instruction*, *routing trace*)
  - [ADR-0005](ADR-0005-verb-and-concept-namespaces.md) (the two-class
    namespacing this ADR's survey rule operates inside)

## Context

[ADR-0004](ADR-0004-predicate-graph-routing.md) deferred the question of
what concepts compound workflows should terminate in. Engine F
(presentation) takes "raw aggregated data" and produces "UI components."
Neither side is a real-world domain concept. ADR-0004 proposed minting
`mesh:RawAggregatedData` and `mesh:UIInstruction` as platform concepts.

That proposal was caught as lazy: **existing ontologies already cover
much of this surface**, and minting parallel `mesh:` vocabulary
unnecessarily hurts interoperability and inflates the platform's
maintenance burden. The team flagged Apple's App Intents framework in
particular, plus the W3C / Schema.org standards.

The platform's existing UI archetypes (`PROCESS_TOPOLOGY`,
`HAZARD_DECLARATION`, `ASSET_STATE_METRIC`, `KNOWLEDGE_DOCUMENT` per the
Engine F architecture) were minted as `mesh:`-style platform concepts
without surveying standards. Some of them map cleanly to existing
vocabularies; others don't. We need a written rule about how to make
that determination going forward, applied retroactively where useful.

## Decision

**Survey before mint.** Before any `mesh:` concept (or `mesh:` verb) is
created for a system-level operation or output, the platform team must
survey the following ontologies in this order. The first match wins:

### 1. Apple App Intents framework

Apple's structured ontology for intents/actions in Siri, Shortcuts, and
system integration. The conceptual model maps directly to the SPO
substrate of [ADR-0004](ADR-0004-predicate-graph-routing.md):

- `AppIntent` — the verb. Categories include `OpenIntent`,
  `PerformIntent`, `QueryIntent`, `MediaIntent`, `SearchIntent`,
  `ForegroundContinuableIntent`.
- `AppEntity` — typed subjects/objects with semantic identity.
- `IntentParameter` — typed parameters with resolution, including the
  `DynamicOptionsProvider` pattern that maps cleanly to BAML
  TypeBuilder.
- Has the same SPO shape: intent (verb) + entity (subject) + parameters
  (typed inputs).

The Swift-macro implementation is iOS-only, but the **conceptual
vocabulary** (intent categories, entity semantics, parameter
resolution) is portable. When the mesh needs a system-level verb
category, check App Intents first.

### 2. Schema.org Actions

W3C-blessed, JSON-LD friendly, widely adopted via Google's structured
data ecosystem. `Action` is the parent type with subtypes including:

- `BuyAction`, `ChooseAction`, `CommunicateAction`, `MoveAction`,
  `OrganizeAction`, `PlayAction`, `SearchAction`, `ConsumeAction`,
  `AssessAction`, `TradeAction`
- Each Action has `agent`, `object`, `result`, `instrument`, `target`,
  `participant` properties — full SPO with context

Action statuses (`PotentialActionStatus`, `ActiveActionStatus`,
`CompletedActionStatus`, `FailedActionStatus`) map cleanly to mesh
routing states.

### 3. W3C Activity Streams 2.0

The "Subject performs Activity on Object" model is literally SPO at the
wire level. JSON-LD. Used by ActivityPub (Mastodon, etc.).

- Activity types: `Create`, `Update`, `Delete`, `Question`, `Announce`,
  `Listen`, `View`, `Follow`, `Accept`, `Reject`
- `actor` / `object` / `target` / `result` properties

Most relevant when the mesh emits external-facing activity records or
when a domain concept maps cleanly to one of the Activity types.

### 4. W3C SOSA (Sensor / Observation / Sample / Actuator)

For telemetry, sensor readings, observed properties, time-series
measurements. `sosa:Observation` has `hasFeatureOfInterest`,
`observedProperty`, `hasResult`, `resultTime`. Maps directly to
"Engine X observed value Y about asset Z at time T" workflows.

### 5. Broader Schema.org vocabulary

For entities (not actions): `schema:Article`, `schema:Dataset`,
`schema:HowTo`, `schema:CreativeWork`, `schema:Person`, etc. Used for
the outputs of compound workflows — what the mesh *produces* rather
than what it *does*.

### 6. Mint `mesh:`

Only when none of the above covers the case. When minting:

- Add a one-line entry to `docs/adr/minted-concepts.md` (created the
  first time it's needed) with:
  - the new URI
  - the date
  - the PR or ADR justifying it
  - the ontologies surveyed and why each was rejected
- The minted concept enters the platform namespace per
  [ADR-0005](ADR-0005-verb-and-concept-namespaces.md) governance.

### Retroactive mappings (proposed)

The existing mesh UI archetypes get reconsidered against this rule.
Proposed mappings:

| Current archetype | Recommended mapping | Notes |
|---|---|---|
| `KNOWLEDGE_DOCUMENT` | `schema:Article` (or `schema:CreativeWork` for less prose-like outputs) | Clean fit; rendered markdown is a `schema:Article` with text/html encoding |
| `ASSET_STATE_METRIC` | `sosa:Observation` | Telemetry maps directly; the table fields become `sosa:observedProperty` + `sosa:hasResult` |
| `PROCESS_TOPOLOGY` | `schema:HowTo` (with `step` array) OR reference an external `bpmn:Process` | `schema:HowTo` covers sequential steps; BPMN reference for full process semantics with gateways |
| `HAZARD_DECLARATION` | `schema:Action` subtype with `actionStatus: PotentialActionStatus`, severity in custom properties | Or stay `mro:HazardDeclaration` if the MRO ontology has it — investigate before deciding |
| `mesh:RawAggregatedData` (proposed in ADR-0004 draft) | `schema:Dataset` (with `distribution` and `variableMeasured`) | Cleaner than minting `mesh:` |
| `mesh:UIInstruction` (proposed in ADR-0004 draft) | App Intents' `PerformIntent` shape for the *intent*, Schema.org structured data for the *content* | Decomposes into two existing-vocabulary concepts |
| Engine F's `DesignUI` verb | `apple:PerformIntent` shape (subject = data aggregate, action = render, target = persona) | Conceptual fit is exact; mesh verb name still uses `mesh:` per ADR-0005 |

These mappings are proposals, not decisions — each gets reviewed when
the corresponding migration commit lands. The point is that the
retroactive sweep happens *before* the predicate graph is populated
with mesh-only concepts that have to be unwound later.

## Consequences

**Wins:**

- **Mesh outputs become interoperable.** A third-party agent consuming
  JSON-LD with `schema:Action` can ingest mesh activity records without
  learning a parallel `mesh:` vocabulary. Same for `sosa:Observation`,
  `schema:HowTo`, etc.
- **Reduces vocabulary drift.** New tool authors have a survey order
  instead of a blank canvas. The choice "use `mesh:` or not" gets
  pushed through the same questions every time.
- **The platform's maintenance surface shrinks.** Concepts that already
  exist in standards-body ontologies don't need to be defined,
  documented, or evolved in the iagent repo.
- **External standards do the platform team's homework.** App Intents,
  Schema.org Actions, etc. have been refined by smart people for years.
  Reusing them imports that thinking.
- **Engine F's existing archetypes get a path to standards alignment.**
  The retroactive mapping table is a concrete migration plan.

**Costs:**

- **Survey adds friction to new concept minting.** Five ontologies to
  check, even when the answer is obvious. Mitigation: experienced
  reviewers can speed-check; the `minted-concepts.md` log captures the
  reasoning so subsequent similar cases reuse the decision.
- **Some ontologies are conceptually portable but not directly usable.**
  Apple App Intents is iOS-only at the implementation level; we reuse
  its conceptual vocabulary but not its API. Documenting this
  distinction at each mapping is small overhead.
- **Schema.org is large and inconsistent in places.** Picking the right
  Action subtype isn't always obvious. Same for `schema:CreativeWork`
  subtypes. Mitigation: when in doubt, the broader parent type
  (`Action`, `CreativeWork`) is acceptable; refining to a subtype can
  happen later without breaking compatibility.
- **The retroactive mapping table is opinion, not decision.** Each
  archetype's migration is its own follow-up — `KNOWLEDGE_DOCUMENT →
  schema:Article` is *probably* right but needs the Engine F team to
  confirm before the predicate graph absorbs it.

## Alternatives considered

- **Mint everything in `mesh:`** (status quo before this ADR).
  Rejected. Loses interoperability; parallels existing standards;
  inflates the platform's maintenance burden; reproduces work others
  have already done.

- **Adopt one ontology end-to-end** (e.g., commit fully to Activity
  Streams). Rejected. No single standard covers all the mesh's cases.
  Activity Streams is great for activity records but doesn't help with
  observations (SOSA does). Schema.org Actions covers verbs well but
  not telemetry. The right answer is *multiple standards in a defined
  order*.

- **Survey but don't require justification for minting.** Rejected.
  Without the `minted-concepts.md` log, the rule degrades to "consider
  the standards" and gets quietly skipped under time pressure.

- **Defer the decision (ad-hoc case-by-case in code review).**
  Rejected. Leaves the choice unprincipled; vocabulary drifts; the
  retroactive cleanup gets bigger over time.

- **Mandate exactly one survey ontology per concept category** (e.g.,
  "all verbs from App Intents, all entities from Schema.org"). Rejected
  as too rigid — the right standard depends on the concept. SOSA for
  observations, Activity Streams for activity records, schema.org for
  entities. The ordered survey rule is the flexible version.

## Indicators for revisiting

- **An ontology emerges that subsumes multiple of the recommended
  ones.** Unlikely soon; would require a W3C-or-equivalent unification
  effort. If it happens, the survey order collapses.
- **Apple App Intents becomes Swift-only conceptually as well as
  implementationally.** Currently the conceptual model is portable; if
  Apple's evolution makes it iOS-specific even at the modeling layer,
  it falls out of the recommended survey order.
- **The `mesh:` namespace grows large enough** despite the survey rule
  to need internal subnamespacing. At that point ADR-0005's note on
  partitioning `mesh:` activates and we revisit how minted concepts
  cluster.
- **A `mesh:` concept proliferates because nothing in the survey
  order fits.** At that point a follow-up ADR may carve out a new
  internal subnamespace or admit that the concept genuinely is novel
  and document its definition formally.

## Tracking file

`docs/adr/minted-concepts.md` is created on first `mesh:` mint that
follows this ADR. Format:

```
| URI | Date | PR / ADR | Surveyed (rejected) | Reason for mint |
| --- | ---- | -------- | -------------------- | --------------- |
| mesh:FanOutResult | 2026-MM-DD | #NNN | App Intents (no fan-out result type), schema.org Action (results are single, not parallel) | Mesh-specific multi-engine result aggregation; no external equivalent |
```

One row per mint. Grows over time. The file itself is part of the
governance record.
