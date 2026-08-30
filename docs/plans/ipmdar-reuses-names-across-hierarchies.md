---
id:         ipmdar-reuses-names-across-hierarchies
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 Addendum 2026-08-29 (the THIRD trigger shape — ambiguous subject class); ADR-0045 (Decision 2, IPMDAR vocabulary + "future interchange maps field-for-field"); ADR-0031 (instance resolution ladder)
code-site:  agent_fleet/finance_agent/seed.py (check_consistency, the duplicate-label guard), agent_fleet/finance_agent/main.py (_candidates), tests/finance/test_engine_f_contracts.py (test_no_two_entities_share_a_label)
summary:    FOUND 2026-08-29 by RUNNING Engine F's resolver, not reading it. `resolve_instance("Integration and Test")` returned TWO EXACT MATCHES at score 1.0 in different classes — ControlAccount 3.1 and WBSElement 3 — because the seed gave one name to the control account, the WBS element and the OBS element. Two classes tied at 1.0 name no routing subject, so the router abstains and the question is UNROUTABLE WHILE EVERY COMPONENT REPORTS HEALTHY. Patched in the notional seed (distinct name per axis) and guarded by check_consistency. THE PATCH DOES NOT GENERALISE, AND THAT IS THE ITEM: IPMDAR's own vocabulary reuses names across its hierarchies by design — a real program genuinely has WBS "3 Integration and Test" AND control account "3.1 Integration and Test" — so a faithful field-for-field mapping of a real system reproduces the collision and my guard would REFUSE IT. The guard is a notional-data guard wearing a model invariant's clothes. RULED 2026-08-29 (architect), recorded as ADR-0033's Addendum: this is a THIRD `ask` trigger shape — AMBIGUOUS SUBJECT CLASS — distinct from missing-slot (#1) and ambiguous-instance (#2) because the options are CLASSES rather than members, each implies a DIFFERENT VERB, and it fires at subject resolution BEFORE verb selection. Still ask-from-the-phone-book: classes are enumerable from the graph, every option is a registered verb's input_uri, so menu integrity holds; one more trigger into the SAME disposition and the SAME card, never a fourth surface. BELONGS TO ADR-0033, NOT TO FIX 3 — the elicitation lane picks it up after fix 3 ships or when a live case arrives, whichever is first; nothing is built and nothing should be, because the two candidate designs (clarify the class vs filter to the slot referent) are not refinements of each other. EVIDENCE IS THE WEAKEST OF THE FOUR CONSUMERS AND SAYS SO: one witnessed occurrence, notional seed, undeployed engine. What raises it is STRUCTURAL not frequency — IPMDAR name reuse is a property of the standard, so it arrives with the first real-system read. Engine F is its only source today, recorded as such.
---

# IPMDAR reuses names across its hierarchies, and the resolver abstains on it

**Found 2026-08-29, building Engine F.** By running the resolver, not by reading it — which is
the only way this class of defect surfaces, because every component reports healthy throughout.

## What happened

```
POST /resolve_instance  {"text": "Integration and Test"}

[ {"identity": "3",   "label": "Integration and Test", "class_uri": fin:WBSElement,     "score": 1.0},
  {"identity": "3.1", "label": "Integration and Test", "class_uri": fin:ControlAccount, "score": 1.0} ]
```

Two **exact** matches, in **different classes**. `mesh:InstanceResolution`'s own contract says
the router consumes candidates with a decision table — *exact match / fuzzy-unanimous-class /
**fuzzy-mixed-class abstain** / empty fall-through* — and that **"only the class is used to set
the routing subject."**

Two classes tied at the top set no subject. **The question is unroutable, and nothing anywhere
reports an error.** The engine is healthy, the verb is registered, the resolver answered, the
score is 1.0, and the answer never arrives.

## The immediate cause was mine. The general cause is not.

**Mine:** `build_seed` gave the control account, the WBS element and the OBS element a single
`name` column. Fixed — each axis now carries its own name, which is also what the axes *mean*
(the WBS names the PRODUCT, "Integrated System"; the OBS names the ORGANIZATION, "Test and
Evaluation Directorate"; the control account names the WORK where they intersect). Guarded by
`check_consistency`, sealed by `test_no_two_entities_share_a_label`.

**Not mine, and this is the item:** **IPMDAR reuses names across its hierarchies by design.**
A real program's WBS element `3 Integration and Test` and its control account
`3.1 Integration and Test` genuinely carry the same words — the control account is *named after
the WBS branch it sits in*. That is not sloppy data entry; it is how the standard's
decompositions relate.

## ⛔ So my own guard is wrong for the case ADR-0045 promises

ADR-0045 Decision 2 chose IPMDAR partly so that *"future interchange maps field-for-field. If
this ever reads a real program system, IPMDAR is the format that system already speaks. A local
vocabulary makes that a migration; the standard makes it a mapping."*

**A faithful field-for-field mapping of a real program would trip
`check_consistency`'s duplicate-label refusal and be rejected at boot.**

So the guard I added is a **notional-data guard wearing a model invariant's clothes**. It is
correct for the seed — the seed is invented, so a collision in it is an authoring accident with
no upside — and it would be wrong the first day this engine reads anything real. It is left in
place *and labelled here* rather than weakened, because a guard that is right today and wrong
later should be findable when later arrives, and the only thing that makes it findable is this
packet.

**What the durable fix is NOT:** renaming on ingest. That is the translation layer ADR-0045
refused at the ontology layer, arriving one plane down and for the same bad reason.

## RULED 2026-08-29 — it is a third trigger shape, and it is not fix 3

**The architect ruled on this, and the ruling is recorded in ADR-0033's Addendum 2026-08-29.**
The section below is the analysis as filed; the ruling confirmed it and placed the result.

> **`ask` has three trigger shapes, not two.** #1 missing slot (elicitation), #2 ambiguous
> instance (disambiguation), and **#3 ambiguous subject class** — where the options are
> **classes rather than members**, each implies a **different verb**, and the trigger fires at
> **subject resolution, before verb selection**. It is still asking from the phone-book:
> classes are enumerable from the graph, every option is a registered verb's `input_uri`, so
> menu integrity holds. **One more trigger into the same disposition and the same card**,
> never a fourth surface.
>
> **It belongs to ADR-0033 and NOT to fix 3.** The elicitation lane picks it up after fix 3
> ships, or when a live case arrives, whichever comes first. **Nothing is built for it and
> nothing should be** until then.
>
> **Its evidence is the weakest of ADR-0033's four consumers, and the record says so.** One
> witnessed occurrence, in a notional seed, on an engine not yet deployed. What raises it above
> a curiosity is structural rather than frequency-based: IPMDAR's name reuse is a property of
> the standard, so it arrives with the first real-system read. **Engine F is its only source
> today** — recorded, so "one consumer" is a visible fact rather than a discovery waiting on a
> lucky question.

## The analysis the ruling confirmed

The elicitation lane's disambiguation path is **built, correct, and has no live corpus case
reaching it** — fixture-tested, and their packet says so. It is tempting to hand this over as
their first live source. **I am not doing that, because I am not sure it is theirs**, and the
distinction is structural:

| | slot-fill ambiguity (their machinery) | what this is |
|---|---|---|
| what is ambiguous | which **instance** fills a slot whose **referent class is known** | which **class** the subject is |
| what the menu offers | members of one class | candidates whose classes imply **different verbs** |
| when it is decided | after a verb is chosen | **before** — the class sets the routing subject |

In Engine F the two tied classes route to different verbs: `fin:ControlAccount` is
`finVarianceDrivers`' input, `fin:Program` is `finVarianceAnalysis`'. So "the variance on
Integration and Test" is not a slot the user under-specified — it is a **question whose verb is
undetermined**, and the abstain happens upstream of anything a slot menu can serve.

Their own build already drew a neighbouring line and drew it the harder way: *a retained
cross-class candidate is EVIDENCE, not an OPTION*, because the class filter that preserves menu
integrity removes exactly the candidate that was kept. This case may be the same shape one level
up — in which case the honest surface is not a menu but a clarifying question about **what kind
of thing** was meant ("the work, the product branch, or the organization?").

**What was asked of that lane:** a ruling on which of the two it is. Not a build. **Answered
above** — it is neither, it is a third shape sharing their disposition.

## Why this is worth a packet at all

Three properties, and it is the combination that makes it durable rather than incidental:

1. **It has no symptom.** Healthy engine, registered verb, scored answer, no error, no answer.
2. **It is a property of the DOMAIN, not of the data.** Renaming fixes a fixture and cannot
   fix a mapping.
3. **It is the first case in this fleet where the resolver's mixed-class abstain fires on
   candidates that are each individually correct.** The prior instances were a filler emitting a
   name into an id slot — a wrong answer. Here both answers are right and the question is which
   one was asked.

## What is already true

* The notional seed no longer collides; `check_consistency` refuses one that does.
* `_members_of` dedupes by identity, so the resolver and the enumerator cannot disagree.
* `tests/finance/test_engine_f_contracts.py::test_no_two_entities_share_a_label` is the seal.
* **Nothing about a real-system read is built, and nothing here should be built until fix 3
  ships or a live case arrives** — the two candidate designs (clarify the class vs. filter to
  the slot's referent) are not refinements of each other, so choosing between them without a
  live case is the blank-page start ADR-0033's build posture refuses.
* `ADR-0033` carries the ruling as its **Addendum 2026-08-29**, with the three-shape table and
  the funnel position. That document, not this packet, is what a future reader consults.
