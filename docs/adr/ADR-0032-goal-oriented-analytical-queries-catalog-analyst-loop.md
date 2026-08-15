# ADR-0032 — Goal-oriented analytical queries: the catalog-analyst loop (the LLM authors, enforcement disposes)

**Status:** Proposed — model shape + build order; build staged; evaluation set banked (red-first)
**Date:** 2026-07-23
**Deciders:** Platform team
**Related:**
  - [ADR-0011](ADR-0011-multi-spo-routing.md) — multi-SPO routing (deferred; this ADR is the signal it was waiting for)
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — the process-workflow model (SPO steps + human-await on Restate); the enforcement/approval machinery this ADR routes through
  - [ADR-0027](ADR-0027-composable-approval-policy.md) — multi-approval; [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md) — answer-seeding
  - [ADR-0031](ADR-0031-instance-resolution-ladder.md) — the instance-resolution ladder + the phonebook candidate-generator (LLM proposes, deterministic disposes)
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — sunset LLM-invented classification; the objection this ADR reconciles ("LLM plans must not *execute unvalidated*", not "LLMs must not plan")
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — the generalist fallback that today absorbs (badly) what this ADR names
  - [ADR-0030](ADR-0030-verb-output-is-a-fixed-type.md) — D4 deterministic lineage with honest outcomes, the model for catalog-level honest degradation

## Context

The system routes an atomic NL query to a single `(subject, verb, object)` and answers it. That is the right shape for catalog Q&A ("what tables feed this dashboard"). It is the wrong shape for **goal-oriented analytical queries** — a class of prompt that is not a question about a thing but a *goal* that decomposes into a multi-step investigation.

A representative stress-test (generalized; the captured prompts + failures are the evaluation set, below) asks the system to:

1. **Explore the catalog across multiple data domains** (e.g. Engineering/PLM, Supply-Chain/procurement, Finance/cost-accounting) to identify the tables relevant to a cost/risk analysis.
2. **Map the available metadata** and **formulate a step-by-step data strategy** to correlate signals across those domains.
3. **Present a plan** — proposed joins, the definition of the risk metric derived from what was found, and any **lineage gaps / data-quality issues** that would block the analysis.
4. **Await approval** before executing.

Observed failure modes on this class:

