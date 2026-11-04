---
title: The mesh_demo_customers s3 object isn't in the catalog, so grant_sync refuses the file
feature: finance
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:a DataHub read of the s3 URN and the catalog sync]
pr: []
ruling_ref: architect's owed list: the dagster to s3 URN form on the mesh_demo_customers grant
updated: 2026-11-04
---

0.4.78's grant names the `s3` form, which matches the live Redis route key. Topaz answers 404 for it and 200 for the `dagster` form, with two controls. `grant_sync` refuses the whole file (exit 3) until the object exists, and no hook runs `grant_sync`, so this can't stop a roll.

DataHub answered 401 without a token, and I don't fetch one from a pod. So whether DataHub holds the `s3` form isn't measured. dag-tools' `test_inventory_urn_derivation.py` pins `_derive_urn` to `dagster`, which disagrees with the live key: read, not run.
