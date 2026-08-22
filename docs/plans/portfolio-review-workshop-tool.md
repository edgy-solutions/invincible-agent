---
id:         portfolio-review-workshop-tool
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/presentation_agent/capability_registry.py, src/iagent/gateway.py
repo:       invincible-agent
summary:    Live portfolio-review workshop tool — a T+7 demo whose real job is to demonstrate the presentation-SPO arc on a second grounding. REVISION 2 (2026-08-20): rev 1 was authored against the architecture as it stood a week earlier and the presentation-SPO arc landed seven commits underneath it; as written it would have rebuilt a parallel presentation stack (client-side measures never crossing /render_ui, an intent catalog naming chart types = `archetype-chosen-before-data` re-opened one day after it closed). Ruled by ADR-0042. Binding changes: measures are VERBS running server-side from commit 1 (mock the store, never the placement); intents declare `output_uri` never a view; every widget ships a `.contract.ts`; Gate 1 asserts `presentation_source == "registered"`, not "a card appeared"; two-repo cycle (BFF routes are in-scope, a second Fastify/tRPC backend is deleted); D6 VERIFIED 2026-08-20 against the live endpoint (/api/tags): `gpt-oss-120b` is ABSENT (the documented 404), sandbox is configured for `gpt-oss-128k:120b` (131072 context) NOT plain `gpt-oss:120b`, and the declared hardware fallback `gpt-oss:20b` IS NOT PRESENT — pull it or delete the escape hatch.
---

# Live portfolio-review workshop tool — phased build (revision 2)

**Revision 3 (2026-08-21) is a DELTA, not a rewrite:**
[`portfolio-review-rev3-delta.md`](portfolio-review-rev3-delta.md). It records what the
requirements packet ADDS to what is built; section A of that packet is already landed and cited
here. Where the delta and the repo disagree, the repo is right.

**Ruled by:** [ADR-0042](../adr/ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md).
Read it before Phase 0. Where this plan and that ADR disagree, the ADR wins and this plan is wrong.

**Repos:** TWO, unavoidably — `invincible-agent` (verbs, measures, BFF routes, eval suite) and
`cortex-ui` (renderers, contracts, canvas). Rev 1's "repo target: cortex-ui" was false for its
own Phase 2 and Phase 4.

**Consumed by:** build agent. Phases are gated; each gate is binding. Do not start a phase before
the prior gate passes.

**Demo:** T+7. Phases 0–6 are the demo path. Phase 7+ is planned now so 0–6 forecloses nothing.

---

## 0. Intent

The target is not "a better gantt chart." It is **the efficiency of the portfolio review
meeting**, operationalized as a loop:

> **tension → question → view → proposal (scenario) → consequences (diff) → decision + reason**

Four binding inversions:

1. **INV-1 Question conjures the view.** Answers are projections of the model with a one-line
   narration. Each answered question mints a card on the canvas; the canvas is the meeting's
   visual record.
2. **INV-2 Manipulate the outcome, not just inputs.** Forward simulation (drag → recompute) and
   goal-seek (pin an outcome, system proposes moves). Goal-seek v0 is one goal type: budget cap.
3. **INV-3 The answer to "what if" is a diff, not a state.** Changes happen in forked scenarios;
   every change produces a diff naming what improved/degraded, in leader language.
4. **INV-4 The meeting leaves a memory.** A committed change carries its question trail,
   alternatives, and stated rationale as a decision artifact.

**Grounding contract (binding, all phases).** The LLM never computes or asserts a number.
NL question → intent match + slot fill against a typed intent catalog → validate → **execute a
registered verb** → render whatever `select_presentation` chooses from the result → LLM narrates
ONLY the result rows. Every numeric token in narration must appear in the result set; this is
machine-checked server-side. Ambiguity surfaces as an interpretation card, never a silent guess.
Out-of-model questions get the honest-refusal path and the miss is logged.

### 0.1 Why this demo is worth building at all

A portfolio review is *one workspace, many groundable domains* — the platform thesis made
visible. The doc-finding pipeline and the plan-model pipeline are siblings behind one BFF and one
presentation path. That argument only lands if the planning side rides the rails that shipped
this week. **A parallel stack would demonstrate the opposite of the thing being demonstrated.**

---

## 0b. Backend scope map

**Tier 1 — `invincible-agent`: IN SCOPE, unavoidably.**
- Planning verbs + their fixed output types (ADR-0030), with an in-memory seed store behind them.
- BFF routes: measure execution, plan-state/scenario/decision persistence, seed loading.
- LLM proxy for intent routing + narration, with the number-check enforced server-side.
- The eval suite (Python, this repo — the routing it tests executes here).
- **There is NO separate Fastify/tRPC backend.** Rev 1 carried that idea in two places after
  deleting it in a third. It is deleted. Persistence lands in `src/iagent/gateway.py`, which
  already owns `/me/canvases`, `/reviews`, `/instances_by_property`.

**Tier 2 — the iagent answer pipeline (routing/retrieval/doc-grounding): deliberately NOT in the
planning question path.** Planning questions compile to deterministic measures over structured
state; routing them through doc-retrieval would add latency and failure modes while making
answers less verifiable. Optional Phase-6 script beat (non-blocking): one doc-finding question
asked mid-review through the same chat rail, answered by the existing pipeline.

**Tier 3 — substrate (Neo4j write-model, projector, Restate, graph plan entities): Phase 8.**
Nothing in 0–6 may foreclose it.

