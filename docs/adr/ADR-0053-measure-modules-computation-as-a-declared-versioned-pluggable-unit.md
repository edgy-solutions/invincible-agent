# ADR-0053 — Measure modules: computation as a declared, versioned, pluggable unit

**Status:** Proposed — decision recorded 2026-09-11. **ADR and seal skeleton only; no engine
changes.** The finance extractions continue under R-001 and the money ruling as already sequenced,
in another lane.

**READ THE TREE FIRST, AND IT CORRECTS THE SKETCH IN ONE PLACE THAT MATTERS.** The dispatch
describes "a measure is a pure, versioned module" as the pattern *as built*. Half of it is built
and half is not, and the ADR is only useful if it says which:

| claim | state in the tree, verified 2026-09-11 |
|---|---|
| measures are **pure, typed, no-I/O** functions over a state object | **BUILT** — `cost_agent/measures.py`, e.g. `cost_lot_breakdown(state, *, lot, rate_vintage)` |
| **money in `Decimal`** at the boundary | **BUILT**, and measured before relied on — `finance_agent/measures.py:604` records all 108 money facts in the seed as exactly representable |
| a **comparison verb that runs every method** | **BUILT** — `fin_eac_comparison` (`measures.py:568`, `9106967`) |
| measures carry a **version** | **NOT BUILT.** No per-measure version anywhere |
| methods resolved from a **registry** | **NOT BUILT.** `EAC_METHODS` is a module constant and the three algorithms are inline branches in a nested `compute()` (`measures.py:613-622`) |
| the measure registry is **data** | **NOT BUILT.** `cost_agent/measures.py:774` is `VERBS = {name: function}` — a Python dict |

**Date:** 2026-09-11
**Deciders:** Architect (claim and refusals), Platform team
**Related:**
  - [ADR-0046](ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) §2 — `run_any_graph`
    **refused**. §2 below is that refusal generalised from graphs to computations.
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — seed ships open, work
    overlays deltas. A customer method is an **overlay row**, and §2 inherits the composition site.
  - [ADR-0045](ADR-0045-engine-f-finance-verbs-over-standard-ontologies.md) — `fin_eac_calculation`
    takes `method: EACMethod` and raises `MethodRequired`; a bare ask is refused with the choice.
  - [ADR-0047](ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) — the
    export carries its own algorithm. §4 is that ADR's class, held to one.
  - [`docs/rulings/README.md#r-001`](../rulings/README.md) — all three EAC methods on one panel;
    pinning hides the divergence that is the finding.
  - [`principles/a-surviving-mutation-means-you-cannot-tell-yet.md`](../principles/a-surviving-mutation-means-you-cannot-tell-yet.md)
    — the **equivalent-mutant bound**: a mutation that produced an equivalent program is discarded,
    not counted. §6's seals are stated against that bound rather than as coverage.
  - `setup/ontologies/pcn_disposition_rules.ttl` — policy-as-data, on file and live.
  - `policy/graphs/fin_program_brief.yaml` — **the precedent this ADR generalises.** See §1.

## Context — the pattern already exists, for graphs

`policy/graphs/fin_program_brief.yaml` is a ratified config row that **points at a declared
module**: `graph_id`, `module: graphs.fin_program_brief`, `builder: build`, plus the verb metadata.
Its own header states the property that makes it work:

> *"A graph module on disk with no row here is INVISIBLE to the mesh, which is ADR-0046 §2's
> refusal of `run_any_graph` made structural rather than followed."*

**That is "registries are data" already built, one domain over.** So this ADR is not inventing a
mechanism; it is extending one, and the alternative it refuses is the one already in the tree:
`VERBS = {name: function}`, a registry in **code**, which cannot carry a version, cannot be
overlaid by a customer, and cannot be reviewed like a grant.

**And the EAC case shows why the inline form runs out.** `fin_eac_comparison` is correct and
careful — no `method` slot (R-001), the spread carried rather than left to the reader, an undefined
method keeping its row with `eac: null` and a reason. But its three algorithms are branches inside
one function. A fourth method is a code change to that function; a customer's method is
unrepresentable; and nothing anywhere states which version of "CPI" produced a figure.

## Decision

**A measure is a pure, versioned module. A verb is a thin wrapper around one. The mapping from
method name to module is DATA.**

### 1. The measure-module contract

A measure module declares: **inputs and outputs with types**, a **version**, and nothing else it
needs. It performs **no I/O** — no graph read, no network, no clock. Money is `Decimal`. It is
**deterministic**: same inputs, same figures.

The version is the module's own, not the engine's. It exists so §5 can say which algorithm produced
a number, and bumping it is a claim that the figures may change.

### 2. Method registries are DATA, in `policy/`, shaped like `policy/graphs/`

