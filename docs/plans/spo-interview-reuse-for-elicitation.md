---
id:         spo-interview-reuse-for-elicitation
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 (the elicitation surface + one-archetype constraint); ADR-0029 Slice 2 (the SPO interview)
code-site:  agent_fleet/restate_analyst/spo_interview.py (validate_pick — the reusable half), agent_fleet/restate_analyst/main.py:2384 (ProcessInterviewerV2, no caller), src/iagent/gateway.py:3503-3527 (is_interview_active, the modal transport), src/iagent_pure/slot_acceptance.py (where the missing check belongs)
summary:    A READ, NOT A BUILD — dispatched because "does the SPO interview's turn generalize?" decides whether elicitation's remaining work is hours or days. ANSWER IS THREE-PART AND ONE PART IS A SURPRISE. (1) ADR-0033 cites the SPO interview as prior art that "already shipped once". IT SHIPPED AS CODE AND NEVER AS A REACHABLE CALL: ProcessInterviewerV2 — the SPO interview with the authorized-set menu and server-side validate_pick — is registered and mounted with ZERO callers in src/, agent_fleet/, tests/ or cortex-ui. The gateway's only two interview calls both go to V1 (ProcessInterviewer, the BPMN-era LLM one). Instance #4 of [[a-registration-is-not-a-reachable-call]], and the most pointed: the ADR's own prior-art claim is the unreachable thing. (2) THE PURE CORE PARTLY GENERALISES AND THE TRANSPORT MUST NOT BE REUSED. `validate_pick(pick, authorized_set, key)` is entirely generic — it knows nothing of subjects or verbs — and is the server-side select-from-authorized-set enforcement this lane lacks. But InterviewState/apply_pick/try_finalize are welded to WorkflowDefinition authoring (termination = the definition validates), and the gateway transport is a SESSION-LEVEL MODAL LOCK: is_interview_active forces mode=CONVERSATIONAL so "every subsequent message goes back to the interview regardless of NL content". That is a held lifetime — precisely what ADR-0033's stateless-re-route lean was chosen to avoid on measured grounds. (3) AND THE READ FOUND A LATENT GAP IN THE SHIPPED DISPOSITION: menu integrity is enforced at CONSTRUCTION and not at ACCEPTANCE. Verified empirically — accept_slots({'project_id': 'TOTALLY-MADE-UP'}) returns it ACCEPTED with zero refusals, because an instance slot declares `type: str` and no `values`. Latent today (no re-route path exists to return a pick) and live the day the surface lands.

# Does the Socratic turn generalise? Partly — and its best half has no caller

**A read, dispatched 2026-08-30**, because the answer changes the size of the remaining
elicitation work. ADR-0033's Context names the SPO interview as prior art —
*"widget interrogation already shipped once — the SPO interview asks 'which subject did you mean'
from a menu (ADR-0029)"* — and if that turn mechanism generalises, elicitation is wiring rather
than a build.

Read, not inferred. Every claim below cites a line.

## 1. THE PRIOR ART SHIPPED AS CODE AND NEVER AS A REACHABLE CALL

`ProcessInterviewerV2` — the SPO interview, ADR-0029 Slice 2, the one with the authorized-set
menu and server-side pick enforcement — is defined at `agent_fleet/restate_analyst/main.py:2384`,
handler `spo_turn` at `:2422`, and mounted into the Restate app at `:3259`.

**It has no callers.** Searched `src/`, `agent_fleet/` (excluding vendored `.venv`), `tests/`, and
the `cortex-ui` sibling repo: zero. The gateway's only two interview calls both target **V1**:

```
src/iagent/gateway.py:3510   /ProcessInterviewer/{session_id}/get_status
src/iagent/gateway.py:3576   /ProcessInterviewer/{session_id}/process_message
```

`ProcessInterviewer` (V1) is the BPMN-era, LLM-driven interview that V2's own module docstring
says it **supersedes** — *"superseding the BPMN-fused machinery"*, with V2 adding the verb
question, server-side pick validation, and termination-on-validity. The supersession happened in
the code and not on the wire.

> **This is instance #4 of `[[a-registration-is-not-a-reachable-call]]`, and the most pointed one
> yet: the unreachable thing is the ADR's own prior-art claim.** ADR-0033 reasoned from "we have
> already built this once" — true of the module, false of the path. Direction: **downstream** (the
> service is registered and mounted; nothing dispatches to it), the same direction as
> `enumerateInstances`.
>
> Worth noting for the law's guard section: this one was found by asking *"can I reuse it?"* —
> a consumer's question. It had been invisible to everyone reading from the producer's side,
> where V2 looks complete because it **is** complete.

**Not claimed:** that V1 is broken or that V2 is correct in production. V2 has never run against a
user, which is a different and unmeasured thing.

## 2. WHAT GENERALISES — one function, and this lane needs it

`spo_interview.py` is explicitly a **pure core** — *"no Restate, no live LLM"* — which is the same
posture as `slot_acceptance.py` and `slot_disposition.py`. That much is a good sign, and one piece
transfers with no modification at all:

