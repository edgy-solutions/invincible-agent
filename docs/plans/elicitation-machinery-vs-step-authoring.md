---
id:         elicitation-machinery-vs-step-authoring
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 (the ask disposition); ADR-0029 Slice 2 (the SPO interview); ADR-0039 (BPMN import rejected — drawing is an input method, and it supplies no front end)
code-site:  agent_fleet/restate_analyst/spo_interview.py (add_spo_step, authorized_verbs), agent_fleet/restate_analyst/main.py:2421 (spo_turn — the durable held state), agent_fleet/ontology_service/main.py:3343 (/find_compatible_verbs), src/iagent_pure/slot_disposition.py
summary:    A READ. THE PRIMITIVE GENERALISES, THE CONTROL STRUCTURE DOES NOT — and the dispatch's framing was off by one. A step is TWO asks and a DERIVATION, not three: `expected_output` comes from the verb's fixed output type (ADR-0030) and is "never invented by the model". The second menu DEPENDS on the first pick (`authorized_verbs(subject_uri)`, recomputed for the exact proposed subject so the verb is never checked against a stale set), where elicitation's menus are independent and computable up front. And termination differs categorically: elicitation ends when the missing value arrives (bounded at ONE turn by #3); authoring ends when WorkflowDefinition model_validates — unbounded, and a turn bound there would be meaningless. HELD-PROMISE'S CONSUMER EXISTS AND IS ALREADY BUILT AND IS NOT THIS LANE'S: V2's spo_turn holds state/history/focused_subject in a durable Restate VirtualObject, and `focused_subject` IS the partial parse carried across asks. So the graduation condition NARROWS rather than fires — multi-slot elicitation still has a population of zero. On reuse: mirror PURE LOGIC (validate_pick, done), share CONTRACTS for I/O (/find_compatible_verbs), never import across the packaging boundary. VERDICT: step authoring is ADR-0029 Slice 2, not an extension of the disposition. And the V2 reopening condition has FIRED, cited to ADR-0039.
---

# What elicitation's machinery would need to author a step — and why it should not

**A read, 2026-08-30.** Dispatched because authoring multi-turn corpus cases without knowing
whether they test one shape or two means authoring them twice. Three questions asked, and a
fourth the read produced.

Read, not inferred. Every claim cites a line.

## Why this arrived now — the V2 condition fired from an ADR nobody was watching

`[[spo-interview-reuse-for-elicitation]]` recorded a reopening condition for V2's not-live
status: *"a live case needing the **verb question** — the thing V1 genuinely cannot do."*

**ADR-0039 is that case.** It rejects BPMN import and rules that drawing, if it ever matters, is
*"an **input method** — draw, compile through a strict front end, commit the YAML it produces —
never a storage format."* **It then supplies no such front end**, and states the problem it
leaves open: authoring today means reading Python, and schema-plus-scaffold is the minimum.

A `service_task` step needs `(subject, verb)`. **V1 asks subject and object and never a verb** —
V2's own docstring names this as the first of the three things that make it stronger. So the
strict front end ADR-0039 requires is the interview that is registered and unreachable.

> **Condition FIRED. Cutover NOT taken.** Recorded on ADR-0029; the disposition stands until
> someone owning that ADR weighs V1's production evidence against V2's better model. What this
> read adds is that the case is now concrete and cited rather than hypothetical.

## Q1 — does ask-from-authorized-set generalise from one slot to a sequence?

**The primitive does; the control structure does not.** Three measured differences, and the first
corrects the dispatch.

### (a) A step is TWO asks and a DERIVATION, not three

The dispatch read *"asks subject, then verb, then output."* `add_spo_step`:

> *"`expected_output` is derived from the verb's fixed output type (ADR-0030 — a verb's output is
> a fixed type, not result-dependent), **never invented by the model**."*

**Output is never elicited.** It falls out of the verb pick. Asking for it would be asking a human
to supply something the graph already determines — the same error as asking about a slot that
filled cleanly.

### (b) THE SECOND MENU DEPENDS ON THE FIRST PICK — and this is the real divergence

`authorized_verbs(subject_uri)` computes the verb set **for a chosen subject**, and
`add_spo_step` is explicit about why it must be recomputed rather than carried:

> *"the caller recomputes it for the exact proposed subject, so the verb is checked against the
> right subject's eligibility, **never a stale set**."*

| | elicitation | step authoring |
|---|---|---|
| menus | **independent** — every mandatory slot's options come from its own declaration + enumeration | **dependent** — the verb menu is a function of the subject pick |
| order | none; the census says max **one** mandatory slot per verb anyway | forced: subject, then verb |
| staleness | not possible — a slot's vocabulary does not move | a live hazard the code guards against by name |

Stateless re-route *can* serve a dependent sequence — the card carries what was picked, and the
next menu is recomputed from it. So this is not a blocker. It is a **different shape**, and the
one-turn bound is where it stops being one.

### (c) Termination is categorically different, and this is the disqualifier

