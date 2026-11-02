---
title: Re-ingest _p132/_p102 and re-golden the 20 decks
feature: training
lane: doc-tools/lane/tr
repo: doc-tools
status: blocked
priority: next
blocked_on: [01M6A9QDN1QD2GZ58BK6QCMGES, 01M6A9QDN187ZMFPKXPG9R64BS, 01M6A9QDN1VVWTM137W9WVJD9M]
pr: [doc-tools#180]
ruling_ref: 
updated: 2026-10-30
---

#180 (swallowed augmentation failure now fails the run) is merged. tr re-ingests the two failing slides and re-goldens after the PRs land, then sends wb a packet with new hashes. wb re-goldens its two cases too.
