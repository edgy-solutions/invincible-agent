---
id:         store-class-datahub-dataset-catalog
status:     in-flight
owner:      unassigned - raised by invincible-agent-28 [5401d7] / ia-eo
blocked-on: a ruling on `authority` for a store describing systems that do not exist
trigger:
closed-by:
repo:       invincible-agent
summary:    The seeded demo catalogue in DataHub: eleven write sites emitting DatasetProperties for platforms postgres and snowflake that DO NOT EXIST. Reproducibility derives cleanly; AUTHORITY is open, because the store describes systems of record the fleet does not have.
---

# `datahub:dataset(postgres|snowflake)` — canned data describing systems nobody has

Eleven of the fourteen DataHub write sites. `scripts/seed_datahub_catalog.py` emits
`DatasetPropertiesClass` for datasets on platforms **`postgres`** and **`snowflake`** — *"a small
but realistic canned catalog"*.

**A different store from the registrar's** `datahub:mlModel(mesh)` (three sites). The census first
carried both under one invented label: different entity types, different platforms, zero overlap.

| field | value | basis |
|---|---|---|
| reproducibility | **`rebuildable`** | the rows are canned constants in the script; re-running reproduces them exactly. Producer: `scripts/seed_datahub_catalog.py`. |
| **authority** | **OPEN — see below** | |
| sync obligation | **OPEN** — likely `none`, but it follows authority | |
| releasability | reserved (§6) | |

## Why `authority` cannot be derived

The values are `here` / `upstream` / `external system of record`. These rows **describe** datasets
on Postgres and Snowflake — systems the fleet does not operate and, in sandbox, that **do not
exist**:

- `here` is wrong in substance: the fleet does not decide what a customer's Snowflake table holds.
- `external system of record` is wrong in fact: **there is no system of record.** §2 is explicit
  that this shape *"describes a MIRROR of an accepted fact"*, and a mirror of nothing is the failure
  the edge-intent example exists to prevent — *"it would then claim a transaction that nobody has
  made."*
- `upstream` names a producer that is equally absent.

**A fixture shaped like a mirror that mirrors nothing has no honest value in this vocabulary** —
precisely the case §2 says must declare its fields rather than take the nearest shape name. It may
need a fourth value, or an explicit `fixture` marking that keeps it out of any conformance
population.

## What a packet here is for

ADR-0054 §2: *"A store that fits none of the three shapes **declares its four fields anyway**,
rather than being filed under the nearest."* §7: *"No store is reclassified by this ADR; the
classification of each store is the census's output."*

So each field above is **DERIVED** (with the artifact it was read from) or **OPEN** (with the
question, and why the census cannot answer it). An open field is not a gap in this document — it is
the deliverable.

**No walk depends on this.**
