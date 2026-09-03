---
id:         dagster-loader-call
status:     open
owner:
blocked-on: an owner for the Dagster plane — PROMOTED 2026-09-03 from rider to dispatch; it now blocks test isolation across lanes
closed-by:
code-site:  src/iagent/definitions.py
repo:       invincible-agent
summary:    PROMOTED 2026-09-03 FROM RIDER TO DISPATCH — this is past a standing cost and is now BLOCKING TEST ISOLATION ACROSS LANES. build_dynamic_jobs() runs unconditionally on every Dagster load, and `definitions.py` reaches for Postgres AT IMPORT. On a machine with no local Postgres that surfaces under pytest as `ImportError: cannot import name 'Definitions' from 'dagster' (unknown location)` — the partial-import tell — during test SETUP. MEASURED: tests/routing/ alone is 196 passed / 1 pre-existing failure, and tests/planning/test_fill_slots_seam.py alone is green, but RUN TOGETHER they are 12 failed. Minimal repro is two files and it is not an ordering artifact: test_adr0019_contracts.py errors 11/11 in BOTH orders, and running it FIRST additionally poisons the seam tests (15 failed). So a lane cannot trust a green subset, which is the property a shared tree with four lanes most needs. The original question (is bpmn_catalog empty) is still unconfirmed and is now the LESS interesting half.
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


---

## ⚡ PROMOTED 2026-09-03 — it stopped being a standing cost when it started hiding other lanes' results

Filed as a rider by ADR-0039 on the reasoning that the cost was *"small standing cost; larger
standing confusion."* That was right for what was known then. It has since acquired a second,
worse effect, measured while landing ADR-0033's producer-side items.

### Measured

| run | result |
|---|---|
| `tests/routing/` alone | **196 passed**, 1 pre-existing failure |
| `tests/planning/test_fill_slots_seam.py` alone | green |
| **the two together** | **12 failed** |

The failure is not in either suite's subject matter. It is
`ImportError: cannot import name 'Definitions' from 'dagster' (unknown location)` raised during
test **setup** — and *"unknown location"* is the partial-import tell: `dagster` is being imported
while already mid-initialisation.

`src/iagent/definitions.py` calls `build_dynamic_jobs()` at import, which reaches for Postgres.
On a developer machine with no local Postgres that import fails partway, and anything collected
afterwards that touches the same module tree inherits the wreckage.

### It is NOT an ordering artifact, which is what makes it a blocker rather than a nuisance

```
test_fill_slots_seam.py  then  test_adr0019_contracts.py   ->  18 passed, 11 errors
test_adr0019_contracts.py  then  test_fill_slots_seam.py   ->  15 failed, 3 passed, 11 errors
```

`test_adr0019_contracts.py` errors **11/11 in both orders** — so it is broken on its own terms
whenever it is named explicitly. (In a whole-directory run it lands among the skips, which is why
`tests/routing/` looks clean: **the suite is green because those tests do not run**, not because
they pass. A green subset is not evidence.)

Running it first *additionally* poisons the seam tests. So the damage is both intrinsic and
contagious.

### Why this is now a dispatch

**A lane cannot trust a green subset**, and a green subset is the only thing a lane running
alongside three others can afford to run. Every lane in this tree has spent this week attributing
failures — *is this mine, or the neighbour's?* — and this defect makes that question unanswerable
by the cheap method. It cost this lane a full diagnostic detour tonight to establish that 12
failures were not its own, and the answer required a minimal repro rather than a glance.

That is the difference between a standing cost and a blocker: the first is paid once by whoever
owns the plane, the second is paid repeatedly by everyone who does not.

### What the fix probably is, and the ruling it needs

Not this lane's to make, and named so the owner starts from a choice rather than a blank page:

* **guard the call** — skip `build_dynamic_jobs()` when the catalog is unreachable, and log it.
  Smallest, and it makes the import total rather than conditional on infrastructure.
* **make it lazy** — build jobs on first use rather than at module import. Removes the
  import-time dependency entirely and is the shape the rest of this repo prefers.
* **retire it** — if `bpmn_catalog` is genuinely empty everywhere, the loader has no consumers and
  `[[a-registration-is-not-a-reachable-call]]`'s question applies to it directly: what calls this,
  and has that call ever happened?

The original question — *is `bpmn_catalog` non-empty in any environment* — is still unconfirmed
and is now the **less** interesting half. Whatever the answer, the import must not depend on it.
