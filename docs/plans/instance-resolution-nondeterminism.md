---
id:         instance-resolution-nondeterminism
status:     open
owner:      agent
blocked-on: nothing — the discriminating read is a repeat-N run of one query, counting grounded vs ungrounded.
closed-by:
code-site:  agent_fleet/ontology_service/main.py:1584
repo:       invincible-agent
summary:    The SAME query grounds two different ways. Witnessed 2026-08-15: two runs of "give me a couple cage values from publog's p_cage dataset", one resolved the URN and returned rows, the other returned "No DataHub URN resolved". The data path is FLAKY, not fixed — and the ungrounded run is what reached the UI.
---

# One query, two groundings

**Witnessed at work 2026-08-15.** Two runs, identical query text — *"give me a couple cage
values from publog's p_cage dataset"* — same deployment, minutes apart:

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
