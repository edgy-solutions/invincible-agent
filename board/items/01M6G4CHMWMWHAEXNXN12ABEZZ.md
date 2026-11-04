---
title: Master red: 17 shipped rows name a person as grantor (repository paths, repo review, repo release)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#221]
ruling_ref: a shipped row's grantor is the seed, ruled 2026-10-31 on #176
updated: 2026-11-03
---

`tests/security/test_a_shipped_grantor_is_the_seed.py` fails for `policy/repository_paths.yaml` (12 rows) and `policy/task_grants.yaml` (5 rows: lines 557-590, `repo_review:*` and `repo_release:invincible-agent`), all `granted_by: cnogradi`.

Witness: 13 passed at `d8126f4b`, 2 failed at `b4b41ad1` (#149). The rows are commit `4d32285a`. The sixth row in `task_grants.yaml` is saf's, `01M6G4CHTQTR6M6VQ17XCVK3ZG`; that param stays red until both land.

#221 sets all 17 to the seed, and the sixth row in `task_grants.yaml` (saf's 01M6G4CHTQTR6M6VQ17XCVK3ZG) too, because the param cannot go green without it. Read: each of the 18 is a declared rail row, and none records a decision a person took at a time. The seal's last run predates the two later master merges, which only re-placed the changelog line.
