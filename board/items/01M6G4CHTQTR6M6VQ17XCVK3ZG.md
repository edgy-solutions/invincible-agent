---
title: Master red: the safety_finding_review audience row names a person as grantor
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: a shipped row's grantor is the seed, ruled 2026-10-31 on #176
updated: 2026-11-03
---

`policy/task_grants.yaml:327`, `safety_finding_review:SUSTAINMENT`, has `granted_by: cnogradi`, from commit `aebf4734`.

**No pass-to-fail witness exists for this row alone**, because gov's rows had already turned the same param red. What was measured: the count of such rows in the file goes from 5 to 6 at `9e52fd59`, the first master commit carrying `aebf4734`. Gov's rows are `01M6G4CHMWMWHAEXNXN12ABEZZ`.
