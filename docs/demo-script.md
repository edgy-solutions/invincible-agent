# Work-Cluster Demo Script (placeholder template)

**Status:** Current as of B4-complete (four content-kind verbs shipped) + Tier-3
verified. Committable — contains ZERO proprietary data. All asset references are
typed placeholders (`<TOKEN>`); real names are substituted locally at demo time
via §6, never committed, never sent anywhere.

**This one file does two jobs now** (B4 verb-priority is done, so that third job
retired): (1) the demo script you run in the room, (2) the deploy's matrix-row
spec (placeholders → real work-catalog assets).

---

## §0. Readiness legend

| Tag | Meaning |
|-----|---------|
| ✅ READY | Works today on the deployed system; safe to demo live. |
| ⚙ READY-PENDING-SYNC | Capability is live; needs a one-time ops/catalog sync to demo against (see the row's note). |
| 🔭 ROADMAP | Real direction-of-travel, NOT live; show as a slide, never as a live query that would fall through. |

**The cardinal demo rule:** never run a 🔭 row as a live query. A query that
falls through to the generalist in front of the audience reads as failure even
when it's correct behavior. Roadmap items are slides.

**Named-identifier insulation (use it deliberately).** Queries that name a
specific identifier (a DMC, a wpno, a catalog URN) route through instance
resolution *before* any class-vocabulary contest happens — so they're the most
robust live rows. When you want a guaranteed-clean demo moment, name the thing.
When you want to show semantic routing, describe it. Pick per row on purpose.

---

## §1. TIER 1 — Catalog + lineage Q&A (the safe core)

Exercises the catalog phone book (Engine D) + lineage graph. Backed by data you
can visually confirm in DataHub before the demo.

| # | Question (template) | Capability | Expected routing behavior | Tag |
|---|---------------------|------------|---------------------------|-----|
| 1 | "Who owns `<DASHBOARD_A>`?" | instance resolution → ownership | `instance_resolved=true`, provider=catalog, owner returned | ✅ READY |
| 2 | "What is the source of truth feeding `<DASHBOARD_A>`?" | lineage walk | resolves dashboard → walks lineage → names the Snowflake source | ✅ READY |
| 3 | "Tell me about `<SNOWFLAKE_TABLE_1>`." | instance resolution (provenance showpiece) | LLM guesses a class; catalog OVERRIDES to real type; **both shown on screen** | ✅ READY |
| 4 | "What's the owner / schema / freshness of `<DBT_MODEL_X>`?" | catalog attribute lookup | attribute returned with provenance | ✅ READY |

### The lineage showpiece (row 2) — the DataHub contrast

**Structure this as a side-by-side, because the audience may already know
DataHub renders the graph.** The point is NOT "we reproduce the DataHub graph"
— DataHub already shows it. The point is: *DataHub makes you click through the
graph; the tool lets you ask it.*

1. Show the DataHub lineage graph for `<DASHBOARD_A>`: dashboard → charts →
   dataset → tables → Postgres/ClickHouse ↔ Snowflake. **This is the evidence
   slide** — proof the data is real, complete, and bidirectional.
2. Then ask the tool row-2's question in natural language. It collapses the
   multi-hop click-through into one answer.
3. The contrast IS the capability: same data, manual navigation vs. a question.

---

## §2. TIER 1b — The failure demo (the trust-builder)

Put this in. With a technical audience, a system that refuses to confabulate
lands harder than any success — everyone has been burned by a tool that
confidently made something up.

| # | Question (template) | Capability | Expected behavior | Tag |
|---|---------------------|------------|-------------------|-----|
| 5 | "Tell me about `<DELIBERATELY_UNGROUNDABLE_THING>`." | abstention / graceful degradation | `instance_resolved=false` → generalist; **no fabricated answer** | ✅ READY |

Narrate it: "Watch what it does when it *can't* ground the question." The honest
`false` + fall-through is the whole safety thesis in one query.

---

## §3. TIER 2 — Needle-in-haystack (the glory — retrieval ready, join-plan roadmap)

This is where the complete lineage graph becomes an ASSET: the bigger and more
complete the haystack, the more impressive natural-language candidate-surfacing
is versus manual navigation.

| # | Question (template) | Capability | Expected behavior | Tag |
|---|---------------------|------------|-------------------|-----|
| 6 | "Which tables and sources are relevant to building `<DATA_PRODUCT_CONCEPT>`?" | knowledge retrieval over catalog/lineage | **surfaces candidate tables** across a graph too large to eyeball | ✅ READY (as retrieval) |
| 7 | "...and how do I join them — which keys, which order?" | multi-hop composition (ADR-0011) | constructs an actual join plan | 🔭 ROADMAP |

**The honest framing for row 6:** "here's what's *relevant* across a graph you
couldn't scan by eye" — candidate surfacing, NOT a constructed join. Do not
imply it computes the join. Row 7 (the join plan) is the roadmap close — show it
as where-this-goes, never as a live query. This is the "end goal, not
necessary" the team named; treat it accordingly.

---

## §4. TIER 3 — Data path / backend fetch (LIVE-architecture; dispatch path needs investigation)

| # | Question (template) | Capability | Expected behavior | Tag |
|---|---------------------|------------|-------------------|-----|
| 8 | "Fetch a sample of rows from `<SNOWFLAKE_TABLE_1>`." | routing → **live backend execution** (Engine DA) | route to Engine DA → Engine DA's smolagent uses URN to execute via `query_datahub_asset` → return rows | ⚙ READY-PENDING-INVESTIGATION |

**Routing layer LIVE.** Engine D's `/query_metadata` returns the demo URNs cleanly
(confirmed 2026-06-16: `urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)`
returns description, lineage, columns at score 1.0). Engine D's
`mesh:resolveInstance` against `idp:Table` resolves the dataset and routes to
Engine DA via `mesh:analyzeDataset`. The architecture path is real.

**The reframe from "catalog sync" to "tool-roster investigation."** The earlier
characterization of this as a ~5-minute catalog sync was based on an incomplete
diagnosis. Direct probe of Engine D shows the catalog is correct — the URNs ARE
in DataHub, with full metadata. **The actual question is what happens *inside*
Engine DA's smolagent loop.** Engine DA's agent has `tools=[query_datahub_asset]`
only; its augmented prompt instructs the agent to "call `search_datahub` first
to discover the URN" — but `search_datahub` is not in its tool roster (that tool
lives in Engine A). Two paths reconcile this:

  - **Path (a) — supervisor passes the URN.** If the central gateway forwards
    Engine D's resolveInstance result (the URN at score 1.0) into Engine DA's
    invocation context, the agent has the URN from upstream and `query_datahub_asset`
    works directly. Demo row 8 lives or dies on whether this passing happens.
  - **Path (b) — add `search_datahub` to Engine DA's tools.** Small code change
    in `agent_fleet/data_analyst/main.py`: add the same `search_datahub` tool
    Engine A defines. Removes the dependency on the supervisor-URN-passing
    behavior.

