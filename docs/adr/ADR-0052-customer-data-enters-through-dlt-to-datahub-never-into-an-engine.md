# ADR-0052 — Customer data enters through `dlt` → DataHub, never into an engine

**Status:** Proposed — decision recorded 2026-09-11, **written before the build**. `dlt` is **not
currently a dependency of this repo** (verified: no entry in `pyproject.toml`, no import anywhere
outside vendored trees). This ADR decides the SHAPE a customer-data connector takes so that three
engines do not each invent one; it does not claim the connector exists.
**Date:** 2026-09-11
**Deciders:** Architect (pattern), Platform team
**Related:**
  - [ADR-0022](ADR-0022-datahub-integration-owned-wrapper-mining-mcp-reference.md) — the owned
    DataHub wrapper (`agent_fleet/datahub_wrapper/main.py`) is the integration layer. This ADR adds
    an inbound path to it and no second client.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — the DATA plane,
    authored by data engineers, and **provenance is a field never a join**. A customer spreadsheet
    is the farthest `obtained_via` rung on that ladder, not a new kind of truth.
  - [ADR-0044](ADR-0044-routing-ticket-credentials-minted-per-request.md) +
    [ADR-0045](ADR-0045-engine-f-finance-verbs-over-standard-ontologies.md) Decision 5 — an engine
    holds **no standing credential**. The read is under the initiator, and §3 inherits that
    unchanged rather than restating it.
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — seed ships open, work
    overlays deltas. §5 is that pattern applied to *where the data comes from*.
  - [ADR-0051](ADR-0051-sustainment-safety-the-mesh-drafts-a-risk-and-refuses-to-accept-it.md) §10.1 —
    sandbox overlay names a **seeded fixture**, work-side overlay names a **DataHub dataset**. §5
    exists so those do not become two patterns.
  - [`principles/a-population-hardened-against-the-failure-cannot-measure-it.md`](../principles/a-population-hardened-against-the-failure-cannot-measure-it.md)
    — §6's fixture rule is that law arriving at fixture design from the other side.

## Context

Customer data will arrive as **spreadsheets, Access databases, and Power Platform sources**
(Dataverse, SharePoint lists). Three engines — finance, portfolio, safety — will each need it, and
each will need it *soon after* a customer arrives, which is exactly the condition under which a
connector gets invented in a hurry and locally.

**The failure this ADR prevents is not a bad connector. It is three good ones.** Three engines that
each read a customer file directly will disagree about the schema, about identity, about what
happens when a column is renamed — and nobody notices until two boards show different numbers for
the same program. That is the recurring shape in this repo, one plane over: a population nobody
derived, a list nobody maintained, a check each consumer wrote for itself.

**What already exists**, verified rather than assumed:

| piece | where | state |
|---|---|---|
| the DataHub wrapper | `agent_fleet/datahub_wrapper/main.py` | owned integration layer (ADR-0022) |
| catalog seeding | `scripts/seed_datahub_catalog.py` | present |
| governed read by URN | `CortexDataClient(...).get_dataframe(urn)` | live in engine-fin and data-analyst |
| the identity discipline | `finance_agent/main.py:995` | JWT + `X-Originator-*`, **no standing credential**, 401 otherwise |
| **`dlt`** | — | **absent. Not a dependency.** |

So the governed half of the path is real and already refuses to read without an initiator. What is
missing is the *inbound* half: how a customer artifact becomes a URN that path can be pointed at.

## Decision

**Customer data enters through a `dlt` source into a DataHub-registered dataset with a published
schema, and engines read it only by URN under the initiator. No engine reads a customer file.**

```
    dlt source  ->  DataHub dataset (URN + PUBLISHED SCHEMA)  ->  CortexDataClient(urn)
                                                                   under the initiator
                                        ->  engine derives TYPED GRAPH OBJECTS
                                        ->  state lives on the GRAPH
```

### 1. One connector shape, not one per engine

A **`dagster-dlt` asset per source**. Finance, portfolio and safety use the same shape; what
differs is the source and the dataset, never the mechanism. A second shape is the defect this ADR
exists to prevent, and "our source is unusual" is how it arrives.

### 2. The dataset carries a PUBLISHED SCHEMA, and that is the point of the boundary

**Schema drift is sealed at the DataHub boundary.** This is the whole reason the boundary exists
rather than engines reading files: a renamed column, a changed type or a dropped field is a
**registered change on the dataset**, visible to everything downstream, instead of an exception
raised inside one engine at answer time in front of a user.

An engine may rely on the published schema. It may not infer one.

### 3. The read is by URN, under the initiator — inherited, not re-decided

