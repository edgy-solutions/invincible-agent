---
title: Five of the six identity markers: the case-runner routes, the register gate, the missing program
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#251]
ruling_ref: architect 11-03 overnight; register ruled in as its own defect, saf's packet
updated: 2026-11-08
---

Shipped in chart 0.4.79 (released 11-04 21:35Z from `758811d7`), not rolled. Doubles only, nothing live.

A case in flight at the roll is refused: `origin_record` now sends `case_id` and the route requires it. `cortex-bff` and the code location roll together.

The sixth marker (`FIX_B`) stays strict, on `01M6JKEEP6S06CQHXQZ2AA2JZV`.

Sweep 2026-11-08: done. #251 merged; the content is live from 0.4.81 (rev 228). The sixth marker stays on 01M6JKEEP6S06CQHXQZ2AA2JZV.
