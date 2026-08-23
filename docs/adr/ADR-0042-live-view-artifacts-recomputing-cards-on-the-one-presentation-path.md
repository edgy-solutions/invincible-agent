# ADR-0042 — Live view-artifacts: a recomputing card species, riding the one presentation path

**Status:** Proposed — decision recorded 2026-08-20, written **before** the build it governs. Every phase of the portfolio-review workshop tool binds to this document; it exists first precisely so the build has something real to bind to. See **Open questions** for what is deliberately left unsettled.
**Date:** 2026-08-20
**Deciders:** Platform team
**Related:**
  - [ADR-0017](ADR-0017-presentation-as-predicate.md) + its **2026-08-20 amendment** — capability registration is the transport, **the component is the home**. The registration payload is assembled from component contract exports, never hand-authored beside them. This ADR adds a card species; it does not add a registration mechanism.
  - [ADR-0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md) — the AnswerArtifact is **born complete**, carries `valid_as_of`, and generation-state is never an artifact property. This ADR's central tension is that a live view is *not* born complete, and §4 rules how that coexists without amending AnswerArtifact.
  - [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md) — the canvas v1 is the **arrangement** workspace; cards carry SPO provenance + a captured summary. This ADR supplies the card species v1 deliberately did not have, under v1's constraints.
  - [ADR-0030](ADR-0030-verb-output-is-a-fixed-type.md) — a verb's output type is fixed, and result-dependent output was REJECTED. This is what lets an intent declare an `output_uri` before it has rows. §2 depends on it entirely.
  - [ADR-0032](ADR-0032-goal-oriented-analytical-queries-catalog-analyst-loop.md) — the LLM authors, enforcement disposes. A typed intent catalog is a **restriction** of that shape, not a second analyst loop (§6).
  - [ADR-0031](ADR-0031-instance-resolution-ladder.md) — the LLM proposes candidates, the phone-book disposes. Entity resolution for slot-filling reuses this ladder rather than growing a second fuzzy matcher.
  - [`principles/select-from-authorized-set.md`](../principles/select-from-authorized-set.md) — the nominator proposes, the authorized set disposes. §2 is this principle applied to presentation.
  - [`principles/a-green-check-proves-only-its-scope.md`](../principles/a-green-check-proves-only-its-scope.md) — why §5's gate asserts provenance rather than "a card appeared."
  - [`plans/archetype-chosen-before-data.md`](../plans/archetype-chosen-before-data.md) — closed 2026-08-20. §2 exists so a new subsystem cannot re-open it.
  - [`plans/render-request-carries-no-frontend-id.md`](../plans/render-request-carries-no-frontend-id.md) — closed 2026-08-20 by `e947069`. The union-menu fallback it shipped is what makes §5's failure mode silent.

## Context

A planning workspace (the portfolio-review workshop tool) needs cards that answer
"what does the cost curve look like **now**" — where *now* changes as the room drags a
bar on a gantt. That is a card whose content is a function of mutable state, re-evaluated
on change.

Every card the canvas renders today is the opposite: an `AnswerArtifact` is **born
complete**. It captured its grounding at creation, stamped `valid_as_of`, and never
recomputes. ADR-0023 is emphatic that this is not incidental — generation-state is
"provenance-at-creation plus transient UI, not state the artifact carries."

So there is a real new species here, and the question this ADR answers is *what kind of
new thing it is*. The available answers are not equal:

| framing | cost | what it breaks |
|---|---|---|
| a new **artifact kind** (discriminated union on `Artifact`) | every consumer of `Artifact` in cortex-ui and every projection downstream | ADR-0023's single artifact shape; the Electric projection; `updateArtifact` provenance |
| a new **archetype** (a row in the render menu) | one contract export, one binding, one component | nothing |

The second is correct, and the reason is mechanical rather than aesthetic: **cortex-ui's
`Artifact` has no `kind` discriminator and never did.** Species are distinguished by
`rendered_output.components[].archetype`, dispatched in `SemanticInterpreter`, and
declared by a component contract. A task-artifact — already a second species with a
completely different lifecycle — rides that mechanism today without `Artifact` knowing
about tasks at all. A live view is the third species and rides the same rail.

