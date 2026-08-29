---
id:         slots-are-extracted-then-dropped-at-dispatch
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  src/iagent/defs/dynamic_supervisor.py (dispatch payload), agent_fleet/planning_agent/main.py (run_measure)
summary:    CORRECTED 2026-08-28 — the title is wrong and NOTHING IS EXTRACTED: BAML's RouteIntent has ZERO callers, and /route_intent calls ExtractIntent, which returns mode+entity_refs only. FOUR joins, not three, and the first is 'call the function that fills slots'. Ruled: /route_intent calls BOTH in sequence, and mesh_slots is the extraction's acceptance schema. The measured consequence is unchanged and still on real bytes: every verb runs on DEFAULTS. Seeded canvas slot 3 asks "where is funding short by initiative" and returns 11 ORGANISATIONS (group_by=org, subject O1 Corporate Capital Committee) — rendering cleanly with clean provenance and NO disclosure surface. Three of four certified parameterised phrasings deliver the wrong scope; the fourth passes by COINCIDENCE OF DEFAULT. The slot pipeline is one-third built and the built third is the MIDDLE. Certification gap rides along - routes-and-renders is not answers-the-question.
---

# Slots are extracted, then dropped at the dispatch boundary

> ## ⛔ CORRECTION 2026-08-28 — THE TITLE IS WRONG. NOTHING IS EXTRACTED.
>
> **The finding's real shape: EXTRACTION IS DECLARED AND NEVER CALLED.**
>
> This document claimed extraction "EXISTS — the one join already built". It does not. BAML's
> `RouteIntent` — the function returning `ShowFundingGap { group_by; window }`, whose prompt says
> *"fill its slots from what the user actually said"* — **is invoked by nothing:**
>
> ```
> callers of BAML RouteIntent  : 0
> callers of BAML ExtractIntent: 1   (agent_fleet/ontology_service/main.py:2383)
> ```
>
> `/route_intent` calls `b.ExtractIntent(user_query=...)`, which returns
> `ExtractedIntent { mode, entity_refs, confidence, reasoning }` — **no slots, no intent, no
> verb.** It decides CONVERSATIONAL vs ONE_SHOT and pulls entity references. That is all it was
> ever designed to do.
>
> **THE FILENAME AND `id` STAY** even though the title is wrong, because the id is cross-referenced
> from runbook A6, the slot plan item, `test_seed_portfolio_canvas.py` and `mesh_registration.py`.
> Renaming would trade one wrong title for four dangling links. The correction lives here instead.
>
> **HOW THE WRONG VERSION WAS BUILT, because it is the reusable part:** I read the BAML source,
> found `RouteIntent` with typed slot classes, confirmed `/route_intent` was on the live path, and
> concluded the two were the same thing. They share a name-shape and a file. The claim
> "extraction exists" was the ONE claim in the census that came from a code-read rather than a
> live artifact — every other number was measured — and it is the one that was wrong.
>
> **THE NEAR-MISS THIS AVOIDED.** Building the carry against `RouteIntent` would have produced
> correct wiring fed by a function that never runs — *carried-then-never-filled*. Every test
> green: the payload field exists, arrives empty, and **empty is indistinguishable from today's
> behaviour**. It would have been discovered when someone asked why "by initiative" still returned
> organisations after the fix shipped.

**Found by the slot-picker investigation's baseline (Task 1), confirmed on stored artifacts.**
Not a code-read conclusion: the rows below came out of `answer_artifact_projection`.

## The finding

~~BAML extracts verb slots. The supervisor never forwards them.~~ **Retracted — see the
correction above: nothing extracts them.** What survives unchanged, and was measured rather
than read: **every verb runs on its defaults**, and the seeded card returned organisations
for a question that said initiative.

**CORRECTED CHAIN — the original is kept below it, struck, because the error is instructive.**

```
BAML RouteIntent -> ShowFundingGap{group_by, window}   DECLARED, 0 CALLERS  ← nothing runs
/route_intent    -> b.ExtractIntent(user_query)
                    ExtractedIntent{mode, entity_refs, confidence, reasoning}
                                                       no slots, no intent, no verb
RouteIntentResponse{mode, entity_refs, confidence,
                    reasoning, user_persona,
                    entitled_domains, query, domain}   NO FIELD for slots
gateway          -> resolved_intent = that response    nothing to carry
supervisor       -> dispatch payload                   no `params`, no `slots`
Engine P         -> req.params = {}                    verb runs on signature defaults
```

**FOUR JOINS, and the first is "call the function that fills slots"** — not "forward what BAML
extracted", because nothing is extracted today. Every layer downstream faithfully carries nothing,
which is why the symptom looked like a dispatch problem: the routing record IS complete, and it is
complete about a question nobody asked.

~~The original diagram claimed extraction ran at `/route_intent` and was discarded at the
supervisor's payload. The payload enumeration below is still correct and still evidence — the
supervisor genuinely carries no `params`. What was wrong is the box before it: there was never
anything for the supervisor to drop.~~

The payload, unchanged and still true:

