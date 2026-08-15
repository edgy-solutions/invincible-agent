---
id:         instance-resolution-nondeterminism
status:     open
owner:      agent
blocked-on: nothing — the discriminating read is a repeat-N run of one query, counting grounded vs ungrounded.
closed-by:
code-site:  agent_fleet/ontology_service/main.py:1584
repo:       invincible-agent
summary:    THE USER-FACING DEFECT — asking the same question repeatedly returns different answers. Same text, same deployment: one run grounds and returns rows, the next reports "No DataHub URN resolved". A system that is not reproducible for identical input cannot be debugged by the person using it, and cannot be trusted by anyone.
---

# One query, two groundings

**This is the complaint that matters, stated first.** Asking the same question over and over
and getting a different answer each time is not a rough edge — it is the property that makes
every other issue unfalsifiable. A user cannot tell a fixed system from a broken one, cannot
tell their own phrasing from the system's variance, and cannot report a bug reproducibly. Any
"is it working now?" is answered by a coin flip.

## Three runs, three outcomes, THREE DIFFERENT CAUSES

The variance is not one flaky thing, which is exactly why it read as chaos:

| run | what happened | cause |
|---|---|---|
| 2026-08-14 20:12 | blank card, no answer at all | DA OOM-killed → [[da-collects-before-filtering]]; a crashed subtask skips the UI payload |
| 2026-08-15 01:16 | a confident apology | did not ground — **this packet** |
| 2026-08-15 01:16 | `['00000','00001']` | worked |

Each cause is separately filed. This packet owns the middle row only. Recording the split
because a user experiencing all three sees one symptom — "it gives me a different answer every
time" — and would otherwise chase one fix for three defects.

**Witnessed at work 2026-08-15**, and the evidence is specifically the two 01:16 runs — NOT
the 20:12 one, which was the OOM and is accounted for elsewhere. Two runs, identical query
text — *"give me a couple cage values from publog's p_cage dataset"* — same deployment,
minutes apart:

| run | prompt block DA received | outcome |
|---|---|---|
| A | `### Resolved DataHub URN` + the correct s3 URN | queried MinIO, returned `['00000','00001']` |
| B | `### No DataHub URN resolved` | apologised; **this is the one the UI rendered** |

This is NOT the phrasing effect seen a day earlier, where adding the word "table" tipped the
resolver toward a class reading. Same string, two answers.

## Where the nondeterminism can live

Instance resolution has two entry points and both are LLM-mediated:

- `ontology_service/main.py:1584` — `if not candidates and request.entity_refs:` — the
  preemption path, which fires only when class recall is EMPTY. Whether recall is empty is a
  Weaviate hybrid-search outcome near a threshold.
- `main.py:1638-1640` — the post-class-recall path, which requires `ClassifyDomainIntent` to
  emit an `instance_identifier`. That is an LLM extraction, and it is the likelier source: a
  model that names `p_cage` on one call and not the next produces exactly this split.

`entity_refs` themselves come from `/route_intent`'s BAML `ExtractIntent`, so there are
several sampled steps between the query and a URN. Any one of them is enough.

## Why it matters more than a flaky test would

The failure is invisible: run B produced no error, and — see
[[ui-renders-honest-failure-as-answer]] — reported `status: "success"`. So the user's
experience of a working system is a coin flip, and the losing side is articulate about why it
cannot help. A user who sees B first concludes the asset is not in the catalog.

## STRONG LEAD (2026-08-15): it may be a deterministic misparse, not noise

Every failing query ended with a trailing class noun — "p_cage **dataset**", "p_cage
**table**". The one that grounded and returned rows was bare: "publog's **p_cage**".

And there is a mechanism that would explain it exactly. `ClassifyDomainIntent` emits the class
AND the `instance_identifier` in ONE call, and instance resolution only runs when the
identifier is present (`main.py:1638-1639`). A trailing class noun tips that single decision
toward "this is a question about a KIND of thing", which simultaneously selects the
specific-sounding class (Table over Dataset, 0.477 over 1.0) and emits no identifier. Both
observed symptoms, one cause.

If that holds, this packet is MIS-TITLED — it is not nondeterminism, it is a deterministic
misparse with a nameable trigger, and the repair is upstream of selection entirely. See
[[deterministic-decisions-made-by-llm]] for the gates involved.

**Do not design the fix before this read.** Ten runs of each phrasing, compare grounding
rates. If the bare form grounds ~10/10 and the "dataset" form ~0/10, it is deterministic and
the word is the trigger. If both are ~50%, it is genuinely sampling noise and this title
stands. Either way the cheapest hypothesis is settled first.

## The rig — built 2026-08-15, and its precondition is a hand-deletion

`tests/routing/resolver_corpus.yaml` (29 phrasings, 9 axes, seeded with the real work
queries) and `scripts/run_resolver_corpus.py --base-url … --repeat N`. Six columns per run,
because a corpus recording only the chosen class would have missed the defect it exists for:
resolved class · the instance identifier the SAME call emitted · candidate scores · whether
`_resolve_instance` was reached · the argmax counterfactual · `fallback_reason`. `--diff a
b` compares two deployments.

**IT REFUSES TO RUN AGAINST THE WRONG POOL, and that gate is the point.** `idp:Table`,
`Column`, `Pipeline` and `Job` were hand-deleted from sandbox's Weaviate on 2026-06-11
(`STEP0_IDP_BUILD_SPEC.md:172`) and work has them. Against a two-class pool every row
resolves to Dataset unopposed, the trailing-noun effect CANNOT appear because the noun's
target is not a candidate, and the run reports a healthy picker while measuring a different
system. A simulated diff of the two pools shows the trailing-noun rows grounding 100% in the
small pool and 0% in the full one — the corpus certifying the opposite of the truth. That
number would be worse than no number, so the check is a hard gate.

**The session's first finding is the blocker on its last one.** Four classes removed by hand,
never folded into a reproducible path — which is why work got them back and sandbox did not —
and the un-reproduced deletion is now the ceiling on the only measurement that settles this.
[[bootstrap-state-debt]] arriving not as inconvenience but as the measurement's validity.

Two rules for the restoration, both easy to violate:

1. **It goes through the reproducible path**, not a hand-POST mirroring the hand-DELETE.
   Putting them back by hand fixes the pool and preserves the debt. Whatever seeds the
   Weaviate class collection is where it lands, so the next fresh sandbox gets all six
   without anyone remembering.
2. **The pool matches work until the SPO ruling lands.** With the classes restored, sandbox
   will start resolving to `idp:Table` and refusing Dataset-typed verbs — the intercept that
   motivated the original deletion. **That is the defect becoming reproducible, which is the
   entire point.** The pressure to re-delete will be real the first time a demo query fails
   on it. Anyone who wants sandbox green again gets it by fixing SELECTION, not by shrinking
   the candidate set.

## The read that sizes it, before any fix

Run ONE query N times (20 is enough) and count grounded vs ungrounded. That converts "it is
flaky" into a rate, and the rate decides the repair:

- near-100% grounded → a rare sampling excursion; a retry-on-ungrounded may be enough
- ~50% → a genuine coin flip in one step, and the step is findable by logging which entry
  point fired per run
- correlated with anything (cold cache, first call after restart) → not sampling at all

Log the `preemption_path` provenance field that is already threaded
(`class_recall_empty_fallback`) so each run says WHICH path answered it. Without that the
count says there is a problem but not where.

## Note

Determinism is not obviously the right target — instance resolution is deliberately
LLM-mediated, and the abstention gate exists so it can honestly decline. The goal is that it
declines for a REASON, consistently, rather than differing run to run on identical input.