`CortexDataClient(broker_url, jwt_token, originator_sub, originator_email).get_dataframe(urn)`,
exactly as engine-fin does today. ADR-0044 and ADR-0045 Decision 5 already rule that an engine
holds no standing credential and must refuse rather than fall back; nothing here weakens that, and
**a connector that ingests under a service identity does not license a read under one.**

### 4. `dlt` IS for PULL. It is NOT for transactional writes.

Stated as a negative because **an ADR that only says what a tool is for gets used for what it is
not.**

* **For:** scheduled and on-demand *extraction* from a customer source into a registered dataset.
  Idempotent, re-runnable, and the dataset is the artifact.
* **NOT for:** writing back to a customer system; any write that must be transactional; any path
  where a failure mid-run must roll something back. Those are not pulls and `dlt` does not make
  them safe by being nearby.
* **And not a substitute for the graph.** The dataset is an input. **State lives on the graph** —
  typed objects the engine derived, carrying their provenance as a field (ADR-0035). A dataset
  treated as state is a second source of truth that nothing reconciles.

### 5. The fixture path and the work path are ONE pattern, deliberately

ADR-0051 §10.1: the sandbox overlay names a **seeded fixture**; the work-side overlay names a
**DataHub dataset when a customer arrives**. Finance and portfolio already did exactly this.

**The fixture must therefore present the same interface as the dataset** — a URN, a published
schema, read through the same client. If the fixture path becomes "the engine loads a seed file"
while the work path is "the engine reads a URN", then the work path is **exercised for the first
time at a customer**, and every seal green in sandbox will have proven the wrong half. The sandbox
overlay swaps the *source*; it must not swap the *shape*.

### 6. FIXTURES ARE BUILT WITH THE ERRORS IN THEM — a clean fixture proves nothing

Ruled for the safety fixture and general to this ADR's pattern. The safety fixture is to contain
orphaned hazards, paper-closed mitigations, a deferral on a critical safety item, three write-ups
that are one hazard, and a tracked material with a dead safety data sheet.

This is
[`a-population-hardened-against-the-failure-cannot-measure-it`](../principles/a-population-hardened-against-the-failure-cannot-measure-it.md)
arriving from the other side. That law says a population *repaired* of a failure cannot measure it.
The corollary for a fixture you author: **a fixture with no instance of the failure cannot
demonstrate the detection** — and it will pass every seal while proving only that the seal runs.

The diagnostic transfers directly: *does this fixture contain an instance of the failure the
consumer of it is meant to catch?* If not, a green over it is a claim about the fixture.

## Consequences

**We accept:**

* **A new dependency and a new asset family.** `dlt` is not in the tree; adopting it is a real
  addition with its own upgrade surface.
* **The connector is a gate.** A customer arrives and data does not reach an engine until a source
  and a dataset exist. That is the cost of refusing direct reads, and it is the point.
* **Two jobs where teams will see one** — the pull, and the derivation into typed graph objects.
  Collapsing them is how a dataset silently becomes state.

**We get:**

* **One shape across three engines**, so a schema question has one answer.
* **Drift that fails at a boundary rather than at an answer**, in front of an operator instead of a
  user.
* **Sandbox that exercises the work path**, because §5 makes the fixture wear the dataset's
  interface.
* **The identity discipline for free** — the read is already governed and already refuses.

## Non-goals

* **Not a transformation framework.** Derivation into typed objects belongs to the engine, which
  is where the domain types live.
* **Not a second client.** ADR-0022's owned wrapper stays the DataHub integration layer.
* **Not a write path** (§4), in either direction.
* **Not a decision about WHICH customer sources come first.** That is scheduling.

## Open at build time

1. **Where the `dagster-dlt` assets live** — this repo's `src/iagent/defs/` beside the existing
   sensors, or the ingestion repo. The existing extraction sensors are here, which argues for here;
   the two-planes split (ADR-0035) may argue otherwise.
2. **Schema-drift disposition.** A registered change is visible — but is a breaking change a
   *refusal to publish a new version*, or a publish plus a loud downstream failure? §2 requires it
   be sealed at the boundary and does not choose between those.
3. **Whether the fixture's URN is a real DataHub registration in sandbox** or a local stand-in
   presenting the same interface. §5 requires the same SHAPE; it does not require the same
   substrate, and the cheaper option may be enough.

## Indicators for revisiting

* **A second connector shape appears** with a stated reason. The reason is the finding — either
  the pattern is too narrow or someone is in a hurry, and those need different answers.
* **An engine is found reading a customer file directly.** §1 failed, and the interesting question
  is what made that the path of least resistance.
* **A schema change reaches a user as an answer-time error.** §2 failed: the boundary did not seal
  it, and the drift was detected by the wrong party.
* **A fixture passes a seal that the real data then fails.** §6 failed, and the fixture was clean
  in the way that proves nothing.
