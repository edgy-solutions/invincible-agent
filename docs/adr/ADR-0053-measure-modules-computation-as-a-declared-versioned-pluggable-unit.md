# ADR-0053 — Measure modules: computation as a declared, versioned, pluggable unit

**Status:** Proposed — decision recorded 2026-09-11, **after review by `invincible-agent-91` against the tree** (one claim wrong, one false; both corrected in place, neither softened). **ADR and seal skeleton only; no engine
changes.** The finance extractions continue under R-001 and the money ruling as already sequenced,
in another lane.

**READ THE TREE FIRST, AND IT CORRECTS THE SKETCH IN ONE PLACE THAT MATTERS.** The dispatch
describes "a measure is a pure, versioned module" as the pattern *as built*. Half of it is built
and half is not, and the ADR is only useful if it says which:

| claim | state in the tree, verified 2026-09-11 |
|---|---|
| measures are **pure, typed, no-I/O** functions over a state object | **BUILT** — `cost_agent/measures.py`, e.g. `cost_lot_breakdown(state, *, lot, rate_vintage)` |
| **money in `Decimal`** at the boundary | **BUILT**, and measured before relied on — `fin_eac_comparison`'s own comment records all 108 money facts in the seed as exactly representable |
| a **comparison verb that runs every method** | **BUILT** — `fin_eac_comparison` (`9106967`) |
| measures carry a **version** | **NOT BUILT.** No per-measure version anywhere |
| methods resolved from a **registry** | **NOT BUILT.** `EAC_METHODS` is a module constant and the three algorithms are inline branches in a nested `compute()` |
| the measure registry is **data** | **NOT BUILT, AND WORSE THAN A DICT.** A cost measure must appear in **SIX hand-kept tables** — `VERBS`, `OUTPUT_URI`, `INPUT_URI`, `CATALOGUE`, `_DESCRIPTIONS`, plus slot declarations (the only one *derived*, from the signature). A boot check refuses startup unless all six agree |

**CORRECTED BY REVIEW BEFORE PROPOSAL.** `invincible-agent-91` checked five claims against the
tree; **one was wrong and one was false**, and both corrections are in below rather than
softened. The false one — that the Decimal seal discriminates on value — came from a docstring
that was true when written and stale two commits later; it was one review from being published
in an ADR. See §6.

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
    — the equivalent-mutant rule, and it is **PROCEDURAL, NOT NUMERIC**: *the mutant is EQUIVALENT
    on this fixture → **narrow the claim; do not weaken the seal***. The dispatch called it a
    "bound"; the artifact does not support a number. The load-bearing half is the instruction —
    do not touch the test, go find the input where the coincidence breaks.
  - `setup/ontologies/pcn_disposition_rules.ttl` — policy-as-data, on file and live.
  - `policy/graphs/fin_program_brief.yaml` — **the precedent this ADR generalises.** See §1.

## Context — the pattern already exists, for graphs

`policy/graphs/fin_program_brief.yaml` is a ratified config row that **points at a declared
module**: `graph_id`, `module: graphs.fin_program_brief`, `builder: build`, plus the verb metadata.
Its own header states the property that makes it work:

> *"A graph module on disk with no row here is INVISIBLE to the mesh, which is ADR-0046 §2's
> refusal of `run_any_graph` made structural rather than followed."*

**That is "registries are data" already built, one domain over.** So this ADR is not inventing a
mechanism; it is extending one, and the alternative it refuses is already in the tree — a registry
in **code**, which cannot carry a version, cannot be overlaid by a customer, and cannot be reviewed
like a grant.

**AND THE ALTERNATIVE IS SIX TABLES, NOT ONE.** A cost measure must appear in `VERBS`,
`OUTPUT_URI`, `INPUT_URI`, `CATALOGUE` and `_DESCRIPTIONS`, with slot declarations the only one
*derived*. A boot check refuses startup unless all six agree — and it **compared four until it was
widened**, because `CATALOGUE` and `_DESCRIPTIONS` had drifted. Its own comment names the failure:
a verb in `VERBS` and absent from `CATALOGUE` is *"servable by direct call and INVISIBLE TO THE
MESH — the engine boots, reports healthy, answers when addressed by name, and is never routed to"*,
and it points at the reregister hook's hand-kept directory map as the same shape.

**Six hand-kept rows per measure is a far stronger case for a declared row than one dict was**,
and the boot check is the evidence: someone already had to build a guard whose whole job is to
notice that six hand-kept lists disagree.

**ONE WAY GRAPHS AND MEASURES DIFFER, and it does not break the shape — it names the harder half.**
A graph is **already a declared artifact on disk**, and its row makes it *visible*. A measure is a
**Python function**, so its row would be the first time the unit existed as data at all. For
measures §2 is therefore **extraction as well as registration**, and the extraction is the work.
The `run_any_graph` refusal transfers exactly; the cheapness does not.

