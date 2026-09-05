---
id:         an-override-onto-an-unserved-class-must-abstain
status:     open
owner:      agent (lane 1) — BUILT 2026-09-04, NOT ROLLED (roll after the ask/BIND walk)
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 (route | ask | abstain); ADR-0031 (the instance-resolution ladder)
code-site:  agent_fleet/ontology_service/main.py — BOTH preemption returns (the Step 4 pre-step AND the class-recall-empty fallback; the ruling named only the first), _preempted_subject_is_unanswerable, _served_class_uris(include_referents=); src/iagent/defs/dynamic_supervisor.py (_ENGINE_O_ABSTENTION_REASONS — the reason passthrough that was a ternary on one literal)
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

---

## BUILT 2026-09-04 — and two things in the ruling above were wrong

The check is in, at `_preempted_subject_is_unanswerable`, with
`tests/routing/test_post_preemption_productivity.py` holding it. Both corrections were found
by building it, not by reading it again, which is the argument for building rulings promptly
while the reasoning that produced them is still recoverable.

### 1. "code-site: main.py:1886" named ONE site. There are TWO.

The second preemption return is the class-recall-empty fallback — it fires when the class
contest found nothing at all, which makes it the branch MOST likely to reach a subject no verb
serves, and it was the one the ruling did not see. A check on one site is silent by
construction on the other, so the test COUNTS the gated returns against the preemption returns
rather than spot-checking either.

That is the enumeration law arriving in a place nobody had listed as a registry.

### 2. "Same predicate as the gate" would have built a check that cannot fire.

The gate's served-set UNIONs in declared `mesh:ResolvableReferent` classes on purpose: a
referent is groundable, and belongs in the candidate pool. **But a referent is precisely a
class that grounds and cannot be answered** — so the post-preemption check must NOT count it
as served. Two different questions:

* *may the resolver OFFER this?* — the gate. Referents included.
* *can this be ANSWERED?* — this check. Referents excluded.

**And the live graph refutes the urgency while confirming the design.** Measured today: the
referent set is EMPTY (0 classes under `mesh:ResolvableReferent`; 67 verb-carrying classes of
1044 total), and `fin:WBSElement` is in neither set. So a shared predicate would abstain
correctly on WBSElement right now and look correct indefinitely — **until someone declares
WBSElement a referent, which this very document says is the right thing to do.** Doing the
correct thing would silently disable the protection.

Implemented as one Cypher with `include_referents` switching the UNION off via a null root,
rather than two queries that would drift.

### 3. A third thing, found downstream: the router flattened the reason

`_fb_reason` was `"instance_not_found" if is_instance_not_found else "subject_unknown"` — a
ternary on one literal — and **the same flag decided whether Engine O's actionable message
passed through at all.** Reporting a new abstention without widening both would have produced
the generic Contract-B boilerplate under a wrong reason code, with every test on both sides
green. Now a set, `_ENGINE_O_ABSTENTION_REASONS`, so the next addition is one line in one
place.

### The reason reported is `no_compatible_verbs`, reused deliberately

A new enum value needs six sites across two repos — the gateway projection, its two comment
vocabularies, the projection test's enum list, cortex's TS union and its render switch. A
value neither repo knows renders as nothing, which is the same loss in a new coat.
`no_compatible_verbs` is TRUE of this case, and the nuance that the subject arrived via
preemption is carried in provenance (`unanswerable_subject`, `instance_provider`,
`preemption_path`) where it is not load-bearing for rendering.

### Not rolled

Engine O needs a roll for this to take effect, and it is deliberately NOT rolled yet: a human
walk of the ask/BIND path is imminent, and changing routing behaviour underneath a walk in
progress makes both results unreadable. Roll after the walk.
