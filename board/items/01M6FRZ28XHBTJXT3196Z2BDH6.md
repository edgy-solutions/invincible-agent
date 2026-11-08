---
title: Master red: backfill_promotion_origin names a kind with no audit disposition
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#233]
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-04
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_kind_hardcode_audit.py::test_every_DERIVED_site_has_a_disposition names the `document_promotion` site in backfill_promotion_origin (25c339cf, gov). Give it a disposition, or remove the kind from the code.

The test has six sites across lanes 01, 74 and gov, each on its own item, so it stays red until all three are done.

#233 gives this site its row, `excluded`. The test stays red on five other sites after it, on other lanes' items.

Merged in #233. The audit no longer names this site at master 8a2717e0. It is still red for five others: 01M6FRZ2PKYJKHX9FW4W18T24A (lane/74) and 01M6FRZ3QPBAN8D1R97TTWEC3K (lane/01).
