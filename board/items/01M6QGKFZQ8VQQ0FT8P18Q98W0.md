---
title: The where-used verb: an impact table over a product structure
feature: pcn-pdn
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect via Chris 2026-11-07 on #299, ADR-0065 rulings 2 and 4: where-used takes a declared configuration (default as_designed, no data refused loudly) and every impact row names it; ImpactRow is nine fields. Earlier, architect 2026-11-06: where-used goes to 74; obsolescence is logistics; saf gets only the safety-critical check on a part
updated: 2026-11-07
---

ADR directive item E (architect, 2026-11-06; order A, then C, D, E, with B alongside A). Amended by ADR-0065's rulings (#299, cc6597d9).

- **The verb's argument.** It takes a declared `configuration`: `as_designed`, `as_built` or `as_maintained`, with `as_designed` the default. A configuration with no data is refused loudly, never answered empty.
- **The impact row is nine fields:** `{end_item, program, component, qty_per, population, stock, configuration, as_of, data_provenance}`. Every row states the configuration it was computed for. "Absent is not zero" stands.
- **Tests** run against a synthetic 3-level BOM fixture.
- **It builds on C**, which extends `product_structure_extension.ttl` (board item 01M6W93VSQMD9W83YCXJHQND5Z), and **on D**, the registry rows (01M6W93W013YFR30HE67S3VF8B).
- **saf's share** is only the safety-critical check on a part (S3's pattern).
