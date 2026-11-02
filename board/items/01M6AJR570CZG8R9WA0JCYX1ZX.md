---
title: The SDK carries the strict PDP-answer reader
feature: api-sdk-mcp
lane: iagent-mesh-sdk/lane/ca-0.9.13
repo: iagent-mesh-sdk
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 11-02 ruling
updated: 2026-11-02
---

A boolean `check` is the answer, an absent field is no, and anything else raises as an outage, never a no. Source: agent_fleet/utils/pdp_answer.py in invincible-agent#190. The workbench needs it for 01M6A9QDN1VCGZRXDMMKTFWT1T. ca names the release; gov's packet is in master's sessions/, dated 11-02.
