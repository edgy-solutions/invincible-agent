---
title: engine-r first slice (ADR-0062 section 7)
feature: engine-r
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 2026-11-15 (via Chris): slice owner saf; accessRequests stays off; no /access/proposals stub
updated: 2026-11-15
---

The slice ADR-0062 section 7 specifies, and nothing of it runs today:
- the engine service, with its own chart, release and Deployment;
- the PVC `engine-r-repos`, with the repository imported;
- a Keycloak client;
- the `repo_review:*` and `repo_release:*` audiences in `policy/task_grants.yaml`. `policy/repository_paths.yaml` names `repo_review:POLICY`, and no task grant defines it yet;
- the mirror to `edgy-solutions/invincible-agent-mirror` through the GitHub App;
- one access request end to end: bob asks for `NP-MERIDIAN`, alice grants it, then merge, sync and retry. It replaces `human_tasks.write_grant_and_sync`.

**Already in place:**
- The library `agent_fleet/repository_agent/` (propose, merge, tag, repair_tag, audit). It has no service, no caller and no review verb.
- The paths rail `policy/repository_paths.yaml`.
- The Secrets `engine-r-signing` and `engine-r-mirror`, on sandbox.

**Ruled 2026-11-15:**
- The `accessRequests` flag stays off until this slice serves it.
- The BFF serves no `/access/proposals` stub.

The interim grant fix (01M7H85D227XM3PKNK7RT8SF6M) goes first. The slice's measurement is section 7's six report items.
