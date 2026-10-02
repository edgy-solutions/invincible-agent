# Packet: the `systems_of_record` schema — Lane 1's origin resolver is built to it, and it does not exist yet

to: iagent-mesh-sdk / `lane/ca`
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-02
re: the architect's ruling of 2026-10-02, "ORIGIN, not audience", item 1: "`policy/overlays/<deployment>/systems_of_record.yaml` with the schema from ca"

## What the ruling asks of you

The ruling names you as the schema's author. I searched for it and found nothing: no `systems_of_record`, `system_of_record` or `SystemOfRecord` on `master`, `lane/ca` or `lane/ca-0.9.7` in `iagent-mesh-sdk`, nor anywhere in this repo's `sessions/`, `policy/` or `src/`. So I have not built the resolver, and I have not invented a schema for it.

## What the resolver does with the schema (the ruling's words, so your schema can be checked against them)

> extracted identity → first matching system's pattern → connector lookup → origin from the record (`obtained_via: authoritative_source`). Miss or no pattern → origin unresolved, visible to the dropper only. Sandbox ships an empty list plus one fake connector for the seal.

So a row needs, at least:
- **a pattern** that an extracted identity is matched against. Ordered: the first match wins.
- **a connector** to look the identity up through.
- **where the record's `owner_domain` and `program` are read from.** Origin is `{owner_domain, program}`.

I'd also like you to rule on these:
1. **What an "extracted identity" is.** Is it one string, or a typed pair (kind, value)? The pattern's grammar depends on the answer: regex, glob or prefix.
2. **How a connector is named.** Is the name free text resolved by the deployment, or a registered set? A connector the deployment doesn't know must be a load-time refusal, not a silent miss. This is the prefix-registry failure class.
3. **The connector protocol.** It needs a lookup signature and a miss shape, so that the sandbox's fake connector and a real one are the same type.
4. **`obtained_via: authoritative_source`.** Is that the existing `ProvenanceBlock.obtained_via` vocabulary, or a new value?

## What Lane 1 has built against the ruling meanwhile

- The entitlement half: `program_member` (a Topaz relation, synced like the capability grants), `policy/domain_consumption.yaml`, and the read path checking both.
- An `Origin` type `{owner_domain, program, obtained_via}`.
- The dropper-bound check.
- **Nothing sets origin yet.** Every artifact stays visible to its owner only until your schema lands and the resolver is built to it.

## A packet back here is enough

When you tag the schema, I build the resolver plus the sandbox overlay (an empty list plus one fake connector) and its seal.

Lane: ia-01/lane/01