| | terminates when | bound |
|---|---|---|
| elicitation | the missing value arrives | **one turn** (ADR-0033 #3), two for goal-shaped |
| authoring | `WorkflowDefinition` **model_validates** (`try_finalize`) | **none, and a bound would be meaningless** |

Elicitation is a **gap-filler**: something was missing from a question that is otherwise ready to
run. Authoring is an **artifact builder**: nothing is ready until the whole definition validates,
and you keep going until it does. A one-turn bound on an artifact builder would refuse to build
artifacts.

> **So: same primitive, different control structure.** `validate_pick` is shared and already is.
> The loop around it is not transferable in either direction.

## Q2 — does held-promise finally have a consumer?

**Yes, and it is already built, and it is not this lane's to build.**

`spo_turn` (`restate_analyst/main.py:2421`) holds three things in a **durable Restate
VirtualObject keyed on `ctx.key()`**:

```python
raw_state       = await ctx.get("state")             # the accumulating InterviewState
chat_history    = await ctx.get("history")
focused_subject = await ctx.get("focused_subject")   # whose verbs are offered NEXT turn
```

**`focused_subject` IS the partial parse carried across asks** — precisely what the held-promise
design was defined to hold, with Restate owning its lifetime. `apply_pick`'s `FocusSubject`
action *"records nothing here; it only tells the VirtualObject WHICH subject's verbs to compute
for the next turn."*

> ### The graduation condition NARROWS rather than fires
>
> `[[elicitation-ask-disposition]]` registered: *"held-promise earns its place when MULTI-SLOT
> elicitation arrives."* That population is **still zero** — the census says max one
> spoken-mandatory slot per verb, and `test_TRIPWIRE_one_ask_per_dispatch...` still holds.
>
> Step authoring is a **different consumer**, not the arrival of that one. And it already has a
> durable held state. **Building held-promise in the elicitation lane would be building a second
> implementation of a thing that exists** — which is what the tripwire was written to prevent,
> pointed the other way.
>
> The tripwire's wording should be read as it is written: it asks about *slots*, not about
> *turns*. It is not fired by this.

## Q3 — reuse or reimplement `authorized_verbs`?

**Neither: reuse the ENDPOINT, not the function** — and the distinction from `validate_pick` is
the generalisable rule.

`authorized_verbs` is an **HTTP client with service-identity headers** living in an engine
package. `iagent_pure` cannot import it for the same packaging reason it could not import
`validate_pick` — engine images do not ship `iagent_pure`, and the dependency would run the wrong
way besides.

| | what it is | how to reuse it |
|---|---|---|
| `validate_pick` | **pure logic** | **mirror**, pinned by a test — done (`9e6cc20`) |
| `authorized_verbs` | **I/O** | **share the contract**, write your own client, inject it |

The contract is stable and already public:
`POST /find_compatible_verbs {subject_uri, max_hops, entitled_domains} -> {verbs: [...]}`
(`ontology_service/main.py:3343`). That is exactly the shape `decide_disposition` already takes
`enumerate_class` as — an injected callable, so the pure module never learns an engine's URL.

> **The rule, stated once: mirror pure logic; share contracts for I/O; never import across the
> packaging boundary.** Both halves of this arc are now instances of it.

## Q4 — the difference nobody asked about, and it decides the surface

**Who proposes the pick is not the same in the two systems.**

| | proposes | disposes |
|---|---|---|
| **V2 authoring** | a **BAML shell** reading chat history — *"it PROPOSES; the funnel DECIDES"* | `apply_pick` → `validate_pick` |
| **elicitation** | **the user**, choosing from a rendered menu | `resolve_ask` → `validate_pick` |

Same enforcement, **different proposer**. V2's turn is a model-mediated authoring conversation;
elicitation's is a menu render awaiting a human. That is a third independent reason the transport
does not transfer, alongside the modal session lock already recorded — and it is the one that
matters for the deferred card, because a card that renders options for a human is not the surface
an LLM-proposal loop needs.

### One menu-integrity idea worth carrying BACK the other way

V2's subject menu is deliberately sourced from the **capability graph**, not the ontology:

> *"only subjects the mesh can act on (>=1 verb) … so every offered subject **leads to a verb**
> (no 94%-dead-end ontology-vocabulary menu)."*

That is menu integrity raised from *"every option is valid"* to **"every option is productive."**
Elicitation's enumerator returns all members of a class, which is correct for instance slots —
any project is a valid `project_id` — so there is no dead-end population today. **Recorded as a
principle to check when a slot's class ever contains members the verb cannot act on**, which is
the shape that would make an elicitation menu offer a dead end.

## Verdict

**Step authoring is ADR-0029 Slice 2. It is not an extension of the ask disposition**, and it
should not be built in this lane.

* the machinery **exists**, is unit-tested, and is unreachable — the whole finding of
  `[[spo-interview-reuse-for-elicitation]]`;
* its control structure (dependent menus, unbounded turns, artifact-termination) is not
  elicitation's, and forcing either into the other's shape damages whichever loses;
* its held state is **already durable**, so the one piece elicitation was told it might owe is
  the piece it most clearly does not.

**What the two share is exactly what has already been shared:** `validate_pick`, the phone-book
rule, and menu integrity. That was the right amount, and this read did not find a second thing.

## What this means for the corpus, which is why the read came first

**The elicitation corpus tests ONE shape, not two.** Its multi-turn cases are
ask → answer → re-route → assert, with a single bounded turn — **not** an authoring sequence.
Nothing in it should hold state between turns beyond what the card carries, and no case should
be written to exercise a second dependent menu, because elicitation has none.

Had the corpus been authored first, its multi-turn section would have been written against a
control structure this lane does not have — and would have had to be rewritten once the shape
was known. That is the whole value of taking the read first, and it is worth recording that the
read cost an hour and the rewrite would have cost the section.
