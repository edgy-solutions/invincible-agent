---
id:         slots-are-extracted-then-dropped-at-dispatch
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  src/iagent/defs/dynamic_supervisor.py (dispatch payload), agent_fleet/planning_agent/main.py (run_measure)
summary:    MEASURED, on real bytes. BAML extracts verb slots and the supervisor's dispatch payload does not carry them, so every verb runs on DEFAULTS. Seeded canvas slot 3 asks "where is funding short by initiative" and returns 11 ORGANISATIONS (group_by=org, subject O1 Corporate Capital Committee) — rendering cleanly with clean provenance and NO disclosure surface. Three of four certified parameterised phrasings deliver the wrong scope; the fourth passes by COINCIDENCE OF DEFAULT. The slot pipeline is one-third built and the built third is the MIDDLE. Certification gap rides along - routes-and-renders is not answers-the-question.
---

# Slots are extracted, then dropped at the dispatch boundary

**Found by the slot-picker investigation's baseline (Task 1), confirmed on stored artifacts.**
Not a code-read conclusion: the rows below came out of `answer_artifact_projection`.

## The finding

BAML extracts verb slots. The supervisor never forwards them. Every verb runs on its defaults.

```
BAML:        class ShowFundingGap { group_by string; window string? }     ← extraction EXISTS
/route_intent is on the live path (gateway calls it at routing time)      ← extraction RUNS
supervisor dispatch payload:                                              ← extraction DISCARDED
    user_query, user_persona, answerer_persona, persona, domain,
    entitled_domains, entitlement key, user_email, dynamic_schema_map,
    user_id, predicate_verb_iri, routed_verb_iri
    ── no `params`. no `slots`. ──
Engine P: run_measure reads req.params → empty → verb runs on signature defaults
```

**The slot pipeline is one-third built, and the built third is the MIDDLE.** Extraction working
while both neighbours are missing is the strangest configuration available, and it explains the
symptom exactly: slots are computed, forwarded nowhere, logged nowhere, and the routing record
looks complete.

## Measured — four certified Tier-1 phrasings, read from stored artifacts

| certified phrasing | spoken | delivered | verdict |
|---|---|---|---|
| "where is funding short **by initiative**" — **seeded canvas slot 3** | `group_by=initiative` | **`org`** | ✗ **wrong KIND of thing** |
| "maturity grid **as of FY26-Q4**" | `as_of=FY26-Q4` | `as_of=None`, unfiltered | ✗ superset |
| "which sites exceed the threshold **in FY26-Q4**" | `window=FY26-Q4` | **four quarters** | ✗ superset |
| "the plan **broken out by initiative**" | `group_by=initiative` | `initiative` | ✓ **by coincidence — see below** |

The slot-3 read, verbatim:

```
rows            : 11
group_by        : org
subject_id      : O1 | Corporate Capital Committee     ← an ORGANISATION
org_id present  : True    initiative_id present: False
```

**Severity is not uniform.** Two are supersets — right kind, unfiltered, and a reader can mistake
a superset for an answer. Slot 3 returns **the wrong kind of thing**: organisations where
initiatives were asked for. That one is on the seeded board every demo run.

## The fourth row is the sharpest

`plan_schedule`'s default for `group_by` **is** `initiative`. So the certified phrasing "broken out
by initiative" passes **by coincidence**. Change the default and the phrasing breaks with nobody
touching the question.

> **The corpus was not curated away from parameters. It was curated toward questions where the
> default happens to be right.** "By organization" passes because `org` is the default; "by
> initiative" fails identically, and nobody compared the two cards.

## THERE IS NO DISCLOSURE SURFACE

`group_by: org` is present on every row — the truth is in the payload. But:

* the interpretation strip renders resolved **routing** (subject, verb, confidence), not verb
  **parameters**;
* `SHORTFALL_GRID`'s contract passes `value_label` / `scope_label`, neither of which carries
  `group_by`.

So an auditing user has **no surface on which to notice the drop.** The mitigation is not thin —
for this class it does not exist. That is why "make the strip disclose it" is not available as a
pre-fix mitigation, and why the fix is the carry.

## The certification gap — fix the METHOD, not just the corpus

**Routes-and-renders is not answers-the-question.** Certification checked that an answer came
back; the claim being certified was that the answer matched the question. The instrument was
coarser than the claim, and it certified a wrong-scope answer into the seeded canvas.

> **The next corpus certification must compare DELIVERED parameters against SPOKEN ones.**

The `plan_schedule` row makes this urgent rather than tidy: a certification that cannot detect
pass-by-coincidence-of-default is **certifying the defaults, not the phrasings.**

## What this changes about the work

Capability (1) of `[[slot-resolution-entities-in-the-resolver-substrate]]` is **three joins**, not
one — and the census could not have seen the third, because signatures and registrations are both
upstream of dispatch:

| join | state | where |
|---|---|---|
| **declare** | MISSING | `register_engine_to_mesh()` has no slots field; `planCapabilityPath`'s edge carries none. Crosses into `iagent-mesh` — **no external consumers, cheapest moment it will ever have** |
| **extract** | **EXISTS** | BAML classes, live via `/route_intent` |
| **carry** | MISSING | the supervisor's dispatch payload |

**Slot kinds for the declare half** — the census's four classes becoming the registration's type
vocabulary, so the distinction that nearly corrupted the census is structurally unexpressible as
an error: `spoken-mandatory | spoken-optional | handle | ceremony`.

## Disposition, and what is NOT done here

**Slot-3 reword — AGREED, NOT APPLIED.** `PORTFOLIO_CANVAS_QUESTIONS` lives in `gateway.py`, which
another lane has modified in the working tree right now. Editing it risks staging their in-flight
work. **Deferred until that tree is clean**, then: "where is funding short by initiative" →
"**by organization**", which matches the default and makes the seeded card true. One line, no
code, reversible when the carry lands. Truth now and truth later are not in tension.

**The two superset phrasings stay** and are noted in the runbook rather than reworded — rewording
"as of FY26-Q4" to a bare phrasing loses a good beat for a smaller lie.

**The carry is not a pre-demo change.** It touches the supervisor's dispatch payload — the same
seam another lane is in — and the standing fence applies.

## Acceptance, pre-registered

The four-row table above **is** the acceptance test, inverted. The build is done when:

1. "where is funding short by initiative" returns **initiatives**;
2. "maturity grid as of FY26-Q4" returns cells assessed **at or before** that date;
3. "which sites exceed the threshold in FY26-Q4" returns **one** period;
4. "the plan broken out by initiative" still returns initiatives — and a test proves it does so
   because the parameter **arrived**, not because the default agreed.

(4) is the one that matters for the method: it is the pass-by-coincidence case, and only a
delivered-vs-spoken comparison can tell the two apart.
