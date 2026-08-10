---
id:         dagster-loader-call
status:     open
owner:
blocked-on: an owner for the Dagster plane
closed-by:
code-site:  src/iagent/definitions.py
repo:       invincible-agent
summary:    build_dynamic_jobs() runs unconditionally on every Dagster load; whether its catalog is empty is unconfirmed.
---

# Dagster loader call — unconditional, against a possibly-empty catalog

Rider filed by ADR-0039. Recorded as fact, not adjudicated: the Dagster plane's lifecycle is its
owner's decision, made when they touch it.

## The fact — VERIFIED

`src/iagent/definitions.py:27` calls `dynamic_factory.build_dynamic_jobs()` **unconditionally**,
inline in the `Definitions(...)` construction:

```python
    ] + dynamic_factory.build_dynamic_jobs(),
```

No guard, no flag, no emptiness check. It runs on every Dagster load.

## The fact — NOT RE-VERIFIED

The draft stated `bpmn_catalog` contained **zero rows** in sandbox on 2026-08-10. **That read
could not be reproduced here** — the sandbox postgres pod refused a password-less `psql` — so
the count is carried as *reported, unconfirmed by this packet*.

The distinction matters to the framing. *"A loader that has never had a definition in it"* is a
far stronger sentence than *"a loader that runs unconditionally"*, and the stronger sentence is
precisely the one that must not ride on an unreproduced measurement. Whoever owns this should
re-take the count before quoting the stronger form.

## Why it matters

Small standing cost; larger standing confusion. It is a mechanism by which *"we have BPMN
workflows"* keeps sounding true — the claim ADR-0039's naming-collision clause exists to defuse.

## Owner — deliberately empty

`owner:` is **empty**, and the board renders it as `unassigned`. This is a real item with no
owner, and populating the field to satisfy a schema would be schema-satisfaction over truth —
the same refusal as `groups: []` on the registration identities and `owner: unassigned` on the
seed board.

If ADR-0040's owner vocabulary is ever tightened to reject empty, that is an **ADR amendment**,
not a licence to invent an owner here.

## Open condition

If `bpmn_catalog` stops being empty, the vocabulary collision becomes live and ADR-0039's naming
clause becomes mandatory rather than advisory. That condition belongs to ADR-0039's assumptions
and is recorded there too.

## Unverified

Whether `bpmn_catalog` is non-empty in any **other** environment. The count was taken once, in
sandbox — the environment least likely to show it.
