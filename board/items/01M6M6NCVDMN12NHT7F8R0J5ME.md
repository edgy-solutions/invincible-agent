---
title: FLOW_DECOMPOSITION is declared and projected, carrying fin's edge table
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris: fin step 3 so that #255's edge table is served on sandbox]
pr: []
ruling_ref: architect via Chris 11-04: the flow_decomposition archetype; Chris 11-04: Lane 1 declares and projects it
updated: 2026-11-04
---

The architect's EAC flow map is a `flow_decomposition` render archetype drawn from an edge table: a left-to-right, multi-level Sankey. fin serves the table (#255), and cortex draws it with the recharts Sankey it already has. Lane 1 owns the presentation half, as with `subject_concept`: the six sites in `docs/runbooks/adding-an-archetype.md`.

- The archetype arrives like every other one, as `components[*].archetype` (`FLOW_DECOMPOSITION`), and the projector row carries the edge table.
- The runbook puts site 2 (`_PROJECTED_ARCHETYPES` in `agent_fleet/presentation_agent/main.py`) after merge, roll and prime, because its passthrough is what the card reads. So the row's fields are read off the served table, not guessed in advance.
- The contract is fin's seven answers and the sink marker (`2026-11-04-packet-to-cortex-architect-and-lane-01-from-fin-the-edge-table-is-255-seven-answers-and-one-fork.md` and the 11-04 sink-marker packet). The sink fork is closed as ruled: each edge carries `node_kind` (`other` for a sink), and the label shown is `render.other_label`.

The order is fin's measure, then the live finance path, then this, then cortex against the served table.
