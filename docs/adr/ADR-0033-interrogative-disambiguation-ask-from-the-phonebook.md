# ADR-0033 — Interrogative disambiguation: the third behavior between route and abstain (ask from the phone-book)

**Status:** **Accepted 2026-08-29 — woken by the REACHABILITY condition (the second), NOT the frequency one.**
The original gate (*"telemetry shows the ask-eligible rate is material"*) **has not fired and is not
claimed**. See **Status change 2026-08-29** below for the citation, and **Amendment 2026-08-28** for
the second trigger shape (a slot the phrase never filled) brought inside two of the five commitments.
Superseded status line, preserved verbatim: *Proposed — deferred (evidence-gated, post-demo).
Decision shape recorded; build deferred to a slice.*
**Date:** 2026-07-28
**Deciders:** Platform team
**Related:**
  - [ADR-0031](ADR-0031-instance-resolution-ladder.md) — the instance-resolution ladder + the phone-book candidate-generator. This ADR **adds a rung** (ask) and a new `resolved_via: user-confirmed` tier.
  - [ADR-0032](ADR-0032-goal-oriented-analytical-queries-catalog-analyst-loop.md) — "the LLM authors, enforcement disposes." Same trust shape answered for *dialogue*; **shares the elicitation surface + menu-integrity rule** with the goal-shape card.
  - [ADR-0011](ADR-0011-multi-spo-routing.md) — the evidence-gated deferral structure this ADR reuses (defer, name the wake signal, let telemetry accumulate).
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — the sunset of LLM-invented classification: an LLM *proposes* but gains no authority. (The propose/dispose **candidate-generator mechanism** this ADR leans on lives in ADR-0031's phone-book; 0009 is the underlying principle, and its "must not execute unvalidated" reframe is ADR-0032's.)
  - [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md) — the canvas / elicitation-card surface. The disposition-rules pattern (policy-as-data) governs the gate and the growth loop.

## Context

Today the router has **two** behaviors on a query: **route** (confident enough) or **abstain** (an honest degradation card). Between them is a cliff. At low confidence the system does *best-effort* — it routes somewhere on thin signal. That gap is where the worst observed failure lived: the **privacy-notice mis-route** (the ADR-0032 stress-test) — enough signal to route *somewhere*, not enough to route *right*, and no mechanism to spend one user turn converting ambiguity into certainty.

Every piece of the fix already exists **except the conversational turn**:

- **Confidence is honest** — the 0.50 cap, `recall_override`, the `resolved_via` tiers (ADR-0031).
- **Abstention is principled** — multi-hit containment abstains rather than guesses; the goal-shape card offers sub-questions (ADR-0031/0032).
- **Widget interrogation already shipped once** — the SPO interview asks "which subject did you mean" from a menu (ADR-0029).
  > **⛔ CORRECTED 2026-08-30 — THIS SENTENCE WAS TRUE OF THE MODULE AND FALSE OF THE PATH.**
  > `ProcessInterviewerV2` (ADR-0029 Slice 2), which holds that menu and its server-side
  > `validate_pick`, is **registered, mounted, and has no callers** — the gateway drives V1,
  > the BPMN-era interview V2 supersedes. So the menu had never been offered to anyone.
  > **It must not be cited as shipped behaviour.** The reasoning it supported here still
  > holds (the mechanism exists and its pure core is reusable — see
  > `[[spo-interview-reuse-for-elicitation]]`, where `validate_pick` was in fact reused);
  > what does not hold is "shipped". Left in place with the correction attached rather than
  > deleted, because this ADR is the reason the claim propagated and the record should show
  > that. `[[a-registration-is-not-a-reachable-call]]`, instance 4.

The missing middle behavior is **ask**. Best-effort-at-low-confidence is the system jumping off the cliff politely.

## Decision

Introduce a **third behavior — `ask`** — between `route` and `abstain`, and **retire best-effort-at-low-confidence as a policy.** Five decision-grade commitments:

