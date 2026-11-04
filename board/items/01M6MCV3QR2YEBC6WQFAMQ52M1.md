---
title: NetworkPolicy gate-on, sandbox fully enabled by 12-01
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect via Chris 11-04: NetworkPolicy gate-on scheduled; target sandbox fully enabled by 12-01
updated: 2026-11-04
---

The NetworkPolicy templates were built at 0.4.52 and have never been enabled (`networkPolicy.enabled: false`). This item turns them on for the sandbox by 12-01. The work cluster follows only after the sandbox has run a week enabled.

**Preconditions, before any flip.** These are the three from `docs/measurements/2026-10-08-the-networkpolicy-gate-cuts-the-callers-it-admits.md`, as the architect restated them:

1. **Every Job and CronJob template carries `app.kubernetes.io/component`.** Read at `72ec3975`: 7 template files and 8 Job objects carry none, because `invincible-agent.labels` has no component label. The 8 are:
   - `demo-seed-job`, `engine-reregister-job`, `minio-bucket-init-job`, `ontology-seed-job`, `prime-substrate-job` and `realm-reconcile-job`;
   - the two Jobs in `jobs.yaml` (`restate-init` and `db-init`).

   `prime-substrate-job` is a `post-install,post-upgrade` hook, so a policy that cuts it fails the release.
2. **The join seal reads Jobs and CronJobs,** not only Deployments and StatefulSets. Today `tests/test_networkpolicy_direct_callers_join.py` filters on `("Deployment", "StatefulSet")`.
3. **Each substrate's live connections are measured** against the allowlist and recorded: conntrack or an equivalent, one measurement per substrate.

**Then the sandbox is enabled one substrate at a time,** in this order: Jena, then Weaviate, then Neo4j.

- Each step is its own roll with the settle gate, and Chris grants each one by name.
- At each step, the `directCallers` entries in `values-sandbox.yaml` are re-dated or tightened. Every entry expires on `2026-12-14` today, and none may reach that date untouched.

**Done** when all three substrates are enabled on the sandbox, each step's measurement is recorded, and no allowlist entry is past or near its `expires` without a decision.
