---
id:         an-override-onto-an-unserved-class-must-abstain
status:     open
owner:      agent (lane 1) — RULED 2026-09-04, NOT BUILT
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 (route | ask | abstain); ADR-0031 (the instance-resolution ladder)
code-site:  agent_fleet/ontology_service/main.py:1886 (Step 4, the instance-resolution pre-step), agent_fleet/ontology_service/main.py (_served_class_uris, the productive-option gate)
summary:    THERE ARE TWO PATHS INTO resolved_uri AND ONLY ONE IS GATED. The productive-option gate (4d13eee) restricts what the LLM may CHOOSE — the candidate pool is limited to classes carrying a verb in the caller's domains. Step 4's instance-resolution pre-step then OVERRIDES that choice with a unanimous provider answer, unchecked, so a phone-book match can install a class no verb serves. Measured by the engine-cost lane: 10 of 18 draws had a winner outside the candidate set, and every one resolved to fin:WBSElement, which carries no verb in ANY domain. That is the DOMINANT dead end in their data — 5 of 9 scoped draws — and it is reached by the one path the gate cannot see. THE OVERRIDE IS NOT THE DEFECT: a caller named "lot 4", a provider resolved it, and fin:WBSElement is a DECLARED drill-down referent in engine-fin's _NO_VERB_BY_DESIGN. The instance resolution is working. What is missing is that nothing notices the resolved subject cannot be answered. RULED: a productivity check AFTER preemption — same predicate as the gate, applied to the WINNER rather than the pool — abstaining or asking, with the resolved instance carried as context.
---

# An override onto an unserved class must abstain, not proceed

## Two ways into `resolved_uri`, one of them gated

The productive-option gate restricts the **candidate pool** to classes carrying a verb in the
caller's domains. It is a constraint on what the LLM may *choose*.

`main.py:1886` — Step 4, the instance-resolution pre-step — then overrides that choice:

```python
identifier = result.instance_identifier          # "lot 4"
instance_subject, prov = await _resolve_instance(identifier, query)
if instance_subject is not None:
    return SemanticResolutionResponse(
        resolved_uri=instance_subject, ...,
        candidates=candidates,       # the PRE-override pool, deliberately
    )
```

The pre-override pool is carried **on purpose**, and the code says why: *"The class contest DID
run before instance preemption overrode it — carry the pool so the decision path can show 'LLM
guessed X from these candidates; instance resolution then overrode to Y'."*

**So a winner outside the candidate set is documented behaviour, not an anomaly.** It was
reported as one, and the meaning was legible in code nobody had opened. Recording that here
because the next reader will make the same inference from the same evidence.

## Why blocking the override would be the wrong fix

`fin:WBSElement` is in engine-fin's `_NO_VERB_BY_DESIGN`. It is a **declared drill-down
referent** — a class a caller names *on the way to* another answer. Resolving "lot 4" to it is
the instance ladder working exactly as designed.

**Blocking the override would break a working referent path in order to fix a missing
refusal.** The defect is not that the override happens; it is that nothing then notices the
resolved subject has no verb in scope, so the router falls through to the generalist — which
answers from the catalog wearing the caller's own persona, indistinguishable from a real answer
until a human reads the card.

## The ruling

**A productivity check AFTER preemption. Same predicate as the gate, applied to the winner
rather than the pool.**

When the overridden `resolved_uri` carries no verb in the caller's domains, the honest outcome
is **abstain or ask**, with the resolved instance carried as context rather than discarded —
the resolution succeeded and saying so is more useful than a bare refusal:

> *"I found lot 4, but nothing here answers about a lot directly; did you mean the program?"*

That is ADR-0033's `ask` with a genuine option source, and it is strictly better than the two
alternatives: a generalist answer that looks real, or a refusal that throws away a correct
instance resolution.

**Same degradation discipline as the gate.** An empty served-set means the lookup failed, and
the check must then let the override stand — restoring today's behaviour rather than converting
a Neo4j hiccup into a refusal storm.

## The test for the next case, from the engine-cost lane

> **Does a caller name the class ON THE WAY TO another answer, or ask about it DIRECTLY?**

* `fin:WBSElement` — the first. A drill-down referent, correctly marked, correctly resolvable,
  and correctly served by no verb.
* `cost:CostCategory`, `cost:Supplier` — the second. Both named in engine-cost's own spec and
  left unimplemented when six verbs were chosen. Ruled: **both get verbs, neither gets the
  marker.**

That distinction is what keeps `mesh:ResolvableReferent` from becoming a place to park
omissions. A class a question WILL target with nothing behind it is a missing verb; declaring
it a referent converts an omission into something wearing a decision's clothes.

## What this does NOT do

It does not give `WBSElement` an answer, and it should not. The point is that a question landing
there stops being answered *incorrectly* — the cross-engine seal stays red until each owning
lane mints or declares, and a check that hid the seal's population would remove the symptom and
the signal together.
