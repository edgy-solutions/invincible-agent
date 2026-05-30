# ADR-0005 — Two-class namespacing for verbs and concepts in the predicate graph

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) (establishes the
    predicate model; this ADR settles the namespace convention it deferred)
  - [ADR-0006](ADR-0006-verb-registry-location.md) (where the registry lives)
  - [ADR-0007](ADR-0007-survey-before-mint.md) (how to pick existing
    ontologies for system-level concepts before minting `mesh:`)

## Context

[ADR-0004](ADR-0004-predicate-graph-routing.md) establishes the predicate
graph as the routing substrate: tools are named, typed predicates between
concept classes. The verb name carries identity (`mesh:applyDiagnostics`,
`mro:inspectRotor`); the domain/range carries typing (`mro:Symptom`,
`mro:FaultReport`). All three live in URI namespaces.

ADR-0004 deferred the question of *what* the namespace convention should
be. Reviewing the question surfaced a substantive distinction that the
original framing missed:

**Domain verbs name operations that exist in the world.** A mechanic
applies diagnostics whether or not the agent mesh exists. The verb is
recognized by domain experts; it has natural-language definitions,
authoritative provenance, and possibly an entry in a published
ontology (IOF MRO, MIMOSA, etc.). Examples: `mro:applyDiagnostics`,
`mro:inspectRotor`, `logistics:reorderPart`, `compliance:auditProcedure`.

**Platform verbs are implementation projections.** They exist *only
because the mesh exists*: routing the request, fanning out to personas,
synthesizing a multi-engine report, composing a UI payload. A domain
expert doesn't recognize them; they have no real-world existence. They
are system plumbing made visible. Examples: `mesh:routeRequest`,
`mesh:fanOutToPersonas`, `mesh:synthesizeReport`, `mesh:composeUIPayload`.

The same distinction holds for **concepts**. `mro:Symptom` is a real-world
MRO concept; `mesh:RoutingTrace` is a system artifact that exists only
because the mesh produces routing traces.

These two classes have different governance, different validation rules
at registration time, and different external-interoperability implications.
Trying to make one convention serve both produces either an over-strict
platform layer (every `mesh:` verb has to be defended against a domain
ontology) or an under-strict domain layer (anyone can claim
`mro:applyDiagnostics` without justifying themselves against IOF).

## Decision

The predicate graph uses **two namespace classes** for verbs and concepts:

### Domain namespaces

Each domain owns a URI prefix. The domain's ontology process governs:
- What verbs and concepts exist in the namespace
- HITL/schema review for additions
- Authoritative provenance and natural-language definitions
- Possibly external standards alignment (IOF, MIMOSA, ISO/IEC)

| Prefix | Owner / source ontology |
|---|---|
| `mro:` | Industrial Ontology Foundry — Maintenance, Repair, Operations |
| `iof:` | Industrial Ontology Foundry — top-level / shared |
| `mimosa:` | MIMOSA OSA-EAI (Open Systems Architecture for Enterprise Application Integration) |
| `sosa:` | W3C SOSA (Sensor / Observation / Sample / Actuator) |
| `logistics:` | TBD — currently iagent-owned domain ontology; may align with a standards body later |
| `compliance:` | TBD — currently iagent-owned domain ontology |
| (more) | New domain = new prefix entry here, with owner identified |

### Platform namespace

Exactly one: `mesh:`. The platform team owns it. Governance is
lightweight — the team mints new `mesh:` verbs and concepts as the mesh
grows, with a minimal review step (PR + ADR or PR + reference to an
existing ADR for the pattern).

Subject to [ADR-0007](ADR-0007-survey-before-mint.md): **before minting a
`mesh:` concept for a system-level operation, survey existing standards
ontologies** (Apple App Intents, Schema.org Actions, W3C Activity Streams,
SOSA). Reuse where possible; mint `mesh:` only when no existing concept
fits.

### `namespace_authority` property

Every verb and concept registered in the predicate graph carries a
`namespace_authority` property with value `"domain"` or `"platform"`. This
is stored:
- In Neo4j as a property on the `:OntologyClass` node and on the verb edge
- In DataHub as a custom property on the registering entity (aiTool,
  glossaryTerm)
- Implicit from the prefix (everything in `mesh:` is `platform`; everything
  in a domain prefix is `domain`) — but stored explicitly to allow future
  cases the prefix can't disambiguate

### Registration-time validation rules

Different per class:

**Domain registrations** (`mro:`, `iof:`, etc.):
- The verb/concept URI MUST already exist in the domain ontology that
  owns the prefix. doc-tools validates this at the propose stage by
  querying Engine O against the relevant Jena Named Graph
  (`http://internal/mro`, etc.).
- A tool claiming to implement a domain verb is claiming semantic
  conformance with the domain's definition. This is a substantive
  claim; HITL review is the default unless confidence-banded
  auto-approval is configured.
- Unrecognized domain URIs are rejected at the propose stage with a
  clear error: *"The verb `mro:doStuff` does not exist in the MRO
  ontology. Add it through the domain process first, or use the
  `mesh:` namespace if this is platform-internal."*

