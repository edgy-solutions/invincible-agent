---
iri: docs:cortex-capabilities-primer
# The concepts this primer explains — each edge points at the IRI that DELIVERS
# the feature. Every target must exist in the graph (the invented-IRI rule),
# which makes this doc's own ingest a TRUTH-CHECK on the doc: a claimed
# capability whose verb doesn't exist fails the gate. [roadmap]-tagged features
# below carry NO edge (they explain nothing that exists yet) — so the
# live/roadmap distinction is machine-enforced, not editorially maintained.
# SEED list of confirmed IRIs; the builder completes it against the registered-
# verb list at ingest, and work's overlay may shadow this page.
explains:
  - mesh:LineageTopology
  - mesh:ImpactSet
  - mesh:resolveInstance
  - mesh:InstanceResolution
  - mesh:queryKnowledgeGraph
  - mesh:retrieveKnowledge
  - mesh:GraphQuery
doc_kind: reference
audience_hint: leader
---

# The Cortex / iagent toolchain — what it does for you

> You ask in **plain English**, get an answer **with its provenance shown** (so you can trust it), the system is **honest when it's unsure** (it asks or abstains rather than guessing wrong), everything is **governed by who you are** (you only see what you're entitled to), decisions run **human-in-the-loop with an audit trail**, and it **gets better the more you correct it**. No SQL, no knowing where data lives, no separate tool per data source.

**How to run a priming session with this doc:** lead each group with the *recognition questions* — the ones that make someone see their own pain — then let the features land as the relief. People don't request features; they recognize problems. The tags **[live] / [in rollout] / [roadmap]** are honest — use them so nobody hears a promise you can't keep.

---

## Part A — For the people *building* on it (data engineers making data products)

**Ask these first (recognition questions):**
- How long does *"what breaks downstream if I change this table"* take you today — and how confident are you that you found everything?
- Where does your access-control logic live, who audits it, and how many times have you re-implemented it per data product?
- When you ship a data product, how much of it is **glue you'll personally own forever** — and what happens to it when you move teams?

**What answers them:**

- **Your contribution rides declared rails — it stays durable and fundable, not a script you own forever [live/roadmap].** This is the deepest one: your domain content — ontologies, rules, mappings, workflows — plugs in **without touching mechanism**; your ingestion **declares what its source is and what it cannot say**; your work stays inside your walls via **overlays**. That's what turns "another one-off someone maintains" into a governed, hand-off-able asset. *(For the people you're recruiting to build on this, this is often the decisive feature.)*
- **Ask-the-catalog in natural language [live].** "What tables feed the Customer 360 dashboard?" → the answer *and* the real upstream tables. Kills the "which of our 4,000 tables" tax; onboards you to an unfamiliar estate in minutes.
- **Deterministic lineage / impact analysis [live].** Before you touch a table, trace every downstream dashboard, report, and asset that depends on it — *deterministically*, with **honest outcomes** (the list vs. "no upstreams" vs. "couldn't locate that asset"), never a confident wrong answer.
- **Coverage & gap analysis [roadmap].** *Before* you build, ask "what do we have to answer X, and what's missing?" — it surfaces lineage gaps, missing join keys, and DQ issues, and proposes the nearest join candidates. Weeks of dead-end exploration → a feasibility check.
- **Author workflows by interview, not by hand-coding [in rollout].** Build a repeatable data-product/process by being walked through a menu of *authorized* subjects + verbs — the system only offers choices that actually route, so you can't build a dead-end. (Replaces hand-authoring BPMN.)
- **Turn an answer into a workflow step [in rollout].** Ran a good ad-hoc query? Seed it directly as a governed step — productize exploration instead of re-deriving it.
- **Encode business logic as ratifiable rules, not code [live].** "What to do when this condition/change occurs" lives as **policy-as-data** a steward can ratify and audit, tunable per environment without a code redeploy.
- **Entitlement/authorization built in [live].** Your data product automatically respects who's allowed to see what — no per-product access control, and it passes audit because the gate is the same everywhere.
- **The system learns from your corrections [live → roadmap].** Override-with-reason feeds the rules today; disambiguation picks will feed the resolver's aliases next — corrections become *durable* improvements, so the same manual fixup doesn't recur.
- **Routing & workflow observability [live].** The Live Context HUD shows how a question resolved, which engine answered, the confidence, and the provenance tier — "why did it answer that?" is debuggable, and you can watch workflows run.
- **One surface over many sources [live].** Catalog, knowledge graph, technical documents, and analytics behind one natural-language door, routed automatically — no tool-hopping.

---

## Part B — For the people it *serves* (sustainment, manufacturing, quality, supply chain, program/finance)

### Cross-cutting (everyone)

