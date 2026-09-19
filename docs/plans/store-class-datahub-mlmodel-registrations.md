---
id:         store-class-datahub-mlmodel-registrations
status:     in-flight
owner:      unassigned - raised by invincible-agent-28 [5401d7] / ia-eo
blocked-on: a ruling on `sync obligation` when the fleet writes into a system it does not own
trigger:
closed-by:
repo:       invincible-agent
summary:    The registrar's verb catalogue in DataHub - three sites emitting mlModel entities on the mesh platform. Rebuildable as a registration; the open field is SYNC OBLIGATION, because this is the fleet writing INTO a system it does not own and never reads back.
---

# `datahub:mlModel(mesh)` — registrations that live in someone else's system

Three write sites: `agent_fleet/utils/mesh_registration.py` (2), `agent_fleet/mesh_registrar/main.py`
(1). Entities are `urn:li:mlModel:(urn:li:dataPlatform:mesh,<name>,PROD)`.

| field | value | basis |
|---|---|---|
| reproducibility | **`rebuildable`** | §2 names **registrations** directly; re-registration reproduces them, registrar as producer. |
| authority | **`here`** | the fleet decides what its own verbs are; nothing upstream defines them. |
| **sync obligation** | **OPEN — see below** | |
| releasability | reserved (§6) | |

## Why `sync obligation` cannot be derived

The field asks *"what must cross a location boundary, and in which direction?"* — and this store
**is on the far side of one**. DataHub is a separate system with its own lifecycle; the fleet pushes
into it and never reads back.

`none` is the tempting answer, and it is only right if DataHub is a projection the fleet may
overwrite at will. But then **nothing in the class says the fleet must re-push after DataHub is
wiped**, and a registration present in Neo4j and absent from DataHub becomes a silent divergence
with no declared obligation to repair.

`flush-up` describes the direction correctly — everything moves outward, nothing returns — but §2's
worked example uses it for *intent reconciling toward an authority*, and here the authority is on
the sending side. **The value may be right and the reason wrong**, which is the match §2's class-6
warning is about: a shape name fixing several axes at once.

## What a packet here is for

ADR-0054 §2: *"A store that fits none of the three shapes **declares its four fields anyway**,
rather than being filed under the nearest."* §7: *"No store is reclassified by this ADR; the
classification of each store is the census's output."*

So each field above is **DERIVED** (with the artifact it was read from) or **OPEN** (with the
question, and why the census cannot answer it). An open field is not a gap in this document — it is
the deliverable.

**No walk depends on this.**