### The drift this ADR is written to prevent

A planning workspace is naturally authored as a self-contained frontend: types in
`src/model/`, pure measure functions over an in-memory store, an intent catalog that maps
each question to a chart type. Every one of those choices is locally sensible and
collectively builds a **parallel presentation stack** beside the one that shipped between
2026-08-18 and 2026-08-20. Specifically:

- **Measures computed in the browser never cross `/render_ui`.** They are ungoverned (no
  verb, no output type, no entitlement), unregistered (invisible to every menu), and
  unvalidatable (no contract for the backend to check a payload against). Nothing built
  this month can see them.
- **An intent catalog that names a chart type chooses the archetype from the question**,
  before any rows exist. That is `archetype-chosen-before-data` — closed 2026-08-20, one
  day before the plan that would re-open it in a new subsystem.

Both are the same error at different altitudes: **a decision the platform already owns,
re-made locally by a component that has less information.**

## Decision

### 1. A live view is an ARCHETYPE, not an artifact kind. `AnswerArtifact` is untouched.

The live view species is declared exactly as every other renderable species is: a
component contract export, a mesh-vocabulary binding, an assembled registry row. No field
is added to `Artifact`. No discriminated union is introduced. No AnswerArtifact code path
is modified, and an AnswerArtifact is never rendered under live-view assumptions because
the two are different archetypes with different contracts.

**Rejected: a `PublishedArtifact`-style discriminator.** That node type is
[ADR-0024](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md)'s **proposed Neo4j
node**, not a frontend pattern, and it has never existed in cortex-ui. Citing it as
precedent for a UI discriminator was a phantom precedent, and this clause is recorded so
the next reader does not chase it.

### 2. The card declares WHAT it is, never HOW it renders. `select_presentation` disposes.

A live view card holds `{ output_uri, params }`. It does **not** hold a chart type, a view
name, or an archetype.

The archetype is resolved by `capability_registry.select_presentation(frontend_id,
output_uri, payload, persona, domain)` — filter candidates by `output_uri` (a **hint**),
keep only those whose registered contract the payload satisfies, rank by affinity. The
same path, the same provenance vocabulary, the same refusal reasons as every other answer
in the system.

This is [`select-from-authorized-set`](../principles/select-from-authorized-set.md) applied
to presentation: **the intent nominates a subject, the caller's registered menu disposes
the shape.** It is also the only formulation under which the same question renders
correctly on a second frontend that registered a different menu — which is the entire
point of the ADR-0017 amendment.

**Binding consequence for intent catalogs.** An intent's declared output is an
`output_uri`. An intent MAY NOT carry a `view:` field. If a catalog entry names a chart
type, that catalog has re-opened `archetype-chosen-before-data`.

### 3. The measure is a verb. It runs where verbs run.

A live view's `output_uri` must be a real declared output type of a real registered verb
([ADR-0030](ADR-0030-verb-output-is-a-fixed-type.md): fixed output per verb, result-dependent
output rejected). It follows that **the computation runs server-side, from the first
commit** — not because server-side is inherently better, but because a browser-computed
row set has no verb to be the output of, and therefore cannot have an `output_uri`, and
therefore cannot enter §2's path at all.

**What may be mocked, and what may not.** The store behind a measure is legitimately a
placeholder and is expected to move: in-memory seed → Postgres → the graph write-model.
The *placement* of the measure is not a placeholder. This is
[ADR-0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md)'s own lesson stated for
computation rather than types — **the contract is fixed and the source-of-truth path
swaps underneath it.** Fixing the types while letting the placement float gets the lesson
exactly half right, and the half that is wrong is the expensive one.

The rule, for any future build that reaches for a client-side computation:

> **Mock what sits behind an interface. Never mock the interface's location.**

### 4. Content is state-master; arrangement is UI-master; freshness is per evaluation.

- **Content** — the rows a live view draws — is owned by the evaluation. The card never
  caches rows as truth. Re-evaluation replaces them wholesale.
- **Arrangement** — position, size, pinned/unpinned, title — is owned by the UI and
  persists through [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md)'s canvas
  persistence. Arrangement is never recomputed and never travels in a payload.
