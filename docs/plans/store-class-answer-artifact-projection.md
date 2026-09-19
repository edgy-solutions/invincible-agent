---
id:         store-class-answer-artifact-projection
status:     in-flight
owner:      unassigned - raised by invincible-agent-28 [5401d7] / ia-eo
blocked-on: a ruling on whether `reproducibility` asks CAN or DOES
trigger:
closed-by:
repo:       invincible-agent
summary:    THE ONE STORE OF EIGHTEEN WHERE THE TWO CLASSIFICATION BASES DISAGREE. Section 2 as amended says rebuildable (the projector replays a durable log); the prime PRESERVES it instead of dropping and rebuilding. CAN-be-rebuilt versus IS-rebuilt, and the ADR has to pick.
---

# `sql:answer_artifact_projection` — the two bases disagree

**The only store of eighteen where two independent classification bases return different answers,
and the disagreement is the interesting one.**

| basis | says | evidence |
|---|---|---|
| **A** — §2 as amended | `rebuildable` | *reproducible by a bootstrap from a durable, declared source — seed, overlay, manifest, **or log**.* The projector (`src/iagent/projector/apply_loop.py`) replays `neo4j:AnswerArtifact`, and the prime **preserves** that graph, so the log is durable and the producer is named. |
| **B** — the prime's drop set | `stateful` | `setup/prime_databases.py`: *"PRESERVED, untouched: … the derived Postgres projection stores (answer_artifact_projection, human_task_projection, projector_cursor)."* It is not dropped for the projector to rebuild. |

## The question, stated so it can be ruled

**Does `reproducibility` ask what a bootstrap CAN do, or what it DOES?** §2's wording is *"can a
bootstrap produce this again from seed and overlay?"* — which reads as CAN, and makes basis A
right. The prime's behaviour is the fleet's standing answer to DOES, and it says otherwise.

## THE FACT THAT DECIDES IT, AND IT IS IN NEITHER BASIS

**The projection cannot be rebuilt alone. It is coupled to `sql:projector_cursor`.** `apply_loop.py`
commits the row write and the cursor advance in one transaction, and the prime preserves both
together. Emptying the projection *without* resetting the cursor rebuilds nothing — every replayed
row lands below the cursor and is skipped.

Not hypothetical; the prime's own comment records it happening:

> *"The blanket `MATCH (n) DETACH DELETE n` this replaced deleted `WatermarkSequence`, resetting the
> monotonic answer-watermark sequence to 1 while the projector's Postgres cursor stayed parked at
> its old high value — so every new answer landed BELOW the cursor and never projected to the UI
> (the stranded-cursor bug, work 2026-07-18)."*

**So this store is rebuildable only as a SET with its cursor and the sequence** — the strictest-store
ruling appearing on the *rebuild* side rather than the write side. A per-store `reproducibility`
field cannot say "rebuildable, but only together with these two", and that may be the real finding.

## What a packet here is for

ADR-0054 §2: *"A store that fits none of the three shapes **declares its four fields anyway**,
rather than being filed under the nearest."* §7: *"No store is reclassified by this ADR; the
classification of each store is the census's output."*

So each field above is **DERIVED** (with the artifact it was read from) or **OPEN** (with the
question, and why the census cannot answer it). An open field is not a gap in this document — it is
the deliverable.

**No walk depends on this.**