**Ask first:** *When a system gives you an answer today, can you see where it came from? When it's been wrong, could it show you why? And when automation makes a call, what evidence would you need before you'd trust it?*

- **Evidence you can see, not just cite [live].** Click a part in a review and the **original vendor PDF page appears with the source value highlighted** — and when the extraction *couldn't* anchor a value, the system **says so and shows you the page to check yourself.** Every domain expert has been burned by a tool that transcribed a document wrong and couldn't show its work; this is the feature that converts skeptics.
- **A trust lifecycle you control [in rollout].** New vendor formats start **fully supervised**; every decision is **recorded as evidence**; you **promote to automation only when the record proves it earned trust**, and **one bad check demotes it automatically.** This is the answer to the first question every skeptical director asks — *"what if it's wrong?"*
- **Self-serve answers in plain English, with a sources trail [live]** — no analyst-in-the-loop for routine questions.
- **An honest assistant [live → roadmap].** It says *"did you mean the X dashboard or the Y dashboard?"* or *"this is a multi-step goal — here are the pieces I can answer now"* instead of guessing wrong. (Honest abstention is live; disambiguation + goal-shape card are roadmap.)
- **Role-appropriate views [live].** You see what's relevant to your entitlement and persona — not the whole firehose.
- **Human-in-the-loop with an audit trail [in rollout].** Review, approve, or override-with-reason; every decision is attributable.

### Sustainment / obsolescence & change management
**Ask first:** *When a change notice arrives, how many systems do you touch before the first disposition is made? Who finds out if a part on that notice got missed? How would you prove, a year later, why a part went last-time-buy?*
- **Change-notice (PCN/PDN) grouped review [in rollout].** One card lists *all* affected parts → per-part disposition (qualify replacement, last-time-buy, override-with-reason) → approve. Compresses obsolescence response; helps avoid line-down.
- **Auto-opened qualification tasks** from a disposition decision — the "qualify the replacement" work item is created for you.
- **Procedure & diagram lookup [live].** "Find the maintenance procedure / the diagram for X" — semantic search over the technical manuals (the system knows *TechnicalManual*, *Diagram*, *ProcedureStep* as first-class things).

### Manufacturing / production engineering
**Ask first:** *How does a design change reach the floor today — and how do you know which work instructions and parts it touched?*
- **BOM & change-impact queries [live/roadmap].** What parts are on this BOM; what's affected by an ECO.
- **Work-instruction & diagram retrieval [live].** Shop-floor reference without digging through a document store.
- **Supplier/lead-time flags [roadmap].** Flag components with both a lead-time increase and a cost-variance move.

### Quality / compliance
**Ask first:** *When an auditor asks where a reported number came from, how long does the answer take — and do you catch bad data before it reaches a decision or after?*
- **Lineage for traceability & audit [live].** Prove where a number came from, end to end.
- **Data-quality surfacing [roadmap].** Find poor-quality or gap-ridden data *before* it's used.
- **Nonconformance/review workflows [in rollout].** The same approval machinery, pointed at quality gates.

### Supply chain / procurement
**Ask first:** *Which of your single-source parts are also under cost or lead-time pressure right now — and could you answer that without a week of spreadsheet stitching?*
- **Supplier-performance & unit-cost queries [live/roadmap].** Single-source risk; components with lead-time + cost-variance pressure.
- **Join-candidate bridging [roadmap].** No direct key linking vendor performance to unit cost? It proposes a fuzzy-match / intermediate-table strategy instead of shrugging.

### Program / finance / affordability
**Ask first:** *How long does a cross-domain cost/affordability question — spanning engineering, supply chain, and finance — take your team today, and how much of that is finding the data vs. doing the analysis?*
- **Cross-domain risk investigation [roadmap].** Pose a goal — "assess affordability/cost risk across engineering, supply chain, and finance" — and the system explores the catalog, **proposes the joins and the risk definition, names the data gaps, and pauses for your approval before running anything.** The headline: analysis that today eats weeks of analyst time becomes a plan you review.

### Decision-makers / leaders
**Ask first:** *When automation makes a call on your behalf, what evidence would you want before trusting it — and does anything you run today actually produce that evidence?*
- **Trustworthy self-serve answers [live]** — provenance-backed; no analyst needed for routine questions.
- **Approve plans, not just queries [in rollout → roadmap].** Multi-approval join with an audit trail; and (roadmap) pose a *goal* and get a plan to approve rather than a raw report.

---

## The differentiators to hammer

Plain-English in, **provenance out**; **honest** (asks/abstains, never confidently wrong); **evidence you can see** (the source page, highlighted); a **trust lifecycle you control** (supervised → earned → auto-demoted); **governed by default**; **human-in-the-loop with audit**; **self-hardening** (better with use); and **one interface** over catalog + graph + documents + analytics.
