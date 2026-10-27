# Cortex ingest API changelog

Every change to the ingest-v1 surface gets an entry here, and a version bump when the shape hash moves (see scripts/generate_ingest_openapi.py). Wording-only changes do not move the hash.

## 1.2.0 — 2026-10-25

One request field is loosened. Every request that worked before still works.

- `POST /ingest`: `on_behalf_of` is optional now, and blank or absent means the caller. This
  page said "send it blank to mean myself" from 1.0.0 on, but the route declared the field
  required and answered a blank with 422 `missing`, so the documented call failed.

## 1.1.0 — 2026-10-25

Additive for a reader: new keys on the status row, and four existing keys can no longer be null.

- `GET /ingest/{ingest_id}/status`, at `review`: `review_task_id` now names the task a steward
  actually acts on. A zero-row notice held for confirmation names its `document_empty_confirm`
  task; before this release it named a promotion task that was never filed. New keys:
  `review_shape` (`"empty"` or `"promotion"`) and `account` (the extraction's own account of why
  it found no rows, set only when `review_shape` is `"empty"`). Off `review`, all three are null.
  At `review` all three are null when the task store cannot be read: poll again.
- `GET /ingest/{ingest_id}/status`: `extraction_defect` is `{task_id, edits}` for the newest
  defect filed about the drop, or null when none is on record. The key is absent when the server
  cannot tell. `edits` counts rows corrected, added and deleted; header corrections are not counted.
- `kind`, `sha256`, `created_at` and `updated_at` on the status row are always present and never
  null (they are NOT NULL columns; the schema said nullable).
- `POST /human_tasks/{task_id}/act` (document promotion): `row_edits` is declared as exactly
  `{corrected, added, deleted, header}`, which is what it always carried. Its `extraction_defect`
  stays a string: the same id as the status row's `extraction_defect.task_id`.

## 1.0.0 — 2026-10-23

First published contract: 13 routes, POST /ingest/{ingest_id}/empty is preview.

- Every 200 JSON body is a declared model (extra keys refused), published in
  `ingest-v1.openapi.json` and checked against every v1 200 that a test drives.
- Authentication: when the authorisation directory is down and the token has no cached
  grants, the answer is 503 `authorization_unavailable` (`retryable: true`). Before this
  release the same outage reached the caller as 401 "Authentication failed: 503: …". The
  same fix stops a token with no identity being reported as "Authentication failed: 401: …";
  it is now 401 "Invalid token payload: …".
