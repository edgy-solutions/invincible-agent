---
title: The chart's domain broker is a third copy of the door: no token on register, resolve ungated
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: the architect's four answers, item 4
updated: 2026-11-03
---

`helm/invincible-agent/files/domain-broker.py` runs as `iagent-domain-broker`. Its `POST /api/v1/internal/resolve` returns raw DB credentials and is classed `ungated_by_accident` CRITICAL in the gating manifest. Its register call carries no token, so under `INTERNAL_DOOR_POSTURE=enforce` the gateway refuses it and its URNs drop.

It needs its own PR here before anyone sets enforce. dag-tools#8 guards the other two copies.
