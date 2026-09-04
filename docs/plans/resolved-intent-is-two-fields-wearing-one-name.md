---
id:         resolved-intent-is-two-fields-wearing-one-name
status:     open
owner:      agent (lane 1) — FILED, NOT RENAMED (a rename crosses four surfaces)
blocked-on: a ruling on whether the extraction keeps a field of its own
repo:       invincible-agent
ruled-by:   ADR-0023 (the AnswerArtifact node shape)
code-site:  src/iagent/gateway.py:3739 (the extraction capture), src/iagent/gateway.py (the subtask_slots_decision consumer), src/iagent/answer_artifact_writer.py:130 and :486 (the model field and the Cypher SET)
summary:    `resolved_intent` HELD EXTRACTION, NOT RESOLUTION, on every artifact ever written. It was populated once at bundle creation from /route_intent's ExtractIntent output — `mode` and `entity_refs`, captured before any resolution runs — and never updated. The post-run write now fills it with the real thing (accepted slots, refused slots, per-slot resolution outcomes, disposition), so THE NAME IS NOW TRUE and this packet is no longer urgent. What remains is a naming question with a real consequence: the extraction is still a fact worth keeping, and it no longer has a home. Filed rather than renamed because the field name is a Neo4j property written by `a.resolved_intent = $resolved_intent`, so a rename is a graph migration plus a writer change plus every reader, and it must not ride in on a correctness fix.
---

# `resolved_intent` is two fields wearing one name

## What was true until 2026-09-04

```python
# gateway.py:3739 — at bundle creation, before anything resolves
"resolved_intent": intent_extraction or {},
```

`intent_extraction` is `/route_intent`'s response: `mode`, `entity_refs`, `confidence`,
`reasoning`. **It is the FIRST hop.** No subject, no verb, no slots, nothing resolved. And
nothing updated the field afterwards, so every artifact in the graph carries extraction under a
name promising resolution.

**The name was not merely imprecise — it was the only description of that field anyone had.**
A reader auditing "what did the system understand about this question" got the model's opening
guess and had no way to know it.

## What is true now

The supervisor emits `subtask_slots_decision` at its disposition point — the only line where the
accepted parameters, the refused ones, the per-slot resolution outcomes and the
`route | ask | abstain` decision all exist at once — and the gateway writes that into
`resolved_intent`. The field now holds what it says.

**So this packet is not urgent, and that is exactly why it is worth writing down.** The pressure
to rename came from the field being wrong. Now that it is right, the remaining problem is quieter
and will be forgotten: **the extraction lost its home.**

## The question this leaves

`mode` and `entity_refs` were real captured facts. They are what `/route_intent` returned, and
they are the input the whole rest of the run was computed from. Today they are simply dropped
from the artifact — overwritten by the resolution rather than recorded beside it.

Three dispositions, and they differ in what a later reader can ask:

1. **Leave it dropped.** The extraction is recoverable from the run's own logs and is rarely the
   question anyone asks of an artifact. Cheapest, and it loses the ability to answer *"did the
   model mis-extract, or did resolution go wrong?"* from the artifact alone — which is the
   question a wrong answer actually raises.
2. **A second field, `extracted_intent`.** Honest, symmetrical with `resolved_intent`, and makes
   the mis-extraction question answerable. Costs a graph property, a writer change and a
   projection.
3. **Nest both under one field.** Avoids a schema addition and reintroduces the original defect
   in miniature: two answers to *"what did the system understand"* in one place, with nothing
   saying which is current. **Refused on the same grounds the overwrite was chosen over a merge.**

**My lean is (2), and I am not taking it.** The rename half — should `resolved_intent` become
something else — is answered by doing (2): it stays, because it is now accurate, and the
extraction gets its own name rather than the resolution getting a new one.

## Why this was not just done

`resolved_intent` is a **Neo4j property name**, written by
`a.resolved_intent = $resolved_intent` (answer_artifact_writer.py:486) and declared on the
bundle model at :130. A rename is a graph migration over every existing artifact, plus the
writer, plus every projection and reader — and doing it inside a commit whose purpose was to fix
what the field CONTAINS would have made a correctness fix unreviewable and a migration invisible.

Recorded per the standing rule that a rename rides its own change, never someone else's.
