# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) for the
Invincible Agent fleet — short, immutable documents that capture
architectural decisions, their context, what we considered, and the
indicators that would lead us to revisit.

## Why ADRs

Commit messages explain *what changed*. ADRs explain *what we decided*
and *why* — particularly for decisions that have long half-lives, span
multiple commits, or could plausibly be re-litigated by future contributors
who don't have the original context. An ADR's job is to let a colleague
six months from now answer the question *"why did we do it this way?"*
without spelunking through Slack archives or PR threads.

If a decision is purely local (renamed a variable, picked a library
because it's the obvious one, fixed a bug) — commit message. If a decision
shapes how future work gets done — ADR.

## Layout

Each ADR is a single Markdown file named `ADR-NNNN-short-slug.md`, where
`NNNN` is a zero-padded sequence number. Numbers are assigned at merge
time and never reused. ADRs are immutable once accepted — if a decision
is reversed or superseded, write a new ADR that links back to the old
one and update the old one's *Status* field accordingly.

Template skeleton:

```
# ADR-NNNN — Short imperative title

**Status:** Proposed | Accepted | Superseded by ADR-XXXX | Deprecated
**Date:** YYYY-MM-DD
**Deciders:** name(s)
**Related:** ADR-XXXX, ADR-YYYY  (cross-links if applicable)

## Context

What's the situation, what problem does this decision address, what
constraints are in play.

## Decision

The thing we decided to do, stated declaratively.

## Consequences

What follows from this decision — both the wins and the costs we accept.

## Alternatives considered

Other options we evaluated and why we rejected them. Short bullets are
fine.

## Indicators for revisiting

The conditions under which we'd reopen this ADR. If we can't write any,
the decision probably isn't ADR-worthy — it's permanent.
```

## Index

| # | Title | Status |
|---|---|---|
| [0001](ADR-0001-mem0-llm-decouple.md) | Decouple mem0's internal LLM from the agent reasoning LLM | Accepted |
| [0002](ADR-0002-mem0-monkeypatches.md) | Carry two upstream-mem0 monkey-patches in `utils/mem0_utils.py` | Accepted |
| [0003](ADR-0003-llm-rightsizing.md) | Right-size LLMs per workload class on the agent mesh | Accepted |
| [0004](ADR-0004-predicate-graph-routing.md) | Predicate-graph routing for the agent mesh (SPO/verb model) | Accepted |
| [0005](ADR-0005-verb-and-concept-namespaces.md) | Two-class namespacing for verbs and concepts (domain vs platform) | Accepted |
| [0006](ADR-0006-verb-registry-location.md) | DataHub as proposal inbox, Neo4j as runtime substrate | Accepted |
| [0007](ADR-0007-survey-before-mint.md) | Survey existing ontologies before minting `mesh:` concepts | Accepted |
| [0008](ADR-0008-routing-fallback-policy.md) | Routing fallback policy (LLM as generalist fallback) | Accepted |
| [0009](ADR-0009-sunset-classification-axes.md) | Sunset persona / domain / intent as classification axes | Proposed |
| [0010](ADR-0010-distributed-tracing-strategy.md) | Distributed tracing strategy (OpenTelemetry at the HTTP boundary) | Proposed |
| [0011](ADR-0011-multi-spo-routing.md) | Multi-SPO routing in NL (design exploration) | Proposed |
| [0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md) | iagent AnswerArtifact as a graph-native CQRS object (Neo4j write + Electric read) | Proposed |
| [0024](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md) | Standards composition (BPMN / CALM / ODPS / ODCS) + publish/promotion (one-way emit; PublishedArtifact thin reference; SUPERSEDES chain; honest dangling) | Partially Proposed (publish 2026-06-27); Reserved (standards) |
| [0025](ADR-0025-instance-plane-access-control-as-provenance.md) | Instance-plane access control as provenance (ABAC over Topaz; captured on Source/CITES; carried by Artifact) | Proposed (+ amendments) |
| [0026](ADR-0026-persona-entitlement-topaz-authorization.md) | Persona & entitlement authorization via Topaz (matrix, git-asserted, per-prompt declared) | Proposed |
| [0027](ADR-0027-composable-approval-policy.md) | Composable multi-dimensional approval policy (grant-issuance governance over the single decider; auto-checked attributes vs human approvals; multi-approval extends HITL) | Accepted (architecture) — single-dimension built, composable deferred |
| [0028](ADR-0028-canvas-answer-composition-workspace.md) | The canvas as an answer-composition workspace (SPO eligibility made spatial; cards carry SPO provenance from v1; Q&A→workflow bridge — aggregation v2, workflow-seeding v3 coupled to ADR-0024) | Accepted (v1 forward-compat constraints) — deeper canvas directional/deferred |
| [0029](ADR-0029-process-workflow-model-spo-steps-restate.md) | The process-workflow model (SPO-native steps + human-await on Restate, git-asserted definitions, superseding BPMN→Dagster; standard→substrate mapping) | Accepted (model shape + process→Restate seam); build deferred to slices |
| [0030](ADR-0030-verb-output-is-a-fixed-type.md) | Re-confirms ADR-0017 §1 (fixed output type per verb) under ADR-0029, and RECORDS THE REJECTION of result-dependent output (it breaks the spo_operation verifier + Slice-4 seeding). ~70% re-derivation; the kept 30% is the dated rejection + edgeless-topology honesty. Presentation transforms marked directional-not-required; content-based render selection left an open question | Accepted |
| [0031](ADR-0031-instance-resolution-ladder.md) | Instance-resolution ladder (exact → containment → LLM-candidate → abstain); LLM demoted from classifier to candidate generator ("proposes, phone-book disposes"). Rungs 1–2 built (`87fe361`); rung 3 (LLM) deferred pending real telemetry (recall_override / no_instance / RESOLVE_INSTANCE_ALIAS logs); descriptor list defended as a frozen closed grammatical class; v2 alias-persistence growth loop scoped | Accepted (rungs 1–2; rung 3 deferred) |
