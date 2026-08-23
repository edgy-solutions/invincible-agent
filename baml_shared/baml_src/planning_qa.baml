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
  // @@intent_id: coverage_gap
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

// ── BLOCKED: dependency traversal ─────────────────────────────────────────
// The SHAPES exist so the router can still recognise these questions and the
// rail can refuse them BY NAME. Engine P's plan_dependency_violations takes no
// project parameter and reports only breaches, so routing here to it would
// answer a different question AND go blank when nothing is violated — "nothing
// blocks it" when the truth is "three predecessors, all satisfied".
// The catalog carries `blocked:` with the pending verb
// (plan_dependency_neighborhood); when it registers, only the catalog changes.

class WhatBlocks {
  // @@intent_id: what_blocks
  project string
}

class DownstreamOf {
  // @@intent_id: downstream_of
  project string
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
  nearest_intent_id string?
  out_of_model_concept string?
  reason string
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
    - If nothing matches, or the question needs something the model does not
      carry (return on investment, risk ownership, headcount/staffing), return
      NoIntentMatch with the reason and the nearest intent. Choosing the nearest
      WRONG intent is worse than refusing: it produces a confident answer to a
      question nobody asked.

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
