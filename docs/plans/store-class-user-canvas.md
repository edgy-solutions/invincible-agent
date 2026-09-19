---
id:         store-class-user-canvas
status:     in-flight
owner:      unassigned - raised by invincible-agent-28 [5401d7] / ia-eo
blocked-on: §6 releasability remaining reserved while a store needs it
trigger:
closed-by:
repo:       invincible-agent
summary:    User-authored canvases in Postgres. Reproducibility and authority derive immediately (stateful, here); this packet exists because it is the fleet's clearest waiting case for the RESERVED releasability field - and a reserved field with a case is a different state from one without.
---

# `sql:user_canvas` — the store that needs the field ADR-0054 reserved

| field | value | basis |
|---|---|---|
| reproducibility | **`stateful`** | a person authored it. No seed, overlay, manifest or log reproduces it; losing the table loses the work. |
| authority | **`here`** | the user's canvas is decided here and nowhere else. |
| sync obligation | **`none`** | it crosses no location boundary. |
| **releasability** | **RESERVED (§6) — and this store is why that matters** | |

## The point of this packet

§8 explains the reservation and is right to: *"`releasability` is reserved precisely because nothing
reads it yet."* That is the discipline this fleet applies everywhere — a Protocol operation with no
caller was removed rather than implemented.

**But a reserved field with a waiting case is a different state from a reserved field with none**,
and saying which is the census's job. `user_canvas` is user-authored content in a multi-actor
system, and `human_task_projection` next door already carries a **clearance-bounded** contract in
its own docstring — *"the projection row is visible to every authorized actor and must not leak
content an actor authorized for the TASK is not cleared for."*

So one store already enforces by hand exactly what the reserved field would declare. That is not an
argument to implement it now — **it is evidence that the first consumer exists**, which is the
condition §8 itself sets for un-reserving it.

## What a packet here is for

ADR-0054 §2: *"A store that fits none of the three shapes **declares its four fields anyway**,
rather than being filed under the nearest."* §7: *"No store is reclassified by this ADR; the
classification of each store is the census's output."*

So each field above is **DERIVED** (with the artifact it was read from) or **OPEN** (with the
question, and why the census cannot answer it). An open field is not a gap in this document — it is
the deliverable.

**No walk depends on this.**