**Electric.** Already the canvas read path. The constraint is "no NEW shapes this cycle," not
"no Electric" — rev 1's anti-goal was unsatisfiable in the target repo.

---

## 1. Anti-goals (Phases 0–6). Violating these is a plan violation.

- **No client-side measure computation.** A browser-computed row set has no verb, therefore no
  `output_uri`, therefore cannot enter `/render_ui`. ADR-0042 §3.
- **No intent that names a view.** Intents declare `output_uri`. `select_presentation` disposes
  the archetype. An intent carrying `view: 'gantt'` has re-opened `archetype-chosen-before-data`.
  ADR-0042 §2.
- **No hand-authored capability registry rows.** Every renderer exports its contract;
  `assembleCapabilities()` derives the row. A hand-authored row is dropped on contact.
- **No domain-named archetypes, components, or UI branches.** `PERIOD_SERIES`, not `COST_CURVE`.
  `subject_uri` may be domain-flavored; the archetype may not. ADR-0042 §7.
- **No new Neo4j / projector / Restate / Redpanda work,** and no new Electric shapes.
- **No free-form NL→query synthesis.** Slot-filling into typed intents only; free-form is Phase 7
  and is ADR-0032's build arriving, not a second analyst loop.
- **No hand-rolled gantt rendering.** OSS timeline component, timeboxed spike.
- **No silent interpretation.** Every answered question shows its interpretation card.
- **No invented measures.** Soft language maps to a registered measure or refuses.
- **No editing baseline directly from a drag.** All manipulation is inside a scenario fork.
  (Exception: cost/funding entry with no active scenario may write baseline, and still produces a
  change record.)
- **No ontology plumbing.** The type shapes must be alignment-correct; the ADR is Phase 7.
- **No destabilizing the grounding workspace.** Flag-off behavior is a Gate 1 check.
- **No mutating AnswerArtifact semantics.** ADR-0042 §1 is the clause that avoids one.

---

## 2. Phase 0 — Contracts, verbs, seed (Day 1 morning)

**Goal:** freeze the type contracts, the verb signatures, and the demo dataset. Per ADR-0023 and
ADR-0042 §3: the contract is fixed; the source-of-truth path swaps underneath it.

### 2.1 Domain types — the ONE canonical definition

Unchanged from rev 1 and still correct. Every field carries a why-comment so a future pass cannot
strip it as incidental. Summarized; see rev 1 for the full listing, which is adopted verbatim:

`Portfolio` · `Initiative` (status is an enum) · `Phase` (planned: Interval — without it no
timeline is drawable) · `Project` · `BusinessProcess` (plateaus) · `Capability` ·
`CapabilityContribution` (project-level; initiative→capability is DERIVED, never asserted in
parallel) · `Site` (saturation_threshold — the metric must be defined, not implied) · `SiteImpact`
(the edge carries an Interval) · `Technology` + two edges · `Dependency` (**two ends** +
Allen-flavored type + lag) · `Organization` (a funder is an entity, never a string) ·
`FundingRequirement` / `FundingCommitment` (demand and supply split so multi-funder gaps stay
unambiguous) · `MaturityAssessment` (**append-only**; current level = latest).

Temporal things are `Interval`s, never bare dates.

**Where the types live is now a consequence, not a choice.** The measures are verbs (§2.3), so the
canonical types live server-side in `invincible-agent`. cortex-ui receives payloads shaped by the
contracts, and each renderer's `.contract.ts` states what it needs. The types are not duplicated
into the frontend.

### 2.2 Scenario / diff / decision types

`PlanOp` (move_project, set_cost, set_commitment, move_site_impact) · `Scenario` ·
`Effect` (metric, direction, magnitude, affected — computed, never generated) · `Diff` ·
`QATrace` · `DecisionArtifact` (question trail, alternatives, **required** rationale, decided_by,
committed ops). Adopted verbatim from rev 1.

### 2.3 The measure registry is a VERB registry — CHANGED

Each measure is a registered verb with a **fixed output type** (ADR-0030) and a declared
`output_uri`. It runs server-side from the first commit. Behind it is an in-memory seed store that
will become Postgres (Phase 4) and then the graph (Phase 8) — **that store is the placeholder; the
placement is not.**

| verb | output_uri | answers | definition (binding) |
|---|---|---|---|
| `planCostCurve` | `mesh:PeriodCostSeries` | Q12, Q16, Q17 | per-period sum of FundingRequirement by kind, scoped, vs optional cap |
| `planFundingGap` | `mesh:FundingGapSet` | Q13–Q15 | per group: required − committed, split by kind |
| `planSiteLoad` | `mesh:LoadThresholdGrid` | Q9, Q11 | per site per period: Σ load_weight of overlapping SiteImpacts; flag over threshold |
| `planDependencyViolations` | `mesh:ConstraintViolationSet` | Q10 | successors violating dep_type + lag |
| `planMaturityGrid` | `mesh:MaturityMatrix` | Q3 | capability × site, latest-assessment level vs target, as-of param |
| `planCapabilityPath` | `mesh:ContributionSequence` | Q7 | contributing projects by weight, ordered by planned.end |
| `planProcessEvolution` | `mesh:PlateauTimeline` | Q1, Q2 | plateaus + enabling capabilities and their trajectory |
| `planTechFootprint` | `mesh:FootprintSet` | Q8 | capabilities enabled + projects participated, with windows |
| `planSchedule` | `mesh:IntervalSchedule` | Q4–Q6 | initiative→phase→project rows with intervals |
| `planSessionChanges` | `mesh:ChangeLog` | INV-4 | ops + diffs accumulated this session |

