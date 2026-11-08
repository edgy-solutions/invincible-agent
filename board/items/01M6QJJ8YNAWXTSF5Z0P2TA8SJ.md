---
title: A CDRL sourcing a dataset-backed measure exports through the resolver, grant-checked (blocks the 0.4.81 roll)
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: review
priority: now
blocked_on: []
pr: [invincible-agent#280]
ruling_ref: architect via Chris 11-05: CDRL export on a dataset-backed measure is a defect, not a consequence; 0.4.81 does not roll until export works on fin_tcpi with the flag on
updated: 2026-11-05
---

With `FIN_DATASET_URN` set (0.4.81, #277), all three sample CDRL profiles source `fin_tcpi`, and `/cdrl_export` refused them with 409 `asset_export_unsupported`. The architect ruled that a defect: a CDRL reads the same resolver the canvas does, is grant-checked the same way, and the profiles stay as they are.

- `/cdrl_export` runs each source through `_measure_envelope` as the caller. The caller's grant on each asset is checked before anything is measured or written, and the program's facts come from the asset.
- Each entry in the envelope's `sources` carries its provenance.
- `/artifact` checks the fetcher's grant.
- A package export naming a declared measure stays a 409, because its recipient readers are unruled.

Done when the PR merges and a CDRL of `fin_tcpi` exports on the sandbox with the flag on. The 0.4.81 roll waits for that.