- **Freshness** — each evaluation carries its **own** `valid_as_of`, stamped at
  evaluation, and the card displays it.

The freshness clause is load-bearing and is the one place a live view could quietly lie.
A born-complete artifact's `valid_as_of` is honest forever because its content is frozen
with it. A live view that minted at 09:00 and re-evaluated at 11:20 while still showing
`valid_as_of: 09:00` asserts that 11:20's numbers were true at 09:00. **A live view MUST
NOT inherit its mint-time `valid_as_of`.** This preserves ADR-0023's semantics rather than
weakening them: `valid_as_of` continues to mean "the time-point the substrate was sampled
at," and a live view simply samples more than once.

### 5. Provenance is asserted, not assumed. The gate reads `presentation_source`.

Any acceptance gate for a live view asserts `presentation_source == "registered"` — never
"a card rendered."

**Why this clause has to be explicit.** Before `e947069`, an unidentified caller collapsed
to `UNIVERSAL_ARCHETYPES` and every answer became a `KNOWLEDGE_DOCUMENT`. Loud, immediate,
impossible to miss. After `e947069`, an unidentified caller selects from `union_menu()` —
the derived union of all registered menus — and gets a **plausible archetype chosen from
someone else's menu**. The card draws. It usually looks right.

That is a same-observation-opposite-reasons inversion, and it happened *while this ADR was
being written*. The change is correct on its own terms (an anonymous caller has no menu to
contradict, so the union is the most that can truthfully be said about it) — but its cost
is that the failure it replaces was self-announcing and the failure it introduces is
silent. A gate that asserts on rendering cannot tell the two apart;
[`a-green-check-proves-only-its-scope`](../principles/a-green-check-proves-only-its-scope.md)
is the general form. The provenance field is right there in the envelope. Read it.

**Amendment 2026-08-21 — `presentation_source` alone is not enough. Read `selection_basis` too.**
Found by running the selector against a planning `output_uri`, not by reading it.

`select_presentation` treats `output_uri` as a HINT: when it matches no capability on the
caller's menu, the search **widens to the whole menu** rather than ending — *"a miss widens
the field rather than ending the search."* That is correct for its purpose. Its consequence
for a gate is not obvious and is severe:

```
output_uri = mesh:PeriodCostSeries        (a planning verb, no contract registered yet)
payload    = [{period, total}]            (one categorical column, one numeric)

ARCHETYPE CHOSEN     CHART_WIDGET
presentation_source  "registered"      <-- §5's assertion PASSES
selection_basis      "payload-only (output_uri matched no capability)"
```

The caller has a menu, a capability was selected from it, and the card draws — as a bar
chart, plausibly, wrongly. `presentation_source` is a fact about **whether a menu was
consulted**. It is not a fact about **whether this output type was found on it**.

So a live-view gate asserts BOTH:

```
presentation_source == "registered"
selection_basis     == "output_uri+payload"      # NOT "payload-only (…)"
```

The second is the discriminant between *my registered contract was found* and *something
else absorbed my payload*. Without it the gate is green while the archetype is wrong, which
is precisely the same-observation-opposite-reasons shape this ruling already exists to
close — arriving one layer deeper, through the field the ruling told the reader to trust.

Recorded with its own irony intact: this section ends *"the provenance field is right there
in the envelope. Read it."* Reading ONE of the provenance fields was not enough.
[`a-green-check-proves-only-its-scope`](../principles/a-green-check-proves-only-its-scope.md)
applied to the check this ADR itself prescribed.

**Corollary for Phase 1's build order.** Until a planning renderer's `.contract.ts` is
registered, planning payloads do not refuse — they are ABSORBED by whichever existing
archetype their shape happens to satisfy. So the contracts are not a tidying step that can
follow the widgets; they are what makes the widgets addressable at all, and a planning card
that "already renders" before its contract exists is evidence of the absorption, not of
progress.

### 6. The renderer's contract is its home, and its refusal vocabulary is published.