Note what the `output_uri` column is and is not: it names **what kind of answer this is**, never
how it draws. `mesh:PeriodCostSeries` may render as `PERIOD_SERIES` today and as something better
tomorrow, on a frontend that registers it, with no change here.

The soft-language mapping table ("overloaded" → the site-load verb over threshold; "blocked" →
dependency violations) lives with the catalog config, not in a component and not in a prompt.

### 2.4 Seed dataset

Realistic scale, internally consistent, engineered so **the demo moments exist in the data**:
1 portfolio, 3 initiatives, 4 phases each, 12–15 projects, 4 sites, 8 capabilities, 2 processes ×
3 plateaus, 5 technologies, 3 funding orgs.

Seeded tensions: (a) FY26-Q3 cost exceeds the cap; (b) an FS dependency a natural "drag left"
would violate; (c) Site B over threshold in Q4 from 3 overlapping impacts; (d) an org whose
commitments leave a visible gap; (e) a capability path missing its process plateau date.
Assessment history: 2–3 per capability×site cell so "as-of" is demonstrable.

### 2.5 Gate 0

- [ ] Types compile; every field carries its why-comment.
- [ ] All 10 verbs implemented, registered, with a declared output type, and **unit-tested against
      seed data** — each test asserts its SEEDED TENSION is detected.
- [ ] Seed loads; consistency check passes (every FK resolves; every project has ≥1
      FundingRequirement; intervals well-formed).
- [ ] The 17 leadership questions → verb map is written, with any unanswerable question **flagged,
      not fudged**.
- [ ] Every verb is callable through the BFF and returns rows. No measure executes in a browser.

---

## 2b. Phase 0.5 — Integration survey (Day 1 afternoon; timebox 3h; GATE)

ADR-0042 already answers what rev 1 sent the survey to discover, so the survey's job shrinks to
**sizing named build work**, not establishing feasibility. Rev 1's three questions had the
answers "no such ADR exists," "no such discriminator exists," and "neither routing nor flags
exist" — a survey pointed at phantoms.

What the survey actually sizes:

1. **The mount.** cortex-ui has **no router** (no react-router; `App.tsx` has zero routes) and
   **no feature-flag mechanism** (`config.ts` is a closed 5-key deployment interface). Mode
   switching is `InterviewPhase = "active" | "blueprint" | "compiling" | "complete"` in
   `useInterviewStore`, branched in `SessionSurface`. Size: a fifth phase value + a sixth config
   key. Small, but it is a build, not a reuse — rev 1 budgeted it at zero.
2. **The live-view render seam.** ADR-0042 §4 settles the contract (content state-master,
   arrangement UI-master, per-evaluation `valid_as_of`) and leaves the **trigger** open
   (ADR-0042 open question 1). Decide push vs pull here and record it. Interactive canvas cards
   are precedented — `ApprovalTaskCard` holds local state, calls the server, and mutates the store
   from inside the canvas render path.
3. **The Electric reconciliation collision.** `useCanvasStore` carries an `ELECTRIC_COVERED_FIELDS`
   provenance map and `updateArtifact(id, patch, source)` requires a source tag;
   `electricUpsertArtifact` is a live clobber path for locally-minted cards. This is the one
   genuine unknown and it is what the fork below exists for.

**Review-machinery map (30 min, read-only, and it is a reference not a hunt).** The portfolio
review is structurally a PCN/PDN review: notice → card of affected things → per-item disposition
with reason → approval, audit-trailed. The machinery is `gateway.py`'s `/reviews`,
`/reviews/{workflow_id}/batch`, `/human_tasks/{task_id}/act`, `src/iagent/human_tasks.py`,
`GroupedReviewTable` + its contract, under [ADR-0027](../adr/ADR-0027-composable-approval-policy.md)
and [ADR-0029](../adr/ADR-0029-process-workflow-model-spo-steps-restate.md). Note the seam by which
Phase 3's commit ceremony is its **degenerate single-approver case**. No integration this cycle;
the map exists so Phase 3 shapes commit to upgrade without restructuring.

### The fork — NARROWED

- **Fork I — INTEGRATE.** Planning cards live in the real canvas and artifact store. Default.
- **Fork E — EMBED (narrowed).** Own **canvas instance**; **same artifact store, same registration,
  same contracts.** Defers layout only.
  Rev 1's Fork E kept its own artifact list with convergence as a named Phase 7 task — that is
  throwaway by construction and it re-creates the parallel-stack problem this revision exists to
  prevent. The escape hatch survives; what it may defer does not include the store or the registry.
- **Neither fork is "build a standalone app."** If the survey concludes cortex-ui is unsuitable,
  STOP and escalate — that contradicts the design premise and is a human call.

**Gate 0.5:** survey doc exists with the three sizings + the review-machinery map; fork chosen with
reasons; ADR-0042 open question 1 (evaluation trigger) decided and recorded; flag-off check defined
for Gate 1.

---

## 3. Phase 1 — Workspace, anchor timeline, live consequence signals (Days 1–2)

**Goal:** the room's legibility layer. The timeline is the ANCHOR projection — their shared
vocabulary, demoted but not discarded — with the consequence signals that make dragging meaningful.

### 3.1 Tasks

1. **Mount** per the fork: new `InterviewPhase` value, new config key, cortex layout and design
   system, chat rail present (wired Phase 2).