**Until path (a) is confirmed or path (b) is shipped, treat row 8 as
demo-uncertain.** A separately scoped session pulls one query end-to-end through
the central gateway, captures whether the URN is passed into Engine DA's
context, and either confirms ✅ or ships path (b). That session is "bigger than
5 minutes" but smaller than a sprint — it's an investigation with a known
exit on either side.

**Demo-day fallback if row 8 remains uncertain:** show the *routing* step live
(question → Engine DA dispatch, latency-evident), and present the URN/SQL
generation as a screenshot/walkthrough rather than running it cold. The routing
+ tool-roster discipline is the demonstrable capability; the live row execution
is the polish atop it.

---

## §5. TIER 4 — Manuals (maintenance / tech-manual) — now LIVE

**Scope note.** This tier is **maintenance / technical-manual** content
(S1000D + MIL-STD-40051, ingested via B2/B3a). It is **not** manufacturing
work-instructions — manufacturing is a separate, not-yet-demoable track (the
`mfg:*` classes lack a Weaviate corpus entry; see "Out of scope" below). Don't
phrase these rows as manufacturing.

All four content-kind verbs shipped in B4. Each content kind routes via its
typed verb. **Phrasings below are the probe-tested ones that resolve for the
right reason** — use these, not paraphrases, since the content-kind boundaries
are lexically sensitive (a "steps to..." phrasing resolves to the *content*
layer, a "what data module..." phrasing to the *document* layer; see the note
after the table).