Per the ADR-0017 amendment, every live-view renderer exports its contract beside itself —
archetype, component, layout, typed field map, row requirements, refusal reasons — and the
registration payload is **assembled** from that export. A hand-authored registry row is
the two-masters defect wearing a registrar's blessing, and `assembleCapabilities()` drops
it on contact.

The clause that matters most for a *live* view is the **refusal vocabulary**. "This
project has no funding rows recorded" is not a UI empty state to be styled; it is a
registered refusal reason that `select_presentation` reads when deciding whether this
archetype can draw this payload. Publishing it converts honest-empty from a rendering
convention (enforced by discipline, invisible to the backend) into a contract clause
(enforced mechanically, and the reason the picker chooses a different archetype instead of
drawing an empty box).

### 7. Archetype names are structural. Domain vocabulary rides the payload.

The GENERIC-AT-BIRTH rule reaches archetypes with full force, because the archetype string
is what registers, what the backend validates against, and what appears in every caller's
menu. A domain word in an archetype name puts that word in the mesh vocabulary permanently.

- **Structural, required:** `INTERVAL_TIMELINE`, `PERIOD_SERIES`, `THRESHOLD_GRID`,
  `MATRIX_GRID`, `DELTA_SET`, `DECISION_RECORD`.
- **Refused:** `SITE_LOAD`, `COST_CURVE`, `MATURITY_GRID`, `GANTT`.

A precision worth recording, because the rule is easy to over-apply: `subject_uri` **may**
be domain-flavored — `mesh:PartObsolescenceReviewBatch` is a registered subject today.
That is backend mesh vocabulary, and naming a thing in the ontology is the ontology's job.
The prohibition is on the **archetype, the component, and any UI branch**. The precedent
to copy is `INSTANCES_BY_PROPERTY`, whose registration comment states the test exactly:
*"domain-agnostic by construction — the payload carries columns/rows/vocabulary; the
renderer knows no domain."*

### 8. A typed intent catalog is a RESTRICTION of ADR-0032, not a second loop.

[ADR-0032](ADR-0032-goal-oriented-analytical-queries-catalog-analyst-loop.md) rules that
the LLM authors and enforcement disposes. A catalog of typed intents with slot-filling is
the same shape with the authoring step frozen to a fixed set — a deliberate narrowing for
verifiability, not a different mechanism.

Recording it as a restriction has one concrete consequence: when the catalog later widens
to authored query plans, that is ADR-0032's build arriving, validated by ADR-0032's banked
evaluation set, against the same registered verbs. It is not a second analyst loop growing
beside the first. Any catalog that cannot be described as "ADR-0032 with the authoring step
pinned" has drifted.

Entity resolution for slot-filling reuses
[ADR-0031](ADR-0031-instance-resolution-ladder.md)'s ladder — exact, containment,
LLM-candidate, abstain — rather than growing a second fuzzy matcher with its own failure
modes.

### 9. A live view refuses anonymous rendering. The refusal is the selector's, not the component's.

*Added 2026-08-20, after the eight rulings above were drafted. It resolves what this ADR
originally filed as open question 3; the question is left recorded below as answered rather
than deleted, so the reasoning that produced the ruling stays visible.*

**Live-view archetypes never enter the anonymous union.** An unidentified caller requesting
one gets a labelled refusal carrying the reason `live_view_requires_registration`. The
static, one-shot rendering of the same data remains available to that caller — this is
honest degradation, not a denial.

**Why a live view is different in kind from a one-shot answer.** A one-shot answer delivered
anonymously is a complete artifact whose rendering is a *courtesy*: `union_menu()` is the
honest best-effort, and if the shape lands imperfectly the payload is still intact and true.
A live view is a **standing contract** — a subscription that recomputes against moving state
and re-renders over time. Honouring it for a caller the backend cannot name means maintaining
an ongoing obligation to an unknown identity against a menu that is a guess. When that
caller's actual capabilities diverge from the union, the one-shot's failure is **bounded** —
it happens once, to one payload — while the live view's **compounds**, repeating silently for
as long as the subscription lives. Bounded-versus-compounding is the whole of the distinction,
and it is why the same union that is honest for an answer is dishonest for a subscription.

