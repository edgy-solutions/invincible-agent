---
status: Accepted (v1 forward-compat constraints) — deeper canvas DIRECTIONAL / deferred
date: 2026-07-09
deciders: Platform team
---

# ADR-0028 — The canvas as an answer-composition workspace (SPO eligibility made spatial; the Q&A→workflow bridge)

## Status

**Accepted** for a SMALL set of **v1 forward-compatibility constraints** (2026-07-09);
the deeper canvas is **DIRECTIONAL — reasoned, not decided.**

⚠️ **Read the settled-vs-directional ratio honestly.** Unlike ADR-0027 (whose
invariants were forced by already-built, sealed things), most of THIS ADR is a
*vision* over unbuilt ground: canvas v1 is minimal, v2 (aggregation) is
designed-not-built, and v3 (workflow-seeding) is coupled to ADR-0024's workflow
builder, which is itself unbuilt. So this ADR's **concrete, load-bearing output is
a few v1 constraints** (chiefly: v1 cards CARRY THEIR SPO PROVENANCE) that keep the
minimal build from precluding the deep one. The rest — Uses 2 and 3 — is captured
**directionally**, on record so the vision is coherent and v1 doesn't foreclose it,
but **explicitly marked designed-not-decided, with triggers**. Do not read the
answer→canvas→workflow arc as settled architecture; what is settled is "build v1 so
it doesn't preclude the arc." This is the follow-through on ADR-0023, which named
the canvas and deferred it.

## Context

ADR-0023 (AnswerArtifact as graph-native CQRS) made **answers the cornerstone** of
the dashboard — the left-bar history and the canvas both organize answers — and
**hinted at canvas arrangements without deciding them** (a deliberate
minimal-first deferral). This ADR reasons the canvas out *before* the minimal v1 is
built, so v1 carries what the deep version needs.

**The reframe (the load-bearing insight): the canvas is not a freeform whiteboard —
it is the SPO eligibility intersection made SPATIAL and interactive.** When a user
drags answers together, they are assembling a **subject-set** and asking "what can I
do with these together?" That question is NOT open-ended: composing a set is
**invoking a verb over the set**, and whether that's possible is governed by the
same machinery as routing — do the answers share a compatible subject-type, and is
there a verb whose **arity** accepts the set. The same eligibility intersection
([[feedback_verb_eligibility_intersection]]: domain ∩ arity ∩ argument-fit,
wrapped by permission) that decided "enumerateCatalog is set-arity, describeAsset is
single" decides "these dragged-together answers can be aggregated by verb X because
they are all subjects of a class X operates on, and X is set-arity." So the canvas's
"what can I do with these" is **computed, not hardcoded** — `find_compatible_verbs`
over the union subject-type of the selected cards, filtered to set-arity (and
permission — see Decision 3). Select-from-the-authorized-set
([[feedback_select_from_authorized_set]]) as a direct-manipulation UI.