```
user_query, user_persona, answerer_persona, persona, domain, entitled_domains,
entitlement key, user_email, dynamic_schema_map, user_id, predicate_verb_iri,
routed_verb_iri            ── no `params`. no `slots`. ──
```

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
| **declare** | **LANDED DARK** (`7f3e225`) | `register_engine_to_mesh(slots=)` → `mesh_slots`, derived from signatures. **In-repo** — `agent_fleet/utils/mesh_registration.py`, NOT the SDK, which was a second wrong premise |
| **project** | FILED | doc-tools' `aitool_linker.py` builds the edge from an explicit ALLOWLIST, so `mesh_slots` is dropped silently until a row is added (`doc-tools@e6418a2`) |
| **call the slot-filler** | **MISSING** | `RouteIntent` has zero callers. RULED: `/route_intent` calls BOTH — `ExtractIntent` for mode, then `RouteIntent` for typed slots once a verb candidate exists |
| **carry** | MISSING | `RouteIntentResponse` grows `slots`; gateway forwards; supervisor payload gains `params` |

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

## THE RULING — two functions, two claims, one function per claim

`/route_intent` calls **both, in sequence**. They were never rivals; they answer different
questions at different stages:

* **`ExtractIntent` decides MODE** — conversational vs one-shot — and pulls entity refs. That is
  disposition-stage work the funnel needs *before any verb exists*. Its job survives unchanged.
* **`RouteIntent` fills TYPED SLOTS against a chosen intent**, which is only meaningful once
  routing has a verb candidate.

So the pipeline is **extract mode → route verb (the existing funnel) → then invoke the typed
slot-filler for the routed verb's intent class**, with the phrase and the verb both known.

**Both alternatives were refused, and for the same reason.** Growing `ExtractedIntent` slot fields
would ask the mode-classifier to do slot work against every intent simultaneously — a job it was
not designed for. Making the typed intents the route's return would collapse two stages into one
call and put the disposal thresholds and slot-filling in a single prompt, arguing with each other.
One function per claim.

### The declarations are the extraction's ACCEPTANCE SCHEMA

The rider that makes the chain testable without a live model: **the slot-filler's output is
validated against `mesh_slots`.**

* a filled slot **not in the declaration** is dropped **LOUDLY** — logged, not honoured;
* a spoken value for a **`handle`-kind** slot is refused, per the boundary already ruled.

So the declarations landed in `7f3e225` are not merely router-facing metadata — they are the
contract the extraction must satisfy. That is what lets every deterministic join be proven by
fixtures, with the model's own behaviour pre-registered and run only when the last join lands.

## Acceptance, pre-registered

The four-row table above **is** the acceptance test, inverted. The build is done when:

1. "where is funding short by initiative" returns **initiatives**;
2. "maturity grid as of FY26-Q4" returns cells assessed **at or before** that date;
3. "which sites exceed the threshold in FY26-Q4" returns **one** period;
4. "the plan broken out by initiative" still returns initiatives — and a test proves it does so
   because the parameter **arrived**, not because the default agreed.

(4) is the one that matters for the method: it is the pass-by-coincidence case, and only a
delivered-vs-spoken comparison can tell the two apart.

## VERIFYING THE LIGHT — after doc-tools deploys (2026-08-29)

The projection is **built and pushed** (`doc-tools@ac35dbd`) but **not deployed**. The
`doc-tools` pod runs an image; until it is rebuilt and rolled, the graph carries no
`slots` property and the guard keeps failing closed. **The deploy is a cluster write and a
cross-repo boundary — a human's to trigger.**

Everything either side of that one hop is already proven:

| link | state | how |
|---|---|---|
| producer derives declarations | ✅ | `test_slot_declarations_derive_from_signatures` |
| Neo4j stores + returns the string | ✅ | live probe, real declarations, byte-identical, 0 residue |
| doc-tools projects it | ⛔ **needs deploy** | 11 assertions green against the shipped source |
| consumer decodes | ✅ | `decode_declarations`, 6 tests |
| guard accepts/refuses | ✅ | `test_slot_acceptance` (11), incl. two red-proven seals |
| engine honours `params` | ✅ | acceptance table, rows 1/3/4 |
| dark → lit transition | ✅ | `test_the_dark_to_lit_transition_is_the_PRESENCE_of_declarations` |

### Pre-registered expectations, to be written down before the reads, not after

1. `plan_funding_gap`'s edge carries a `slots` property that is a **string**, not a list.
2. Decoded, it holds **exactly two** records — `group_by` and `window`.
3. `group_by`: `kind=spoken-optional`, `type=enum`, `values=["org","initiative"]`,
   `default="org"`. `window`: `type=list[str]`.
4. `plan_diff` carries `baseline_state` with `kind=handle`.
5. `plan_session_changes` carries `ops` **and** `scenario_name`, both `kind=handle`.

### The instruments, corrected per the prime playbook

* **Read the graph by NAME, never a count.** "12 verbs have slots" passes when all twelve
  carry `"[]"`. Query the property, decode it, and compare each record against the
  signature it was derived from.
* **Never the engine's in-process view.** `/verbs` reads engine-p's own table and would
  report declarations that never left the process — the exact defect that made `verbs: 14`
  pass for a completely unregistered engine.
* **Compare against signatures, not against memory.** `slots_for(fn)` is the producer; a
  graph record that disagrees with it means the derivation is still lossy somewhere, which
  is the `Optional`-unwrap defect's sibling. **If any shape disagrees, stop.**

### Then, and only then

The guard flips from fail-closed to enforcing on its own — no code change, because the
transition IS the presence of declarations, and that is already tested from both sides. The
remaining work is `[[the-slot-filler-belongs-where-the-verb-is-known]]`: one endpoint, and
the feature's last unknown.
