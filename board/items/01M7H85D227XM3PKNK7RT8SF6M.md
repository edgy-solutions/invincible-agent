---
title: Interim fix for case-1's uncommitted grant, ahead of engine-r's slice
feature: engine-r
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 2026-11-15 (via Chris): interim fix owner saf, ahead of the slice; accessRequests stays off; no /access/proposals stub
updated: 2026-11-15
---

Today's access loop is the case-1 path: `POST /access_requests`, then the approver's `POST /human_tasks/{id}/act`, then `human_tasks.write_grant_and_sync`.

That last step writes `/app/policy/asset_grants.yaml` inside the running BFF pod and syncs Topaz, and it never commits. That has three effects:
- The grant has no author and no audit record.
- The file is image-baked, with no mount, so the pod's next restart loses it.
- The seed CronJob re-syncs Topaz from git's copy, which lacks the grant. Whether that sync removes the relation is UNMEASURED.

This item closes that gap until engine-r's first slice replaces the path. It goes ahead of the slice. The design is saf's.

Done means:
- an approved grant survives a BFF restart and the next seed sync;
- it carries who approved it and when, in a record someone can read back.

The step-by-step read is Lane 1's engine-r status page of 2026-11-14 (section 6).