**Where the refusal is emitted — and why not in the contract.** This refusal fires at
**menu-scoping time, inside `select_presentation`, before any payload is evaluated.** It is
therefore NOT a member of the renderer's `refusalReasons` list under §6, and an implementer
who follows §6 literally will put it there and be wrong.

The reason is mechanical. §6's refusal vocabulary is the set of reasons *the component can
return* when a payload fails its contract; the published list is what lets the backend
distinguish "this payload missed requirement X" from a generic failure. A component never
refuses `live_view_requires_registration` — it is never reached, because the selector
declined before the payload was looked at. Publishing it in the contract would put an
**unemittable reason** on the wire, and the backend would wait on a discriminant that never
arrives. That exact defect is already on record one archetype over: `ChartWidget.contract.ts`
deliberately withholds `"no series values in scatter data"` because the branch is unreachable
by construction, and the seed test caught it on its first run.

So the refusal joins the **`presentation_source` vocabulary as a fourth state** —
`registered` · `default-menu` · `unrenderable` · **`refused`** (first drafted as
`refused-anonymous-live`; see the amendment below for why the cause moved out of the name) —
alongside the three that `capability_registry` already names. It is a fact about the caller meeting the
menu, exactly as `unrenderable` is a fact about the menu meeting the data, and it is labelled
for the same reason the other three are: an unlabelled refusal is indistinguishable from a
decision.

**Amendment 2026-08-21 — the state is categorical, and the selector needs something to fire on.**
Two corrections to the paragraph above, both from review, both worth recording rather than
silently absorbing.

*The fourth state is `refused`, not `refused-anonymous-live`.* The three existing states are
cause-agnostic **categories** that carry their specifics in adjacent fields — `unrenderable`
carries a structured `refusals` list naming which requirement each candidate missed;
`default-menu` carries `presentation_menu`. A state named after one cause would be the only
one that is, and it invites a fifth state the next time a selector-level refusal class appears.
The vocabulary stays categorical and the reasons stay extensible:

```
presentation_source: "refused"
refusal_code:        "live_view_requires_registration"   # machine discriminant
reason:              "live views require a registered caller; …"   # prose, as every state carries
```

`refusal_code` rather than `refusal_reason` deliberately: `refusals` (plural) already exists in
this vocabulary meaning *per-candidate contract misses*. The two never co-populate — `refused`
fires before candidate evaluation, so there is no per-candidate list — but a singular
`refusal_reason` beside a plural `refusals` makes a reader work out which is which, and this
project has paid twice for exactly that blur.

`refused` and `unrenderable` are genuinely different diagnostics and must not collapse:
**`unrenderable`** = the selector nominated and nothing fit — *your menu and this payload
disagree* (fix: register the archetype, or fix the payload). **`refused`** = the selector
declined to nominate at all — *policy stopped it before evaluation* (fix: identify yourself).
Different first question, different operator action.

*The selector needs a discriminant, and it is a contract FIELD — not a refusal reason.* Nothing
in `select_presentation(frontend_id, output_uri, payload, persona, domain)` says an archetype
recomputes, so as first drafted this ruling had nothing to fire on. The contract declares it:

```
LIVE_VIEW_CONTRACT = { archetype: …, component: …, layout: …, recomputes: true, fields: {…} }
```

This needs **no shape change anywhere**: `assembleDerivedCapabilities()` already places the whole
`contract` object on the assembled row, and `capability_registry._satisfies()` already reads
`cap.get("contract")`. The selector has it in hand; it simply had nothing to look for.

