// ═══════════════════════════════════════════════════════════════════════════
// PLANNING Q&A RAIL — routing and narration (Phase 2)
//
// The LLM ROUTES and NARRATES; it never answers. Answers come from Engine P's
// verbs, executed server-side against the seed store. These two functions are
// the only LLM surface in the rail.
//
// ── NEW FILE, SOLE OCCUPANCY ──────────────────────────────────────────────
// `contracts.baml` is NOT touched — it is in another lane's pinned landing.
// `ClassifyDomainIntent` is NOT touched — it is the one genuinely shared call
// between the extraction and class-selection lanes. Nothing here reads,
// alters, or reprompts either.
//
// ── CANONICAL-SOURCE SPLIT (plan §4.2) ────────────────────────────────────
// THIS FILE is canonical for intent SHAPES — names, slots, types. Enforcement
// owns the contract, so a malformed model output becomes a typed parse failure
// and never a malformed intent reaching code.
// `agent_fleet/planning_agent/intent_catalog.yaml` is canonical for phrasings,
// synonym and soft-language maps, and intent→verb→output_uri routing.
// They meet on `intent_id`, asserted by
// tests/planning/test_catalog_baml_agreement.py in BOTH directions.
// No third encoding may exist.
//
// Each class carries an explicit `// @@intent_id:` marker rather than relying
// on class-name-to-snake-case guessing — a naming convention is a third
// encoding wearing a convention's clothes, and it breaks silently the first
// time someone names a class reasonably but differently.
//
// ── CLIENT PINNING (A3, BINDING) ──────────────────────────────────────────
// Both functions pin to `client Ollama` — the INTERNAL endpoint — with NO
// cloud fallback, following VerifyVerbChoice's precedent rather than
// MainAgent's `fallback [OpenRouter, OpenAI, Ollama]`, which tries cloud
// FIRST. These calls carry funding figures, site names and capability maturity
// for a defense-adjacent customer. MainAgent would ship all of it to OpenRouter
// the moment the internal endpoint hiccups, and the failure mode is a SUCCESS
// that exfiltrated the portfolio — which no error log records.
//
// When the internal endpoint is unreachable these fail closed to TEMPLATE
// CAPTIONS. A failure that renders a template caption is a good day compared to
// a success that leaked the portfolio.
//
// Model string and base_url come from env via the Ollama client
// (`env.OLLAMA_MODEL`, currently `gpt-oss-128k:120b`), never hardcoded here:
// sandbox is Ollama, work is vLLM — same weights, different model NAME. The
// client already pins `temperature 0`.
//
// ── HARMONY FORMAT RULE (BINDING) ─────────────────────────────────────────
// gpt-oss emits reasoning in a channel separate from the final answer, and the
// model advertises `capabilities: ["completion","tools","thinking"]`, so the
// separate reasoning channel is real rather than assumed. The BFF extracts ONLY
// the final channel. The number-check runs against final-channel text.
// Reasoning-channel text never reaches a card, the canvas, or a demo-visible
// log — it is a draft, and a draft shown to a room reads as an answer.
// ═══════════════════════════════════════════════════════════════════════════

// ── COST ──────────────────────────────────────────────────────────────────

class ShowCostCurve {
  // @@intent_id: show_cost_curve
  scope string?
  window string?
  kind string?
  over_cap_only bool?
}

class ShowFundingGap {
  // @@intent_id: show_funding_gap
  group_by string
  window string?
}

// ── SITES ─────────────────────────────────────────────────────────────────

class ShowSiteLoad {
  // @@intent_id: show_site_load
  site string?
  window string?
  over_threshold_only bool?
}

class SiteSchedule {
  // @@intent_id: site_schedule
  site string
  window string?
}

// ── SCHEDULE ──────────────────────────────────────────────────────────────

class ProjectsIn {
  // @@intent_id: projects_in
  window string?
  scope string?
}

// ── CAPABILITY / PROCESS / TECH ───────────────────────────────────────────

class MaturityGrid {
  // @@intent_id: maturity_grid
  as_of string?
}

class CapabilityPath {
  // @@intent_id: capability_path
  capability string
}

