---
title: Master red: the review-export catalogue seal, item_kind and review_shape are not in the reviewed list
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-02
---

test_s3_the_catalogue_is_the_reviewed_list fails on master (measured at 3e4e0162): NOTICE_FIELDS has item_kind and review_shape, which CATALOGUE_NOTICE does not. The seal says widening the catalogue is a deliberate act that edits its list, so someone has to decide whether those two may be served as export columns. Filed by gov, not fixed; not in the suite-signal census.
