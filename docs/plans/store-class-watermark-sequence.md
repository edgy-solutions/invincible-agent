---
id:         store-class-watermark-sequence
status:     in-flight
owner:      unassigned - raised by invincible-agent-28 [5401d7] / ia-eo
blocked-on: whether ADR-0054 can express a store that is only rebuildable as a SET
trigger:
closed-by:
repo:       invincible-agent
summary:    neo4j:WatermarkSequence - a store with no row of its own in the census until now, because its only write shares one atomic transaction with three other labels. Stateful and derivable; the packet exists for the COUPLING, which no per-store field can express.
---

# `neo4j:WatermarkSequence` — the store the census could not see

**It had no row of its own.** Its only write is inside `answer_artifact_writer._tx_merge` — the
single `execute_write` spanning `Actor`, `AnswerArtifact`, `Source` and `WatermarkSequence` in one
atomic transaction — so the census carried it as a four-label composite rather than as a store. The
strictest-store ruling (an atomic write is classified by *every* store it touches) is what splits it
back out.

| field | value | basis |
|---|---|---|
| reproducibility | **`stateful`** | the prime preserves it: *"the answer-durability graph in Neo4j (`AnswerArtifact` / `Actor` / `Source` / `WatermarkSequence`)"*. |
| authority | **`here`** | a monotonic counter the fleet owns outright. |
| sync obligation | **`none`** | |
| releasability | reserved (§6) | |

## THE COUPLING, which is why this is a packet and not a table row

Its value is **meaningless except in relation to `sql:projector_cursor`**, and the fleet has already
paid for treating the two separately:

> *"The blanket `MATCH (n) DETACH DELETE n` this replaced deleted `WatermarkSequence`, resetting the
> monotonic answer-watermark sequence to 1 while the projector's Postgres cursor stayed parked at
> its old high value — so every new answer landed BELOW the cursor and never projected to the UI
> (the stranded-cursor bug, work 2026-07-18)."*

Both stores were individually in a defensible state. **The invariant BETWEEN them broke**, and no
per-store declaration — however carefully each is classified — can express it.

`WatermarkSequence`, `projector_cursor` and `answer_artifact_projection` form a set that must be
dropped together or not at all. ADR-0054 classifies stores one at a time; this is the case that asks
whether it needs a way to say *these three share a fate*.

## What a packet here is for

ADR-0054 §2: *"A store that fits none of the three shapes **declares its four fields anyway**,
rather than being filed under the nearest."* §7: *"No store is reclassified by this ADR; the
classification of each store is the census's output."*

So each field above is **DERIVED** (with the artifact it was read from) or **OPEN** (with the
question, and why the census cannot answer it). An open field is not a gap in this document — it is
the deliverable.

**No walk depends on this.**
