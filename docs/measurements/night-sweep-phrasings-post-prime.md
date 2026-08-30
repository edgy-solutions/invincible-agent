---
id:         night-sweep-phrasings-post-prime
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  docs/demo-stable-phrasings.md, agent_fleet/ontology_service/main.py (/resolve)
summary:    NO POST-PRIME SUBJECT DRIFT. Gate 1 re-measured for all 34 TIER 1 + TIER 2 phrasings against a substrate that genuinely moved (prime ran, engine-p at 16, engine-fin added, presentation bindings 23 -> 43). TIER 1: 22 of 22 HOLD, every one at 0.95-0.99. TIER 2: 11 of 12 unchanged — the recorded wrong subjects are still wrong in the same way, which is the corpus being honest rather than the resolver being broken. One movement: "who is short" went Capability -> BusinessProcess at 0.22, a low-confidence coin-flip between two classes that are both wrong for the verb it wants. THE FIRST VERSION OF THIS MEASUREMENT REPORTED 22 OF 22 MOVED, and that was the instrument: it sent `entitled_domains` where the field is `domains`, so the pool fell back to MAINTENANCE.
---

# Stable phrasings, post-prime — no drift

**Gate 1 only** — does the subject resolve to the class the verb is typed against. That is the
gate the corpus records a baseline for; gates 2-4 are measured elsewhere.

## TIER 1 — 22 of 22 HOLD

Every phrasing resolves to its recorded class, at **0.95 to 0.99**:

| subject | phrasings | confidence range |
|---|---|---|
| `Capability` | 2 | 0.95 – 0.97 |
| `Portfolio` | 15 | 0.95 – 0.97 |
| `Site` | 5 | 0.96 – 0.99 |

**Nothing moved and nothing weakened.** The certification seal's own drift example (0.86 →
0.75 across one prime) is the thing this was hunting; it did not recur. The prime added
`finance_extension.ttl` and its `fin:` classes to the pool without displacing planning
subjects — which is the outcome domain-scoping is supposed to produce and the first time it
has been checked across a prime.

## TIER 2 — 11 of 12 unchanged

The tier records phrasings that resolve **confidently to the wrong class**, where the fix is
the corpus rather than the resolver. They still do, identically:

```
where are we against where we said we would be  Portfolio        0.86  (recorded Portfolio)
what is happening in FY26-Q3                    Capability       0.60  (recorded Capability)
what runs during FY26-Q3                        Capability       0.60
what lands in the third quarter of FY26         Capability       0.62
show me the cost curve                          Site             0.10
how is the money phased                         Site             0.12
who has not put up their share                  Site             0.20
which organization is under-committed           Site             0.95
who is taking the hit and when                  BusinessProcess  0.73
what is happening at Site A - Aurora            Site             0.98
show the schedule for Site A - Aurora           Site             0.99
```

**The one movement:** *"who is short"* went `Capability` → `BusinessProcess` at **0.22**. Both
are wrong for `show_funding_gap`, which wants `Portfolio`, and 0.22 is deep in coin-flip
territory — the phrasing is two words and names nothing. Recorded as movement rather than
drift: the class changed, the outcome did not.

**Worth noticing in the confidences:** four TIER 2 rows sit at 0.10–0.22. Those are the
resolver being *unconfident and still answering*, which is exactly the population an abstain
threshold would catch — and `[[slot-resolution-entities-in-the-resolver-substrate]]` records
that threshold as unruled.

## The first version of this measurement was wrong, and loudly

It reported **22 of 22 MOVED**, with planning phrasings resolving to MRO/IOF maintenance
classes at varied confidences. That is exactly the shape of the regression the sweep existed
to find.

**It was the harness.** It sent `entitled_domains`, which is not a field on `ResolveRequest`;
the key was ignored and `domain` fell back to its default `"MAINTENANCE"`, scoping the
candidate pool to the maintenance ontology. A planning question then resolved to a maintenance
class because that was the only kind of class on offer.

> **A plausible result has no tell.** Two other instrument failures this night announced
> themselves — a uniform `None`/`0.00`, and a DBMS warning. This one produced varied names and
> varied confidences and carried its own corroboration. What caught it was diffing the
> harness's request against `dynamic_supervisor.py`'s actual `/resolve` payload, field for
> field.

## What is NOT measured here

Gate 1 alone. The corpus's own standard is *a card renders with content* — four gates — and
gates 2 (fillable slots), 3 (bound archetype) and 4 (hardened renderer) are not exercised by
this sweep. **A phrasing holding here means its subject still resolves, not that it still
answers.**
