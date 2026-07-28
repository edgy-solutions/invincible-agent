# ADR-0033 — Interrogative disambiguation: the third behavior between route and abstain (ask from the phone-book)

**Status:** Proposed — deferred (evidence-gated, post-demo). Decision shape recorded; build deferred to a slice.
**Date:** 2026-07-28
**Deciders:** Platform team
**Related:**
  - [ADR-0031](ADR-0031-instance-resolution-ladder.md) — the instance-resolution ladder + the phone-book candidate-generator. This ADR **adds a rung** (ask) and a new `resolved_via: user-confirmed` tier.
  - [ADR-0032](ADR-0032-goal-oriented-analytical-queries-catalog-analyst-loop.md) — "the LLM authors, enforcement disposes." Same trust shape answered for *dialogue*; **shares the elicitation surface + menu-integrity rule** with the goal-shape card.
  - [ADR-0011](ADR-0011-multi-spo-routing.md) — the evidence-gated deferral structure this ADR reuses (defer, name the wake signal, let telemetry accumulate).
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — the sunset of LLM-invented classification: an LLM *proposes* but gains no authority. (The propose/dispose **candidate-generator mechanism** this ADR leans on lives in ADR-0031's phone-book; 0009 is the underlying principle, and its "must not execute unvalidated" reframe is ADR-0032's.)
  - [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md) — the canvas / elicitation-card surface. The disposition-rules pattern (policy-as-data) governs the gate and the growth loop.

## Context

Today the router has **two** behaviors on a query: **route** (confident enough) or **abstain** (an honest degradation card). Between them is a cliff. At low confidence the system does *best-effort* — it routes somewhere on thin signal. That gap is where the worst observed failure lived: the **privacy-notice mis-route** (the ADR-0032 stress-test) — enough signal to route *somewhere*, not enough to route *right*, and no mechanism to spend one user turn converting ambiguity into certainty.

Every piece of the fix already exists **except the conversational turn**:

- **Confidence is honest** — the 0.50 cap, `recall_override`, the `resolved_via` tiers (ADR-0031).
- **Abstention is principled** — multi-hit containment abstains rather than guesses; the goal-shape card offers sub-questions (ADR-0031/0032).
- **Widget interrogation already shipped once** — the SPO interview asks "which subject did you mean" from a menu (ADR-0029).

The missing middle behavior is **ask**. Best-effort-at-low-confidence is the system jumping off the cliff politely.

## Decision

Introduce a **third behavior — `ask`** — between `route` and `abstain`, and **retire best-effort-at-low-confidence as a policy.** Five decision-grade commitments:

### 1. The third behavior exists: `route | ask | abstain`

Between "confident enough to route" and "abstain with an honest card," insert **ask**. Routing on thin signal is retired.

A reasonable engineer could argue "just abstain more aggressively" — the ADR's job is to say why not. **Best-effort throws away the signal; abstention throws away the signal; asking captures it.** One user turn converts ambiguity into certainty *and* produces training data (see #5). Abstaining is honest but leaves the user stuck and teaches the system nothing.

### 2. Ask from the phone-book, never from the void

The clarifying question's options **must be resolvable entities** — the containment ladder's multi-hit set, the top-k from `resolveInstance`, verb candidates from the capability graph. *"Did you mean the `Customer 360` dashboard or the `Sales Performance` dashboard?"* where both options are guaranteed-routable.

This is ADR-0031's phone-book candidate-generator (on ADR-0009's propose-but-don't-authorize principle) applied to dialogue: the resolver (or LLM) proposes, the deterministic layer disposes, and **the user is the disposer of last resort.** Never an open question (*"what did you mean?"*) — that is abstention wearing a question mark, and it re-imports the free-text ambiguity we are retiring. **The menu-integrity rule from ADR-0032 applies verbatim: every offered option must route successfully when chosen.**

### 3. One turn, then commit or abstain — never a loop

Bounded at **one round** in v1 (two for goal-shaped queries where subject *and* verb are both murky, asked as one combined card). If one turn doesn't resolve it, fall to the existing honest abstain card.

An unbounded clarification loop is the parked-join DoS shape in conversational clothing. It also degrades trust: **two questions reads as diligence, four reads as broken.**

### 4. Gated on resolution provenance — the weak path's behavior, never the default's

The trigger is **not** a new confidence model; it is a **policy over existing discriminators**:

- `resolved_via == llm-alone` → **ask**
- containment **multi-hit** → **ask** (nearly free — the abstain already holds the candidate list and currently discards it)
- **capped-0.50** → **ask**
- **exact / containment-unique** → **never ask**

