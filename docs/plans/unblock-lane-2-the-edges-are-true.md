# Lane 2 — UNBLOCKED. The classes are in the graph and the edges are true.

**Date:** 2026-08-28 · **From:** Lane 1 · **Status:** your items 3 and 4 can build tonight

## What landed

The prime ran and was verified by name and parent — not by count, which this run proved is not
a valid instrument (see the prep doc's corrections):

```
mesh#CanvasSeedResult -> mesh#Response     ✅ the payload, subject end
mesh#CanvasSeed       -> mesh#Archetype    ✅ the treatment, object end
```

Both endpoints of the binding now pre-exist as `:OntologyClass`, so **Contract D is satisfied**
and the `mesh:ContributionSequence`-style refusal that would have met an early registration
cannot fire.

Then `reregister` ran and Engine P's verb edges were rewritten:

```
iagent-engine-p.sandbox.svc.cluster.local:8095   edges = 14   (was 14 at the BARE host)
```

That second part matters to you as much as the classes. The endpoint is baked into the verb edge
at REGISTRATION time, so until this ran the mesh still pointed at a bare service name — which
resolves in the sandbox and **dies behind a corporate proxy**, because a name with no dots does
not suffix-match a `NO_PROXY` entry of `.svc.cluster.local`.

## What is already true, so you do not re-verify it

* `CANVAS_SEED` is in `KNOWN_ARCHETYPES` — a declared contract is a name the backend knows
* the contract, the binding row, and the **component-or-consumer** category are landed
  (`7457a15`), both seals biting with negative controls run
* the binding declares a `consumer` (`canvasSeedFromArtifact`), not a component — nothing
  renders a seed answer, and the seal checks whichever was declared

## Your items

**3. The sixth hardened arm** — project `{archetype, name, artifact_ids}`, same deterministic
pattern as the other six. Cortex's recogniser is the contract everyone matches:

```
{ archetype: "CANVAS_SEED", canvas_type?: string, name?: string, artifact_ids: string[] }
```

declared in ONE place (`src/lib/canvasSeedFromAnswer.ts`) and stated there as the single
source. `artifact_ids` is **slot-ordered** and the order is load-bearing — it is the producer's
declaration of which measure lands in which slot.

**4. Capability registration + dispatch.** Your own proposal already established the dispatcher
is generic over the endpoint (`endpoint = predicate["endpoint"]`), so no supervisor change is
needed — the endpoint lives in the registration, and `action_endpoint` gets deleted from the
catalog rather than left to drift.

## First acceptance item, per the standing rule

**The shape check against real bytes**, before anything else. Not a schema argument — an actual
payload, compared against what `canvasSeedFromArtifact` reads. That comparison caught the
delivery-path mismatch before either half shipped, and it is cheaper than discovering it in a
browser.

## And the acceptance for the feature as a whole

**The phrase working end to end**, not either half passing its own tests. Cortex's call site and
your registration are one feature; neither alone produces a working `make me a portfolio canvas`.
That is the cheapest way to keep this from becoming the sixth declared-but-unwired instance.

## Also waiting on you — two rulings, not builds

1. **The partial-seed composition question** (`bounding-the-answer-not-just-the-source.md` and
   the seed-route ruling): today a partial seed strips nulls and shifts every card up a slot —
   real cards, no errors, wrong board. Your route, your response contract.
2. **The taxonomy handback** (`handback-the-graph-taxonomy-is-flat-by-design.md`): the finding is
   revised with control evidence and needs a ruling between two branches. It is not an ingest
   fault — the graph is flat by ingest design, and no prime can change that.
