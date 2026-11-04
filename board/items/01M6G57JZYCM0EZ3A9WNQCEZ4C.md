---
title: can_configure subjects come from a registry; a misspelt key fails validation (#223)
feature: training
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#223]
ruling_ref: fork 25, answered by the architect (a registry, as for can_review)
updated: 2026-11-03
---

`policy/configure_subjects.yaml`, first row `deck_template`. `validate_policy` refuses a `can_configure:<S>` key whose S is not in it. No answer changes: `can_configure:` is inert until the workbench asks. Mutants S1-S7 killed. In-process only; CI does not run these seals.
