---
title: ADR-0065 C: the ontology slice extends product_structure_extension.ttl with configuration, lifecycle_status and ltb_decision
feature: pcn-pdn
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect via Chris 2026-11-07 on #299, ADR-0065 ruling 1: extend product_structure_extension.ttl (ADR-0051's file); no new file; one Part node; add the configuration, lifecycle_status and ltb_decision classes there
updated: 2026-11-07
---

This is ADR-0065 item C. The order is A (ADR-0066), then C, D and E.

- **No new file and no second Part class.** `ps:Part` is the one Part node, and the IOF Core alignment is added on it. `ps:PartUsage` already carries the used-in relation, with quantity, reference designator and applicability.
- **Three classes are added:**
  - `configuration`: `as_designed`, `as_built` or `as_maintained`;
  - `lifecycle_status` on a Part: `{status, source, as_of, successor?}`. Status absent means not assessed. Status null means assessed, and none known;
  - `ltb_decision`: `{quantity, by, rationale, approved_by}`.
- **Vocabulary** is cited from AP242, S3000L, EIA-649 and S5000F, and never copied.
- **The where-used verb (E) reads these classes.** E's `configuration` argument takes its values from this item's `configuration` class.
