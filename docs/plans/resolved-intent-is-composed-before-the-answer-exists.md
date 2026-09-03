---
id:         resolved-intent-is-composed-before-the-answer-exists
status:     open
owner:
blocked-on: Lane 1 (the resolved_intent producer write) — this packet is the seam finding it needs, not the write itself
repo:       invincible-agent
code-site:  src/iagent/gateway.py:3739 (bundle creation), :4224 (the write), src/iagent/defs/dynamic_supervisor.py:2551 (output_uri selection)
ruled-by:   ADR-0033 (the ask disposition); the projector build plan (AnswerArtifact fields)
summary:    ASKED TO CONFIRM THE ASK'S PARTIAL FILL REACHES THE ARTIFACT. IT DOES NOT, AND THE REASON IS STRUCTURAL RATHER THAN A MISSING LINE. `_artifact_bundle["resolved_intent"]` is set ONCE at bundle creation (gateway.py:3739) from `intent_extraction` — the /route_intent response, produced BEFORE the supervisor runs — and is never assigned again; grep for the key finds exactly two sites, the creation and the write at :4224. Eleven other bundle fields ARE updated post-run (routing, graph_trace, sources, rendered_output, duration_ms, status), so the pattern exists and resolved_intent is simply not in it. CONSEQUENCE: nothing the supervisor learns can reach resolved_intent — not the filler's output, not the resolver's outcome, and not the ask's partial `accepted_slots`. Lane 1's planned write has no hop to write into. THE ASK'S DATA IS NOT LOST, it is in the wrong place: `accepted_slots` rides `expert_response` into `generate_ui_payload` and reaches Engine F as `raw_data`, so it survives to the RENDERER but not to the ARTIFACT. GOOD NEWS FROM THE SAME TRACE, verified rather than assumed: `generate_ui_payload` selects the archetype from `expert_res.get("output_uri")` (dynamic_supervisor.py:2551), which is exactly the field `ask_card` now emits — so `mesh:SlotElicitation` is wired to its consumer.

# `resolved_intent` is composed before the answer exists

**Found 2026-09-03** by the confirmation asked for when `duration_ms` / `resolved_intent` were
ruled to be the gateway's fields and not the ask's: *"confirm the partial `accepted_slots` reaches
the artifact; the rest is Lane 1's."*

**It does not.** And the reason matters more than the fact, because it means the owed write has
nowhere to land rather than merely not having been written yet.

## The trace, three greps

```
gateway.py:3739   "resolved_intent": intent_extraction or {},      <- bundle creation
gateway.py:4224   resolved_intent=_artifact_bundle["resolved_intent"],   <- the write
```

Those are the **only two** occurrences of the key. There is no third.

`intent_extraction` is the `/route_intent` response, and `/route_intent` runs **before the
supervisor is launched** — it is what *decides* the launch. So `resolved_intent` records what the
router guessed from the raw sentence, and the artifact is stamped with it before any engine has
run.

**The pattern for updating a bundle post-run exists and is used eleven times** — `status`,
`routing`, `produced_by`, `graph_trace`, `graph_trace_alternates`, `sources`, `rendered_output`,
`duration_ms`. `resolved_intent` is simply not among them.

> **So this is not a missing line, it is a missing hop.** Lane 1's planned write — *"carry what
> was filled before the ask fired, and the missing slot's resolution outcome"* — has no seam to
> write into. Adding the producer side without this would produce a correct value with no path.

## Why it reads as a defect and not an omission

The field is named `resolved_intent`, and **nothing in it is resolved.** It is *extracted* intent:
the router's read of the sentence, pre-fill and pre-resolution. That is exactly the
actively-misleading shape already filed against it — a card showing `site S2` with no `spoken`,
where the id came from somewhere the artifact cannot name.

For an ask it would be worse than misleading. The whole content of an ask is *what is missing*,
and an artifact whose `resolved_intent` predates the disposition records the router's guess at a
question the system then declined to answer.

## The ask's data is not lost — it is in the wrong place

`accepted_slots` rides `expert_response` out of `execute_subtask`, and `generate_ui_payload` sends
the whole `results` array to Engine F as `raw_data`. So the partial fill **survives to the
renderer** and can be shown; it just never becomes part of the artifact's own record.

That is a real distinction for the ask's purpose: the card can already say *"I have the window; I
need the program"* from `raw_data` today. What it cannot do is have that fact **persisted as
provenance**, which is what an AnswerArtifact is for.

## Verified in the same trace, and it is the good half

`generate_ui_payload` picks the archetype like this (`dynamic_supervisor.py:2551`):

```python
if isinstance(expert_res, dict) and expert_res.get("output_uri"):
    agent_output_uri = expert_res["output_uri"]
```

That is **exactly the field `ask_card` now emits** (`fbcf4e7`). So `mesh:SlotElicitation` is wired
to the consumer that selects on it — confirmed by reading the selector rather than by assuming the
emission was enough. It still needs the prime to exist in the graph.

## What is owed, and to whom

**This lane:** nothing further. The ask emits `output_uri`, carries `accepted_slots`, and both
reach `generate_ui_payload`. Confirmed and stated rather than assumed.

**The gateway/artifact owner:** a post-run update to `resolved_intent`, or a second field that
carries the resolved truth beside the extracted guess. **Whichever, the two must be
distinguishable** — collapsing "what the router extracted" and "what the system resolved" into one
key is what made the current value misleading, and re-using the key for the corrected value would
inherit the confusion rather than fix it.

**Lane 1:** the producer write, once the hop exists.

> **Sequencing, stated because it is the cheap fact here:** the write cannot be tested before the
> hop exists, so building it first produces a value nobody can observe — the shape
> `[[a-registration-is-not-a-reachable-call]]` names. The hop is the prior item.
