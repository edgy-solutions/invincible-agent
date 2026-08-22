---
id:         portfolio-review-rev3-delta
status:     open
owner:      unassigned
blocked-on: architect fills C3's private-overlay path
closed-by:
code-site:  agent_fleet/planning_agent/types.py, agent_fleet/planning_agent/measures.py
repo:       invincible-agent
summary:    Revision 3 of the portfolio-review plan, in DELTA form — what sections B/C/D of the 2026-08-21 requirements packet ADD to what is already built, never a re-plan of section A. A is not merely planned, it is LANDED AND CITED (abf16fd, 83 tests), and re-deriving built work in a plan document is how a plan drifts from its own repo. Every B item names the existing type or verb it extends so a reader can tell extension from invention. Carries one correction back to the packet: the sandbox runs `gpt-oss-128k:120b`, so the Day-5 eval must assert the CONFIGURED model name, not the name a document remembers.
---

# Revision 3 — the delta against what is built

**Read [`portfolio-review-workshop-tool.md`](portfolio-review-workshop-tool.md) first.** This
document does not replace it. It records what the 2026-08-21 requirements packet adds, and it
is deliberately subordinate to the tree: where this and the repo disagree, the repo is right
and this is stale.

**Priority on conflict:** [ADR-0042](../adr/ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md)
> §A > §C > §B > §D. Where anything below conflicts with the ADR, the ADR wins and the conflict
is flagged rather than silently resolved.

---

## §A — already landed. Not re-planned here.

| item | state |
|---|---|
| A1 server owns plan state; ADR-0042 OQ1 + OQ2 disposed in one ruling | **built** — `abf16fd`, `agent_fleet/planning_agent/state.py` |
| A2 drag-optimistic / drop-evaluated, N measured on Day 2 | **ruled** — `abf16fd`, plan Gate 1 |
| A3 planning BAML functions pinned internal, no cloud fallback, fail closed | **ruled** — `abf16fd`, plan §4.2 |
| A4 Day-5 eval against the real endpoint, unconditional | **ruled** — `abf16fd`, plan §4.2 |
| A5 vLLM vs Ollama | **answered** — sandbox Ollama, work vLLM, same weights and context, different NAME |

### A4 — a correction owed back to the packet

The packet cites the model as `gpt-oss:120b`. Probed live 2026-08-21, the sandbox is configured
for **`gpt-oss-128k:120b`** (`helm/invincible-agent/values-sandbox.yaml:174`, 131072 context).
Both tags exist, so this was never going to 404 — it is a silent context divergence.

**So the Day-5 eval asserts the CONFIGURED name, read from `env.OLLAMA_MODEL`, not a name
copied from a document.** This is the same class as the two-field presentation gate: assert what
the system reports about itself, never what a document remembers about it. A test asserting the
packet's cited string would fail against a correctly-configured system, which is the worst
possible direction for a gate to be wrong in.

Related, and still true: **`gpt-oss:20b` is not on the endpoint at all**, so any fallback clause
naming it is a permitted fallback to a 404.

---

## §B — customer-requirement deltas, each citing what it extends

### B1 — type additions

All of these EXTEND existing dataclasses in `agent_fleet/planning_agent/types.py`. None
introduces a new entity.

| addition | extends | note |
|---|---|---|
| `executive_owner`, `business_owner`, `technology_owner` | `Portfolio`, `Initiative` | upper-tier ownership |
| `owner` | `Phase`, `Project` | single owner at the working tiers |
| `priority`, `criticality` | `Initiative`, `Project` | ordinals, labels are data (see C) |
| `timing_confidence` | `Phase` | how firm the interval is |
| `status: pending \| committed \| approved` | `FundingCommitment` | **the enum replaces nothing** — the type exists and gains a field |
| `attributes: dict` | every entity | the extras map (see below) |

