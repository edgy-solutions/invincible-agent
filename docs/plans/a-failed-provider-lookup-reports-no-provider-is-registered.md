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

## The shape when it lands

1. `_discover_enumerate_providers` raises on a substrate failure rather than returning `[]`. Its
   cache discipline matters here: **a failure must not be cached as an empty provider list**, or
   one blip silences enumeration for the whole TTL. That is the sharper half of this packet.
2. `/enumerate_instances` gains a fifth outcome — `lookup_failed` — distinct from `no_provider`.
   The vocabulary belongs to the MeshGraph contract, which is why this waits for it.
3. `_discover_instance_resolvers` (L1553) is the sibling read with the same shape and the same
   cache. **Both or neither** — they were written as a matched pair and the comment says so.
4. The seal asserts the DISTINCTION, not the refusal: a registry that genuinely holds no provider
   still answers `no_provider`, and a failed lookup never does.
