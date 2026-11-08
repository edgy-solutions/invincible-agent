---
title: Run the two-actor rehearsal checklist with Chris and watch the ledger
feature: workflow-socratic
lane: invincible-agent/lane/74
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:approve the read-only ledger reads again for the Monday window, chris:pick an asset with no open fault episode, chris:set the window and who holds the roll lock, chris:run the two-actor rehearsal script]
pr: []
ruling_ref: 
updated: 2026-11-07
---

Lane 1 holds a screenshot-per-step checklist and ledger-watch scripts. Needs a fresh case on an asset with no open episode. Whether the run happened is not recorded in the sources; any wrong screen is a defect.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/74 (architect confirmed Lane 1's reassignment table, 2026-11-06).

2026-11-07, lane 74: the plan for Monday 2026-11-09 is one page, given to Chris. It keeps Lane 1's 10-30 checklist unchanged. Chris drives both profiles and OpenDDIL, and 74 watches the ledger. On the morning, the live release is read from the release itself, worker6 must read Ready, no roll may be in flight and no run STARTED. The 10-30 ledger approval does not carry over. The run stops at the first wrong screen, with no retry.