**Funding at-risk is DERIVED, never stored.** `committed + approved < required` is computed by
`plan_funding_gap`, which already computes `required - committed` per group per period. A stored
`funding_gap` field is refused: stored-beside-derivable is the two-masters defect in miniature,
and this plan has already paid for that class twice.

**The extras map answers the NoSQL ask without becoming one.** An `attributes` dict per entity
satisfies "highly configurable attributes" now; the graph substrate at Phase 8 is the real
answer. Rationale worth recording because it will be asked again: **their question list is
join-heavy and interval-heavy — the two things document stores are worst at.** Q7 walks
project→capability→process; Q9 asks which targets are affected *and when*; Q10 compares two
intervals against a constraint. A document store makes each of those an application-side join.

### B2 — maturity

`MaturityAssessment` already carries `level`, `target_level`, `assessed_at`, `assessed_by`,
`evidence_ref`, and is already append-only. Two additions:

- **A configurable named ordinal scale** — the labels are DATA, not code (C2: ship a neutral
  1–5 or CMMI-style default; customer labels load from overlay). Extends the type with a
  `scale_id`; the label table is config.
- **Per deployment target** — already the case. `MaturityAssessment.site_id` is per-target
  today, and `plan_maturity_grid` already returns a capability × target matrix.

**Their prompt dropped per-target maturity while their question list still demands it.** Keeping
per-target resolves their own contradiction in their favour, and costs nothing because it is
what exists.

### B3 — `Site` generalises to `DeploymentTarget`

Extends `Site` with `type: site | program` plus an interval and status. **The load and
saturation machinery is unchanged** — `SiteImpact` already carries its own window and
`saturation_threshold` is already a per-subject governance field. This is a rename plus two
fields; `THRESHOLD_GRID` is already domain-blind and needs no change at all, because it draws
"subjects × periods against a threshold the subject owns" and has never known what a subject is.

### B4 — verb additions

| verb | output type | note |
|---|---|---|
| **coverage-gap** (new, twelfth) | `mesh:CoverageGapSet` | processes and capabilities covered by NO initiative — an ABSENCE query |
| `group_by ∈ {strategy, capability, target}` | param on existing `plan_schedule` | the timeline pivot — see the finding below |
| `risk_flag` | field in `plan_schedule`'s rows | generic; funding-risk is today's only producer |
| `color_by` | standard param on schedule and grid verbs | values ride the payload |

**The coverage-gap verb is the only genuinely new one.** It is an absence query, which is worth
naming because absence is the thing this model is best placed to answer and the thing a
spreadsheet cannot: "which processes have no initiative touching them" requires the
capability→process edge (`Capability.enables_process_ids`) and the project→capability edge
(`CapabilityContribution`), both of which exist.

**`risk_flag` and `color_by` are generic by construction (GENERIC-AT-BIRTH).** The renderer
receives a flag and a colour key; it never learns that today's flag means funding risk. A
contract clause states the vocabulary rides the payload.

### THE PIVOT ALREADY HAS ITS DATA MODEL — do not add the join table

B5's group-by-capability pivot is flagged marquee and un-cuttable, and it **needs no model
change**. `CapabilityContribution` (project_id, capability_id, weight) is already the
many-to-many, and initiative↔capability is already **derived** from it via
`PlanState.initiative_of_project` rather than stored in parallel — the two-writers rule, applied
when the type was written.

So the marquee feature is a `group_by` parameter on an existing verb.

**This line exists so nobody later "adds" the join table that is already there.** The flat model
the requirement complains about is not this model; it was the source model, and the gap was
closed in Phase 0.

### B5 — Phase 1 UI additions

| addition | how it falls out |
|---|---|
| quarterly timeline granularity | `FISCAL_PERIODS` is already the period vocabulary |
| **group-by pivot (MUST KEEP)** | a `group_by` param — see above |
| collapsible filter panel | **filters are VERB PARAMS, not view logic.** Shared params fed to every live view; falls out of the architecture rather than being built |
| KPI strip | one more filter-scoped live view (stat-summary archetype). **Cuttable under schedule pressure; the pivot is not** |
| **card slots editable in place** | the interpretation card becomes the VIEW-CONTROL surface on every live view (group_by, window, scope, color_by) — not only a Q&A artifact |

