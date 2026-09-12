---
status: MEASURED against the live fleet — 4 of 5 prompts fixed, 1 fails in a NEW way with the SAME shape
date: 2026-09-12
fleet: engine-o / engine-cost / engine-fin at 2803900557cdfb16959e3b5b6c0b2e0c0b5d5c93; 14 other services at 22c53bed (named divergence, not a half-applied fleet)
instrument: POST /resolve on iagent-engine-o:8084, from inside the cluster. NOT a card walk — no screen was seen.
---

# The instance override survived its own fix, and the last question proves it

Measured after the roll, against `POST /resolve` with
`domains=['PRODUCTION_COST','PROGRAM_FINANCE']`:

| prompt | `resolved_uri` | conf | instance | classifier's own guess | |
|---|---|---|---|---|---|
| how concentrated is purchasing on lot 4 | `cost:ProductionLot` | 0.95 | Lot 4 / exact | **`cost:Supplier`** | ❌ |
| did the rates move against the estimate on lot 3 | `cost:ProductionLot` | 0.90 | Lot 3 / exact | `cost:ProductionLot` | ✅ |
| …on lot 3, using the 2021-02-01 vintage | `cost:ProductionLot` | 0.92 | Lot 3 / exact | `cost:ProductionLot` | ✅ |
| what is the labor split on lot 4 | `cost:ProductionLot` | 0.98 | Lot 4 / exact | `cost:ProductionLot` | ✅ |
| what rates are we using in FY2021 | `cost:RateTable` | 0.97 | — none — | (no override) | ✅ |

**Four of five are fixed, and they are properly fixed** — they reach cost, the lot binds exactly,
and the provider agrees with the classifier. Lane 1's demotion is visibly working:
`instance_out_of_domain_demoted` names `engine_p_planning` on every lot question.

**The fifth is not fixed. It fails in a new way with the same shape.**

## The one that still fails is the one whose original diagnosis was exactly right

`"how concentrated is purchasing on lot 4"` is a **supplier** question. "Lot 4" is a **filter**.
The classifier said so the first time, at 0.92, in its own words: *"The mention of 'lot 4' is a
filter but does not change the primary focus on suppliers."* It says so again now — the response
records `LLM guess: cost#Supplier` — **and the instance pre-step overrides it anyway.**

    BEFORE:  classifier cost:Supplier 0.92  ->  overridden by fin:WBSElement 0.500 (bare digit)
    AFTER:   classifier cost:Supplier 0.92  ->  overridden by cost:ProductionLot 1.0 (exact)

**Same defect, better-looking winner.** The override is no longer nonsense — Lot 4 genuinely is
Lot 4 — which makes it harder to see and not less wrong.

## And the subject it lands on cannot answer the question

Measured on the same fleet via `/find_tool`:

    subject cost:Supplier      + "how concentrated is purchasing"  -> costSupplierConcentration ✅
    subject cost:ProductionLot + "how concentrated is purchasing"  -> "No predicate edge ... matches"

`cost_supplier_concentration` declares `input_uri = cost:Supplier`. Once the subject is
`ProductionLot`, **the verb that answers the question is unreachable.** The four verbs on
`ProductionLot` are lot breakdown, rate comparison, labor composition and price composition, and
none of them is about purchasing concentration.

**The post-preemption check will not catch this one.** It abstains when the resolved class
*carries no verb in the asked domains*. `ProductionLot` carries **four**. The check's condition is
satisfied and the question is still unanswerable — a guard whose premise is true and whose purpose
is defeated.

## The rule the measurement points at

The pre-step treats every instance hit as a claim about **what the question is about**. But an
instance is very often a **filter** — and the classifier already distinguishes the two, in the
reasoning field, on both runs. That judgement is computed and then discarded.

> **An instance hit may override the subject only if the resulting subject carries a verb that
> matches the question.** Otherwise bind the instance as a filter and keep the classifier's class.

For this prompt that yields subject `cost:Supplier` with `lot=4` bound — which is the answer both
halves of the system already independently produced. The machinery to check it exists: `/resolve`
already computes `excluded ... reason: no_verb_in_scope` for other classes in the same response.

**Owner: Lane 1** — the pre-step is theirs, and this is a change to override semantics, not to any
engine's scorer. **Nothing in `cost_agent/` should change**: this provider is behaving correctly.
Asked "is there a Lot 4", the right answer is yes, at 1.0. It is the *consumer* of that answer
that must decide whether a lot is the subject or a filter.

## What this measurement is NOT

**No screen was seen.** This is `/resolve` and `/find_tool` over HTTP, which is a payload check,
and a payload check is not a card walk (`docs/runbooks/writing-a-walk-sheet.md`). Four prompts now
resolve correctly and **nothing here says a card drew**. Q5's designed refusal — the screen that
has never been confirmed to render — is untouched by this and still needs a human with the UI
open.

Fleet state when measured: three services ahead of the release record at `2803900`, fourteen at
`22c53bed`. A named divergence rather than a half-applied fleet: the five prompts exercise only
the three rolled services.
