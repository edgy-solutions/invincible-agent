# Cortex ingest API changelog

Every change to the ingest-v1 surface gets an entry here, and a version bump when the shape hash moves (see scripts/generate_ingest_openapi.py). Wording-only changes do not move the hash.

## 1.0.0 — 2026-10-23

First published contract: 13 routes, POST /ingest/{ingest_id}/empty is preview.

- Every 200 JSON body is a declared model (extra keys refused), published in
  `ingest-v1.openapi.json` and checked against every v1 200 that a test drives.
- Authentication: when the authorisation directory is down and the token has no cached
  grants, the answer is 503 `authorization_unavailable` (`retryable: true`). Before this
  release the same outage reached the caller as 401 "Authentication failed: 503: …". The
  same fix stops a token with no identity being reported as "Authentication failed: 401: …";
  it is now 401 "Invalid token payload: …".
