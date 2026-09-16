---
id:         a-failed-provider-lookup-reports-no-provider-is-registered
status:     open
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on: the MeshGraph contract — the fix changes what /enumerate_instances returns, and the outcome vocabulary is the interface's
trigger:
closed-by:
repo:       invincible-agent
summary:    A Neo4j failure in provider discovery returns no providers, and /enumerate_instances renders that as outcome no_provider, detail "no mesh:enumerateInstances provider is registered" — a false statement about the registry, in the field a person reads. The same module argues against this one screen below.
---

# A failed provider lookup reports "no provider is registered"

**RULED 2026-09-14** with its two siblings. Held for the stated reason — it changes what a
consumer sees — and it is the one whose wrong answer is a **sentence**, not an empty list.

    _discover_enumerate_providers (L1520)   except Exception -> return []
    /enumerate_instances          (L2095)   if not providers: outcome "no_provider",
                                            detail "no mesh:enumerateInstances provider is registered"

**THE DETAIL IS A CLAIM ABOUT THE REGISTRY, AND A NEO4J FAILURE MAKES IT FALSE.** Providers may be
registered and healthy; the lookup failed. The route cannot tell, so it asserts the thing it did
not check — and it asserts it in prose, to whoever asked.

## The module already makes this exact argument, twelve lines lower

Directly below that branch, `/enumerate_instances` goes to deliberate lengths over a FOURTH
outcome its providers emit:

> *"`unsupported` — 'I answered, and I do not hold this class.' It is neither `empty` (which claims
> the class exists and has no members) nor unreachable (which claims nothing at all), and counting
> it as either **produces a false statement in the very field a person reads**."*

That is this defect's own indictment, written by whoever built the outcome vocabulary — and the
branch above it does precisely what the comment forbids, one frame earlier, for the discovery read
rather than the provider answer. **The care went into distinguishing what the providers say, and
none into whether we managed to ask.**

## The symptom has been produced here before, by a different cause

`_ENUMERATE_PROVIDERS_CYPHER`'s own comment records it: two providers were registered on
`mesh#InstanceClass`, the supervisor's `ENUMERATE_INSTANCES_URL` pointed at one of them, and
`fin:Program` came back **"cannot be listed"** — *"not because nothing could list it, but because
the one thing that could was never asked."* Same sentence reaching the user, different cause. A
failure in discovery reproduces it exactly, and the fix for the first one does not cover it.

## RULED 2026-09-14 — THREE STATES, AND ONLY TWO OF THEM ARE CACHEABLE

    registered        the providers, as today
    none registered   a real, checked answer about the registry   -> CACHEABLE
    unknown           the lookup failed                           -> NEVER CACHED

**The sentence is the defect**, and the cache is what makes it last: a claim about the registry
that a Neo4j failure makes false, held for the whole TTL by one blip. The module already
distinguishes `unsupported` twelve lines below for exactly this reason — *"counting it as either
produces a false statement in the very field a person reads"* — it simply never asked whether it
managed to ask.

## RATIFIED 2026-09-14 — THE SHARED RESULT TYPE, built before any interface has a method

This packet's three states are not this packet's invention any more. **One result type in the SDK
carries both axes and `MeshGraph`, `MeshOntology` and `MeshVectors` all return it:**

    outcome   answered | empty | failed | unreachable     -- WHETHER it was answered
    mode      how it was answered, where a mode exists    -- e.g. hybrid | bm25

ca builds the type first; this packet lands ON it. The reason it is cheap now: there are not two
converging decisions (a status field on the graph side, a mode field on the vector side, meaning
one thing in two vocabularies) — **there is one decision, and it is only one because the `mode`
axis had no implementation yet to be consistent with.** That is the correction that made it a
single type instead of a later reconciliation.

## The shape when it lands

1. `_discover_enumerate_providers` returns the three states rather than `[]`-for-everything.
   **`unknown` is never written to the cache**; that is the half that turns a blip into a window.
2. `/enumerate_instances` renders `unknown` as its own outcome, distinct from `no_provider`, and
   never as the sentence above. The outcome vocabulary belongs to the `MeshGraph` contract, which
   is why this waits for it.
3. `_discover_instance_resolvers` (L1553) is the sibling read with the same shape and the same
   cache. **Both or neither** — they were written as a matched pair and the comment says so.
4. **THE SEAL RULE, shared by all three packets:** *a fixture that exercises only the legitimate
   empty cannot tell the fix from the defect.* Both empties in every fixture: a registry that
   genuinely holds no provider still answers `none registered` and still caches; a failed lookup
   answers `unknown`, caches nothing, and is asserted to produce a DIFFERENT return.
