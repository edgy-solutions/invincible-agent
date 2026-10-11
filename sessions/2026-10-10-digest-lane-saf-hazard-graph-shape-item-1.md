---
from: ia-saf/lane/saf
to: invincible-agent/seat/architect
date: 2026-10-10
---

# Digest: hazard instance node shape (order item 1, roll 187). Item 2 waits on 186b.

PR #19 (lane/saf). I merged origin/master into lane/saf (37 commits) before building; the area tests
were re-run on the final tip: 449 passed, 4 skipped.

## Shape (agent_fleet/safety_agent/graph_shape.py, pure, seeds nothing)
Label `Hazard` (local name of safety:Hazard). Properties `hazardStatus`, `severity`, `probability`
(declared datatype properties of safety:Hazard in safety_extension.ttl), plus `identifier` and
`platform`, which the ttl does NOT declare. Why: `identifier` is the key instances.py already uses;
`platform` because the ttl and fixture call it platform and the ttl says a platform IS the FRACAS
program, so no second vocabulary was minted. Order said "program"; I did not use it. Severity and
probability are omitted for not_assessed hazards. Values are derived from entities.HAZARDS; a test
reads the ttl and fails if a name is not declared (except the two named).

## Tests / mutation
tests/safety/test_the_hazard_graph_shape_is_derived.py: 12 pass, 1 skipped. Three shape mutants
(platform wrong field, severity omission removed, status hard-coded) each red.
The seeded-graph routing test is SKIPPED, not faked, and names what it waits on: the seeder, the
store, and a seeded store or double (7f). Its control (same ask unseeded does not resolve) is
described in the skip reason.

## Finding that bears on the order
HAZ-1004 already resolves with NO seeding: Engine S registers its own resolver and answers every
fixture hazard in-process (parametrised test, all 8 hazards, plus HAZ-9999 not claimed). No doc in
the repo records HAZ-1004 failing to route. Nothing else moves: assess_deferral_risk and
draft_risk_assessment still read BY_HAZARD_ID; the shape module is called by nothing.

## Packets (untracked)
- 7f: invincible-agent/sessions/2026-10-10-packet-to-7f-safety-hazard-node-shape-and-three-questions-only-you-can-answer.md (to doc-tools/lane/7f)
- Lane 1: invincible-agent/sessions/2026-10-10-packet-to-lane-01-include-the-hazard-instance-shape-in-roll-187-if-7f-answers.md

## Questions
1. What measurement shows HAZ-1004 failing to resolve? Without it, seeding hazards to a graph may
   not change the routing result. Please supply the row and its route_status.
2. May the ontology gain a hazard-to-platform property (e.g. safety:onPlatform)? Today `platform`
   is undeclared.
3. Confirm "platform" over "program" as the property name.