### 1. The third behavior exists: `route | ask | abstain`

Between "confident enough to route" and "abstain with an honest card," insert **ask**. Routing on thin signal is retired.

A reasonable engineer could argue "just abstain more aggressively" — the ADR's job is to say why not. **Best-effort throws away the signal; abstention throws away the signal; asking captures it.** One user turn converts ambiguity into certainty *and* produces training data (see #5). Abstaining is honest but leaves the user stuck and teaches the system nothing.

### 2. Ask from the phone-book, never from the void

The clarifying question's options **must be resolvable entities** — the containment ladder's multi-hit set, the top-k from `resolveInstance`, verb candidates from the capability graph. *"Did you mean the `Customer 360` dashboard or the `Sales Performance` dashboard?"* where both options are guaranteed-routable.

This is ADR-0031's phone-book candidate-generator (on ADR-0009's propose-but-don't-authorize principle) applied to dialogue: the resolver (or LLM) proposes, the deterministic layer disposes, and **the user is the disposer of last resort.** Never an open question (*"what did you mean?"*) — that is abstention wearing a question mark, and it re-imports the free-text ambiguity we are retiring. **The menu-integrity rule from ADR-0032 applies verbatim: every offered option must route successfully when chosen.**

### 3. One turn, then commit or abstain — never a loop

Bounded at **one round** in v1 (two for goal-shaped queries where subject *and* verb are both murky, asked as one combined card). If one turn doesn't resolve it, fall to the existing honest abstain card.

An unbounded clarification loop is the parked-join DoS shape in conversational clothing. It also degrades trust: **two questions reads as diligence, four reads as broken.**

### 4. Gated on resolution provenance — the weak path's behavior, never the default's

The trigger is **not** a new confidence model; it is a **policy over existing discriminators**:

- `resolved_via == llm-alone` → **ask**
- containment **multi-hit** → **ask** (nearly free — the abstain already holds the candidate list and currently discards it)
- **capped-0.50** → **ask**
- **exact / containment-unique** → **never ask**

That last clause is the guardrail against the clippy failure mode. **A system that asks when it knows is worse than one that guesses when it doesn't** — the asymmetry users actually feel. Interrogation is the weak path's behavior. The gate is **policy-as-data** (disposition-rules pattern): thresholds in config, ratifiable and tunable per deployment without a roll. And because `resolved_via` is a *living* vocabulary (this ADR adds a tier; more are filed), the gate is an **allowlist over a growing set** — the discard-pattern trap. Guard it: the gate policy **declares a disposition per tier and fails loudly on an undeclared tier at policy load** (the `validate_ruleset` discipline), never silently defaulting an unknown tier to `route`. Otherwise a future weak tier would stop triggering asks the day it is added, and no one would notice.

### 5. The confirmed pick is provenance-bearing training data — the alias growth loop

When the user picks `Customer 360` from the disambiguation, that is a **confirmed alias mapping** (their original phrasing → the resolved entity) — the growth-loop input the alias-persistence design has awaited since the original ladder ruling.

- Add **`resolved_via: user-confirmed`** — a new provenance tier. Keep **two orderings separate** (do not conflate them): for *audit strength* it is arguably stronger than exact-match (a human attested it); for *routing precedence* it is **not a matching tier at all** — it is the *output* of the ask behavior, and exact/unique still short-circuit before any ask fires (commitment #4's "never ask"). So `user-confirmed` never enters the resolution ladder.
- **Ratify recurring picks into aliases** (provenance-marked, owner-audited — same discipline as learned disposition rules). The interrogation rate declines over time: *the system asks less because asking taught it.* When a **ratified alias** later produces an exact-match hit, its provenance carries its lineage — **`resolved_via: exact-via-learned-alias`**, not plain `exact` — so a dialogue-born match never launders into a native one.

This is the self-hardening shape's **third instance** (phone-book alias growth, disposition-rule learning, now disambiguation→alias). It is what elevates this from a UX patch to an architecture feature: best-effort discards the signal, abstention discards the signal, **asking captures it.**

### Scope: decision vs build

The five above are the ADR. **Not** decided here — they are the design note the ADR points at, decided at build time under the schema-not-rushed rule:

- the **elicitation card's archetype shape** (the citizen shell's fourth tenant — options + a "none of these" escape);
- the **supervisor's pending-state mechanics** — stateless re-route with the clarified subject substituted (simplest v1) vs. a held-promise the way grouped reviews hold suspended promises.

