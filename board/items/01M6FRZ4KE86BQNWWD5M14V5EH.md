---
title: Master red: Neo4jGraph lacks the SDK Protocol's is_safety_critical
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_mesh_graph_conforms.py::test_it_satisfies_the_protocol_structurally. SDK v0.9.12 added `is_safety_critical` to the Protocol (interfaces.py:384), ruled 10-30 as a type-only stub ahead of a concrete client in v0.9.13. `Neo4jGraph` (agent_fleet/ontology_service/mesh_graph.py:159) lacks it. The red arrived with the pin bump at 5c16695f.

The capability is absent by ruling, so the fix is either to implement it or to make the seal say the stub is expected until v0.9.13.