**Three uses, which are a PROGRESSION on ONE primitive** ("a selected set of
answers with computed eligible operations"), at increasing richness:
- **Use 1 — arrange / relationship-layout** (spatial, related, like the decision
  map): the *identity* operation — just show the set, related. Presentation.
- **Use 2 — aggregate** (set → new answer via a set-arity verb): a *single verb*
  over the set. The SPO model as composition UI.
- **Use 3 — workflow-seed** (answers as step-templates / data-inputs for the
  ADR-0024 builder): a *sequence of verbs* seeded from the set. The strategic
  center.

**The product thesis this makes explicit:** the canvas is the **bridge from ad-hoc
Q&A to repeatable workflow.** You explore by asking (answers accumulate in the
left bar), you curate onto the canvas (arrange the useful ones), and you promote
the curated set into a workflow (each answer becomes a step-template or a
data-input). That arc — question → curated set → repeatable process — is what turns
the system from "a smart Q&A tool" into "a tool where you build repeatable
analytical workflows from your Q&A," a materially bigger product. Stating it here
keeps v1, the ADR-0024 builder, and the composition features visibly serving ONE
thesis rather than being disconnected features.

## Decision — the SETTLED constraints (small, firm; they guide the v1 build now)

1. **The canvas's core primitive is "a selected set of answers with COMPUTED
   ELIGIBLE OPERATIONS."** The canvas is not a freeform whiteboard; it is a place
   to assemble a subject-set and see the operations the system computes as eligible
   for it. Settled because it is FORCED by the SPO architecture (composition over a
   set = verb-eligibility over a union subject-type). This determines what v1 must
   carry (Decision 2).

2. **v1 cards CARRY THEIR SPO PROVENANCE — subject, verb, subject-type, and the
   TRACE — even though v1 does NOT compute over it.** THIS IS THE LOAD-BEARING
   FORWARD-COMPAT CONSTRAINT and the concrete reason to write this ADR before v1:
   Uses 2 and 3 compute eligibility over the cards' subject-type; if v1 renders
   cards as opaque blobs, that data must be re-derived later (or is lost), forcing
   re-work. The decision-path already CAPTURES this SPO identity per answer
   ([[project_resolution_discard_pattern]]'s inverse — carry the captured fact
   forward, don't re-derive it). Same capture-on-the-artifact-so-the-future-feature-
   can-use-it discipline as ADR-0025's Capture A. **v1 instruction: the card is not
   a thumbnail; it is an SPO-tagged answer object.**

3. **Canvas composition is ACCESS-GOVERNED by the SAME eligibility intersection
   (subject-type ∩ arity ∩ permission) — the canvas INHERITS enforcement, it does
   not add its own.** "What verbs can aggregate these answers" is
   `find_compatible_verbs` filtered by the FULL intersection, including the
   permission dimension ([[feedback_access_regulates_persona_domain]]): a verb the
   caller may not invoke is not offered, and the answers themselves are access-
   scoped (they are the user's). So the canvas's composition offerings are governed
   by the enforcement model BY CONSTRUCTION — do NOT build a separate canvas
   access-control. The uniform-model payoff again (routing, the HITL queue, and now
   the canvas are the same eligibility intersection).

4. **The answer SUMMARY is a captured fact** (the headline-at-answer-time), a v1
   prerequisite regardless of canvas depth — the card needs a stable, captured
   label, not a re-derived one. Capture-at-creation, per
   [[feedback_optimistic_defaults_are_dishonest]] / the Capture-A discipline.

## DIRECTIONAL — reasoned, NOT decided (deferred, with triggers)

Captured so the vision is coherent and v1 doesn't foreclose it — **NOT settled
architecture.** These need real usage / dependent builds; deciding their specifics
now is premature over-design.

- **Use 2 — aggregation (the natural v2).** The ARCHITECTURE is settled
  (eligibility over the union subject-type, set-arity filter, permission-filtered,
  offer-the-eligible-set); the *specific interaction* ("drag together → show the
  few eligible verbs → invoke → produce an aggregate answer") and the
  `find_compatible_verbs`-over-a-SET extension (compute compatible verbs for a set
  of subjects, not one) are DEFERRED. Honest failure-honesty: a heterogeneous set
  (no common subject-type, or no set-arity verb) yields "these can't be aggregated"
  — the system tells the truth about what's composable rather than forcing a
  nonsense combination. *Trigger:* v1 ships and usage shows people want to compose
  sets.
- **Use 3 — workflow-seeding (the strategic center, DIRECTIONAL).** Answers as
  step-templates or data-inputs for the ADR-0024 workflow builder: an answer is a
  *worked example of a step* (it carries the verb, the subject, the result, the
  TRACE), so dragging it into the builder = "make a step like this" (template) or
  "this result feeds the next step" (data-input). This is the Q&A→workflow bridge
  made real. **Explicitly COUPLED to ADR-0024** — you cannot seed workflow steps
  from answers until the builder exists to seed into; and it is a VISION, not a
  committed design. *Trigger:* ADR-0024's workflow builder reaching the point where
  steps can be seeded.
- **Use 1 — relationship-layout (a presentation feature, deferrable).** Arrange
  answers spatially by how they relate (mesh-graph proximity, rendered like the
  decision map — reuses that rendering), the canvas-as-VIEWER. Differentiating and
  cheap-ish (reuses built decision-map rendering) but NOT architecturally
  load-bearing. *Trigger:* whenever the visual layer is prioritized.

## Rollout / current state

- **Built:** nothing canvas-composition yet (ADR-0023's canvas is minimal).
- **v1 (the build this ADR guides):** the arrangement workspace — drag answers on,
  curate a spatial set, cards are the unit. **Constraint from this ADR: the cards
  CARRY SPO PROVENANCE + a captured summary** (Decisions 2 & 4) and the canvas
  inherits enforcement (Decision 3), so v2/v3 can compute over the cards without
  re-derivation. v1 does NOT compute eligibility yet — it just must not preclude it.
- **v2 (deferred, triggered):** aggregation — the eligibility computation over the
  union subject-type made interactive.
- **v3 (directional, ADR-0024-coupled):** workflow-seeding — the strategic
  destination.

## Consequences

- v1 built to this ADR carries the data (SPO provenance, summary) that v2/v3 need —
  no re-work to add composition later; the minimal build opens onto prepared ground.
- The canvas gets access-control for free (Decision 3) — a future builder does NOT
  add canvas ACLs; composition offerings are the enforcement-governed eligibility
  intersection.
- The product thesis is on record: the pieces (v1 canvas, ADR-0024 builder, the
  composition features) visibly serve ONE arc (Q&A → curated set → repeatable
  workflow), not disconnected features.
- HONEST caveat: "decided ground" here is mostly the v1 constraints. The deep canvas
  (v2/v3) is directional; do not build to it as if settled.

## Non-goals (this session)

Building the canvas (v1 or beyond), the aggregation interaction, the
`find_compatible_verbs`-over-a-set extension, or the workflow-seeding. This ADR
records the v1 forward-compat CONSTRAINTS and the DIRECTIONAL vision; the builds are
separate (v1 next; v2 triggered; v3 coupled to ADR-0024).

## Related

- **ADR-0023** — AnswerArtifact as graph-native CQRS; made answers the cornerstone
  and HINTED at the canvas + deferred it. This ADR is the follow-through.
- **ADR-0024** — standards composition + the workflow builder; **Use 3
  (workflow-seeding) couples to it** — the canvas promotes curated answer-sets into
  ADR-0024 workflow steps.
- **[[feedback_verb_eligibility_intersection]]** — the SPO eligibility intersection
  (domain ∩ arity ∩ argument-fit ∩ permission) the canvas's composition IS, made
  spatial. Use-2 aggregation is `find_compatible_verbs` over a union subject-type,
  set-arity + permission filtered.
- **[[feedback_select_from_authorized_set]]** — offer the computed-eligible verbs,
  never let the user/LLM author an arbitrary aggregation.
- **[[feedback_access_regulates_persona_domain]]** — the permission dimension the
  canvas inherits (Decision 3).
- **ADR-0025 / [[project_adr0026_topaz_authz]]** — the enforcement model the canvas
  composition inherits by construction.
