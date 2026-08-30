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