ADRs rot when they carry build detail; those stay in the note.

## Wake condition (why deferred, and the evidence gate)

**Build after the demo.** This touches the router's **hot path** — the wrong thing to modify three weeks out.

The evidence gate is **accumulating for free**: every `recall_override` flag, capped-0.50 answer, and multi-hit abstain in the logs is exactly the population this feature serves. Build when telemetry shows the **ask-eligible rate is material**, measured against real traffic — the same deferral structure as ADR-0011, whose wake signal *did* fire (the stress-test).

## Relationship to ADR-0032's immediate step (one elicitation surface, not two)

The goal-shape abstain card (ADR-0032 immediate step) and this feature will meet in the UI as **sibling elicitations** — one offers *sub-questions*, one offers *disambiguation options* — and they **share the elicitation surface and the menu-integrity rule.** They must be built as **one archetype** (the elicitation card), not two components. Absent this sentence, two agents build them separately and the citizenship grammar forks at its first extension.

## Consequences

- **More honest *and* more accurate** — the rare feature where those don't trade against each other (best-effort and abstain both discard signal; asking captures it).
- **A new producer into a guarded substrate** (the phone-book): disambiguation picks → aliases. That alone clears the ADR bar; it inherits the ratification/audit rules of the disposition-rules pattern.
- **A new `resolved_via: user-confirmed` tier** in routing metadata — audit-strong, because a human attested.
- **A hot-path change**, held behind the evidence gate — the deferral keeps premature complexity off the critical routing path until traffic justifies it.
- The system's **observable conversational contract changes**: a system that *asks* is categorically different from one that only answers or abstains. That blast radius is why this is an ADR, not a design note.

## Non-goals

- **Open-ended clarification / free-text follow-up** — explicitly rejected; it re-imports the ambiguity this retires.
- **Unbounded multi-turn dialogue** — bounded at one round (maybe two for goal-shaped).
- **A new confidence model** — the gate reuses existing discriminators.
- **Specifying the elicitation-card schema or the supervisor pending-state mechanics** — design note, at build time.

## Open questions

1. **One turn vs. two for goal-shaped queries** (subject *and* verb murky) — one combined card, or sequential?
2. **Ratification threshold** for promoting a disambiguation pick to a persisted alias (recurrence count + owner audit). **Default lean:** start by reusing the disposition-rule threshold; split into its own only when evidence shows alias-promotion needs different friction (the start-shared-split-on-evidence rule).
3. **Pending resolution in v1** — stateless re-route (clarified subject substituted) vs. held-promise.

