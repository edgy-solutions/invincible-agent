---
id:         adr0039-deliverables
status:     open
owner:
blocked-on:
closed-by:
repo:       invincible-agent
summary:    ADR-0039's three artifacts — schema generated from the executor models, authoring scaffold, BPMN exporter.
---

# ADR-0039 deliverables — schema, scaffold, exporter

ADR-0039 decided the workflow-definition authoring schema and its BPMN export. The decision is
recorded; **the artifacts are not built**, and until this packet existed there was no board line
saying so — the ADR read as done because a decision document reads as done.

## The three, each sealed separately

**1. JSON Schema generated from the executor's own models.** Not hand-written beside them. The
whole point is that two declarations of one shape cannot disagree, which means the schema is a
projection of the models plus a **drift test** that fails when they diverge. Same discipline as
the board (ADR-0040) and, per ADR-0036, config layering — this repo has now applied
generated-not-asserted three times and hand-written it zero times deliberately.

**2. Authoring scaffold.** A new workflow definition should be startable from something that is
already schema-valid, so the first feedback a definition author gets is from the schema rather
than from a runtime rejection.

**3. BPMN exporter.** The export direction only. Import is not in scope and should not be added
without its own decision — a round-trip claim is much stronger than an export claim and would
need its own seals.

## Sequencing note

The schema is first because the other two consume it: a scaffold that predates the schema is a
guess about shape, and an exporter without a schema has nothing to validate its input against.

## Rider already filed separately

`dagster-loader-call` — `build_dynamic_jobs()` runs unconditionally against a catalog whose
emptiness is *reported but unconfirmed*. It is ADR-0039's rider and lives in its own packet
because its owner is the Dagster plane's, not this one's. **If `bpmn_catalog` stops being empty,
ADR-0039's naming-collision clause becomes mandatory rather than advisory** — that is the
condition linking the two items.

## Acceptance

- Schema regenerates identically from the models; drift test bites, proven broken-on-purpose.
- Scaffold output validates against the generated schema without hand-editing.
- Exporter round-trips a known definition to BPMN and the output is checked against a fixture,
  not eyeballed.

## Owner

Empty — unassigned.