class ProcessEvolution {
  // @@intent_id: process_evolution
  process string
}

class TechFootprint {
  // @@intent_id: tech_footprint
  technology string
}

// ── COVERAGE / SESSION / DIFF ─────────────────────────────────────────────

class CoverageGap {
  // @@intent_id: model_coverage
  // RENAMED 2026-08-23. The CLASS keeps the name CoverageGap (it mirrors the
  // verb plan_coverage_gap, which is Engine P's and did not change); the INTENT
  // id is model_coverage because a name reading as a funding synonym pulls
  // funding questions in ANY architecture. The explicit marker is what lets the
  // two differ safely — a snake_case convention would have silently broken here.
  placeholder string?
}

class SummarizeSession {
  // @@intent_id: summarize_session
  placeholder string?
}

class CompareScenarios {
  // @@intent_id: compare_scenarios
  a string
  b string
}

// ── MUTATIONS ─────────────────────────────────────────────────────────────

class MoveProject {
  // @@intent_id: move_project
  project string
  when string
}

class SetCost {
  // @@intent_id: set_cost
  project string
  kind string
  period string
  amount string
}

// ── DEPENDENCY TRAVERSAL ──────────────────────────────────────────────────
// Wired 2026-08-22 to plan_dependency_neighborhood -> mesh:DependencyNeighborhoodSet.
// The verb's own measurement confirmed why traversal could not be a parameter on
// the violations verb: violations returns [] on the seed, so "what blocks P5?"
// routed there answered with SILENCE, which reads as "nothing depends on P5"
// rather than "P5's predecessor is satisfied".
//
// `direction` is OPTIONAL here and PRESET IN THE CATALOG per intent. The two
// questions differ ONLY by direction, and asking the model to infer it from
// "what blocks" versus "what does it block" is a coin-flip on a word order the
// eval phrasings deliberately vary. The model may still supply it when the user
// is explicit; the catalog default is what makes the common case deterministic.

class WhatBlocks {
  // @@intent_id: what_blocks
  project string
  direction string?
}

class DownstreamOf {
  // @@intent_id: downstream_of
  project string
  direction string?
}

// ── NO MATCH ──────────────────────────────────────────────────────────────
// A first-class outcome, not an error. A question that matches nothing, or that
// references an out-of-model concept (ROI, risk owner, headcount), routes HERE
// so the rail can state what the model does not capture and offer the nearest
// intent. Misses are agenda items, not failures — and an intent union with no
// escape hatch forces the model to pick the nearest wrong answer, which is the
// confident-wrong outcome Gate 2 fails the whole gate for.

class NoIntentMatch {
  // @@intent_id: no_intent_match
  //
  // REFUSAL IS EXPENSIVE ON PURPOSE (2026-08-23). Measured: ~20 of 36 eval
  // failures were this class chosen for questions that DO route. In a 17-way
  // union an always-available escape hatch is the CHEAPEST answer — the model
  // reaches for it whenever any intent's fit is imperfect, because refusing
  // costs nothing while committing risks being wrong.
  //
  // So it now costs something. `nearest_intent_id` and `nearest_rejected_because`
  // are REQUIRED: to refuse, the model must name the intent it came closest to
  // picking and state why that one does not fit. Forced to write "the nearest is
  // show_funding_gap, and it does not fit because..." for the question "where is
  // funding short by initiative", it has to produce a sentence that is visibly
  // false — much harder than silently taking an exit.
  //
  // The justification is not for the reader. It is friction priced into the
  // wrong choice.
  // Optional as of the two-step build: the friction these were added to
  // create is now supplied structurally. Measured 21 -> 18 when required.
  nearest_intent_id string?
  nearest_rejected_because string?
  out_of_model_concept string?
  reason string
}


