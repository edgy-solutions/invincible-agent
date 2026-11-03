---
title: Master red: the MCP chart seal trips on a changelog line
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

tests/test_mcp_chart.py::test_invincible_agent_chart_is_unchanged_by_this_chart finds `iagent-mesh-mcp` in helm/invincible-agent/CHANGELOG.md (line 158 at e0a2ab9b, from 9f833cd0, 0.4.74). A changelog is prose, not chart content, so the seal should exclude it.