2. **Plan state — THE SERVER OWNS IT.** Rev 2 moved the computation server-side and left the
   store where rev 1 put it, which left two stores with no ruled relationship: a client
   `effectiveState()` selector, and verbs executing in `invincible-agent` against a server store.
   **A server verb cannot read a browser selector.** That is the two-masters defect this whole
   lineage exists to prevent, and it is ruled here rather than improvised on day 3.

   - **Baseline, scenarios, and ops live server-side and are addressable.** A scenario has an id
     the server can resolve; ops POST as they happen.
   - **Verbs evaluate over `(state_ref, ops[])`** — stateless with respect to the caller, so an
     evaluation is reproducible from its arguments and a diff is expressible without a session.
   - **The client store is an OPTIMISTIC MIRROR**, and its only job is interaction feedback. It
     is never the source of a number that reaches a card.
   - `effectiveState()` survives as the client mirror's selector, and the Gate 1 grep-check still
     applies to *views*. It is no longer claimed as the input to a verb.

   Until Phase 3 lands, ops apply to one implicit scenario labelled **SANDBOX** in the UI so
   nobody believes baseline is being edited.

   **This single ruling also disposes ADR-0042's open questions 1 and 2**, because all three are
   the same question wearing different hats: OQ1 (push vs pull re-evaluation) and OQ2 (a diff as
   one verb over two state refs vs one verb run twice) both presuppose an answer to *where
   mutable plan state lives*. Server-addressable scenarios make the state-ref form available, so:
   **OQ2 → one verb over two state refs.** **OQ1 → pull, on a server-issued state version** —
   the client re-requests when the version it holds is stale, which is the form that survives a
   second client and a reconnect, where push does not. Record both in the Phase 0.5 survey doc as
   decided, and amend ADR-0042 to point at that record.
3. **Contracts before components.** Each renderer ships `<X>.contract.ts` — archetype, component,
   layout, typed field map, `rowRequirements`, `refusalReasons` — and a `DERIVED_BINDINGS` row in
   `assembleCapabilities.ts`. The refusal vocabulary is where honest-empty is *enforced*: "no
   funding rows recorded" is a registered reason the picker reads, not a styled empty state.
   Archetypes: `INTERVAL_TIMELINE`, `PERIOD_SERIES`, `THRESHOLD_GRID`, `MATRIX_GRID`, `DELTA_SET`,
   `DECISION_RECORD`.
4. **Timeline spike (timebox 3h).** Evaluate 2–3 OSS timeline components (vis-timeline,
   frappe-gantt, svar-gantt — check licenses) for drag-to-move, row grouping, custom bar styling,
   controlled-component mode. Record choice + rejects. If none passes in 3h, take vis-timeline and
   move on. DO NOT extend the spike. Note: `recharts` and `@xyflow/react` are already dependencies,
   so the period series and the dependency graph need no new library — only the timeline does.
5. **Anchor timeline:** rows grouped initiative → phase → project from `planSchedule`; phase bands;
   drag emits `move_project`.
6. **Three consequence strips**, always visible, recomputed on every op: period cost series with
   cap line; site-load threshold grid; dependency-violation badges on bars (red links if the lib
   supports them, else badges + a violations list).
7. **Drill-in — reuse the review idiom, do NOT invent a bespoke side panel.** Click a bar → detail
   opens adjacent in the pattern reviews use for supporting documents: fields, capabilities with
   weights, sites with windows, technologies, dependencies both directions, requirements vs
   commitments per period. Editable: cost/funding rows. **Supporting refs go to the HUD** — which
   verb, which slots, which rows back a shown number — exactly as doc-grounding refs do today. That
   is what visually unifies plan-grounding with doc-grounding in the demo.
8. **Canvas frame:** the workspace holds pinned live-view cards, each `{ output_uri, params }` per
   ADR-0042 §2. Timeline + three strips are permanent; question-minted cards append.

### 3.2 Gate 1

- [ ] **BOTH provenance fields, on every planning card** — VERIFIED NECESSARY 2026-08-21 by
      running the selector, not by reading it:
      `presentation_source == "registered"` **AND**
      `selection_basis == "output_uri+payload"` (never `"payload-only (…)"`).
      `presentation_source` alone is INSUFFICIENT and would have passed this gate while the
      card rendered wrong: `output_uri` is a HINT, so a miss widens the search to the whole
      menu, and a planning cost series (`[{period, total}]`) satisfies CHART_WIDGET's contract
      and is absorbed by it — `presentation_source: "registered"`, archetype CHART_WIDGET,
      card draws, looks plausible. Only `selection_basis` separates *my contract was found*
      from *something else absorbed my payload*. ADR-0042 §5 + its 2026-08-21 amendment.
- [ ] Corollary, and it reorders the work: **contracts are not a tidying step after the
      widgets.** Until a planning renderer's `.contract.ts` is registered, its payloads do not
      refuse — they are absorbed. A planning card that "already renders" before its contract
      exists is evidence of absorption, not progress.
- [ ] Each card's `valid_as_of` advances on re-evaluation and is displayed. A card showing its
      mint-time stamp after a drag is a Gate 1 failure, not a cosmetic one. ADR-0042 §4.
- [ ] **Drag is optimistic; drop is evaluated.** During drag only the BAR moves — that is
      arrangement, UI-master, legitimately client-side (ADR-0042 §4). On drop, the op commits and
      the verbs re-evaluate; the strips update from server rows.
      The gate is **"drop → strips updated within N ms," where N is MEASURED against the real BFF
      on day 2 and written here** — not asserted in advance.
      Rev 1's flat `<100ms` was priced for client-side pure functions and is unpassable across a
      BFF round trip plus Keycloak plus a demo-day network. **An unpassable gate is not a high
      standard; it is an invitation to compute one little measure in the browser on day 3**, which
      is the §3 violation this plan is largely about preventing. The drag still feels live and the
      numbers stay governed.
