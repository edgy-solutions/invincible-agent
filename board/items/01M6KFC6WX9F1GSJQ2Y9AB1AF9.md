---
title: Adoption ratchet fork 4: restate_analyst's workflow DSL is hand-copied from the SDK
feature: api-sdk-mcp
lane: invincible-agent/lane/74
repo: invincible-agent
status: blocked
priority: later
blocked_on: [01M6A9QDN107DJ6YGHPX7J0MR6]
pr: []
ruling_ref: architect 2026-11-04 (fork 4)
updated: 2026-11-04
---

`agent_fleet/restate_analyst/workflow_definition.py` hand-copies 11 SDK DSL classes (CompletionPolicy, the eight step classes, WorkflowDefinition, StubVerb) instead of importing them. The adoption ratchet counts this as fork 4. Starts after the Socratic bar (ADR-0061: a runnable run with the planted contradiction caught).
