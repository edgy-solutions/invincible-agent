---
title: Run the two-actor rehearsal checklist with Chris and watch the ledger
feature: workflow-socratic
lane: invincible-agent/lane/74
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:run the two-actor rehearsal script on Monday 2026-11-09 at 19:00Z]
pr: []
ruling_ref: 
updated: 2026-11-07
---

Lane 1 holds a screenshot-per-step checklist and ledger-watch scripts. Needs a fresh case on an asset with no open episode. Whether the run happened is not recorded in the sources; any wrong screen is a defect.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/74 (architect confirmed Lane 1's reassignment table, 2026-11-06).

2026-11-07, lane 74: the plan for Monday 2026-11-09 is one page, given to Chris. It keeps Lane 1's 10-30 checklist unchanged. Chris drives both profiles and OpenDDIL, and 74 watches the ledger. On the morning, the live release is read from the release itself, worker6 must read Ready, no roll may be in flight and no run STARTED. The 10-30 ledger approval does not carry over. The run stops at the first wrong screen, with no retry.

2026-11-08, Chris decided:
- the read-only ledger reads are approved for this rehearsal;
- 74 runs copies of Lane 1's ledger scripts, and Lane 1 watches and holds nothing;
- the asset is `dis:2:1:9002`, never used;
- the run is at 13:00 CT (19:00Z), after OpenDDIL's walk.

74 holds the roll lock by a written handover from Lane 1, and there is no start without it. The start checks are scripted, and the read-only check on asset 9002 runs first.
