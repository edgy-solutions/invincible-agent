---
id:         fix-1-pre-registration
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  docs/measurements/slot_corpus_v1.json, scripts/slot_fill_battery.py
summary:    WRITTEN AND COMMITTED BEFORE THE RUN. Predicted split of the five referent_unresolved cases after fix (1): four resolve correctly (C05 Aurora->S1, C06 Brandon->S2, D04 ERP Modernization->I1, H04 Order to Cash->BP1) and one does NOT (E05, because "ERP Modernization" names an Initiative and the slot wants a Project — and no project bears that name, so the corpus expectation of P1 cannot be satisfied by any correct resolver). Predicted headline 42 -> 46 correct, WRONG 5 -> 0, MISSED 1 -> 2. The most likely refutation is named: the resolveInstance fan-out is fleet-wide, so another provider matching the same name in a different class would produce `mixed` and leave the slot unresolved.
---

# Fix (1) — what I expect the corpus to do, written before running it

## The five `referent_unresolved` cases

| id | phrasing | slot | resolver says | predicted |
|---|---|---|---|---|
| C05 | "how loaded is the Aurora site" | `site_id` | `S1` *Site A — Aurora*, 0.83, class `#Site` ✓ | **CORRECT** |
| C06 | "is Brandon over capacity next quarter" | `site_id` | `S2` *Site B — Brandon*, 0.84, class `#Site` ✓ | **CORRECT** |
| D04 | "spend for ERP Modernization" | `scope_initiative_id` | `I1`, 1.00, class `#Initiative` ✓ | **CORRECT** |
| H04 | "how has Order to Cash evolved" | `process_id` | `BP1`, 1.00, class `#BusinessProcess` ✓ | **CORRECT** |
| **E05** | "what does the ERP Modernization project depend on" | `project_id` | `I1`, class `#Initiative` ✗ wants `#Project` | **MISSED** (`wrong_class`) |

**Predicted totals: CORRECT 42 → 46, WRONG 5 → 0, MISSED 1 → 2.** Headline 87.5% → 95.8%.

## E05 will not pass, and the corpus expectation is the reason

`expect: {"project_id": "P1"}`. **No project is named "ERP Modernization"** — it is initiative
`I1`, and `P1` is *"Current-State Assessment"*. Verified against the seed: all fourteen project
names checked, none matches.

So **no correct resolver can satisfy this expectation.** The right behaviour is to resolve the
name, notice it is an `Initiative` where the slot declares `#Project`, refuse it, and report
`wrong_class` with the candidate retained — which is what the implementation does.

**This is flagged as a probable authoring error, not scored as a fix failure.** If the intent
was "a project belonging to the ERP Modernization initiative", that is a *traversal*, not a
resolution, and no slot-filler should perform it. The case is still valuable: it is the only
one exercising the resolved-but-wrong-kind path.

## The most likely refutation, named in advance

**`mixed` from the fleet-wide fan-out.** `_resolve_instance` asks *every* registered
`mesh:resolveInstance` provider, not just Engine P. If Engine D matches "ERP Modernization" as
a DataHub dataset, or Engine E as a graph node, the decision table sees candidates in two
distinct classes and returns `mixed` → `instance_resolved: False` → the slot is refused and
reported unresolved.

**That would show as MISSED where I predicted CORRECT**, and it would be a real finding rather
than a bug: it means referent resolution for a domain-scoped slot needs a domain-scoped
fan-out, and the fix would be to filter providers by the slot's domain before asking.

Second possibility, smaller: the filler now emits the id directly for a name it happens to
know, making resolution a no-op for that case. Harmless, but it means the case stops testing
what it was written to test.

## What would count as the fix failing

* any of C05 / C06 / D04 / H04 still WRONG — the name reaching the engine;
* **any slot left in `slots` holding an unresolvable string** — the pass-through the
  elicitation lane measured, which this was built to remove;
* a case regressing from CORRECT to anything else — the same acceptance shape the coercion
  fix was held to.

Refutations get reported as prominently as confirmations.
