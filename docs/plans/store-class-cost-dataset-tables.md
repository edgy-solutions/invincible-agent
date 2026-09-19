---
id:         store-class-cost-dataset-tables
status:     in-flight
owner:      unassigned - raised by invincible-agent-28 [5401d7] / ia-eo
blocked-on: 
trigger:
closed-by:
repo:       invincible-agent
summary:    lots, rates and results - the DuckDB cost dataset. The census first filed all three as UNCLASSIFIED and they are the cleanest rebuildable in the fleet: a declared seed module, a manifest hash, and a named producer, settled by reading the builder's first import.
---

# `sql:lots` · `sql:rates` · `sql:results` — rebuildable, and the derivation is the point

Four write sites, all in `scripts/build_cost_dataset.py`. **Folded, not hand-run**:
`agent_fleet/cost_agent/measures.py` does `import build_cost_dataset as dataset_builder` inside
`_cost_dataset_path`. **Cited by its code rather than by a line number**, because the number this
packet first carried (`:888`) was already stale when it was written — a 104-commit merge had moved
it to 909, and a line number is the part of a citation that rots first.

| field | value | basis |
|---|---|---|
| reproducibility | **`rebuildable`** | the builder imports `agent_fleet.cost_agent.seed` (`build_state`, `lots_for_recipient`) — a declared, versioned source in this repo — and the result is *"hashed into the manifest"*. Seed + manifest + named producer is §2's amended definition met three times over. |
| authority | **`here`** | the figures are the engine's own, computed by `pricing.py` before storage. |
| sync obligation | **`none`** | the package is exported as a file; nothing flows back. |
| releasability | reserved (§6) | see ADR-0047 for the export's own governance. |

## Why this one is a packet at all

Because the census first filed all three as UNCLASSIFIED, and they are not — they are the cleanest
`rebuildable` in the fleet. **Reading the builder's first import settled in seconds what a prose
argument about "is a generated dataset reproducible?" would not have settled at all.**

The builder's docstring also states the constraint that makes the class stick: *"DATA LAYER ONLY. NO
ARITHMETIC IN SQL. Every figure in `results` is one the engine already computed with `pricing.py`;
the database stores and selects, it does not derive."* **A store that computes nothing cannot
disagree with its producer** — which is what makes the rebuild trustworthy rather than merely
possible.

## What a packet here is for

ADR-0054 §2: *"A store that fits none of the three shapes **declares its four fields anyway**,
rather than being filed under the nearest."* §7: *"No store is reclassified by this ADR; the
classification of each store is the census's output."*

So each field above is **DERIVED** (with the artifact it was read from) or **OPEN** (with the
question, and why the census cannot answer it). An open field is not a gap in this document — it is
the deliverable.

**No walk depends on this.**