```python
def validate_pick(pick: str, authorized_set: list[dict], *, key: str = "uri") -> str:
    """SERVER-SIDE select-from-authorized-set enforcement (the old constraint was
    prompt-only). Returns the pick if it EXACTLY matches an entry's `key`; else raises
    PickRefused naming the closest options..."""
```

It knows nothing about subjects, verbs, or workflows — `(pick, set, key)` in, pick or refusal out.
**That is menu integrity enforced on the ANSWER**, and it is the half ADR-0033 #2 implies but does
not spell out: the ADR says *every offered option must route when chosen*; the complement is that
**a pick must have been offered.**

### What does NOT generalise, and the boundary is clean

| piece | reusable? | why |
|---|---|---|
| `validate_pick` | **yes, verbatim** | fully parameterised, no domain knowledge |
| `authorized_subjects` / `authorized_verbs` | **as a pattern only** | they call Engine O `/classes` and `/find_compatible_verbs`; elicitation's equivalent is `enumerateInstances` |
| `InterviewState`, `apply_pick`, `try_finalize` | **no** | welded to `WorkflowDefinition`: multi-turn accumulation whose termination is *"the definition validates"*. Elicitation is one bounded turn to unblock a question, not an artifact being authored |
| the gateway transport | **NO — and reusing it would undo a ruling** | see below |

## 3. THE TRANSPORT IS A MODAL LOCK, WHICH IS THE THING THE MECHANISM PLAN REJECTED

`src/iagent/gateway.py:3503`, in its own words:

> *"When a session is mid-interview, **every subsequent message goes back to the interview
> regardless of NL content** — the binary mode below gets forced to CONVERSATIONAL."*

The gateway polls `get_status` for `is_active` and, when set, skips `/route_intent` entirely and
sets `mode = "CONVERSATIONAL"`. **That is a session-level held state with a lifetime** — exactly
the shape `[[elicitation-ask-disposition]]` rejected when it registered the stateless-re-route
lean:

> *"It introduces no new lifetime. A re-route **is** a route: every existing guard applies
> unchanged, nothing persists between turns, and there is no expiry semantics to get wrong. The
> held-promise design adds a suspended state with a lifetime — which is the vault's TTL questions
> arriving in a new costume."*

A modal interview lock is a held promise with a stronger claim: it captures **every** subsequent
message, not just the answer. For an interview authoring a workflow that is correct — the user
*is* in a mode. For a one-turn clarification it is wrong, and measurably unnecessary: the census
says **max one spoken-mandatory slot per verb**, so an elicitation never needs to hold a partial
parse across turns.

> **The verdict: take the core's `validate_pick`, take the authorized-set PATTERN, and do not
> take the transport.** The one-archetype constraint is about the **card**, not the transport, so
> this splits cleanly and violates nothing.

## 4. THE READ FOUND A LATENT GAP IN THE SHIPPED DISPOSITION

Looking for where `validate_pick` would go surfaced the reason it is needed.

**Menu integrity is enforced at CONSTRUCTION and not at ACCEPTANCE.** `decide_disposition` filters
candidates by the slot's `referent` so a wrong-class option is never offered — but nothing checks
that a value coming *back* was one of the offered options. Verified empirically, not reasoned:

```
accept_slots({"project_id": "TOTALLY-MADE-UP"}, slots_for("plan_dependency_neighborhood"))
  ->  accepted: {"project_id": "TOTALLY-MADE-UP"}   refusals: []
```

It passes because an instance slot declares `type: "str"` with **no `values`** — there is no
closed vocabulary for the guard to test membership against. The same species as
`[[period-slots-declare-no-vocabulary]]`, one layer over: *the declaration is less precise than
the requirement, and the imprecision runs toward permissiveness.*

**Latent today** — no re-route path exists, so no pick can come back — and **live the day the
surface lands**, which is the cheapest possible moment to close it.

> **Where it belongs:** not in `accept_slots`. That module's contract is *the declarations are the
> acceptance schema*, and the offered menu is not a declaration — it is a per-turn artifact. The
> check belongs beside the re-route, against the `options` the card carried, which is exactly
> `validate_pick`'s signature. Adding it to `accept_slots` would make that module depend on
> conversation state, which is the thing it was built pure to avoid.

## 5. What this changes about the remaining work

**Hours, not days — for the part this lane owns.** The re-route's server side is:
`validate_pick` against the card's `options`, then re-issue with `{**accepted_slots, slot: pick}`.
Both halves exist: the merge seam is `config.slots` (already outranks the filler) and the
enforcement is an import.

**Days, and not this lane's, for the part that remains.** The surface is still deferred and still
jointly designed with cortex — nothing here changes the archetype-unity constraint. What this read
removes is the *risk* that the surface work would also have to invent pick enforcement.

### Recommended, not taken

**V2's reachability is a question for whoever owns ADR-0029**, and it is filed rather than fixed:
either wire the gateway to V2 and retire V1, or record why V1 remains the live path. Both are
defensible; leaving a superseding implementation registered and unreachable is not, because the
next reader will cite it as shipped — as ADR-0033 already did.