*(Resolved during review, folded into commitment #5: the precedence of `user-confirmed` vs `exact` — they are different orderings, `user-confirmed` is not a matching tier, and ratified-alias matches carry `exact-via-learned-alias` lineage rather than laundering into plain `exact`.)*

---

## Amendment 2026-08-28 — the zero-candidate trigger, and a second wake condition

**The decision stands.** `route | ask | abstain`, one bounded turn, and options drawn from a
governed vocabulary are unchanged. What this amendment adds is a **second trigger shape** the five
commitments were not written against, and a **second wake condition** recorded as its own reason.

Raised by the slot-resolution work (`[[slot-resolution-entities-in-the-resolver-substrate]]`),
which found this ADR already ruling most of what it needed — and two places where it does not.

### The shape the commitments assume, and the one they do not

The ADR is written throughout against **disambiguation**: a resolution attempt produced *too many*
candidates, and the user narrows them. *"Did you mean the `Customer 360` dashboard or the
`Sales Performance` dashboard?"*

The slot picker's case is the **cousin, not the twin**: a resolution attempt produced *none*,
because the phrase never carried the value at all. *"Variance analysis for Q3"* names no project.

| | disambiguation | elicitation |
|---|---|---|
| candidates | many | **zero** |
| the user does | narrows a set the resolver produced | **supplies a value the phrase never carried** |
| `resolved_via` | `llm-alone` / multi-hit / capped-0.50 | **none — nothing was resolved** |

Same disposition (`ask`), same one-turn bound, same menu-integrity rule. Different trigger, and two
commitments key on the trigger.

### Commitment #2 gains a FOURTH option source — the rule is preserved, not bent

#2 names three sources, and **all three are outputs of a resolution attempt**: the containment
ladder's multi-hit set, the top-k from `resolveInstance`, verb candidates from the capability
graph. A missing slot produced none of them, so #2 as written has nothing to offer from — and its
own prohibition (*"never an open question… that is abstention wearing a question mark"*) would
forbid asking at all.

**The fourth source, in the same spirit as the three:**

> For a slot the phrase did not fill, the ask names the **slot** from the verb's **registered slot
> inventory — WHICH MUST FIRST EXIST; see the plan item's capability (1)** — and offers
> **instances enumerated from the substrate** where resolution can enumerate them.

Both halves are governed vocabularies. Nothing is composed. Menu-integrity holds verbatim: every
offered option must route when chosen.

> ### ⛔ CORRECTION 2026-08-28 — THERE IS NO REGISTERED SLOT INVENTORY TODAY
>
> This clause was written naming a source that **does not exist**, and it is retracted in place
> rather than quietly rewritten.
>
> `register_engine_to_mesh()` accepts `mint, name, description, verb, input_uri, output_uri,
> verb_synonyms, endpoint_url, owner_persona, domains, cost_class`. **There is no parameter for
> slots.** The authoritative record agrees: `mesh:planCapabilityPath` — the canonical slot-taking
> verb — carries thirteen edge properties in the graph and not one describes a parameter.
>
> Slots exist in three places, **none of them a registration**: `intent_catalog.yaml` (read by
> tests and eval runners only — a catalog entry is not a registration), BAML classes (the
> slot-FILLING stage, which runs only after a verb is already classified), and Python function
> signatures (visible to the engine at call time, invisible to the router).
>
> **THE DECISION STANDS; THE SUBSTRATE IS NOT READY FOR IT.** The ask *should* name the slot from
> a governed inventory — that is still right, and it is still the only formulation that keeps the
> phone-book rule intact. What was wrong is the assumption that such an inventory could be read
> today. It must be **built first**, and that is capability (1) of
> `[[slot-resolution-entities-in-the-resolver-substrate]]`, which is prior to the resolution work
> the item was originally scoped around.
>
> **THE MESH HAS ARITY OF SUBJECTS, NOT ARITY OF PARAMETERS.** This is why the gap feels like it
> should already be closed — its neighbours are. A registration declares a verb's *type signature
> at the class level* (`input_uri` / `output_uri`: what it is about, what it produces) and its
> vocabulary (`verb_synonyms`, `anti_synonyms`). It has never declared what the verb **takes**.
> The slot inventory is the second arity being born.
>
> **CONSEQUENCE FOR THE ROUTER, and it retires a class of proposals.** The router cannot know a
> slot is missing, because no slot was ever declared — it only knows nothing cleared threshold.
> So `NO_VERB_CLASSIFIED` on a slot-shaped question is an **information gap, not a threshold
> problem**, and threshold tuning cannot fix it. (Pre-registered as a prediction for the
> investigation's baseline; the measurement decides it.)
>
> **THIS IS NOT AN EDGE-CASE FEATURE.** The severity was understated when this amendment was
> written as "four unreachable verbs plus Engine F". Every parameterised question a working
> session actually asks — *"schedule for Wave 2"*, *"cost curve for FY27 only"*, *"site load at
> Monterrey"*, *"maturity as of Q4"* — is a verb the system HAS plus a parameter the phrase
> carries. Nobody asks the bare-verb version twice; narrowing is what analysis IS. The certified
> corpus routes at high confidence because it is composed of the bare versions, which is a
> **corpus fact, not a capability fact**.
>
> The engines already accept these parameters and the interpretation strip already renders
> resolved ones. **The ends are built and the middle is missing:** a spoken parameter has no path
> to a verb's parameter. Slots are therefore not Engine F's prerequisite that planning happens to
> share — they are **the planning engine's own unfinished half**, and Engine F merely arrives
> after the fix rather than before it.
>
> **Sizing, recorded because this is the cheapest moment it will ever have:** the slots field
> crosses into the `iagent-mesh` SDK, which has no consumers outside this repo — no migration, no
> deprecation window, no compatibility shim. ADR-0045's Engine F is the SDK's second consumer and
> its flagship verb is slot-heavy, so the sequence writes itself: **SDK schema change → planning
> verbs re-register with declarations → Engine F born declaring.** Additive-schema discipline
> applies (absent means what it means today).

**THE FREE-TEXT BOUNDARY IS EXPLICIT, because this is where a lazy implementation drifts.**
Free text is permitted **only** when the substrate genuinely cannot enumerate the slot's domain —
never as a default, never as a convenience, and never because enumeration was not attempted. An
enumerable slot asked as free text is the open question this ADR retired, wearing a slot's name.

### Commitment #4 must DECLARE a `slot-unfilled` disposition

#4's gate is keyed entirely on `resolved_via` — `llm-alone` → ask, multi-hit → ask, capped-0.50 →
ask, exact/containment-unique → never. **A missing slot has no `resolved_via` at all.**

**The ADR's own tripwire caught this before it could fire.** #4 mandates that the gate *"declares a
disposition per tier and fails loudly on an undeclared tier at policy load, never silently
defaulting an unknown tier to `route`."* Without this amendment the slot case would have surfaced
as a **policy-load failure**, not a silent misroute — which is the fail-loud discipline working as
designed, and worth recording as evidence that it does.

> **Declared:** `slot-unfilled` → **ask**, subject to the same guardrail as every other tier.

The guardrail is unchanged and cuts against a naive picker: *"a system that asks when it knows is
worse than one that guesses when it doesn't."* The picker asks **below the same thresholds that
gate disambiguation**, never as a default. A slot that filled cleanly is never asked about.

### Commitment #5 — one sentence, so nothing empty enters a guarded substrate

#5's growth loop is defined as *"their original phrasing → the resolved entity."*

> **A supplied slot value is a confirmed FILL, not an alias.** When the phrase carried no phrasing
> for the slot, there is no mapping to learn, and **nothing enters the alias-growth loop.**
> `resolved_via: user-confirmed` still applies to the answer's provenance; the alias ratification
> path does not.

Without this sentence the loop would ratify empty-keyed aliases into the phone-book — a guarded
substrate accepting entries with no left-hand side.

### A SECOND wake condition, recorded beside the first — not folded into it

The original gate is a **frequency** argument:

> *build when telemetry shows the ask-eligible rate is material, measured against real traffic.*

The slot picker is a **reachability** argument, and it is a different claim:

> **A whole class of questions is unreachable without `ask`** — not "the eligible population is
> now large enough to be worth it," but "these questions cannot be asked at all."

Three consumers, already in the record: four planning verbs built and unreachable (Tier 3, *"do not
script these"*), the triage's instance-resolution abstentions firing on 19 candidates **and** on
exactly 1, and Engine F (ADR-0045), whose flagship question carries an instance slot and four of
whose six verbs take an entity.

**Both are legitimate. They are not the same, and a status change must cite WHICH ONE FIRED.**

Recording reachability as the frequency gate firing would misstate the evidence — and this is the
ADR that invented `resolved_via: exact-via-learned-alias` precisely so a dialogue-born match could
never launder itself into a native one. The same care applies to its own status: **when this moves
to Accepted, the status line names the wake condition that woke it.**

### What this amendment does NOT change

- The three existing option sources, the one-turn bound, the never-ask-when-certain guardrail.
- The **archetype-unity constraint**: this and ADR-0032's goal-shape card are **one elicitation
  card, not two**. The ADR already predicted the failure — *"absent this sentence, two agents build
  them separately and the citizenship grammar forks at its first extension"* — and a slot picker is
  exactly the third agent that would fork it.
- The build/decision split. The **supervisor's pending-state mechanics** remain deferred to build
  time with both candidates already named (stateless re-route vs. held-promise); the plan item
  starts from that choice rather than from a blank page.

---

## Status change 2026-08-29 — Proposed→Accepted, and WHICH wake condition fired

The amendment ruled that *"a status change must cite WHICH ONE FIRED"*, because recording
reachability as the frequency gate firing would misstate the evidence — the same care this ADR
invented `exact-via-learned-alias` to enforce on matches. So, plainly:

> **The REACHABILITY condition fired. The FREQUENCY condition did not, and is not claimed.**

**The frequency gate is still dark, and honestly so.** No ask-eligible rate against real traffic
has been measured. The only rate-shaped number in the record is the slot-fill battery's, and it is
a *filler accuracy* rate on a 48-case authored corpus — not traffic, not ask-eligibility. Nothing
here says the eligible population is large.

**What fired is the other claim: a class of questions cannot be asked at all.** Three citations,
all measured since the amendment was written:

| # | evidence | measured where |
|---|---|---|
| 1 | **`E04` — "what phases feed into P7"**: three slots present in the phrasing, **all three missed**, at confidence **0.96**. The user's question is fully formed and the system produces nothing from it. | `docs/measurements/slot-fill-battery-run2.json` |
| 2 | **`E05` / `H04`** — an entity spoken by NAME on a **spoken-mandatory** slot (`project_id`, `process_id`). The filler emits the name; the engine takes an opaque id; the user gets a **422**. A miss would have reached an ask; a confident wrong fill reaches the engine. | same run; `[[the-filler-has-no-entity-resolution]]` |
| 3 | **`400 bad params … missing 1 required keyword-only argument: 'project_id'`** — a Python signature error rendered to a person who asked about phases. | `[[a-missing-mandatory-slot-is-a-400-not-an-ask]]` |

Each is a **question the system cannot answer and cannot honestly decline** — it produces a
protocol error where the missing thing is one sentence from the user. That is reachability, not
volume, and it is the condition the amendment recorded precisely so this moment would not have to
borrow the other one's evidence.

### Confidence was tested as the ask signal and is REJECTED — on evidence, not taste

The obvious cheap trigger was a confidence threshold, and
`[[a-missing-mandatory-slot-is-a-400-not-an-ask]]` proposed it explicitly (*"a confidence threshold
is the cheap version of gap (1)"*) on a single observation of `confidence: 0.0` on an incomplete
fill. The corpus tested it at n=48 and it does not survive:

| class | n | min | median | max |
|---|---|---|---|---|
| CORRECT-**filled** | 26 | **0.93** | 0.99 | 1.00 |
| CORRECT-**empty** | 14 | 0.00 | 0.95 | 0.99 |
| WRONG | 5 | 0.90 | 0.92 | **0.96** |
| MISSED | 1 | 0.96 | 0.96 | **0.96** |

Correct fills bottom out at **0.93**; wrong fills reach **0.96**; the one genuine miss scored
**0.96**; and four *correct* empties scored **0.00**. **No threshold separates them in either
direction.** The 0.0 that motivated the proposal was a real signal and an unrepresentative one.

The reason is structural and worth stating so it is not re-proposed: **confidence reports how sure
the model is about the values it DID produce, never whether it produced everything the question
named.** It is incapable of flagging an omission, and an omission is exactly what `ask` must
detect. A model-derived number cannot be the gate on a model's silence.

> **Therefore the slot-unfilled trigger is DETERMINISTIC and model-free: a slot declared
> `spoken-mandatory` that is absent after filling → `ask`.** Read from the declarations
> (`agent_fleet/planning_agent/slots.py`, derived from signatures), not from the model. This is
> commitment #4's spirit exactly — *"the trigger is not a new confidence model; it is a policy over
> existing discriminators"* — and the declarations are now one of those discriminators.

### The trigger's measured reach, recorded before the build so it cannot be overclaimed later

The presence test, applied to the 48-case run **as it stands today**, fires on **2 of 48**: `H06`
(required slot named nowhere) and `E04` (required slot spoken and missed). It does **not** fire on
`E05` or `H04`, because those slots *are* filled — with a name instead of an id. **A presence test
cannot see an unresolvable value.**

So citation 2 above is reachable by `ask` **only after** entity resolution can report failure. That
is an interface requirement on the resolver join, recorded here because it constrains a component
this ADR does not own:

> **Resolution must be three-valued — `resolved` / `unresolved` / `not-attempted` — never
> "substitute an id when you can, pass the name through when you can't."** A silent pass-through
> converts an askable gap into a 422 and is indistinguishable, at the disposition point, from a
> successful fill. The vocabulary to express this already exists: `instance_match` in
> `agent_fleet/ontology_service/instance_resolution.py` is `exact | fuzzy | mixed | not_specific |
> empty`, and its authors already fought the exact fight (`empty` split from `not_specific` so the
> gate's actions could not hide inside a not-found).

### What this status change does and does not authorize

**Does:** the build, scoped in `[[elicitation-ask-disposition]]` — pre-registered acceptance,
mechanism plan, and the disposition point named.

**Does not:** widen any commitment. The one-turn bound, the never-ask-when-certain guardrail, the
free-text boundary, the archetype-unity constraint and the confirmed-fill-is-not-an-alias clause
all stand exactly as written. In particular the guardrail is now *measurable* rather than
aspirational: 37 of the 48 corpus cases are on verbs with **no** spoken-mandatory slot, so the
trigger is structurally incapable of firing on them — the anti-clippy property is a consequence of
the declarations, not a tuned threshold.

---

## Addendum 2026-08-29 — a THIRD trigger shape: ambiguous subject CLASS

**Ruled by the architect, 2026-08-29, on a finding from the Engine F lane.** This adds a
trigger shape to `ask`; it widens no commitment. See the closing subsection for what it does
*not* authorize.

### The finding

Engine F's resolver, run rather than read, answered a spoken finance name with **two exact
matches at score 1.0 in different classes** — `fin:ControlAccount 3.1` and `fin:WBSElement 3`,
both labelled *"Integration and Test"*. `mesh:InstanceResolution`'s decision table abstains on
mixed class, and *"only the class is used to set the routing subject"* — so two classes tied at
the top set no subject and **the question is unroutable while every component reports healthy.**

The immediate cause was a notional seed giving one name to three objects, and is fixed. **The
general cause is not fixable**: IPMDAR reuses names across its hierarchies *by design* — a real
program's control account is named after the WBS branch it sits in — so this recurs every time a
real program system is mapped. Full packet: `[[ipmdar-reuses-names-across-hierarchies]]`.

### Why this is a THIRD shape and not an instance of the second

The tempting read is "candidates exist, therefore disambiguation, therefore the built path." It
is wrong, and the elicitation lane's own build already drew the neighbouring line the harder way
— *a retained cross-class candidate is EVIDENCE, not an OPTION*, because the filter preserving
menu integrity removes exactly the candidate that was kept. This case is that same shape **one
level up**:

| | **#1 missing slot** | **#2 ambiguous instance** | **#3 ambiguous subject class** |
|---|---|---|---|
| what is ambiguous | nothing was said | which **instance**, referent class **known** | which **class** the subject is |
| the options are | members of the slot's class | members of one class | **classes**, not members |
| each option implies | the same verb | the same verb | **a different verb** |
| fires at | after verb selection | after verb selection | **subject resolution, BEFORE verb selection** |

In Engine F the two tied classes route to different verbs — `fin:ControlAccount` is
`finVarianceDrivers`' input, `fin:Program` is `finVarianceAnalysis`'. So *"the variance on
Integration and Test"* is **not an under-specified slot**; it is a question whose **verb is
undetermined**. The abstain happens upstream of anything a slot menu can serve, which is why
this is a separate build rather than a case the disposition already covers.

The honest surface is therefore a clarifying question about **what kind of thing was meant** —
*"the work, the product branch, or the organization?"* — never a list of members.

### Decision #2 holds VERBATIM — this is still asking from the phone-book

The phone-book rule is not bent to admit this, and it does not need to be:

* **the options are resolvable** — classes are enumerable from the graph, and
  `mesh:enumerateInstances` already exists as the option-source verb;
* **menu integrity holds** — every offered class routes successfully when chosen, because each
  one *is* a registered verb's `input_uri`;
* **it is not an open question** — *"what did you mean?"* remains abstention wearing a question
  mark; *"the work or the product branch?"* is a closed set drawn from the graph.

The one-turn bound, the never-ask-when-certain guardrail and the archetype-unity constraint all
apply unchanged. **This is one more trigger into the same disposition and the same card**, not a
fourth elicitation surface — the fork the ADR predicted at its first extension is exactly what
sharing the disposition prevents.

### Sequencing, and the honest state of its evidence

**It belongs to this ADR. It does NOT belong to fix 3.** The elicitation lane picks it up after
fix 3 ships, or when a live case arrives, whichever comes first. Nothing is built for it, and
nothing should be until then — the two candidate designs (clarify the class, versus filter
candidates to the slot's referent) are not refinements of each other, and choosing between them
without a live case is the blank-page start this ADR's own build posture refuses.

**Its evidence is weaker than #1's and must not be overstated.** #2's disambiguation path is
built, correct, and has **no live corpus case** — fixture-tested, and its packet says so. #3 has
**no built path and no live case**: one witnessed occurrence, in a notional seed, on an engine
that is not yet deployed. What raises it above a curiosity is a **structural** argument rather
than a frequency one, the same distinction this ADR drew between its two wake conditions:

> IPMDAR's name reuse is a **property of the standard**, so a faithful mapping of any real
> program system reproduces it. ADR-0045 Decision 2 chose that standard precisely so future
> interchange would be *"a mapping rather than a migration"* — which means this arrives with
> the first real read, not eventually.

**Engine F is its only source today.** Recorded as such, so that "one consumer" is a visible
fact rather than a discovery waiting on a lucky question — the enumerate-your-consumers law this
project has already paid for twice.

### What this addendum does and does not authorize

**Does:** record the third trigger shape, its funnel position, and its assignment to this ADR's
disposition. Nothing more.

**Does not:** authorize a build; widen the one-turn bound, the never-ask-when-certain guardrail,
the free-text boundary or the archetype-unity constraint; or promote #3's evidence to the
reachability standing that woke #1. It is a **fourth consumer in the record**, listed beside the
three the amendment names, and the weakest of the four on evidence.
