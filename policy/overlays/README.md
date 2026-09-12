# `policy/overlays/` — the overlay layer, and the first one that ever ran

**Created 2026-09-12**, under [ADR-0036](../../docs/adr/ADR-0036-config-layering-seed-overlay-composition.md).
That ADR's own status line says it was *"written BEFORE the first one, so the pattern is doctrine
rather than whatever the first deployment improvised."* This is the first one.

## Why it exists: the composition branch had never executed

Measured 2026-09-12 by `invincible-agent-28` while looking for somewhere to put safety's task
kinds, and confirmed independently:

```
find . -type d -name "*overlay*"                    -> nothing
GRAPH_OVERLAY_DIRS   (graph_host/main.py:78)        default ""
  set in values.yaml?                               NO
  set in any configmap?                             NO
```

So `compose(GRAPH_POLICY_DIR, GRAPH_OVERLAY_DIRS)` at `graph_host/main.py:109` ran with **zero
overlays on every deployment that has ever existed**, and the same was true of the task-kind
composition. **The seed path is well covered; the overlay path was a branch nothing took.**

That is not a cosmetic gap. Two defects this week came from reading a *seed* as if it were the
*whole set* — `NOT IN _VERBS_BY_KIND ≠ NOT DECLARED`, then `NOT IN policy/task_kinds/ ≠ NOT
DECLARED` — and the second would have made 18 of 55 live task rows unactionable. A mechanism
that is called everywhere and exercised nowhere is the shape those defects grow in.

## What goes here, and what does not

| layer | lives in | who writes it |
|---|---|---|
| **mechanism** | code, shipped in the image | platform |
| **seed** | `policy/<mechanism>/` — STRUCTURAL species only | platform |
| **overlay** | **here**, and in the customer's private policy repo | the deployment |

`policy/task_kinds/` reserves itself for structural species in its own header, and
`test_no_domain_name_entered_the_platform_seed` fails the build if a domain name enters it. **A
domain species is absent from the seed because the design requires it**, not because nobody
declared it.

**Rows here are labelled `# SAMPLE` in-file.** They are invented in this repo and replaced with
real values in a deployment — a reader must be able to tell the fixture from the thing, and a
sample that reads as production data is worse than no sample.

## The three ADR-0036 properties, and where each is enforced

**a. The composed result passes the SAME validation.** `compose()` returns the same typed rows
`load_*` returns, so the overlay inherits the seed's guards for free rather than needing its own.

**b. Provenance survives** — *"which layer said this?"* has an answer. Every file here carries its
layer in a comment, and the composition logs the overlay directories it read.

**c. An overlay is a STATEMENT, never a fork of a seed file.** Copying a seed row here to change
one field is the failure this clause exists to prevent: the fork stops inheriting mechanism
updates, and the two copies drift silently. **An overlay row is a FULL REPLACEMENT by key** — it
carries its own complete definition, which is what lets a domain species declare a verb the
structural seed has never heard of.

## Deletion is a tombstone, and a tombstone is checked

`deleted: true` removes a seeded key. **A tombstone for a key the seed does not ship is an
ERROR, not a no-op** — because a tombstone that silently matches nothing is indistinguishable
from a tombstone that worked, and a deployment would carry a deletion it never made.

That property is also the cheapest proof the composition path *ran* rather than the seed simply
being read: a seed-only read cannot produce that error.

## Pointing a deployment at it

    TASK_KIND_OVERLAY_DIRS=/app/policy/overlays/sample/task_kinds
    GRAPH_OVERLAY_DIRS=/app/policy/overlays/sample/graphs

**UNSET IS NOT THE SAME CLAIM AS EMPTY**, and the task-kind gate turns on the difference: unset
means *"I was not told where to look"* and leaves the declared set unknowable, so the gate does
not fire. A deployment with genuinely no domain species points the variable at an **existing
empty directory** to say so. A path that does not exist is unreadable, not empty — `compose()`
composes a missing directory to silence, so a typo would otherwise yield the seed set and the
gate would fire on it.