The last one is the largest and is worth stating as a contract consequence: if the interpretation
card controls a live view, then a live-view card's params are user-editable, and **an edit is a
re-evaluation** — which is exactly ADR-0042 §4's per-evaluation `valid_as_of`. It costs nothing
because the ruling already covers it.

---

## §C — open-source vocabulary tiering (BINDING; this repo is public)

**C1 tiering.** Code = structural names only (already ruled, ADR-0042 §7 and enforced by a test
per contract). Shipped defaults and example seed = citable industry-standard vocabulary only.
Customer-specific terms = customer-side overlay, never committed.

**C3 seed split — audited 2026-08-21, no exposure.** Every proper noun in
`agent_fleet/planning_agent/seed.py` was invented: target names are alphabetical placeholders,
process names (`Order to Cash`, `Plan to Produce`) are APQC-standard and shippable under C2, and
the capability and initiative names are generic PPM vocabulary. One tightening applied in
`6e0cb55`: the technologies named real vendor products, which are citable under C5's litmus but
in a public repo's *demo seed* read as somebody's actual stack. Now generic categories with
identical modelling weight.

**What C3 still needs is the LOADER, not a scrub.** The seed builder must accept an overlay
path — same schema, same loader, path outside the repo, absent by default. **The path itself is
the architect's blank.** Until it is filled, `build_seed()` stays the shipped generic dataset and
the gates run against it, which is what C3 asks for anyway.

**C5 litmus, restated for anyone adding a name:** citable to a public standard or an incumbent's
public documentation → shippable; otherwise → overlay.

---

## §D — competitive framing and script deltas

**D1 — this is a bake-off, and at least one competing output is a static mockup.** A mockup looks
finished and can answer nothing, diff nothing, persist nothing, refuse nothing. So the script
majors on the arc a mockup cannot fake: **ask → drag → diff → commit → reload**, front-loaded.

**D2 — new beats.**
- **Group-by-capability pivot**, live. It demonstrates the many-to-many a flat model cannot
  express, which their own UI ask requires.
- **Spoken mutation:** "set the Q3 capex for [project] to 500k" through the chat rail →
  interpretation card confirms → the curve moves. Framed against incumbent form-entry.
- **The line to rehearse:** *in this tool the meeting is the data entry.* Dragging a bar enters
  schedule data; a typed cost enters funding data; a commit-with-rationale enters decision data
  no incumbent captures. Freshness rides the meeting cadence, not an admin's backlog.

**D4 — honest scope on entry, and it belongs in the plan rather than the pitch.** Bulk initial
population is real work no conversation removes; it is the Phase-7 ingestion seam (CSV import
with lineage — this data always already lives in someone's spreadsheet). **In-meeting capture is
for CHANGES and DECISIONS; import is for ONBOARDING.** Claiming otherwise in a room where
someone has done a migration would cost more trust than the feature wins.

*(D3's incumbent framing is deliberately not recorded here — it is positioning for a room, not
an architectural fact, and this repo is public.)*

---

## Acceptance for this revision

- [ ] Every B1 field added to `types.py` with its why-comment; no stored `funding_gap`.
- [ ] `plan_funding_gap` derives at-risk from `status`; a test asserts the derivation and asserts
      no stored field exists.
- [ ] Coverage-gap verb implemented, declared in the ontology (both ends), seam-tested.
- [ ] `group_by` on `plan_schedule` with a test proving the capability pivot uses the EXISTING
      `CapabilityContribution` join.
- [ ] `color_by` / `risk_flag` generic — a test asserts no domain vocabulary in the contract.
- [ ] Seed loader accepts an overlay path; absent by default; gates run on the shipped dataset.
- [ ] Day-5 eval asserts the CONFIGURED model name, read from config, not a literal.
