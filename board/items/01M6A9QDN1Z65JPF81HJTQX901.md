---
title: DocumentReviewCard reads /review-shapes and item-form coverage
feature: pcn-pdn
lane: cortex-ui/master
repo: cortex-ui
status: review
priority: next
blocked_on: []
pr: [cortex-ui#62]
ruling_ref: config rule test 4 (10-30)
updated: 2026-11-03
---

Card still picks on a literal review_shape name and sends a private section_verdicts wire. Producer cannot yet verify section coverage (only a part universe exists). Cortex asked lane 01 three questions; no code until answered.

cortex-ui#62 merged; the card passes against a sections[] fixture. The producer half is invincible-agent#225. cortex keeps the names marked PROPOSED until a seal can read them from a release carrying #225, and that release must also re-pin cortex (26a2049 asked for).
