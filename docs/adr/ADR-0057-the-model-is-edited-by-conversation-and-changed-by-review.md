# ADR-0057 — The domain model is edited by conversation and changed by review

**Status:** Proposed. Drafted by Lane 1 from the architect's packet of 2026-10-14. This is a PR,
not merged; Chris reviews. Nothing is built.
**Date:** 2026-10-14
**Deciders:** architect (decision); Chris (review); Lane 1 (draft)
**Related:**
  - [`ADR-0007`](ADR-0007-survey-before-mint.md): survey before mint. A proposed class is
    surveyed against vendored ontologies before it can be ratified.
  - [`ADR-0019`](ADR-0019-ontology-routing-substrate.md): the ontology is the routing substrate.
    It is the model this ADR makes editable.
  - [`ADR-0026`](ADR-0026-persona-entitlement-topaz-authorization.md): persona and entitlement
    authorization. The ownership and entitlement questions a proposal must answer (§2) are the
    ones this ADR's authorization model reads.
  - [`ADR-0027`](ADR-0027-composable-approval-policy.md): composable approval policy. It governs
    the ratification task in §4.
  - [`ADR-0036`](ADR-0036-config-layering-seed-overlay-composition.md) and
    [`ADR-0050`](ADR-0050-canvas-templates-are-ratified-yaml-a-panel-is-a-pre-resolved-step.md):
    ratified, in-repo config changed by PR and applied by the roll. §4 puts the model under the
    same governance as content-kind rows and finance templates.
  - [`ADR-0054`](ADR-0054-data-classes-every-write-declares-what-it-is.md): data classes.
    §2's "system of record" question is that ADR's `authority` field, asked at modelling time.

**Numbering.** The architect's packet named this ADR-0042. That number already belongs to
[`ADR-0042`](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md)
(live-view artifacts). 0057 is the next free number on master and on every pushed branch at
`16f44e6a`.

---

## Context

Customers need to iterate on their domain models after onboarding: the portfolio model, and
others. Today the model exists as OWL/SHACL in Jena and is served to engines through the mesh.
**It has no editing surface.** A change today means someone hand-edits the TTL under
`setup/ontologies/` (17 files) and lands it through a PR, which no customer can do.

Each existing modelling tool fails on a different axis:

| tool | what it models | why it does not fit |
| --- | --- | --- |
| Visio | pictures | No semantics. A drawing cannot be validated, diffed or applied. |
| Neo4j Enterprise | a property graph | Not our ontology: no classes, no SHACL shapes, no OWL semantics. |
| C4 / Structurizr | software structure | Models containers and components, not the domain. |
| ER tools | tables | Produce a relational schema, a different artifact from a class model. |
| TopBraid EDG | SHACL-native, governed | The nearest commercial fit. It does not ask the ownership and entitlement questions the platform depends on (who owns a class, who may consume it, which system of record is authoritative). |

The questions the platform cannot work without are the ones no modelling tool asks. Authorization
reads them, and so do routing, the origin gate and the data-class census. A model that answers
them only by convention is a model the platform has to guess about.

This ADR is also meant to stop the "just buy Neo4j" conversation from recurring, by recording
why each alternative was refused.

## Decision

### 1. The platform is the modelling tool

Model editing is a cortex conversation backed by engine-o verbs:
- `mesh:explainModel`: what the ratified model says about a class or property, and why;
- `mesh:proposeModelChange`: start or extend a proposal;
- `mesh:diffModel`: a proposal against the ratified model.

The verbs are ontology-driven and domain-agnostic. They work over whatever model the deployment
has ratified, not over a portfolio-specific schema.

### 2. Proposals are socratic

A proposal asks, for each class it introduces or changes:
- **identity:** what makes an instance unique;
- **system of record:** where the authoritative copy lives;
- **owning domain;**
- **consuming domains;**
- **cardinality;**
- **history versus property:** is a change a new fact with a date, or an overwrite;
- **lifecycle.**

**A proposal is incomplete until each question is answered or explicitly deferred.** A deferral
is recorded with its reason. It is a declared absence, not a blank.

### 3. A proposal renders as a MODEL canvas

The canvas shows classes and properties, the diff against the ratified model, and the
system-of-record and domain annotations.

**Diagrams (Mermaid, C4-style) are exports, never inputs.** A diagram is a view of the model; it
is never parsed back into one.

### 4. The model never changes from a conversation

1. A completed proposal files a **ratification task** to the ontology stewards.
2. Approval produces a **TTL/SHACL change plus a migration note, as a PR**.
3. **The roll applies it.**

This is the same governance as content-kind rows and finance templates. The change is a reviewed
diff with a named approver; the conversation only produces the proposal.

### 5. Source format

**TTL/SHACL in the repo stays authoritative.** Whether to adopt LinkML as the authored form is a
follow-up decision and is not made here.

### 6. Import and export

- **SHACL round-trip with TopBraid EDG**, for customers who already govern there.
- **SysML (Cameo) import**, where a program mandates it.

Neither replaces §4: an import produces a proposal, not a change.

## Consequences

**Three units of work, all after the OpenDDIL dry run:**

| unit | owner |
| --- | --- |
| engine-o verbs (`explainModel`, `proposeModelChange`, `diffModel`) | lane/74 |
| the MODEL canvas | cortex-ui |
| the ratification audience and route | Lane 1 |

**Model changes become auditable diffs with a named approver.** Every change to the ratified
model has a proposal, a ratification task, a PR and a roll behind it.

**The ownership questions get asked at the moment of modelling,** instead of being reconstructed
later from grants and overlays.

## Alternatives considered (rejected)

- **Neo4j Enterprise.** It models a property graph, not our ontology, and buying it does not
  give the platform an editing surface for OWL/SHACL.
- **C4 / Structurizr as the model.** These model software structure. They remain acceptable as
  an export format (§3).
- **Direct TTL editing as the customer path.** It stays the stewards' path, through the PR in §4.
  It is not offered to customers: it asks none of §2's questions and skips review.

## Open questions (named, not decided here)

- **Who the ontology stewards are, per deployment.** That is §4's ratification audience, and it
  is Lane 1's unit of work.
- **Migration notes.** What a migration note must contain when a change alters identity or
  cardinality over existing instances.
- **LinkML** (§5): a follow-up decision.

## Indicators for revisiting

- A customer needs a model change the socratic questions cannot express.
- TopBraid EDG (or another tool) starts asking the ownership and entitlement questions natively.
- Ratification latency becomes the bottleneck on customer iteration.