// ── TWO-STEP ROUTING (2026-08-23) ─────────────────────────────────────────
// WHY THE SHAPE CHANGED RATHER THAN THE WORDING. Two config fixes aimed at
// named targets — rewording model_coverage, pricing refusal — moved routing
// 21/51 -> 18/51. Nothing. The refusal-economics theory was pre-registered with
// its own falsification branch and this is it: the refusals were HONEST. The
// model could not tell the money intents apart, so making refusal expensive
// just made it write justifications.
//
// The defect is geometric. A 17-way single-shot decision asks one question with
// seventeen margins, and three of them (cost_curve / funding_gap /
// model_coverage) are near-tied for money phrasings. At temperature 0 a near-tie
// resolves on last-bit floating-point noise — measured: five cases flipping on a
// QUIET host at n=3.
//
// Two-step moves the boundary off the thin walls. "Is this about money" has a
// FAT margin. "Which of three money intents" is asked SECOND, among three
// options instead of seventeen, with room for contrastive descriptions that
// would bloat a single-shot prompt into uselessness if written for all 17.
//
// Do not buy better dice. Ask questions with bigger gaps.

enum IntentFamily {
  MONEY       @description("spend, budgets, funding, commitments, caps")
  SCHEDULE    @description("what runs when, across the portfolio")
  SITE        @description("what happens at a location, and site change-load")
  CAPABILITY  @description("capabilities, processes, technologies and their maturity")
  DEPENDENCY  @description("what blocks what, and what slips if something slips")
  STRUCTURE   @description("what NOTHING is working on — absence in the plan itself")
  SESSION     @description("what changed this session, or comparing scenarios")
  MUTATION    @description("changing the plan: moving a project, setting a cost")
  NONE        @description("the system genuinely cannot answer this")
}

function RouteFamily(question: string, context: string) -> IntentFamily {
  client Ollama
  prompt #"
    Which FAMILY of planning question is this? One word.

    This is deliberately coarse. You are not choosing a specific answer yet —
    only the neighbourhood. Pick the family whose subject the question is about,
    even if you are unsure which specific question within it applies.

    MONEY covers anything about spend, budget, funding, commitments or caps.
    STRUCTURE is about what has NOBODY working on it — an absence in the plan.
    It is NEVER a money question, even when the word "gap" appears.

    Answer NONE only if the question needs something this system does not carry
    at all: return on investment, risk ownership, headcount or staffing.

    QUESTION:
    {{ question }}

    CONTEXT:
    {{ context }}

    {{ ctx.output_format }}
  "#
}

// ── FUNCTIONS ─────────────────────────────────────────────────────────────

function RouteIntent(question: string, context: string) -> ShowCostCurve | ShowFundingGap | ShowSiteLoad | SiteSchedule | ProjectsIn | MaturityGrid | CapabilityPath | ProcessEvolution | TechFootprint | CoverageGap | SummarizeSession | CompareScenarios | MoveProject | SetCost | WhatBlocks | DownstreamOf | NoIntentMatch {
  client Ollama
  prompt #"
    You route a planning question to exactly one intent. You do NOT answer it.

    The answer will be computed server-side by a registered verb. Your only job
    is to pick the intent and fill its slots from what the user actually said.

    RULES:
    - Fill a slot ONLY from the question or the context. Never invent a value.
    - Leave an optional slot null when the question does not determine it. A
      guessed default is indistinguishable from a stated one downstream.
    - REFUSE ONLY AS A LAST RESORT. NoIntentMatch is for questions this system
      genuinely cannot answer — NOT for questions whose best intent is an
      imperfect fit. An intent slightly wider or narrower than what was asked is
      still the RIGHT route if it returns useful rows. Prefer the closest intent.
    - To refuse you MUST name `nearest_intent_id` — the intent you came closest to
      picking — and `nearest_rejected_because`, stating why THAT intent does not
      fit. If you cannot write a sentence there that is actually true, the answer
      is that intent, not a refusal.
    - Refuse when the question needs something the model does not carry: return on
      investment, risk ownership, headcount/staffing. Those have no intent at any
      distance, and `out_of_model_concept` names which one.

    QUESTION:
    {{ question }}

    CONTEXT:
    {{ context }}

    {{ ctx.output_format }}
  "#
}

