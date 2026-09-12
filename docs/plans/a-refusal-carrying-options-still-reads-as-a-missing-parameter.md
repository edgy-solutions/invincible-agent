---
id:         a-refusal-carrying-options-still-reads-as-a-missing-parameter
status:     open
owner:
blocked-on: the cost card walk (do it after, not before — the walk is what says whether the values render at all)
repo:       invincible-agent
code-site:  agent_fleet/cost_agent/main.py (the slot_required branch in /measure/{fn_name})
summary:    The VALUES half is fixed and the WORDING half is not. A slot_required refusal now carries `options: {"rate_vintage": ["2021-02-01", "2021-08-01"]}` while its `reason` still reads "cost_rate_comparison needs rate_vintage" — a missing-parameter statement attached to a payload that is offering a choice. The message is generic across every verb in the engine, so it cannot say what the options mean. Minimum fix: say "choose a rate vintage" when `options` is non-empty. Better fix: let the verb supply its own reason, the same way it now supplies its own options. Small, cortex-adjacent. Ruled a ticket rather than a walk-blocker by the architect 2026-09-11.
---

# A refusal carrying options still reads as a missing parameter

## The state it is in

Fixed today (`93297bf`): the route computes legal values from the slots the caller **did**
supply, so the refusal for *"did the rates move against the estimate on lot 3"* now carries both
vintages by name. Before that, `_require_vintage` — the only code that knows them — was
**unreachable through the path the UI uses**, because a generic `slot_required` answers first.
See [`reachability-is-a-property-of-a-path`](../principles/reachability-is-a-property-of-a-path.md).

What still goes over the wire:

```json
{ "refused": true, "outcome": "slot_required",
  "reason": "cost_rate_comparison needs rate_vintage",
  "missing": ["rate_vintage"],
  "options": { "rate_vintage": ["2021-02-01", "2021-08-01"] } }
```

**The payload offers a choice and the sentence reports a gap.** A renderer following `reason`
writes *"needs rate_vintage"*; a renderer following `options` draws two buttons. Both are reading
the same object correctly.

## Why it is the same defect as the one just fixed

The values half and the wording half are **one defect seen twice**: a generic guard cannot speak
about a specific verb. It could not produce the vintages, and it cannot produce the sentence that
explains why they are needed — *a forward-looking figure needs its assumption set named*, which
is what `VintageRequired` says and what `slot_required` structurally cannot.

Fixing only the values leaves the refusal **half-migrated**, and a half-migrated refusal is the
worse state to stop at: it now looks answered.

## Options, in the order they should be considered

1. **Minimum, and the one to do first.** When `options` is non-empty, phrase the reason as a
   choice: *"choose a rate vintage"*. One conditional, no new registry, and it makes the sentence
   agree with the payload. **It does not carry the WHY**, so it is an improvement and not a
   completion — say so where it lands.
2. **Let the verb supply its reason**, keyed `(verb, slot)` beside `OPTION_SOURCES` in
   `measures.py`. Symmetric with the fix already shipped, keeps the knowledge with the verb that
   owns it, and can carry the basis-level explanation. **The honest cost:** a second per-slot
   registry, and this engine already pays for six verb tables — worth naming before adding a
   seventh.
3. **Reached-verb refusals** — let the route call through and have the verb raise. **Rejected
   for now:** that is what produced `TypeError: missing 1 required keyword-only argument` shown
   to a person who asked a question, which the `slot_required` branch exists to prevent. See
   [`a-missing-mandatory-slot-is-a-400-not-an-ask`](a-missing-mandatory-slot-is-a-400-not-an-ask.md).

## Do it after the walk, and that is deliberate

The walk is what establishes whether the **values** render at all. If cortex drops `options`, the
sentence is not the binding constraint and this ticket is aimed at the wrong layer — the split is
written into the sheet: *if the refusal draws but the two values do not appear, the payload is
right and the renderer is dropping them.*

## What is already sealed, so a fix here does not regress it

`tests/cost/test_the_refusal_carries_its_options.py` — seven seals, all four mutations proven to
bite. The one to preserve is **the join**: the verb's `available` and the route's `options` are
two computations of one truth by paths that never meet, and nothing else can see them disagree.
Any change that moves reason-building must keep that test passing unchanged.

**Also sealed:** every option offered is one the verb accepts. An option list is a promise, and
offering a value that is then refused sends the caller into a second failure — worse than
silence, because it was specific.
