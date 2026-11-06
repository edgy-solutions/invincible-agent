---
title: Promotion's SUBJECT_TO edits and deletes bypass the SDK writer
feature: cross-cutting
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-06
---

Re-filed from 01M6A9QDN1VEWA9EZWB70GCHMB (a3). In src/iagent/promotion_stores.py, node creates and edge writes go through the SDK writer (`self._writer.write_node` :396, `write_edge` :438, `delete_edges` :455). The SUBJECT_TO row edits and deletes in Neo4jIngestGraph are raw `session.run` calls: `_DELETE_BARE_NODE_CYPHER` :465, `_REMOVE_EDGES_CYPHER` :493, `_DELETE_EDGE_CYPHER` :533. Assigned to 74 as the SDK-revisions lane; the architect may redirect.