- [ ] Seeded tensions (a)(b)(c) are visible on first load with no interaction.
- [ ] Drill-in shows all model edges for a clicked project; a cost edit re-drives the series.
- [ ] Honest-empty comes from the **registered refusal vocabulary**, not a UI branch.
- [ ] No view reads state except through `effectiveState()` (grep-check).
- [ ] Flag-off: the grounding workspace is behaviorally identical (smoke the doc-finding path).
- [ ] `npm run build` green — it runs the transport guard, **vitest**, tsc, and vite build.

---

## 4. Phase 2 — Grounded Q&A rail (Days 3–4)

**Goal:** INV-1. The LLM routes and narrates; it never answers.

### 4.1 Intent catalog — the funnel walls

Each intent: `{ intent_id, description, slots (typed, with defaults), verb, output_uri,
example_phrasings[] }`.

**There is no `view` field.** ADR-0042 §2.

~16 intents: `show_cost_curve{scope,window,kind?}` · `show_funding_gap{group_by,window}` ·
`show_site_load{site?,window}` · `what_blocks{project}` · `downstream_of{project}` ·
`maturity_grid{as_of?}` · `capability_path{capability}` · `process_evolution{process}` ·
`tech_footprint{technology}` · `site_schedule{site,window}` · `projects_in{window,scope?}` ·
`compare_scenarios{a,b}` (stub until Phase 3) · `move_project{project,when}` (mutation) ·
`set_cost{project,kind,period,amount}` (mutation) · `goal_seek_budget{scope,window,cap}` (stub
until Phase 5) · `summarize_session{}` (stub until Phase 3).

Per ADR-0042 §8, this catalog is **ADR-0032 with the authoring step pinned** — the same
LLM-authors/enforcement-disposes shape, narrowed for verifiability. Any catalog that cannot be
described that way has drifted.

### 4.2 LLM wiring

- **Where.** A BFF route. A frontend LLM call fails the transport guard, which runs inside
  `npm run build`. Provider and model are BFF config; the frontend never knows either.
- **Provider — RULED: internal only, no cloud fallback, fail closed.** BAML's `MainAgent` is
  `fallback [OpenRouter, OpenAI, Ollama]` — cloud **first**, Ollama last. For this domain that is
  not a configuration preference, it is a boundary violation waiting for a bad day: the planning
  functions carry funding figures, site names, and capability maturity for a defense-adjacent
  customer, and `MainAgent` sends all of it to OpenRouter the moment the internal endpoint hiccups.

  **`RouteIntent` and `NarrateResult` pin to the internal client with NO cloud fallback.** The
  precedent is `VerifyVerbChoice`, which pins directly to `client Ollama` for exactly this class of
  reason. When the internal endpoint is unreachable the functions **fail closed to template
  captions** — a fallback this plan already carries, which exists for precisely this case. A
  failure that renders a template caption is a good day compared to a success that exfiltrated the
  portfolio.

  **Environments — ANSWERED 2026-08-21.** Sandbox is **Ollama**; work/deployment is **vLLM**; the
  weights and context window are the same, the model NAME differs. So the BFF must not hardcode a
  model string, and the plan must not assume one name reaches both — `env.OLLAMA_MODEL` already
  makes this configmap-driven, and the same discipline extends to the vLLM client. **Adding the
  vLLM client to `clients.baml` is named Phase-2 work**, not existing infrastructure; the
  risk-line "one BAML client fronts both endpoints" becomes true only once it exists.