**And the EAC case shows why the inline form runs out.** `fin_eac_comparison` is correct and
careful — no `method` slot (R-001), the spread carried rather than left to the reader, an undefined
method keeping its row with `eac: null` and a reason. But its three algorithms are branches inside
one function. A fourth method is a code change to that function; a customer's method is
unrepresentable; and nothing anywhere states which version of "CPI" produced a figure.

**AND THE INLINE FORM HAS ALREADY FORCED ONE DECISION BY HAND.** `REMAINING_AT_BUDGET` projects no
index, so it *always* answers — which made the "every method undefined" refusal its author first
wrote **unreachable**, discovered from a dead branch rather than from a declaration. Per-method
metadata as DATA would carry `requires_index: false` and the refusal's reachability would be a
property of the rows rather than something found by reading code. That is §2's value in one
concrete instance, and it is the kind that only shows up after the third method.

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

**Corrected in review: the ENVELOPE generalises, the DOMAIN HALF does not, and "one export
class" must mean the first.** The manifest is `{schema, modules, composition, checks}`:

| generalises cleanly | does NOT |
|---|---|
| `schema`, `modules` (name → sha), `algorithm_sha`, locator, `recipient_scope`, the audit line, entitlement scoping | `composition` — a list of `StepSpec`, *"strike this rate on that basis"*; and `checks[].lot` / `checks[].rates`, which are **cost nouns in key positions** |

So the ruling is: **generalise the envelope in the SDK**, and define a check as
`{case_id, inputs, expected, intermediates}` with a **domain-opaque `algorithm_description`**
where `composition` sits. Finance puts its EAC method list there; safety puts something else.
`cost_agent/export.py` already versions the manifest *shape* (`MANIFEST_SCHEMA = "cost-export/1"`)
and hashes intermediates rather than only outputs — the hard part, done once.

**A SECOND ENVELOPE IS THE FORK.** A second *domain* section is not — it is the design. "A second
class with a stated reason" is the honest fallback for the domain half only, and never for the
envelope.

### 5. The artifact records method NAME and VERSION beside every figure

**Two answers to one question must be distinguishable by which algorithm ran.** Today
`fin_eac_comparison` already carries `method` and `formula` per row — this extends that to the
*version*, and to every measure rather than the one that compares.

Without it, a figure that changes after a module bump is indistinguishable from a figure that
changed because the data did, and the first is a release note while the second is a finding.

### 6. Seals, stated against the equivalent-mutant bound

Each is a **mutation with a named expected red**. A mutation that survives because it produced an
equivalent program on this fixture does not weaken the seal and does not count as coverage — it
**narrows the claim**, and the response is to find the input where the coincidence breaks
([`a-surviving-mutation-means-you-cannot-tell-yet`](../principles/a-surviving-mutation-means-you-cannot-tell-yet.md)).

| seal | mutation | expected |
|---|---|---|
| module purity | add an I/O call to a module | **red** |
| Decimal at the boundary | make a money field a `float` | **red on DERIVATION, not on value** — see the correction below |
| registry-row → module resolution | **positive control**: a row naming a module that does not exist | **red**, and a valid row resolves |
| the comparison verb runs **every registered method and no unregistered one** | add a row / add an unregistered module | **red in both directions** |
| artifact carries method + version | drop the version | **red** |
| export round-trip | a **finance** payload through the **cost** class | passes |

The registry-resolution seal needs its positive control stated because a resolver that returns
nothing for everything passes a "no unregistered methods ran" assertion perfectly.

**AND ONE CLAIM IN THIS TABLE WAS FALSE UNTIL REVIEW, WHICH IS WHY THE TABLE READS AS IT DOES.**
The draft asserted that the Decimal seal discriminates on VALUE — float giving
`1662607.7097505666` against `1662607.71`. That was true when the docstring was written and
**false two commits later**, once the row floats were quantized to the cent so the panel would
stop disagreeing with its own caption. Quantizing absorbs the difference: both paths yield
`1662607.71`, and **two mutations were measured surviving because of it** — reverting the spread
to float subtraction, and computing the indices by float division. Corrected at source in
`e063e02`.

What the seal actually asserts is the **derivation**: the spread comes from the exact column
rather than the float edge. A regression to float changes *where the number came from*, not the
number, on this seed.

**Stated plainly because an ADR is exactly where this would have hardened:** the Decimal work is
**compliant and exact under data that would break float**. It did **not** fix a wrong number
here, and it must not be cited as a correctness result it has not earned. I took that sentence
from a docstring and was one review from publishing it.

### 7. Migration order for finance

`fin_eac_comparison` **done**. **`fin_variance_drivers` next**, and the reason is the money
ruling's own test rather than convenience: it **ranks by `abs(contribution)`, which is a
comparison**, so the ruling's "producers and any consumer that subtracts or compares" clause
catches it. The Decimal pass and the module extraction therefore want to happen **in one move
rather than two** — 91's read, and it is right: extracting a module and then changing its
arithmetic is two behaviour-preserving claims where only one can be checked at a time.

The remaining four follow. Each extraction **behaviour-preserving**, with the seal green **before
and after**; a green only after is a rewrite wearing a refactor's name.

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
