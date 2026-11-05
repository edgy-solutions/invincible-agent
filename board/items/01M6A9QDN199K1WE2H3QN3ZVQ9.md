---
title: Gov follow-ups on iagent-mesh v0.9.13, once master pins it (fork 7)
feature: api-sdk-mcp
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: later
blocked_on: []
pr: [invincible-agent#256, invincible-agent#262]
ruling_ref: architect 10-31 (seed becomes GRANTED_BY_SEED); 10-30 (converge the loaders in the SDK)
updated: 2026-11-05
---

v0.9.13 is tagged and carries GRANTED_BY_SEED, but master still pins v0.9.12, so these wait on the pin: the `seed` literal becomes GRANTED_BY_SEED (ruled 10-31), and the other follow-ups in earlier handoffs.

v0.9.13 is tagged. What this waits on now is master pinning it, which is 01M6A9QDN1M16XMBNHHWVK9EHJ (#247).

The seed part is #256. Gov's seals import `GRANTED_BY_SEED` and the restated `SEED` is gone. fin's `tests/finance/test_vac_ships_as_a_sample_measure.py` still compares to the literal; that file is fin's.

What remains is the 10-30 loader convergence. v0.9.13 ships `compose_export_profiles`, so `validate_policy.py`'s `known_export_profiles` composition and `_EXPORT_KIND_LABEL` can go, calling the SDK instead. Nothing blocks it. It waits on Chris's word, because the 11-04 go-ahead named `GRANTED_BY_SEED` only.

The loader part is #262, merged at `75c5c95a` (Chris, 11-04: "compose_export_profiles from the SDK, delete the copies in validate_policy.py"). `validate_policy.known_export_profiles` calls `compose_export_profiles` once per row of `policy/export_profile_sources.yaml`. With the seed part in #256, fork 7 is done when #256 lands. Moving the engine loaders onto that file is ca's 01M6A9QDN1GQ20347W16EM0D3X, and the other no-SDK forks in the validator are 01M6MZX82P0XT6HX984DZEXMV9.