## What this read did NOT do

**No code changed.** It answers a question and names two follow-ups (the acceptance-side pick
check; V2's reachability). Building either before the surface exists would be building against an
interface nobody has agreed.

---

## ✅ BUILT 2026-08-30 — the answer side, from the read's own findings

`src/iagent_pure/slot_disposition.py` gains the half the read said was missing.
**35 tests green** (`tests/routing/test_slot_disposition.py`).

**`validate_pick` — MIRRORED, not imported, and the reason is packaging.** Engine images do not
ship `iagent_pure`: `agent_fleet/ontology_service/main.py` mirrors `decode_declarations` and says
so in as many words — *"Mirrored rather than imported because this service does not ship
`iagent_pure`."* So an import in **either** direction breaks an image, and moving the function out
of `spo_interview.py` would touch a live engine's package for a module with no callers. The house
precedent is `SLOT_KINDS`: mirror, and pin the agreement with a test.
`test_MIRROR_agrees_with_the_spo_interview_it_was_copied_from` imports the real
`spo_interview` and asserts both accept an exact match and both refuse anything else — the copy
cannot silently diverge on the property that matters.

**The transport was refused, as ruled.** Nothing here touches `gateway.py`'s
`is_interview_active`.

### THE DESIGN THE BUILD ADDED: a free-text answer is RE-SPOKEN, never BOUND

The dispatch said *"close the menu-integrity gap"*, and doing it surfaced a case the gap's
statement did not cover. **Both live ask cases have no menu** (`too_many`), so "validate the pick
against the options" has nothing to validate against — and the tempting readings are both wrong:

* refuse every menuless answer → the feature is useless exactly where it fires today;
* accept it → `project_id="Wave 1 Cutover"` binds a *phrase* to an id slot. **That is the
  `TOTALLY-MADE-UP` hole with a human's typing in it**, and it reaches the engine as a 422.

> **So `resolve_ask` returns one of two actions, and the distinction is the whole point:**
>
> | | when | what happens |
> |---|---|---|
> | **`BIND`** | a menu was offered | the pick is validated against it and merged — the value came from a provider, so it is already routable, which *is* menu integrity |
> | **`RESPEAK`** | no menu (`too_many` / `unsupported` / `no_provider` / `no_referent`) | the answer re-enters as **words**, appended to the original phrase, and the filler and resolver run on it exactly as on any question |
>
> **Nothing enters a verb unresolved.** And this is ADR-0033's *"stateless re-route with the
> clarified subject substituted"* read literally: for a pick the clarified **value** substitutes
> into the slots; for free text the clarified **wording** substitutes into the query. Neither holds
> state between turns, so the stateless lean survives contact with the case that looked like it
> needed an exception.

### End-to-end, on substrate-verified data

`test_END_TO_END_a_real_menu_a_validated_pick_and_a_reroute` walks the full server-side path —
real menu → card → **fabricated answer refused** → real pick bound → merged slots surviving
`accept_slots`. Its member list is the live probe in
`[[enumerate-probe-2026-08-30]]`, not invented.

**Still not built, and correctly so:** the HTTP entry point that hands an answer back. That is
surface work, and the surface is joint design with cortex. What exists now is everything beneath
it, so the card lands on a working pick-enforcement-and-re-route path instead of inventing one.

---

## Item 4 — V2's reachability: a PROPOSED disposition, since ADR-0029 has no owner in the lane set

Filed rather than fixed on 2026-08-30, then asked for a proposal. Here is one, with the reasoning
exposed so it can be overruled cheaply.

> ### Proposed: **record why V1 stays, and mark V2 not-live.** Do not switch the gateway.

**Why not wire V2 now**, which is the tempting option and the one I would resist:

* **V2 has never run against a user.** Its pure core is unit-tested; the *path* — a turn arriving,
  a pick validated, a definition finalising — has zero production evidence. Switching a live
  conversational surface to it is not a wiring change, it is a cutover.
* **The harm that was actually done is a citation, not an outage.** ADR-0033 reasoned from
  *"already shipped once"* and would have built on it. A note on the ADR and on ADR-0029 closes
  that harm completely, today, at no risk.
* **This lane has no standing to retire V1.** V1 serves process-creation, which is not this lane's
  surface, and *a seal outranks its authorization*: finding a defect in another lane's path is a
  thing to report, never to widen into a change.

**What the note must say**, because the point is to stop the next reader repeating the mistake:

> `ProcessInterviewerV2` (ADR-0029 Slice 2) is **implemented and not reachable** — registered and
> mounted, with no caller; the gateway drives V1. Its authorized-set menu and `validate_pick` are
> real code and **must not be cited as shipped behaviour**.

**The condition that would change this:** a live case needing the SPO interview's *verb* question —
which is the thing V1 genuinely cannot do. Then the cutover has a reason beyond tidiness, and
whoever owns it can weigh V1's production evidence against V2's better model with something at
stake.

**Escalated, not decided:** naming an owner for ADR-0029 is outside this lane. The proposal above
is what I would do; the choice belongs to whoever holds that ADR.