Note the ownership split this preserves, which is the same one §2 and §6 draw everywhere else:
the component declares **that it recomputes** (a fact about the component — §6's home, and a
contract field like `layout`, never a refusal reason); the selector decides **what to do about
an anonymous caller asking for one** (a fact about policy — §2's disposal). Putting `recomputes`
in the contract does not re-open the trap this ruling just closed, because it is not a reason
the component emits.

*Scope note owed to the union check.* `ChartWidget.contract.test.ts`'s
*"every refusal reason the contract publishes is one the component can emit"* asserts over
**component-emittable** reasons. Selector-level refusal codes are outside its subject population
and must not be added to it — a well-meaning extension covering `refusal_code` would re-create
the actor blur from the opposite side. That scope statement belongs in the check itself, per
[`a-green-check-proves-only-its-scope`](../principles/a-green-check-proves-only-its-scope.md).

**Consequence for the demo, and it is not incidental.** Every planning card is
registered-caller by construction, so §5's `presentation_source == "registered"` assertion
holds everywhere in the workshop tool without exception — the gate has no anonymous case to
carve out.

## Rollout / current state

- **Built (2026-08-21):** Ruling 3 — Engine P's ten verbs, each with a declared fixed
  `output_uri`, running server-side over an in-memory seed store. Ruling 6/7 — two component
  contracts (`PERIOD_SERIES`, `THRESHOLD_GRID`), structural names, union-checked refusal
  vocabularies, assembled into the registration payload. Ruling 9 — **both halves**: the
  contracts declare `recomputes: true`, and `select_presentation` now emits
  `presentation_source: "refused"` + `refusal_code: "live_view_requires_registration"`,
  with live views excluded from `union_menu()` so the `output_uri`-miss widening cannot
  become a back door.
- **Ruled, not yet built:** Ruling 4's per-evaluation `valid_as_of` is rendered by the two
  components but nothing yet stamps it server-side — the engine returns `state_version`, and
  the sample-time stamp is owed. Ruling 8's intent catalog is Phase 2.
- **Blocked on infrastructure, not on this ADR:** none of the above is observable in the
  cluster while [`capability-registry-not-graph-backed`](../plans/capability-registry-not-graph-backed.md)
  is open — registration and selection run in different pods over a module-local dict, so no
  menu reaches the picker and every caller is anonymous from the selector's view. The rulings
  hold locally against the real selector; the deployed topology cannot yet exercise them.
- **Inert until primed:** the twelve planning classes are declared in
  `setup/ontologies/mesh_system.ttl` and become `:OntologyClass` nodes on the next ontology
  ingest. Until that runs, a planning registration still fails Contract D — correctly.

## Consequences

- The canvas gains a third card species at the cost of one contract export per renderer.
  `Artifact` is unchanged, the Electric projection is unchanged, `updateArtifact`'s
  provenance map is unchanged.
- A live view renders correctly on any frontend that registered a menu satisfying its
  payload, and refuses honestly on one that did not — for free, because it never asked for
  a shape.
- The measures are governed from day one: entitlement-scoped, verb-registered,
  contract-validated. A planning question and a document question are two groundings behind
  one presentation path, which is the demonstrable form of the platform thesis.
- **Cost, stated honestly:** measures cannot be prototyped in the browser. The first useful
  card requires a verb, an output type, a registration, and a contract. That is slower on
  day one than an in-memory `measures.ts`, and it is the whole of what makes day sixty
  cheap.
- A future second frontend (OpenDDIL, a mobile surface) inherits live views without
  negotiation, because the negotiation is `select_presentation` and it already happened.

## Non-goals

- **Not** a live-*data* mechanism. This ADR governs cards that recompute against state the
  user is editing in-session. Streaming substrate change into a card (Electric shapes over
  planning tables) is a later, separate question and this ADR neither decides nor forecloses it.
- **Not** a canvas v2. ADR-0028's aggregation and workflow-seeding remain directional. A
  live view is a card species, not a composition feature.
- **Not** an amendment to AnswerArtifact semantics. §1 is precisely the clause that avoids one.

## Open questions

1. **Evaluation trigger.** ~~Whether re-evaluation is push (the state store notifies) or pull
   (the card re-requests on a state version bump) is a build-time choice, not decided here.~~
   **ANSWERED 2026-08-21: EVENT-DRIVEN, OVER THE SUBSTRATE THAT ALREADY EXISTS.** Left
   recorded rather than deleted, because the answer's value is that it required NO NEW
   MACHINERY, and a reader who sees only the conclusion cannot tell that was in doubt.

   **The decision routes identically to a one-shot.** A live card is chosen the same way: the
   caller's `frontend_id` scopes the menu, payload-and-output-type nominate,
   `select_presentation` disposes — with Ruling 9's one addition that a live archetype
   requires a REGISTERED caller (no anonymous union). **The decision is one-shot in both
   cases; what differs is what gets DELIVERED.** A one-shot delivers rows; a live card
   delivers a STANDING INSTRUCTION — per §2 its content is `{output_uri, params}`, so the
   artifact says *"I am a PERIOD_SERIES over portfolio_rollup(params)"* rather than *"here are
   the numbers as of minting."*

   **The refresh routes over the pipe that already hydrates every artifact.** No WebSocket, no
   backend-pushes-to-UI path: the measure verb's output lands in the projection store like
   every other governed write, ElectricSQL streams the shape diff, and the card's subscription
   re-renders. **The backend never addresses the UI; the UI holds a subscription and the
   substrate publishes into it** — the reached-by-replying model extended in time, with the
   reply channel simply staying open. (See the row-shape ruling in
   [[capability-registry-not-graph-backed]] for why a renderer has no address to be called at.)

   **WHO recomputes is the one genuinely open lever, and the demo takes the cheap answer:**
   recomputation fires when the INPUTS change — a scenario op lands, a commit applies —
   because those are governed writes already flowing through the pipeline. Write applies ->
   measure re-evaluates server-side (§3) -> projection row updates -> Electric streams ->
   every subscribed card redraws. **Event-driven by construction, no scheduler.** The cadence
   variant ("re-evaluate every N seconds against drifting external data") is the OpenDDIL
   `emit_interval_seconds` pattern and exists as prior art if a card ever needs it — nothing
   in the portfolio demo does, because planning state changes when someone changes it.

   Three inherited rules answer the follow-ons before they are asked:
   * **Coalescing.** Electric delivers LATEST-STATE, which is exactly right for a rollup card
     — you want current truth, not every intermediate. A trend-history card would need the
     append-only split, and §6/§7 name which archetype gets which.
   * **Rate ceiling.** Human-speed planning ops sit deep inside the comfortable zone. Nobody
     builds throttling for a problem the physics does not pose.
   * **Validity.** §4's stamp-per-evaluation means each redraw carries a fresh `valid_as_of`,
     and a broken subscription renders as the LABELLED STALE state — never a silently old
     chart.

   The constraint that bound either choice still binds this one: whatever fires the evaluation
   must stamp the resulting `valid_as_of`.
2. **Where the diff lives.** ~~A diff between two states is structurally a `DELTA_SET` payload
   over two evaluations. Whether it is computed by a verb taking two state refs, or by the
   caller running one verb twice, is open~~ — but the `DELTA_SET` archetype and its contract
   are settled by §6/§7 either way.

   **ANSWERED 2026-08-21 by `abf16fd`: ONE VERB OVER TWO STATE REFS.** Disposed together with
   OQ1 by the server-owns-plan-state ruling, because both presuppose an answer to *where
   mutable plan state lives*. Once scenarios are server-addressable, the state-ref form is
   available, and `plan_diff(state_ref_a, state_ref_b)` is **one governed evaluation with one
   provenance stamp**.

   **Run-twice-and-subtract puts the subtraction OUTSIDE the verb**, where nothing governs it
   and nothing stamps it — the client-side-measures defect in miniature, on the one card whose
   entire job is to say what changed. That is the reason, and it is the same reason §3 gives
   for measures being verbs at all.

   Recorded here 2026-08-22. **The ruling was three days old and this section still said
   "open"** — the plan carried it (§Phase 0.5) and asked for this amendment in the same
   breath; the amendment was not made, so a reader arriving at the ADR would have re-litigated
   a settled question. Cheap to fix, and worth noting that "is it decided?" is answered by
   grepping the tree, not by reading the document that asks.
3. **Anonymous live views.** ~~Whether a live view should **refuse** to render anonymously —
   its recomputation contract being stronger than a one-shot answer's — is a real question this
   ADR does not settle.~~ **ANSWERED 2026-08-20 by Ruling 9: it refuses.** Left recorded rather
   than deleted, because the question is what makes Ruling 9's bounded-versus-compounding
   reasoning legible — a reader who sees only the ruling cannot tell it was contested.