That last clause is the guardrail against the clippy failure mode. **A system that asks when it knows is worse than one that guesses when it doesn't** — the asymmetry users actually feel. Interrogation is the weak path's behavior. The gate is **policy-as-data** (disposition-rules pattern): thresholds in config, ratifiable and tunable per deployment without a roll. And because `resolved_via` is a *living* vocabulary (this ADR adds a tier; more are filed), the gate is an **allowlist over a growing set** — the discard-pattern trap. Guard it: the gate policy **declares a disposition per tier and fails loudly on an undeclared tier at policy load** (the `validate_ruleset` discipline), never silently defaulting an unknown tier to `route`. Otherwise a future weak tier would stop triggering asks the day it is added, and no one would notice.

### 5. The confirmed pick is provenance-bearing training data — the alias growth loop

When the user picks `Customer 360` from the disambiguation, that is a **confirmed alias mapping** (their original phrasing → the resolved entity) — the growth-loop input the alias-persistence design has awaited since the original ladder ruling.

- Add **`resolved_via: user-confirmed`** — a new provenance tier. Keep **two orderings separate** (do not conflate them): for *audit strength* it is arguably stronger than exact-match (a human attested it); for *routing precedence* it is **not a matching tier at all** — it is the *output* of the ask behavior, and exact/unique still short-circuit before any ask fires (commitment #4's "never ask"). So `user-confirmed` never enters the resolution ladder.
- **Ratify recurring picks into aliases** (provenance-marked, owner-audited — same discipline as learned disposition rules). The interrogation rate declines over time: *the system asks less because asking taught it.* When a **ratified alias** later produces an exact-match hit, its provenance carries its lineage — **`resolved_via: exact-via-learned-alias`**, not plain `exact` — so a dialogue-born match never launders into a native one.

This is the self-hardening shape's **third instance** (phone-book alias growth, disposition-rule learning, now disambiguation→alias). It is what elevates this from a UX patch to an architecture feature: best-effort discards the signal, abstention discards the signal, **asking captures it.**

### Scope: decision vs build

The five above are the ADR. **Not** decided here — they are the design note the ADR points at, decided at build time under the schema-not-rushed rule:

- the **elicitation card's archetype shape** (the citizen shell's fourth tenant — options + a "none of these" escape);
- the **supervisor's pending-state mechanics** — stateless re-route with the clarified subject substituted (simplest v1) vs. a held-promise the way grouped reviews hold suspended promises.

ADRs rot when they carry build detail; those stay in the note.

## Wake condition (why deferred, and the evidence gate)

**Build after the demo.** This touches the router's **hot path** — the wrong thing to modify three weeks out.

The evidence gate is **accumulating for free**: every `recall_override` flag, capped-0.50 answer, and multi-hit abstain in the logs is exactly the population this feature serves. Build when telemetry shows the **ask-eligible rate is material**, measured against real traffic — the same deferral structure as ADR-0011, whose wake signal *did* fire (the stress-test).

## Relationship to ADR-0032's immediate step (one elicitation surface, not two)

The goal-shape abstain card (ADR-0032 immediate step) and this feature will meet in the UI as **sibling elicitations** — one offers *sub-questions*, one offers *disambiguation options* — and they **share the elicitation surface and the menu-integrity rule.** They must be built as **one archetype** (the elicitation card), not two components. Absent this sentence, two agents build them separately and the citizenship grammar forks at its first extension.

## Consequences

- **More honest *and* more accurate** — the rare feature where those don't trade against each other (best-effort and abstain both discard signal; asking captures it).
- **A new producer into a guarded substrate** (the phone-book): disambiguation picks → aliases. That alone clears the ADR bar; it inherits the ratification/audit rules of the disposition-rules pattern.
- **A new `resolved_via: user-confirmed` tier** in routing metadata — audit-strong, because a human attested.
- **A hot-path change**, held behind the evidence gate — the deferral keeps premature complexity off the critical routing path until traffic justifies it.
- The system's **observable conversational contract changes**: a system that *asks* is categorically different from one that only answers or abstains. That blast radius is why this is an ADR, not a design note.

## Non-goals

- **Open-ended clarification / free-text follow-up** — explicitly rejected; it re-imports the ambiguity this retires.
- **Unbounded multi-turn dialogue** — bounded at one round (maybe two for goal-shaped).
- **A new confidence model** — the gate reuses existing discriminators.
- **Specifying the elicitation-card schema or the supervisor pending-state mechanics** — design note, at build time.

## Open questions

1. **One turn vs. two for goal-shaped queries** (subject *and* verb murky) — one combined card, or sequential?
2. **Ratification threshold** for promoting a disambiguation pick to a persisted alias (recurrence count + owner audit). **Default lean:** start by reusing the disposition-rule threshold; split into its own only when evidence shows alias-promotion needs different friction (the start-shared-split-on-evidence rule).
3. **Pending resolution in v1** — stateless re-route (clarified subject substituted) vs. held-promise.

*(Resolved during review, folded into commitment #5: the precedence of `user-confirmed` vs `exact` — they are different orderings, `user-confirmed` is not a matching tier, and ratified-alias matches carry `exact-via-learned-alias` lineage rather than laundering into plain `exact`.)*
