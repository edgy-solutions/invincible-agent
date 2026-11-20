---
title: Access requests UI (Request access / Grant / Deny)
feature: engine-r
lane: cortex-ui/master
repo: cortex-ui
status: blocked
priority: later
blocked_on: [01M7H85DYFS5ANPJTWBR6APFK0]
pr: [cortex-ui#50]
ruling_ref: ADR-0062; architect 2026-11-15 (via Chris): accessRequests stays off; the BFF serves no /access/proposals stub
updated: 2026-11-15
---

Merged 10-30 behind a flag; stays off until engine-r exists. A policy refusal shows who can grant.

**2026-11-15:**
- Re-pointed from the ADR item, which is done, to engine-r's first slice (01M7H85DYFS5ANPJTWBR6APFK0), the piece that will serve `/access/proposals`.
- Ruled: the flag stays off, and the BFF serves no stub in the meantime.
