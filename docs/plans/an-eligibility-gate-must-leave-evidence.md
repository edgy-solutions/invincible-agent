---
id:         an-eligibility-gate-must-leave-evidence
status:     open — RECORD BUILT (lane 1), RENDER OUTSTANDING (cortex)
owner:      agent (lane 1) for the record; cortex for the decision-path panel
blocked-on: cortex rendering `excluded` beside the recall candidates
repo:       invincible-agent (+ cortex-ui)
ruled-by:   ADR-0033 (route | ask | abstain); the four-things-per-draw law, applied one layer up
code-site:  src/iagent/defs/dynamic_supervisor.py (`_eligibility_record`, `_abstention_note`, the five routing returns), agent_fleet/ontology_service/main.py (the productive-option gate's structured records + `SemanticResolutionResponse.excluded`), src/iagent/gateway.py (`_project_route_decision`)
summary:    Eligibility gates remove candidates SILENTLY and the record afterwards shows only what survived, so an abstention over a pool of one reads as classifier uncertainty when the truth is that a gate deleted the answer first. Those need opposite remedies. Every gate now records what it removed or flagged and why, the record reaches the artifact through both layers, and the abstention message distinguishes "nothing fit" from "something fit and was excluded" — because only the second is a cue the caller can act on.
---

# An eligibility gate must leave evidence

## The failure, and why it hid

**A pool of one looks healthy.** That is the whole thing.

Measured 2026-09-04: `idp#Capability` carries TWO verbs under `PORTFOLIO_PLANNING`. The arity
gate removed `planCapabilityPath`, leaving `planMaturityGrid` — which does not answer *"what is
the capability path"*. The classifier was handed one **wrong** candidate, honestly returned
UNKNOWN, and the HUD said *"no confident action"*.

Every surface downstream was truthful. The candidate pool was real, the abstention was real, the
confidence was real. **What no surface could say is that the answer had been deleted before the
choice was made**, because `candidates` records what survived and nothing recorded what did not.

I described this myself, in the gate's own docstring, as *"the candidate set went empty"* — and
that was wrong too. Starved-of-options and starved-of-the-RIGHT-option are different failures,
and the second is strictly harder to see.

## What is built

**One vocabulary across both layers**, because a reader asking *"why is there no answer"* does
not know whether a class or a verb was eaten, and a trace covering one layer sends them
confidently to the wrong place:

```
{kind: class|verb, uri, gate, disposal: removed|flagged, reason}
```

* **engine-o** — the productive-option gate emitted a `print`. Printing is not carrying. It now
  returns structured records on `SemanticResolutionResponse.excluded`, on every `/resolve` return
  that carries a pool.
* **the supervisor** — seeds the trace with engine-o's class removals, appends its own verb-level
  records, and carries it on **all five** routing returns. Three of those build their own
  telemetry dict rather than using the shared one, **and the abstention branches are among them**
  — a key added only to the happy path is missing exactly where it explains the most.
* **the gateway** — projects it wherever it projects `candidates`, honest-empty on absence.
* **the abstention message** — `_abstention_note` appends *"Something DID fit and was removed
  before the choice was made: X (excluded by arity: needs an instance)"*. Empty string when
  nothing was excluded, so a genuine "nothing fit" keeps its exact wording.

**`disposal` is two-valued because the arity gate stopped removing.** It now flags
`needs_instance` and keeps the verb, so a trace with only `removed` could not describe the very
gate that motivated the trace. `flagged` is a candidate that survived carrying a condition — the
reason an ask is owed — which is what lets a surface say *"needs an instance"* instead of
inferring it from a slot that happens to be unfilled.

## What is NOT built

**The render.** Cortex already shows *"candidates not chosen (recall)"* with scores; this needs
*"candidates removed (eligibility)"* with the gate and reason beside it. The data now reaches the
artifact; nothing displays it yet, so today the trace is available to a reader who queries the
graph and invisible to one looking at a card.

**The domain gate is not instrumented.** It lives in engine-o's Cypher (`find_compatible_verbs`
filters by `domains` in the query itself), so there is no Python seam where a removed verb passes
through — the excluded set is never materialised. `domain_scope_excluded` is detected today by
**re-asking Neo4j unscoped** on the empty-pool path, which is a different and more expensive
mechanism. Making the domain gate emit records means returning the unscoped set from the walk,
and it is the one gate this change does not cover. **Recorded rather than quietly omitted**,
because a trace that looks complete is worse than one known to have a hole.

## The test that had to be fixed twice

The enumeration assertion was first written as `count >= 4`. Deleting the key from the
no-compatible-verbs branch left four and the test stayed **green** — the aggregate-floor defect,
inside the file written to prevent it. A count cannot say WHICH site is covered, and "which" is
the entire question. It now checks each return site individually and skips only the returns that
hand back the shared dict, with a separate assertion that the shared dict really carries the key
so that skip is earned rather than assumed.
