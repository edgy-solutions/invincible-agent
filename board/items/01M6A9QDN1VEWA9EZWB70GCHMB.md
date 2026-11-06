---
title: Owed by Lane 1: wb audience mapper, cortex document review shape, a2/a3 builds, PRODUCER_REF packet, ca lane row
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: later
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-06
---

Owed items from 10-26: audience mapper on training-workbench realm templates, cortex PR #33 review shape, promotion writes through the SDK writer, NOTICE_PARTS_CYPHER anonymous SUBJECT_TO, cortex PRODUCER_REF packet, ca has no lanes row. Not confirmed still open.

Checked 2026-11-06 against origin/master 483da280, piece by piece (architect, 2026-11-06: close the dead, re-file the live under their owners). Closed here.

- Audience mapper on the training-workbench client: **done**. `audience-self` is emitted at helm/invincible-agent/templates/keycloak-configmap.yaml:195 and realm-reconcile-job.yaml:482.
- cortex PR #33's document review shape: the card merged (cortex-ui d915968b), but its field names were PROPOSED and never ratified. **Live**, re-filed on 01M6QGKGA9ZKYCF6CFEKP5VV9R (seat/architect).
- a3, promotion writes through the SDK writer: node and edge writes do; the SUBJECT_TO edits and deletes do not. **Live**, re-filed on 01M6QGKGGD7567NGRNWVPETTVC (74).
- a2, `NOTICE_PARTS_CYPHER`'s anonymous `SUBJECT_TO`: unchanged at agent_fleet/ontology_service/notice_parts.py:84. **Live**, re-filed on 01M6QGKGPHHJP9MKN45PZH6ZJR (74).
- The cortex PRODUCER_REF packet: never sent. **Live**, re-filed on 01M6QGKGVF12QW1REN9K0K1HMB (Lane 1, the door).
- ca has no row in `.githooks/lanes`: still true. It needs a ruling. **Live**, re-filed on 01M6QGKH0QZ2T4NGSXMPAD7KV1 (seat/architect).