| # | Question (template) | Content kind | Expected routing behavior | Tag |
|---|---------------------|--------------|---------------------------|-----|
| 9 | "Tell me about work package `<DMC_OR_WPNO>`." | (instance) | named-identifier → instance resolution → content kind w/ provenance | ✅ READY |
| 10 | "Search the technical manuals for `<MAINTENANCE_TOPIC>`." | baseline | `retrieveKnowledge` → manual chunks returned | ✅ READY |
| 11 | "Show me the fault-isolation procedure for `<SYSTEM>`." | `mil:FaultIsolationDataModule` | resolves to FaultIsolation kind → Engine W | ✅ READY |
| 12 | "What procedure data module covers `<MAINT_TASK>` removal and installation?" | `mil:ProcedureDataModule` | resolves to Procedure DM (document layer) → Engine E | ✅ READY |
| 13 | "Show me the illustrated parts breakdown for `<ASSEMBLY>`." | `mil:IllustratedPartsDataModule` | resolves to IPD kind → Engine W | ✅ READY |
| 14 | "What is `<COMPONENT>`?" / "Describe `<COMPONENT>`." | `mil:DescriptiveDataModule` | resolves to Descriptive DM → Engine W | ✅ READY |

### The manuals showpiece (row 11) — confidently-wrong → correct

The strongest manuals moment is the before/after captured in B4 verb 1. Frame it
as **"watch it stop being confidently wrong,"** not "we added a verb":

- *Before* (pre-verb / mis-tagged domain): a fault-isolation question resolved to
  `WorkInstruction` at 0.95 — **confidently wrong**, because that was the only
  routable class in the maintenance domain.
- *After*: the same question resolves to `mil:FaultIsolationDataModule` at 0.97,
  dispatched to Engine W's manual-search endpoint — **correct, with provenance.**

That's the whole correctness-over-coverage thesis in one slide.

### Why the phrasings matter (the lexical-boundary note)

Content kinds with *strong distinctive vocabulary* (illustrated-parts,
fault-isolation) resolve cleanly on almost any phrasing. Content kinds with
*weak/overlapping vocabulary* (procedure-data-module vs. work-instruction vs.
descriptive) are sensitive: "steps to install X" wants the *content* layer,
"what procedure data module covers X" wants the *document* layer. For the demo,
use the document-framed phrasings in the table (proven to route correctly). The
structural fix that would make all phrasings robust is banked as **ADR-0020**
(non-urgent; lexical anchors hold today). Named-identifier queries (row 9) are
insulated from this entirely — instance resolution preempts the contest.

---

## §5c. Substrate-DNS reconciliation note (durability check finding, 2026-06-16)

The consolidation session surfaced a drift: three pre-B4 substrate edges
register endpoint URLs against a legacy K8s DNS pattern
(`weaviate-expert-svc.default.svc.cluster.local`,
`neo4j-expert-svc.default.svc.cluster.local`) that doesn't resolve in the
current cluster (services live at `iagent-engine-w` / `iagent-engine-e`).
Affected rows for dispatch (NOT routing — routing is fine for all of them):

- **Row 10** ("Search the technical manuals..."): substrate edge for
  `TechnicalManual` → `mesh:retrieveKnowledge` uses legacy DNS.
- **Engine E's WorkInstruction + ProcedureStep edges**: also legacy DNS (rows
  9/12 are protected by named-identifier instance resolution and the new
  ProcedureDataModule edge, but legacy-DNS dispatch is at the same registration
  identity).

Source-code defaults are now correct (committed this session); helm values
explicitly pin `ENGINE_W_PUBLIC_URL` and `ENGINE_E_PUBLIC_URL` to the right
service names. **Substrate reconciles automatically on next image rebuild +
pod restart** — the source-level `register_engine_to_mesh()` calls overwrite
the legacy edges with the correct URL. **Until that deploy lands**, dispatch
for Row 10 (and any path that touches the legacy WI/ProcedureStep edges) will
fail to reach the engine pods.