- **"I could not determine what asset your question is about."** Single-SPO subject resolution failed: the router tried to map the *entire goal* to one subject, found none (there is no single subject — it's a goal), and hit the honest-degradation floor.
- **A mis-routed policy/privacy card** (e.g. a "supplier data privacy notice"). A multi-noun anchor matched the wrong subject and returned that card — the *silent-wrong-subject* class we spent effort eliminating, firing again because goal-shaped input forces multi-noun text through atomic resolution.

ADR-0011 predicted exactly this and deferred multi-SPO routing until real queries demonstrated the need. **These prompts are that signal.**

### The three-layer decomposition

The prompt exercises three distinct capabilities, only one of which is "multi-SPO":

| Layer | Capability | Status going in |
|---|---|---|
| **1. Planning / chaining** | decompose a goal into a sequence where step N feeds N+1 | ADR-0011, deferred; the "discovery-driven" flavor is "not handled at all" |
| **2. Catalog reasoning + gap analysis** | which tables are relevant across domains, what joins, **what's missing**, which DQ/lineage gaps block the analysis | the apparent big gap |
| **3. Plan → present → await approval** | author a plan, present it, pause for human approval, observe execution | ADR-0029/0027/0028 — **built** (Slices 2–5) |

The naive read frames the fix as a fork: **(a)** a generalist LLM analyst loop with catalog tools, versus **(b)** the purist build of deterministic multi-SPO + a new catalog-reasoning capability + workflow wiring. **This ADR's core claim is that the fork is false.**

## Decision

### The reframe: the LLM authors, enforcement disposes

ADR-0009's objection was never "LLMs must not plan." It was **"LLM-invented plans must not *execute unvalidated*."** We have already solved that trust problem twice, in miniature, this week:

- **The phonebook candidate-generator** (ADR-0031): the LLM proposes candidate strings; the deterministic layer disposes (exact/containment/abstain). The LLM never gains authority — it gains *proposals*.
- **Slice-4 answer→step seeding** (ADR-0029): an answer is *provenance, not authority* — a seeded `(subject, verb)` must still be **eligible** against the capability graph.

Apply the same shape **one level up**. The analyst loop takes the goal, explores the catalog with real tools, and **authors a *proposed workflow*** — steps expressed as SPOs against **registered** verbs, joins expressed as **claims with cited lineage**, gaps expressed as **explicit honest-degradation findings**. That proposal then flows into exactly the machinery Slices 2–5 already built:

- **Enforcement validates every step against the capability graph** — a hallucinated verb cannot survive.
- **The human-await step *is* the prompt's "await my approval."**
- **Slice-3 observation** covers watching the approved plan run.

So **Layer 3 is not future work — it is deployed.** The LLM never gains execution authority; it gains **authorship**, and authorship was already gated. Option (a) becomes architecturally respectable precisely by routing its output through the enforcement Option (b) built — which is why the fork was false.

### What is actually net-new (Layer 2 is not a monolith)

Decomposed against what exists, the "catalog reasoning capability" is a **toolset plus one genuinely new verb**, not a monolith:

- **Asset search** — exists (Engine D).
- **Lineage walking** — exists (D4/ADR-0030: deterministic, with honest outcomes).
- **Instance resolution** — exists and hardening (ADR-0031 ladder).
- **NET-NEW — DQ-metric retrieval as a verb.**
- **NET-NEW — a coverage-assessment verb:** *honest degradation applied at the catalog level instead of the answer level.* The system already says "examined 0 upstream" and "I couldn't determine which asset"; the new verb says **"no key links vendor performance to unit cost; here are the two nearest join candidates."** Same honesty principle, higher altitude. **Its criteria are policy-as-data** (per the disposition-rules pattern): *what counts as a gap* — a missing join key, DQ below threshold, a lineage break — is **ratifiable data with sealed mechanism, owned by a data steward**, not thresholds hardcoded in the verb's implementation.

### Staged build order

**Immediate (days) — stop the faceplant.** Both observed failures are *routing* failures on goal-shaped input. Generalize the abstain discipline: **detect goal-shape** (multiple domains + planning language + no resolvable single subject after the ladder runs) and return an **honest card** — *"this is a multi-step analytical goal; today I answer atomic catalog questions; here are the N sub-questions I can answer now."* Small change; converts embarrassment into credibility; honest about the boundary instead of confidently wrong across it. **Menu integrity is a hard constraint:** those offered sub-questions must be *actually answerable* — decomposed against the **capability graph** (registered verbs + resolvable subjects), never LLM-suggested phrasings that themselves faceplant. A card offering three sub-questions where two dead-end is the select-from-authorized-set ("94%-menu") problem reappearing *inside the very card built to fix dishonesty*. Card construction is therefore a small **deterministic** exercise (decompose against the graph), not a second LLM surface.

**Mid-term (the real build) — the catalog-analyst loop.** An LLM analyst loop with catalog tools (asset search, lineage walk, instance resolution, the new DQ + coverage verbs) that **emits a proposed workflow** through the Slice-2/5 approval machinery. This is option (a) made architecturally respectable by routing its output through enforcement — pragmatic *and* aligned.

**Longer — deterministic chaining matures underneath (ADR-0011).** Approved analyst-authored workflows **are discovered chains**. Ones that recur can be **promoted to registered multi-SPO paths with provenance**, so the deterministic layer grows from *evidence* rather than speculation — the same self-hardening loop as the phonebook's alias growth.

### Scope of this ADR

Per the framing above, this ADR scopes the Layer-2 work as **"catalog-analyst toolset + coverage verb + proposal-workflow integration"** — not a monolithic "catalog reasoning" component. The decomposition in this Decision *is* the outline; the BAML signatures, the exact tool contracts, and the goal-shape classifier live in follow-up slices, not here (same posture as ADR-0011/ADR-0029: decide the shape, defer the build to measured slices).

## Evaluation set (red before green)

ADR-0011's deferral was explicitly waiting for real queries that fail single-SPO routing because they are shaped as chains. These prompts are that signal, so they become **the evaluation set for the whole track** — captured with their *failure* outputs first, so we have the red before any green.

The red baseline is **already captured**: [`docs/reference/analyst-loop-red-baseline.md`](../reference/analyst-loop-red-baseline.md) (committed `1a782a3`, run live 2026-07-23) holds the three prompts and both failure cards, **generalized — no customer/host/URN tokens, same posture as this ADR**. That doc is the fixed red set; this ADR is the design measured against it. The genuinely *verbatim*, customer-specific originals never enter the repo (both artifacts generalized on the way in); if a future capture needs raw wording or screenshots, that belongs in a private/gitignored fixture linked from the baseline — not committed here.

Acceptance shape for the track (to refine against the captured red):
- **Immediate:** each goal-shaped prompt returns the honest goal-shape card (naming answerable sub-questions), never a wrong-subject card and never "couldn't determine asset." **Every offered sub-question routes successfully when asked verbatim** (the card is built against the capability graph, not imagination).
- **Mid-term:** the analyst loop emits a proposed workflow whose every step is a registered verb (enforcement rejects any hallucinated step), joins carry cited lineage, and gaps are surfaced as coverage findings; the plan pauses at a human-await step.
- **Longer:** a recurring approved workflow is promoted to a registered multi-SPO path with provenance.

## Consequences

- **The prompt's hardest-looking layer (plan/present/approve) is already shipped** — the work reduces to an explorer that writes plans + one new honest verb + a goal-shape abstain. Smaller than "build agentic planning."
- **No new execution-trust surface.** The LLM's authority is bounded to *authorship*; the capability graph remains the sole gate on what executes. Consistent with ADR-0009.
- **The deterministic layer grows from evidence, not prediction** (promotion of recurring approved workflows), avoiding the speculative-complexity trap ADR-0011 guarded against.
- **Cost of the immediate step is near-zero** and it is strictly honesty-improving, so it can ship independent of the rest.

## Non-goals

- Specifying BAML signatures for the analyst loop, the DQ verb, the coverage verb, or the goal-shape classifier. Premature — deferred to slices.
- Committing to a specific analyst-loop engine placement (extend Engine A as generalist vs. a dedicated analyst engine). Captured as an open question, not decided here.
- Embedding the verbatim stress-test prompts or their domain specifics in this repo (evaluation fixture is private/gitignored).

## Open questions

1. **Where does the analyst loop live** — Engine A (generalist, ADR-0008's fallback made competent) or a dedicated analyst engine with the catalog toolset? *Placement is not decided here, but the criteria are: the arc's placement precedent applies with more force (a loop is a bigger commitment than a provider route), so whichever placement is chosen pragmatically must ship with its **exit documented** (the named-smell + exit / placement-marker discipline, per the engine-o provider call), and the **toolset contracts must be placement-neutral** so relocating the loop stays cheap. Left unstated, this gets answered by default the day someone starts coding — exactly what an open-questions section exists to prevent.*
2. **Goal-shape detection** — heuristic (domain-count + planning-language + post-ladder no-subject) vs. a constrained LLM classifier. Measurement-driven, like ADR-0011's per-step synthesis choice.
3. **Coverage-verb output type** (ADR-0030) — is "catalog coverage / join-candidate" a first-class verb output type, and how does it render (a canvas card, ADR-0028)?
4. **Promotion policy** — what threshold of recurrence + provenance qualifies an approved analyst workflow for promotion to a registered multi-SPO path?
