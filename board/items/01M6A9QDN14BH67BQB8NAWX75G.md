---
title: Engine S check to SDK is_safety_critical (queue c)
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: blocked
priority: later
blocked_on: [01M6A9QDN1KAR37N824W55YGA3, 01M6A9QDN1P8WX74K5QF71838K]
pr: []
ruling_ref: architect 10-28
updated: 2026-10-28
---

Switch measures.py:248 from SAFETY_ITEMS to SDK is_safety_critical(mpn, domain) served by the gateway. Build nothing until ca and Lane 1 land their parts.
