---
title: The where-used verb: an impact table over a product structure
feature: pcn-pdn
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 2026-11-06: where-used goes to 74; obsolescence is logistics; saf gets only the safety-critical check on a part
updated: 2026-11-06
---

ADR directive item E (architect, 2026-11-06; order A, then C, D, E, with B alongside A). The where-used verb answers an impact table {end_item, program, qty_per, population, stock} for a part, tested against a synthetic 3-level BOM fixture. It builds on C, `setup/ontologies/product_structure.ttl` (component_of with quantity, ref_designator and effectivity), and on D, the registry rows. saf's share is only the safety-critical check on a part (S3's pattern).