**Platform registrations** (`mesh:`):
- The verb/concept may or may not yet exist in the platform's small
  internal ontology. If it doesn't, the registration triggers a
  *minted concept* entry in `docs/adr/minted-concepts.md` (one-line
  log: URI, date, ADR or PR justification, surveyed ontologies
  considered).
- ADR-0007's survey-before-mint rule applies.
- HITL review is optional; default is auto-approve for code-controlled
  tools.

## Concrete: how a tool registration validates

A tool registering with `verb="mro:applyDiagnostics"`:

1. SDK lifespan emits the AITool MCP with `verb_iri = "mro:applyDiagnostics"`.
2. doc-tools' `ingest_global_aitool_links` asset picks it up.
3. Validation step queries Engine O / Jena for the MRO Named Graph:
   *"is `mro:applyDiagnostics` defined here?"*
4. If yes → propose. If no → reject with the error message above.
5. Approved propositions sync to Neo4j as predicate edges with
   `namespace_authority: "domain"` on the verb.

A tool registering with `verb="mesh:synthesizeMultiAgentReport"`:

1. SDK lifespan emits the AITool MCP with
   `verb_iri = "mesh:synthesizeMultiAgentReport"`.
2. doc-tools' `ingest_global_aitool_links` picks it up.
3. Platform validation: is this URI already in the platform's
   `minted-concepts.md` log?
   - If yes → propose with auto-approve.
   - If no → require a one-line addition to `minted-concepts.md` as part
     of the registration commit (caught by CI lint, not by doc-tools).
4. Approved propositions sync to Neo4j with `namespace_authority: "platform"`.

## Consequences

**Wins:**

- External interoperability: a non-mesh agent implementing
  `mro:applyDiagnostics` is discoverable by anyone using IOF. Mesh tools
  that claim domain verbs slot into the broader ecosystem.
- Domain experts retain control of their vocabulary. They don't need to
  argue with the platform team about what `inspectRotor` means.
- The platform team retains control of `mesh:`. They don't need to argue
  with domain experts about what `routeRequest` means.
- Registration validation catches typos and unrecognized claims at
  propose time, not at runtime.
- The two-class distinction maps directly onto the propose-approve-sync
  flow's existing HITL hooks: domain registrations default to HITL,
  platform registrations default to auto-approve.

**Costs:**

- Every new domain prefix needs a governance owner identified. We need
  a `docs/adr/namespace-prefixes.md` registry mirroring this ADR's
  table, kept current as new domains are added.
- The MRO/IOF/MIMOSA/SOSA validation requires those ontologies to be
  loaded into Jena (or at least into the OntologyClass collection in
  Weaviate). doc-tools already does this via `ingest_ontology_to_jena`
  — extends to validation, doesn't require new infrastructure.
- Tools written before the convention has been adopted in CI may use
  the wrong namespace. Mitigation: the validation step at the propose
  stage catches it before it reaches Neo4j; the error message is
  actionable.

## Alternatives considered

- **Single namespace (`mesh:`) for everything.** Rejected. Loses domain
  interoperability and forces the platform team to be the arbiter of
  domain semantics they don't own. We tried this implicitly with the
  hardcoded `MASTER_PERSONAS`/`MASTER_DOMAINS`/`MASTER_INTENTS` dicts —
  see ADR-0004's context for what went wrong.

- **Per-tool generated URIs (UUID-based, opaque).** Rejected. Carries no
  semantic content; can't be matched by NL classification; defeats the
  point of an ontology-backed router.

- **One namespace per engine/tool author.** Rejected. The right axis is
  the *workload's domain*, not the implementer's identity. The same
  domain verb implemented by multiple tools is desirable (vendor
  choice); the same URI carrying author identity prevents that.

- **No registration-time validation.** Rejected. Lets typos and
  unrecognized domain claims through. Failures surface at routing time,
  too late.

- **Allow tools to mint their own domain URIs ad-hoc.** Rejected.
  Defeats the governance distinction this ADR establishes. The domain's
  ontology is the source of truth; tools claim against it, they don't
  extend it.

## Indicators for revisiting

- A domain emerges where multiple parties contribute to the same
  namespace (a true federated ontology, not just multiple consumers).
  Authority arbitration becomes more complex; may warrant per-namespace
  sub-conventions.
- The `mesh:` namespace grows large enough to need internal
  sub-namespacing (e.g., `mesh:ui:`, `mesh:routing:`, `mesh:obs:`). At
  that point a follow-up ADR partitions `mesh:`.
- A domain's ontology process becomes too slow for tool registration
  velocity (e.g., MRO additions take weeks). Mitigation might be a
  staging namespace (`mro-proposed:`) that auto-graduates to `mro:`
  after a delay.
- An external standards body publishes a universal verb ontology that
  subsumes domain-specific vocabularies. Unlikely in the near term but
  would warrant reconsidering the two-class split.