Demo-readiness implication: re-confirm dispatch on the work cluster *after*
the deploy that ships this fix. The matrix (routing layer) was 22/22 throughout
— the discrepancy is purely in the endpoint URL on the substrate edge.

Banked separately for follow-up (not in this consolidation's scope): Engine A
and Engine DA have the same systemic legacy-DNS pattern in their source
defaults (`restate-agent-svc.default.svc.cluster.local`,
`data-analyst-svc.default.svc.cluster.local`,
`datahub-wrapper-svc.default.svc.cluster.local`). Same fix shape; separate
session.

---

## §5b. Out of scope for this demo

- **Manufacturing work-instructions** (`mfg:*`). Not demoable: the manufacturing
  classes exist in Neo4j but have no Weaviate Class-corpus entry at
  `domain='MANUFACTURING'`, and no verbs are typed against them. Banked as a
  separate track (Gap-1 corpus + verb-typing). Don't field manufacturing
  questions live.
- **Join-plan construction** (Tier 2, row 7). Roadmap slide only.

---

## §6. Real-name substitution table (fill LOCALLY at demo time — DO NOT COMMIT FILLED)

| Token | Real asset (fill in your environment only) | Type asserted by the script |
|-------|--------------------------------------------|------------------------------|
| `<DASHBOARD_A>` | _(a Superset dashboard with full downstream lineage)_ | Superset dashboard, deep lineage to Snowflake |
| `<SNOWFLAKE_TABLE_1>` | _(a Snowflake table)_ | Snowflake table (source-of-truth tier) |
| `<DBT_MODEL_X>` | _(a dbt model)_ | dbt model with owner/freshness metadata |
| `<DATA_PRODUCT_CONCEPT>` | _(a domain concept spanning several tables)_ | concept with enough catalog metadata to surface candidates |
| `<DELIBERATELY_UNGROUNDABLE_THING>` | _(something the catalog genuinely doesn't have)_ | absent from catalog — must NOT resolve |
| `<DMC_OR_WPNO>` | _(a real ingested DMC or 40051 wpno)_ | manuals instance identifier |
| `<MAINTENANCE_TOPIC>` | _(a topic present in ingested manuals)_ | manuals search term |
| `<SYSTEM>` | _(an equipment system with fault-isolation content)_ | maps to a FaultIsolation data module |
| `<MAINT_TASK>` | _(a maintenance task covered by a procedure module)_ | maps to a Procedure data module |
| `<ASSEMBLY>` | _(an assembly with an illustrated parts breakdown)_ | maps to an IllustratedParts data module |
| `<COMPONENT>` | _(a component with a descriptive module)_ | maps to a Descriptive data module |

Keep the filled version local. The committed file stays placeholder-only.

---

## §7. What this artifact feeds into the deploy

- **Deploy matrix rows:** rows 1–6 and 9–14 become the work-cluster matrix's
  expected-pass set (re-pointed from sandbox assets to the §6 real assets).
  Predict each row's expected behavior before the deploy matrix run.
- **Pre-demo ops:** the Tier-3 catalog sync (§4) is a deploy-time ops item —
  fold it into the deploy checklist so row 8 is live for the demo.
- **Phrasing discipline:** the Tier-4 rows use probe-tested phrasings; if you
  re-point them to different real systems, re-confirm the phrasing still
  resolves to the intended content kind (strong-anchor kinds are robust;
  weak-anchor kinds are phrasing-sensitive per §5).

---

## §8. One confirmation left to finalize (no real name required)

**Placeholder→type mapping** (§6): confirm the asserted types hold in your
reality — e.g., "yes, `<DASHBOARD_A>` is a Superset dashboard with lineage all
the way to Snowflake," or correct it ("our lineage stops at dbt"). Adjust the
expected-behavior tags accordingly. You can confirm/correct this generically, no
proprietary names required.

*(The earlier Tier-3 readiness confirmation is now resolved — see §4: live,
pending a catalog sync.)*
