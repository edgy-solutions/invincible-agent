---
status: MEASURED — root cause found, three rulings routed, cost-side fix owned by engine-cost
date: 2026-09-11
lanes: engine-cost (91) · router pre-step (Lane 1) · HUD (cortex-60)
---

# Four cost questions abstained, and the cause was a bare digit

Two questions from the cost card walk sheet, typed verbatim into the UI, produced
`Not grounded · conf 0.00` and a DataHub entitlement refusal. **The cards were never reached.**
Nothing in the walk exercised engine-cost, so it tested routing rather than presentation.

## THE CLASSIFIER WAS RIGHT, AND IT DESERVES THE CREDIT

From `iagent-engine-o` at 20:53 and 20:58:

    "resolved_uri": "http://invincible-agent/cost#Supplier",
    "confidence_score": 0.92,
    "reasoning": "The query asks about how concentrated purchasing is, which matches the
                  Supplier class ... The mention of \"lot 4\" is a filter but does not change
                  the primary focus on suppliers.",
    "instance_identifier": "lot 4"

**0.92 on the right class, with reasoning that correctly identifies "lot 4" as a filter rather
than the subject.** The subject descriptions are in the pool and they worked. This was never a
phrasing problem and never a seeded-corpus gap.

**Both phrasings are the engine's own declared synonyms**, taken from `CATALOGUE` in
`cost_agent/main.py` — `how concentrated is purchasing`, `did the rates move`. The walk sheet
did not invent them.

## THE POST-PREEMPTION CHECK'S FIRST LIVE CATCH

    [Engine O] post-preemption check ABSTAINED: 'lot 4' resolved to
    http://invincible-agent/fin#WBSElement which carries no verb in ...

Four times — `lot 4` twice, `lot 3` twice. **This is the check working exactly as designed.**
Without it, four questions would have been answered confidently from the wrong ontology. The
abstention is correct; it simply cannot route to cost, because the subject it was handed was
`fin:WBSElement`.

## ROOT CAUSE: THE PHONE BOOK MATCHES A BARE DIGIT AGAINST `instance_id`

Measured directly against `finance_agent/main.py::_candidates`:

| query | resolves to | `instance_id` | score |
|---|---|---|---|
| `lot 4` | Program Support | `4` | **0.500** |
| `site 4` | Program Support | `4` | 0.500 |
| **`banana 4`** | **Program Support** | `4` | **0.500** |
| **`xyzzy 4`** | **Program Support** | `4` | **0.500** |
| `phase 3` | Integrated System | `3` | 0.500 |
| `lot four` | — | — | **no candidates** |
| `4` | Program Support | `4` | 1.000 |

**`banana 4` is a fabricated control and it resolves.** `lot four` — the same meaning, spelled —
resolves to nothing. **The digit is doing all the work.**

So the blast radius is not cost and not finance: **any question in any domain containing a bare
integer N is eligible to be preempted onto finance's WBS element N.**

### Two properties that make it land rather than fail safely

1. **The hit scores EXACTLY at the floor.** `_RESOLVE_FLOOR = 0.5` and the gate is
   `score >= _RESOLVE_FLOOR`. A boundary-value match passes by the narrowest margin available.
2. **A phone-book hit outranks the classifier by design.** Recipe v2: *"lets the authoritative
   phone-book class override `resolved_uri`."* So 0.500 on a nonsense match outranks 0.92 on a
   correct one.

> **An authority ranking is only safe while the authority is scoped.** "Authoritative" was
> designed when one provider answered; it now means *any* provider's boundary-value hit beats
> every classifier.

## WHAT IS NOT THE FINDING

- Not the phrasing. Both came from the engine's own routing signal.
- Not the seeded corpus. `cost:Supplier`'s description was in the prompt and matched at 0.92.
- Not the cards. Nothing reached presentation.
- Not the abstention. It fired correctly and prevented four wrong answers.

## A SECOND DEFECT IN THE SAME LINE — the diagnostic prints source, not values

    ... which carries no verb in request.domains or ([request.domain] if request.domain else [])

That is **a Python expression rendered as literal text.** The line cannot say WHICH domains were
checked, so the abstention is right and unreadable — which is why this presented as "the cards
are not routing" rather than "a finance provider owns the token." Same family as a log that
prints `✅ Registered` without saying what.

## A THIRD: THE HUD SHOWS TWO STAGES WITHOUT NAMING THEM

The banner reads *"the subject resolved, but no registered capability operates on it"*; the
decision path directly below reads `conf 0.00 · UNKNOWN`. **Both are true of different stages** —
the banner describes the instance pre-step, the decision path describes the post-preemption
discard. Unlabelled, they read as contradictory diagnoses with opposite repairs: one sends a
reader to check registration (and find nine correct verbs), the other to the classifier.

## OWNERS

| finding | owner |
|---|---|
| digit-collision in `_candidates`; hit at the floor treated as authoritative; out-of-domain hit outranking a 0.92 | **Lane 1** — the pre-step and the scorer |
| abstention diagnostic printing an expression | **Lane 1** |
| HUD messages naming their stage | **cortex-60** |
| **no cost-side instance provider for `cost:ProductionLot`** | **engine-cost (this lane)** |

The last is why finance's claim stood unopposed: **cost has no `/resolve_instance` at all**, so
there was nothing for a scope rule to prefer. That is this lane's work, and the four walk-sheet
questions routing to cost with `lot` bound is its seal.
