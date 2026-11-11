---
title: Recipient scope for a program only the asset holds
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: Chris 2026-11-09 (fin source ruling) — a board item, not a blocker
updated: 2026-11-09
---

Under `FIN_DATASET_URN` a package or CDRL can export a program that only the asset holds, not the
seed. Who may receive that file is the recipient rail (`recipient_readers`, read through
`can_read_recipient`); it governs the file, not the asset (ruled 2026-11-08). Its scope for such a
program is not yet settled: the recipient scopes a deployment declares today name the seed's
programs.

Done when a recipient scope can name an asset-only program, the fetch of a file exported for one is
decided by that scope, and a test shows a reader outside the scope refused and one inside served.