function NarrateResult(rows: string) -> string {
  client Ollama
  prompt #"
    Write at most TWO sentences describing these result rows.

    You are given ONLY the rows. You have no other knowledge of this portfolio,
    and anything you add from outside them is fabrication.

    RULES:
    - Every number you write must appear in the rows. A server-side check strips
      any sentence containing a number that does not, and the card falls back to
      a template caption.
    - Do not infer causes, risks, or recommendations. Describe what is there.
    - No preamble. No "based on the data". Just the description.

    ROWS:
    {{ rows }}

    {{ ctx.output_format }}
  "#
}

// ── STEP 2: within-family disambiguation, where the CONTRASTS live ────────
// Three options, not seventeen — which is what makes contrastive descriptions
// affordable. Each says what it computes, what it does NOT answer and who does,
// and which ambiguous phrasings it OWNS. That third part is the one that does
// the work: the intersection is a fact about natural language (people will keep
// saying "gap"), so it is partitioned EXPLICITLY rather than left to a coin flip.
//
// Every tiebreaker below came from a MEASURED flip in the eval, not from
// imagination. The instability map is the specification.

class NotComputableInFamily {
  // @@intent_id: no_intent_match
  //
  // REFUSAL LIVES HERE, NOT AT THE FAMILY LEVEL (2026-08-23). Three runs had
  // `oom-roi` ("what is the ROI on ERP Modernization") route rather than refuse,
  // and the family classifier was NOT wrong: ROI *is* a money question. It is a
  // money question this system cannot compute.
  //
  // Putting NONE in the family enum as a peer of the subjects was a CATEGORY
  // ERROR: it asks "is this about money or about nothing", when the real
  // structure is two independent axes — WHAT IS THIS ABOUT (family) and CAN WE
  // ANSWER IT (coverage). A question can be money-shaped AND unanswerable, and
  // the taxonomy had no way to say so, which is why a fat-margin step sailed
  // past it three runs straight.
  //
  // Relocated because the discriminating information can only exist here: you
  // cannot write "which money questions we cannot answer" as a family-level
  // contrast, but you can write it perfectly among three named computations.
  out_of_model_concept string
  reason string
}

function RouteMoneyIntent(question: string, context: string) -> ShowCostCurve | ShowFundingGap | CoverageGap | NotComputableInFamily {
  client Ollama
  prompt #"
    This is a MONEY-family planning question. Choose which of three it is.
    These three are genuinely different computations. Read the walls carefully —
    the words people use for them overlap; the computations do not.

    ShowCostCurve — spend per period, against an optional cap.
      Answers: "are we spending more than planned?"
      NOT commitments-vs-requirements (that is ShowFundingGap).
      OWNS these phrasings: "over budget", "overspent", "exceeds the cap",
      "capex versus expense", "how the money is phased".

    ShowFundingGap — required minus committed, per org or per initiative.
      Answers: "do commitments cover requirements? who has not put up their share?"
      NOT spend rate (that is ShowCostCurve).
      OWNS these phrasings: "underfunded", "funding short", "under-committed",
      "who owes what they have not committed".

    CoverageGap — capabilities NO project is maturing; processes with no
    capability behind them.
      Answers: "what is nobody working on?"
      NEVER a money question, despite the word "gap". If the question is about
      money at all, it is one of the two above.
      OWNS these phrasings: "nobody is working on", "no project is advancing".

    NotComputableInFamily — a money question this system does not compute.
      Answers nothing; it REFUSES, by name.
      This model carries SPEND, COMMITMENTS and COVERAGE. It does not carry
      RETURN. So: return on investment, ROI, payback period, NPV, valuation,
      benefit or business case are money-shaped questions with no computation
      behind them. Name the concept in `out_of_model_concept`.
      This is NOT for questions that merely fit one of the three imperfectly —
      an imperfect fit that returns useful rows is still the right route.

    THE SHORT RULE: over-budget is spend-versus-plan. Underfunded is
    commitments-versus-requirements. "Gap" alone never means CoverageGap unless
    the question is about what is being WORKED ON rather than paid for. And a
    money question about RETURN rather than spend or commitment is not computable
    here at all.

    QUESTION:
    {{ question }}

    CONTEXT:
    {{ context }}

    {{ ctx.output_format }}
  "#
}
