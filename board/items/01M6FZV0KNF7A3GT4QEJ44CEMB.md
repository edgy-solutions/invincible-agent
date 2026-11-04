---
title: Master red: the malformed-PDP seal writes sys.modules with no restore
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#233]
ruling_ref: none; fin's 11-03 report, re-measured at fd45d864
updated: 2026-11-03
---

`tests/test_the_stub_harness_puts_sys_modules_back.py::test_NO_FILE_WRITES_SYS_MODULES_WITHOUT_A_RESTORE` names six files at fd45d864. This one is `tests/security/test_a_malformed_pdp_answer_is_503_at_every_site.py`, lines 1218, 1222 and 1224, which b9699db2 added (trailer `ia-gov/lane/gov-malformed-is-503-everywhere`, merged in #210).

Attributed from the trailer of the commit that added the file. The census was already red at its parent for other files, so there is no pass-at-parent witness. The other five are on 01M6FRZ3K5477A0CNFKW1D9BBM and 01M6FRZ1Z5BNQ9GQ85GY72YRPC, and the test stays red until all three are done.

#233 takes this file off the ratchet's list with `stub_modules`. The test stays red on five other files after it, on other lanes' items.
