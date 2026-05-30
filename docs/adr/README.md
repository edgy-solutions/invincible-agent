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
| 0005 | Verb namespace convention | TBD (deferred from ADR-0004) |
| 0006 | Canonical verb registry location (DataHub vs Neo4j authority) | TBD (deferred from ADR-0004) |
| 0007 | System-level concepts for compound workflows | TBD (deferred from ADR-0004) |