A method is a **row**: name, module reference, version, and `prov:wasDerivedFrom` for the standard
or authority it implements. Seeded as policy-as-data (`pcn_disposition_rules.ttl`'s shape), ratified
by a **named act**, reviewed like a grant.

**A module on disk with no row is invisible.** Inherited verbatim from
`policy/graphs/fin_program_brief.yaml`, and it is what makes §3's refusals structural rather than
disciplinary.

**A customer's method is an overlay row pointing at a declared module** (ADR-0036), composed at the
repo, passing the same validation as a seed row.

Slot vocabularies attach **from the registry at registration** — so `EACMethod`'s three values stop
being a `Literal` in a signature and become the rows that exist.

### 3. "User-configurable" means SELECTING among ratified methods and SETTING ratified parameters

Adding an algorithm is **adding a declared module with a manifest and a seal**. It is a reviewed
change, not a runtime input.

**Refused by name:**

- **A verb that accepts a formula, expression or code as a slot.** This is `run_any_graph` wearing
  a parameter's clothes (ADR-0046 §2), and every argument there applies unchanged.
- **A method row pointing at anything without a manifest.** A row that resolves to an unmanifested
  target is a registry entry that cannot be verified, which is worse than an absent row because it
  reads as governed.
- **A module that reads the graph or the network.** Purity is what makes a measure exportable,
  comparable and replaceable; a module that reads state is none of those, and its figures cannot be
  reproduced by a recipient.

### 4. ONE export class

Finance and safety emit through `cost:ExportPackage`'s shape (ADR-0047). If it does not fit,
**generalise it in the SDK** — `cost_agent/export.py` already versions the manifest *shape*
(`:53`) and hashes intermediates rather than only outputs (`:14`), which is the hard part and is
done once.

**A per-engine `ExportPackage` is the fork**, and it is the same defect as a second connector
shape or a second registry: three correct implementations that disagree at the boundary.

### 5. The artifact records method NAME and VERSION beside every figure

**Two answers to one question must be distinguishable by which algorithm ran.** Today
`fin_eac_comparison` already carries `method` and `formula` per row — this extends that to the
*version*, and to every measure rather than the one that compares.

Without it, a figure that changes after a module bump is indistinguishable from a figure that
changed because the data did, and the first is a release note while the second is a finding.

### 6. Seals, stated against the equivalent-mutant bound

Each is a **mutation with a named expected red**, and a mutation that produces an equivalent
program is discarded rather than counted as coverage
([`a-surviving-mutation-means-you-cannot-tell-yet`](../principles/a-surviving-mutation-means-you-cannot-tell-yet.md)).

| seal | mutation | expected |
|---|---|---|
| module purity | add an I/O call to a module | **red** |
| Decimal at the boundary | make a money field a `float` | **red** — and it discriminates on VALUE, not type: on this seed the float path gives `1662607.7097505666` against `1662607.71` |
| registry-row → module resolution | **positive control**: a row naming a module that does not exist | **red**, and a valid row resolves |
| the comparison verb runs **every registered method and no unregistered one** | add a row / add an unregistered module | **red in both directions** |
| artifact carries method + version | drop the version | **red** |
| export round-trip | a **finance** payload through the **cost** class | passes |

The registry-resolution seal needs its positive control stated because a resolver that returns
nothing for everything passes a "no unregistered methods ran" assertion perfectly.

### 7. Migration order for finance

`fin_eac_comparison` **done**. **`fin_variance_drivers` next** — it *subtracts and ranks*, so it
exercises the Decimal boundary and an ordering at once. The remaining four follow. Each extraction
**behaviour-preserving**, with the seal green before and after; a green only after is a rewrite
wearing a refactor's name.

## Open — for the architect, deliberately not decided here

1. **Is method ratification per-program or per-deployment?** Per-deployment is simpler and makes a
   method a property of the install; per-program allows two programs to use different EAC methods,
   which someone will eventually ask for and which multiplies the provenance a figure must carry.
2. **May a customer module live outside the platform repo?** The architect's recommendation is
   **yes** — an overlay-referenced package with its own seal, exactly as a graph is. Recorded as the
   recommendation and not as the ruling, because it decides whether the platform can verify what it
   executes.

## Non-goals

- **Not a formula language**, in any form (§3).
- **Not a second export class** (§4).
- **Not a rewrite of the measures.** They are already pure and typed; what changes is how they are
  *declared and resolved*, which is why §7 requires behaviour preservation.
- **Not `safety_risk_matrix.ttl`.** It does **not exist** — ADR-0051 increment 1 has not landed, so
  it is named here as a *planned* second consumer of §2's shape and nothing in this ADR depends on
  it.

## Indicators for revisiting

- **A second registry appears in code** — a `VERBS`-shaped dict for methods. §2 failed and the
  reason will be that a row felt like overhead for the first method.
- **A figure changes and nobody can say whether the algorithm or the data moved.** §5 failed.
- **A module is found reading the graph.** §3's third refusal failed, and the export is no longer
  reproducible by a recipient.
- **The comparison verb's method list is edited in Python.** §2 is being followed for storage and
  ignored for enumeration, which is the half-adopted state that looks compliant.