- **Model string — VERIFIED AGAINST THE LIVE ENDPOINT 2026-08-20.** `GET
  http://192.168.1.126:11434/api/tags` returns eight models. Probed:

  | string | endpoint says |
  |---|---|
  | `gpt-oss-120b` (rev 1 wrote this five times) | **ABSENT** — the 404 `clients.baml` documents |
  | `gpt-oss:120b` | present |
  | `gpt-oss-128k:120b` | present, and **this is what `values-sandbox.yaml` actually sets** |
  | `gpt-oss:20b` (rev 1's declared hardware fallback) | **ABSENT** |

  Two findings beyond the grenade, both from the same ten-minute check:

  1. **The configured model is `gpt-oss-128k:120b`, not `gpt-oss:120b`.**
     `helm/invincible-agent/values-sandbox.yaml:174` sets `OLLAMA_MODEL: "gpt-oss-128k:120b"` —
     the extended-context variant (`parent_model: gpt-oss:120b`, `context_length: 131072`).
     Both tags exist, so this is not a 404; it is a **context-length divergence**, and it matters
     for a workload carrying few-shot exemplars per intent plus result rows. Name the variant
     deliberately rather than inheriting it.
  2. **The declared hardware fallback does not exist.** `gpt-oss:20b` is not on this endpoint.
     Any plan that permits falling back to it is permitting a fallback to a 404. Either pull the
     tag first or delete the escape hatch — a fallback nobody verified is worse than none,
     because it will be reached under pressure.

  Also confirmed from the same response: the model advertises `capabilities: ["completion",
  "tools", "thinking"]` — so BAML tool-use is supported and the separate reasoning channel the
  harmony-format rule below governs is real, not assumed.

  The model is configmap-driven via `env.OLLAMA_MODEL`, so switching is a rolling restart, and
  `temperature 0` is already pinned in the client config — rev 1's "pin sampling params" task is
  already done.
- **Structured output via BAML** — the existing enforcement mechanism; do not introduce a second.
  Intents are BAML functions (`RouteIntent(question, context) -> Intent`, a union of typed intent
  classes; `NarrateResult(rows) -> string`). Malformed model output becomes a typed parse failure,
  never a malformed intent reaching code. If the union proves brittle, two-step classify-then-fill
  is two BAML functions. Budget few-shot exemplars per intent from the start.
- **Canonical-source ruling.** `.baml` definitions are canonical for intent SHAPES (names, slots,
  types — enforcement owns the contract). Catalog config is canonical for what BAML should not know:
  example phrasings, synonym and soft-language maps, intent→verb→`output_uri` routing — loaded data,
  with structural type names. They meet on intent ids, and a build-time check asserts every catalog
  id has a matching BAML class and vice versa. No third encoding may exist.
- **Harmony-format rule.** gpt-oss emits reasoning in a channel separate from the final answer. The
  BFF extracts ONLY the final channel; the number-check runs against final-channel text;
  reasoning-channel text never reaches a card, the canvas, or a demo-visible log.
- **Sandbox hardware caveat — the fallback must be pulled before it is declared.** The 120b is
  ~65GB on disk and needs comparable memory. `gpt-oss:20b` is **not present on the endpoint**
  (verified above), so it is not currently a fallback at all. If dev needs one, pull the tag
  first and record the pull; then the Day-5 real-endpoint eval is promoted from check to hard
  gate. No silent substitution, and no undeclared-but-assumed one either.
- **Entity resolution before slot fill** reuses [ADR-0031](../adr/ADR-0031-instance-resolution-ladder.md)'s
  ladder — exact, containment, LLM-candidate, abstain — not a second fuzzy matcher. Ambiguous match
  → interpretation card lists candidates; zero match → refusal.
- **Interpretation card (binding).** Every answered question renders its filled intent in plain
  language above the result. Cards are correctable: edit a slot → re-run without re-asking.
- **Refusal path (binding).** No intent match, or a slot referencing an out-of-model concept (ROI,
  risk owner, headcount) → state what the model does not capture, offer the nearest intent, log the
  miss. Misses are agenda items, not failures.
- **Narration contract (binding, machine-checked, server-side).** The LLM sees ONLY result rows and
  writes ≤2 sentences. Every numeric token must appear in the rows; violation → strip the sentence,
  log, render with a template caption. Views cannot lie because they are drawn from rows; the check
  holds the prose to the same standard. With a smaller model this WILL fire occasionally — that is
  the fallback working, not a defect.
- Each successful answer mints a live-view card and appends a `QATrace`.

- **Day-5 eval against the REAL demo endpoint — unconditional.** Rev 2 left this surviving only
  inside the 20b-fallback clause, which was a downgrade: it is now checking the **provider path**
  and the **model name** as well as the weights, and both differ between sandbox (Ollama) and work
  (vLLM). The 51-case suite runs against the endpoint the demo will actually use, by Day 5, in
  every scenario. If the sandbox fallback is in play it is additionally a hard gate; otherwise it
  is a blocking check. There is no configuration in which it is skipped.

### 4.3 Eval fixture — CHANGED (lives in `invincible-agent`)

`tests/eval/planning_questions.yaml` + a pytest runner. Rev 1 put a JS harness in cortex-ui for
routing that executes in Python — throwaway by construction, and this repo is where the eval
discipline lives (166 test files, the order-independence suite, ADR-0032's banked set).

17 questions × 3 phrasings (51 cases) with expected `intent_id` + slots, plus 3 out-of-model
questions expecting refusal. Asserts intent match, slot fill, and the narration number-check. This
suite is Phase 2's acceptance instrument and the release gate for Phase 7.

### 4.4 Gate 2

- [ ] ≥90% of 51 cases route to the correct intent with correct slots; **100% of out-of-model cases
      refuse.** A wrong-but-confident answer fails the whole gate, not a point.
- [ ] Interpretation card on every answer; slot-edit re-run works.
- [ ] Number-check wired and demonstrably strips a violation (one adversarial test).
- [ ] Two questions leave TWO cards on the canvas — accumulation, not replacement.
- [ ] Every minted card carries `presentation_source == "registered"` AND
      `selection_basis == "output_uri+payload"` (see Gate 1 — the first without the second is
      green while the archetype is wrong).

---

## 5. Phase 3 — Scenarios, diffs, decisions (Days 4–5)

**Goal:** INV-3 + INV-4. This phase IS the review-efficiency target.

1. **Scenario lifecycle.** "New scenario" forks baseline (named, e.g. "Option A — slide ERP
   right"); picker in the header; SANDBOX becomes a real scenario. Baseline is read-only while a
   scenario is active. (Exception: drill-in cost entry with no active scenario writes baseline plus
   a change record.)
2. **Diff engine.** Run every verb against baseline state and scenario state; subtract; emit
   `Effect[]`, suppressing effects below per-measure materiality floors. Pure computation — no LLM
   anywhere near the numbers.
3. **Diff card** renders `Effect[]` grouped improved/degraded, each line "metric · magnitude ·
   affected named things." Archetype `DELTA_SET`, with its own contract. The LLM MAY write a
   one-sentence headline from the effect rows under the same narration contract. The card is a live
   view and updates as the scenario's ops change. (ADR-0042 open question 2 — whether the diff is
   one verb over two state refs or one verb run twice — is decided here and recorded.)
4. **Compare view.** `compare_scenarios{a,b}` — two diff cards side by side, plus a baseline ghost
   line on the period series.
5. **Commit ceremony — the degenerate single-approver case of the review machinery.** Reuse the
   review card/flow idiom even where wiring into the real machinery is deferred: "Commit scenario" →
   a review-style card that REQUIRES rationale (block on empty — the same semantics as
   disposition-with-override-reason), shows alternatives with a considered/not-considered toggle,
   shows the auto-gathered question trail → produces a `DecisionArtifact`, applies ops to baseline,
   archives the scenario. Decision artifacts get a `DECISION_RECORD` card and a session decision log.
   The multi-party version (finance disposes funding effects, site leads dispose load effects,
   leader approves) is Phase 7 — riding the review idiom now is what lets it upgrade without
   restructuring.
6. **`summarize_session`** goes live: decision log + open scenarios + outstanding tensions.

**Gate 3**
- [ ] Fork → drag two projects → diff card shows the seeded trade (Q3 cost improves, Site B load
      degrades, dependency X violates) with magnitudes unit-tested against hand-computed values.
- [ ] Commit blocks without rationale; the `DecisionArtifact` contains ops + rationale + question
      trail + alternatives.
- [ ] Baseline provably unchanged until commit (snapshot test).
- [ ] `summarize_session` answers from state and passes the narration check.

---

## 6. Phase 4 — Persistence (Day 5)

**Goal:** costs, plans, scenarios, decisions survive reload. The source-of-truth path swaps; the
types do not change — the whole point of Phase 0.

1. Postgres schema mirroring the Phase-0 types. Tables: `plan_op`, `scenario`,
   `decision_artifact`, `maturity_assessment` (append-only), `funding_requirement`,
   `funding_commitment`.
2. **Routes in `gateway.py`** — load-all on boot, write-through for ops, scenario lifecycle,
   commits, cost/funding edits. The in-memory store stays the working model; persistence is
   durability, not the read path, so the demo stays instant. **No second backend.**
3. Seed script writes the Phase-0 dataset; the app boots from the database.
4. **No new Electric shapes.** Skip without guilt; nothing may depend on it.

**Gate 4:** kill the app mid-scenario → reload → scenario, ops, entered costs, and every decision
artifact intact. Baseline reproducible from the database alone.

---

## 7. Phase 5 — Goal-seek v0 (Day 6, FORKED)

**Day-4 fork rule (binding):** at end of Day 4, assess. If Phases 2–3 are not both green, Phase 5
is CUT and Day 6 goes to hardening. The diff card is the must-have "beyond" moment; goal-seek is
the stretch. Ship one honest INV-2 moment or none — never a flaky one.

If green:
1. `goal_seek_budget{scope,window,cap}` — greedy search over `move_project` ops (candidates: slide
   right one quarter, ordered by cost-in-window desc); objective = cost within cap for the window;
   hard constraint = no new dependency violations; soft penalty = load-threshold breaches and slip
   magnitude. Return the top 2 distinct solutions.
2. Each solution materializes as an UNCOMMITTED scenario + its diff card: "Option 1: slide P7, P9
   right one quarter — clears Q3 (−$1.4M), +1 load on Site C in Q4." Picking = activating that
   scenario; proposals ride the same rails as manual edits, no special path.
3. **Honest failure.** If nothing satisfies the constraints, say so and show the nearest miss and
   which constraint binds. Never present a constraint-violating plan as a solution.

**Gate 5:** the seeded Q3 overage is solvable; both options verified constraint-clean **by the verb
functions, not by the search's own claim**; the no-solution path demonstrably works (test with an
impossible cap).

---

## 8. Phase 6 — Hardening + rehearsal (Day 7. NOTHING NEW.)

1. **Script the meeting, not the features** (5 minutes):
   - Open on the canvas: timeline + strips; tensions (a)(c) already red. "It's the quarterly review."
   - "Why is Q3 red?" → interpretation card → cost series card + one-line narration. (INV-1)
   - "Which sites are getting hammered in Q4?" → load grid card. The canvas now carries the
     meeting's questions. (INV-1)
   - Fork "Option A", drag two bars → diff card narrates the trade including the dependency that
     goes red. (INV-3)
   - [If Phase 5 shipped] "Get Q3 under $4M" → two proposed options → the room picks. (INV-2)
   - One deliberately out-of-model question ("what's the ROI on Initiative 2?") → honest refusal +
     nearest offer. **Keep this. The refusal is what buys trust for everything else.**
   - Commit with rationale → decision artifact → "summarize this session." (INV-4)
   - Close: "Reload — it's all still here."
   - Optional beat: one doc-finding question through the same rail, answered by the existing
     pipeline. Two groundings, one workspace, one presentation path.
2. **Pre-answer the sharp question.** "Did I just change the plan?" → "You changed a scenario.
   Baseline changes only at commit, with a recorded reason. Baseline-vs-scenario governance is the
   next increment."
3. **Freeze.** Tag the demo commit. After freeze: rendering defects only, each with a test.
4. **Rehearse twice**, the second time on the machine and screen that will be in the room —
   including `VITE_NO_AUTH=true`, because `RequireAuth` wraps everything and `useSessionIsolation`
   withholds all render until an authenticated subject reconciles.

---

## 9. Post-demo (Phases 7–8, planned so 0–6 forecloses nothing)

**Phase 7 — widen the funnel, harden the model.**
- Free-form NL→query-plan IR — **this is ADR-0032's build arriving**, release-gated on the grown
  fixture including every logged miss. Wrong-but-confident stays an automatic fail.
- Miss-log triage: each miss becomes a synonym, a new intent, a new verb, or a model extension,
  with the governance owner named for any new measure definition.
- Real assessment-capture (who/when/evidence) and a funding-ingestion seam with lineage. These are
  the two workflows that make answers trustworthy.
- **Multi-party review:** wire commit into the real review/approval machinery — leader plus
  contributing parties in their own views, per-effect dispositions, full audit trail. Evaluate
  expressing the portfolio review as a workflow definition ([ADR-0039](../adr/ADR-0039-workflow-definition-authoring-schema-and-bpmn-export.md):
  same executor, new YAML, zero workflow-specific code); `DecisionArtifact` becomes a step output.
- If Fork E was taken: converge the canvas instance. Narrowed Fork E leaves only layout to
  converge — the store and the registry were never forked.
- ADR: ontology alignment map (types ↔ ArchiMate / DoDAF-PV / OWL-Time / P-Plan / PROV / ORG).

**Phase 8 — substrate.**
- Phase-0 types become the write-model shape. Live-view and decision cards already match ADR-0023's
  shape (durable, provenance-carrying, validity-stamped).
- Neo4j write-model + projector + Electric read path per the existing CQRS pattern; Phase-4's
  Postgres becomes the projection target, which is why Phase 4 stayed boring.
- **Presentation is a no-op at Phase 8** — the verbs already declare output types and the renderers
  already registered. That is the payoff for ADR-0042 §3.
- ADR the seam before building it.

---

## 10. Risk register

| Risk | Mitigation |
|---|---|
| Timeline lib fights drag/controlled mode | 3h timebox + named fallback; worst case, bars are divs on a CSS grid — ugly, functional |
| Intent routing below gate | Shrink to the 10 intents the script uses; scripted phrasings are in the eval set, so demo-path accuracy is measured not hoped |
| Diff magnitudes wrong in the room | Every magnitude comes from verb functions unit-tested against hand-computed seed values; no LLM numbers anywhere |
| Goal-seek flaky | Day-4 fork rule cuts it cleanly; the script has a no-Phase-5 variant |
| Demo-day LLM outage | Template captions render without the LLM (narration is additive); app boots from local DB; rehearse the LLM-down path once |
| **Wrong model string** | CLOSED 2026-08-20 by live probe of `/api/tags`. `gpt-oss-120b` confirmed ABSENT; sandbox is configured for `gpt-oss-128k:120b` (131072 context), not plain `gpt-oss:120b`. Re-probe if the endpoint or configmap changes |
| **Fallback model is a phantom** | `gpt-oss:20b` is not on the endpoint. Pull the tag before declaring it a fallback, or delete the escape hatch — an unverified fallback gets reached under pressure and 404s there |
| Provider path assumed rather than chosen | `MainAgent` is cloud-first and no vLLM client exists. Pin deliberately (the `VerifyVerbChoice` precedent) or add the client as named work |
| Intent set drifts between BAML and catalog | Canonical-source ruling + build-time id-agreement check |
| **Portfolio data leaves the boundary on a bad day** | `MainAgent`'s cloud-first fallback is NOT used. Planning functions pin internal with no cloud fallback and fail closed to template captions. This is the highest-severity row in the table: every other risk costs a demo, this one costs the customer |
| Sandbox (Ollama) and work (vLLM) name the same model differently | Model name is configmap-driven on both sides; never hardcoded in the BFF. Day-5 eval runs against the real demo endpoint unconditionally, checking provider path AND name, not just weights |
| Keycloak blocks the demo boot | `RequireAuth` wraps everything; rehearse `VITE_NO_AUTH=true` on the demo machine |
| **A card renders against the wrong menu** | Gate 1 asserts `presentation_source == "registered"` AND `selection_basis == "output_uri+payload"`. Verified 2026-08-21: the first alone PASSES while a planning series is absorbed by CHART_WIDGET via payload-only widening. Rendering is not evidence, and neither is one provenance field |
| **Sandbox cluster runs pre-arc builds** | engine-f (2026-08-18) and cortex-ui (2026-08-15) both predate the entire presentation-SPO arc; a probe today returns `x-presentation-path: fallback-designui`, the OLD LLM path. Any integration check before a redeploy is testing architecture that no longer exists in the tree. See `stale-sandbox-images-predate-presentation-arc` |
| Electric reconciliation clobbers minted cards | Sized in Phase 0.5 item 3; narrowed Fork E is the hatch |
| Planning work destabilizes the grounding demo | Flag-off smoke check at Gate 1; shared components extended, never restructured |
| Scope creep from this document | Anti-goals are binding; anything not in a phase task list is Phase 7+ by default |

---

## 11. Self-check before Phase 1

- [ ] I have read ADR-0042. I can state why a live view is an archetype and not an artifact kind.
- [ ] No measure computes in a browser. No intent names a view.
- [ ] Every renderer I am about to write has a `.contract.ts` with real refusal reasons.
- [ ] Gate 0 passed before any UI work started.
- [ ] The 17-questions → verbs map has no fudged rows.
- [ ] Every type field has its why-comment; `status` is an enum; `Dependency` has two ends; funding
      is split requirement/commitment; assessments are append-only; every temporal thing is an
      `Interval`.
- [ ] I understand the target is the meeting loop, and every deliverable maps to a step of it.
