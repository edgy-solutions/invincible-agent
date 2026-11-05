---
title: Master red: ten cost export tests stop at the recipient check
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#238]
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone. All ten answer 403 `not_a_recipient_you_may_export_to`.

- tests/cost/test_a_board_of_every_cost_card_exports_as_one_canvas.py (5)
- tests/cost/test_an_unavailable_export_is_a_503_and_a_refused_view_never_reaches_review.py (5)

First red at 2a042971 (#181, tip 115d90b0, fin's recipient-readers rail); its parent exits 0. The gateway's new recipient check runs before these tests reach what they assert, and their fixtures configure no recipient.

Decide which it is. If the fixtures only need a recipient, add it. If a cost export with no configured recipient is meant to work, this is a live defect. Whether a live cost export is refused today was not measured.
