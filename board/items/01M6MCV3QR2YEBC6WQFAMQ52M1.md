---
title: NetworkPolicy gate-on, sandbox fully enabled by 12-01
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: [invincible-agent#260]
ruling_ref: architect via Chris 11-04: NetworkPolicy gate-on scheduled; target sandbox fully enabled by 12-01; labels and the seal as one PR tonight
updated: 2026-11-04
---

The NetworkPolicy templates were built at 0.4.52 and have never been enabled (`networkPolicy.enabled: false`). This item turns them on for the sandbox by 12-01. The work cluster follows only after the sandbox has run a week enabled.

**Preconditions, before any flip.** These are the three from `docs/measurements/2026-10-08-the-networkpolicy-gate-cuts-the-callers-it-admits.md`, as the architect restated them:

1. **Every Job and CronJob pod carries `app.kubernetes.io/component`.** Only the pod template's label counts, because a podSelector never sees a Job object's own labels.
   - **The census, corrected 11-04 at `7a93cd2f`:** the chart renders 11 Job and CronJob objects, with sandbox values plus `demoSeed` and `topazSeed` enabled. **Two** pods carry no component: `restate-init` and `db-init`, both in `jobs.yaml`.
   - **The others are already labelled** through `invincible-agent.selectorLabels`, `prime-substrate` (a post-upgrade hook) among them.
   - **The first reading, "8 Jobs", was wrong.** It grepped the templates for the label's literal text and missed the include. The 10-08 addendum's "nine of ten" census predates those includes.
2. **The join seal reads Job and CronJob pods,** not only Deployments and StatefulSets. Today `tests/test_networkpolicy_direct_callers_join.py` arm 4 reads the object labels of `("Deployment", "StatefulSet")`.

   Preconditions 1 and 2 are one PR (architect, 11-04, tonight).
3. **Each substrate's live connections are measured** against the allowlist and recorded: conntrack or an equivalent, one measurement per substrate. This is daytime work with Chris present.

**Then the sandbox is enabled one substrate at a time,** in this order: Jena, then Weaviate, then Neo4j.

- Each step is its own roll with the settle gate. Each flip is granted by name, once that substrate's measurement is on the board.
- At each step, the `directCallers` entries in `values-sandbox.yaml` are re-dated or tightened. Every entry expires on `2026-12-14` today, and none may reach that date untouched.

**Done** when all three substrates are enabled on the sandbox, each step's measurement is recorded, and no allowlist entry is past or near its `expires` without a decision.
