# Goal-shaped query RED baseline (ADR-0011 evaluation set · analyst-loop track)

The **red before the green.** ADR-0011 deferred multi-SPO explicitly *waiting for* "real user queries
that consistently fail single-SPO routing because they're shaped as chains." These three prompts,
run against the live system 2026-07-23, **are that signal** — the deferral's own trigger condition,
now met. Banked here as the fixed evaluation set the whole analyst-loop / multi-SPO track is measured
against. Design (the Layer-2 ADR) is authored separately; this file is the baseline, not the fix.

## The three prompts (goal-shaped, run live)

1. **Affordability risk (full stress test).** Explore the catalog for relevant tables across
   Engineering (PLM/BOMs), Supply Chain (procurement/supplier), Finance (cost accounting/EACs); map
   metadata; formulate a step-by-step strategy correlating ECO volume with actual-to-standard cost
   variances over 24 months; **before executing, present** (1) proposed BOM→cost-variance joins,
   (2) the definition/calculation of "affordability risk" from found metadata, (3) tables / lineage
   gaps / DQ issues blocking identification of single-sourced components with double-digit cost
   growth; **await approval** before generating the final query/report.
2. **Design-to-cost variant.** From historical program data, devise a method to identify which
   subsystem design characteristics (weight, material, software complexity) historically drove cost
   overruns vs initial design-to-cost targets; show the exact data lineage proving the correlation.
3. **Supply-chain variant.** Find all datasets relating to supplier performance and unit cost; map a
   workflow flagging components with both a 15%+ lead-time increase and a negative cost variance over
   the last year; if no direct key links vendor performance to unit cost, propose a fuzzy-match /
   intermediate-table bridge strategy.

## The two observed failures (both diagnostic, both predicted by ADR-0011)

- **(a) Mis-route — a supplier-data *privacy notice* returned.** The "supplier data" anchor matched a
  privacy/policy subject through *atomic* routing. This is the **silent-wrong-subject class** the
  graph/vocab work spent the week eliminating — it fires again here because a goal-shaped, multi-noun
  query is forced through single-subject resolution. Confidently wrong.
- **(b) Honest abstain — "I could not determine what asset your question is about."** Single-SPO
  subject resolution correctly hitting the honest-degradation floor: there is no *single* subject —
  it's a goal, not a question about a thing. Correct behavior, insufficient reach.

Both are exactly what ADR-0011 predicted for multi-noun/chained input ("decomposed into parallel →
worse results, or fall through to Engine A as generalist"). The red baseline's pass criterion is that
BOTH of these convert to the honest goal-shape card (below), and eventually to an authored plan.

## Why multi-SPO alone doesn't clear this red (three layers, not one)

| Layer | What the prompt needs | multi-SPO? | Status |
|---|---|---|---|
| 1 · planning/chaining | decompose a goal into step N→N+1 | yes | ADR-0011, deferred; the discovery-driven flavor is "not handled at all" |
| 2 · catalog reasoning + gap analysis | which tables across 3 domains, what joins, what's missing (lineage/DQ) vs the goal | **no** | **the net-new primitive** — see below |
| 3 · plan → present → await approval | "present your plan… await approval" | no | **already built** — ADR-0029 human-await (Slice 2–5) + ADR-0027 approval + ADR-0028 canvas |

So multi-SPO is necessary, not sufficient. Layer 3 is deployed. Layer 2 is the heart.

## What green looks like (staged — the target the red is measured against)

- **Immediately (days): stop the faceplant.** Detect goal-shape (multiple domains, planning language,
  no resolvable single subject after the ladder) → return an **honest card**: "this is a multi-step
  analytical goal; today I answer atomic catalog questions; here are the N sub-questions I *can*
  answer now." Same abstain discipline, applied at the goal level — converts (a) and (b) from
  embarrassment into credibility. Small change.
- **Mid-term (the real build): the analyst loop.** An explorer that takes the goal, uses real catalog
  tools (asset search = Engine D; lineage walk = D4, deterministic + honest outcomes; instance
  resolution = the ladder), and **authors a proposed workflow** — steps as SPOs against registered
  verbs, joins as claims with cited lineage, gaps as explicit honest-degradation findings. That
  proposal flows through **Slices 2–5**: enforcement validates every step against the capability graph
  (a hallucinated verb can't survive), the human-await step *is* the demanded "await approval," Slice-3
  observation covers watching it run. **LLM authors, deterministic layer disposes — the same trust
  shape as the phonebook candidate-generator and Slice-4 seeding.** The LLM never gains execution
  authority; it gains authorship, and authorship was already gated.
- **Longer:** approved analyst-authored workflows *are* discovered chains — recurring ones promote to
  registered multi-SPO paths with provenance, so the deterministic layer grows from **evidence**, not
  speculation. Same self-hardening shape as the phonebook alias-growth loop.

## The genuinely net-new piece (scopes the Layer-2 ADR)

Not a monolith. Against what exists (search ✓, lineage ✓, instance resolution ✓ hardening), net-new is:
- **DQ-metric retrieval as a verb.**
- **A *coverage assessment*** — "here's what the catalog *can't* answer about your goal" — honest
  degradation applied at the **catalog** level instead of the answer level. The system already says
  "examined 0 upstream" and "couldn't determine which asset"; teaching it "no key links vendor
  performance to unit cost; here are the two nearest join candidates" is that same honesty, more reach.

ADR sketch scope (other agent): **catalog-analyst toolset + coverage verb + proposal-workflow
integration** — NOT a monolithic "catalog reasoning capability." The decomposition above is its outline.
