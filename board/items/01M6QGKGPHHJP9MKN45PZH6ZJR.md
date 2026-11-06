---
title: NOTICE_PARTS_CYPHER matches SUBJECT_TO anonymously
feature: pcn-pdn
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-06
---

Re-filed from 01M6A9QDN1VEWA9EZWB70GCHMB (a2). agent_fleet/ontology_service/notice_parts.py:84 still reads `OPTIONAL MATCH (c:SUSTAINMENT:Component)-[:SUBJECT_TO]->(n)`, with no variable on the relationship. Assigned to 74: obsolescence intake is logistics (architect, 2026-11-06).
