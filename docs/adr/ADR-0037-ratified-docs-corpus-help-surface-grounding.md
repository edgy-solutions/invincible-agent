# ADR-0037 — Ratified-docs corpus + help-surface grounding (the graph is the index, docs are the leaves, `explains` is the edge)

**Status:** Proposed — design settled here; build is packet-sized and near-term (presentation + a docs-ingestion path, both on proven rails).
**Date:** 2026-08-03
**Deciders:** Platform team
**Related:**
  - [ADR-0031](ADR-0031-instance-resolution-ladder.md) — `resolved_via` provenance tiers (doc-search is a weaker tier, made visible).
  - [ADR-0033](ADR-0033-interrogative-disambiguation-ask-from-the-phonebook.md) — ask/abstain-don't-guess grammar (a help surface must not improvise about the system's own capabilities).
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) — `ruleset_ref` content-hash discipline (docs get `doc_ref`); decision records are part of what the graph self-describes.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — docs explain both planes; the priming one-pager is a cross-plane explainer.
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — seed/overlay composition; docs are ratifiable config and inherit it verbatim.
  - The existing citation discipline: `mesh:derivedFrom` (a rule → its source standard) is the template this ADR mirrors for `mesh:explains` (a doc → the concept it explains).

## Context

The instinct is a help system "driven from docs, not baked into code." The system is unusually well-positioned to do it **honestly**, on one condition: **don't build a docs corpus that describes the environment — the environment already describes itself.** The capability graph knows every verb and its subjects; the ontology knows every class with its `mesh:derivedFrom` citations; the workflow definitions are the process documentation; the trust table (ADR-0034) states what's automated vs. supervised; the decision records show what actually happens.

A hand-written `docs/*.md` corpus explaining "what can this environment do" would be the **lowercase-graph-map pattern at documentation scale** — correct at writing, stale at the first verb registration, and *nothing fails when it lies*. So the layering is fixed here, before any implementation, so explanations never get baked into prompts:

- **Capability answers derive from the graph** — "what can I ask about parts?" is computed from registered verbs ∩ the asker's actual entitlements. The answer is therefore **personalized and true by construction**: `alice`'s "what can I do" differs from `bob`'s, because Topaz says so.
- **Markdown carries only what the graph can't** — intent, conventions, the *why* (the two-plane authorship criterion, the provenance doctrine, "what is a disposition review *for*").
- **The answering surface composes both**: graph for what exists now, docs for what it means — and the **honest-degradation rule carries over**: a question the graph can't answer and the docs don't cover gets the abstain card, never an LLM's plausible improvisation about your own system.

### The keying decision (load-bearing)

You do **not** key docs to graph concepts with a new mechanism. A doc is **a graph citizen with an IRI**, and "keying" is ordinary triples — the same move `mesh:derivedFrom` already makes for rules:

```turtle
# today, in pcn_disposition_rules.ttl — a rule cites its source:
pcn:RuleDiscontinuedWithReplacement  a pcn:DispositionRule ;
    mesh:derivedFrom  <...standard...> .

# a doc is the same shape, one new predicate:
docs:disposition-review-explained  a mesh:DocPage ;
    mesh:explains   pcn:proposeDisposition ;   # points at the verb/class/workflow IRI
    mesh:doc_kind   "concept" ;
    mesh:audience_hint "reviewer" .
```

No embedding index as the primary mechanism; no path conventions doing semantic work; no frontmatter-as-database. Just assertions, **validated at ingest like every other assertion** — a doc that claims to explain `mesh:composeReviewBatch` fails ingest if that IRI doesn't exist (the invented-IRI rule, applied to documentation). That makes everything else mechanical: "what explains this verb" is a one-hop query; a doc explaining a retired verb surfaces in the same dangling-reference sweep that catches any other; the help surface composes graph-truth with doc-meaning by **walking edges, not by hoping a search index agrees with reality.**

## Decision

**The graph carries what exists; docs carry what it means; the join is triples, not search.** Five parts.

### 1. The doc model — one tiny new vocabulary

A single small TTL (a `mesh_docs` vocabulary, sibling of `mesh_system.ttl`):

- **`mesh:DocPage`** — the class.
- **`mesh:explains`** — doc → any graph IRI (a verb, an `owl:Class`, a workflow definition, an archetype). The sibling of `mesh:derivedFrom`.
- **`mesh:audience_hint`** — persona (`data-engineer` | `reviewer` | `leader`) — **display routing, not authz.**
- **`mesh:doc_kind`** — `concept` | `how-to` | `reference` | `rationale` (the Diátaxis split — "what is a disposition review" and "how do I override a part" are different answers and route differently).

Each doc's frontmatter declares its own IRI + its `explains` targets; ingest converts frontmatter → triples. **Two validation gates, both loud:**

- Every `explains` target must exist in the graph — **the invented-IRI rule**.
- **Every registered verb must have ≥1 explaining doc of `doc_kind concept`** — coverage enforced *bidirectionally*. This is the load-bearing gate: it converts "docs drift from reality" from a discipline problem into **a build failure** (register a verb with no concept doc → CI red, the way an unregistered archetype falls back honestly).

**Gate granularity — verbs only in v1** (resolved in review). The gate's cost is a human writing *meaning* per gated thing — that is its point — and **verbs are where the cost pays**: they are what users invoke and what the capability answers enumerate. **Classes** are too numerous to gate without becoming a stub-mill (the decorative-seal problem §5 names — hundreds of classes in a domain standard would be a stub-mill or a months-long writing project). **Workflow definitions** are self-describing: post-M3 they *are* the process documentation, and the WORKFLOW lens renders them — a concept doc per definition is real but wakes on the first definition a process owner authors, not on the seed corpus. The gate **expands per-kind on evidence the un-gated kind's absence actually misled someone** — the same evidence-gated expansion grammar as everywhere else.

### 2. Storage & lifecycle — docs are ratifiable config, full stop

- Markdown files in `docs/corpus/`, ingested via the same manifest path the ontology TTLs use, into a dedicated graph **`internal/DOCS`**. (The builder verifies which side of the reproducibility line this graph sits — seed content is **manifest-class, never prime-wiped** — and follows the existing `internal/{domain}` convention.)
- Content-hashed — a **`doc_ref`** per the `ruleset_ref` pattern (ADR-0034).
- **Seed/overlay per ADR-0036**: the open repo ships generic concept docs; work's overlay adds org-specific pages and may **shadow** seed pages (overlay-wins), with **layer-attributed provenance** so "who wrote this explanation" is answerable. The priming one-pager is the **first seed citizen** of this corpus (dogfood: the doc that primes people is also the first thing the help surface serves).

### 3. The answering surface — resolution ladder, then compose

The user doesn't speak IRIs. Between the sentence and the graph-walk sits **resolution** — and that is where the vector store earns its place, in the position the architecture rules it into everywhere else: **the vector DB nominates, the graph disposes.** This is not a compromise on the assertions-not-search design; it is the resolution ladder (the pattern that governs subject resolution, the phone-book, and ADR-0033 disambiguation) extended to one more question type. Three rungs, in order:

**Rung 1 — anchor resolution (graph-direct, highest tier).** If the sentence contains a resolvable anchor — "how do I *override* a part in a *disposition review*" — those tokens resolve through the existing ladder (exact / containment / alias) to IRIs, the `explains` walk fires, docs return by edge with **graph-grade provenance**. No vectors needed; the tier says so.

**Rung 2 — doc-semantic nomination (vector → validate → entitlement-filter).** When the sentence *describes* a capability without naming it — *"is there anything that tells me what breaks downstream if I change a table?"* — no token matches `traceLineage` or any registered name. Intent-to-capability is a **semantic-distance** problem, which deterministic matching is structurally blind to and embeddings are for. So: **embed the corpus** (the `concept` docs especially — written in user language *by design*: "impact analysis," "what breaks," "downstream dependents" all live in the lineage doc's prose though no verb is named there), retrieve candidate docs by vector similarity, then **dispose**: hop each candidate's `explains` edges back into the graph and validate — does the IRI exist, is the verb registered, **is the asker entitled to it.** The vector result is *never the answer*; it is a **nomination whose graph-validation is the answer.** A doc that matches semantically but explains a verb the asker can't invoke is filtered — or better, surfaces honestly as *"this capability exists but isn't in your entitlements,"* which the pure-vector answer could never produce. Carries **`resolved_via: doc-semantic`** so the weaker tier is visible (ADR-0031 provenance-tier doctrine).

**Rung 3 — abstain.** Neither anchor nor surviving nomination → the **abstain card** (ADR-0033). Never an LLM improvising about the system's own capabilities — a help surface that hallucinates features is the confident-wrong answer pointed at itself.

**Capability questions** ("what can I do with parts?") are Rung-1-direct: registered verbs ∩ the asker's entitlements, computed live → personalized, true by construction, with doc snippets attached via `explains` edges as the meaning layer. Snippets render with `doc_ref` + layer as **citations** — the same citation grammar as every other answer.

**Kind routing — unmarked questions default to `concept`, never ask** (resolved in review). A bare "tell me about X" answers with the `concept` doc even when a `how-to` also explains the same IRI — orientation before procedure (Diátaxis's own logic), and asking would be the **clippy failure: interrogation on the *strong* path**. The `how-to` surfaces as a **linked affordance** on the answer ("→ how to override a part") — summoned-not-resident, applied to doc navigation. ADR-0033's ask is reserved for **Rung-2 capability ambiguity**, where it's already specced (two surviving nominations → guaranteed-routable ask-card); it is never spent on kind-selection.

**Why both stores are necessary — and the governance the vector index inherits for free.** Because the embedded artifacts *are* the ratified docs — content-hashed, ingest-validated, coverage-gated, overlay-composed — the semantic layer **cannot drift from reality** the way a free-floating embedding index does. A retired verb's doc fails the dangling-`explains` sweep, leaves the corpus, and *thereby* leaves the index; a new capability can't exist un-embedded, because the coverage gate forces its doc into the corpus the index is built from. The classic vector-DB failure mode — confidently retrieving descriptions of things that no longer exist — is **structurally closed**, because the index is a **projection of governed content, re-derived on corpus change** (same content-hash trigger discipline as everything else). The Weaviate machinery already in the stack is the natural home, and this is arguably its most defensible use in the whole system, since here the embedded text and the graph truth share one validation boundary.

**Disambiguation composes on top (ADR-0033).** When Rung 2 nominates *two* plausible capabilities — "did you mean lineage tracing or coverage analysis?" — the ask-card fires with options that are **guaranteed-routable because they arrived through graph validation.** The vector store's strength is real and used; the design just refuses to let it be **load-bearing for truth** — nomination is its whole job, and in this system that is exactly enough.

### 4. Seals (harness proves it can fail before any green counts)

- **Coverage gate proven-to-bite** — register a verb without a concept doc → red.
- **Dangling `explains` refused at ingest** — the invented-IRI rule, sealed.
- **Entitlement-aware capability answer sealed with the three-caller shape** — `alice`'s answer ≠ `bob`'s answer ≠ the unentitled caller's answer (the discrimination seal, pointed at help).
- **Doc-semantic nomination is entitlement-filtered** — a doc that vector-matches but explains a verb the asker can't invoke **never routes**; it is dropped or surfaced honestly as "exists but not in your entitlements." Seal: the identical intent-shaped question returns a routable capability for an entitled caller and the exists-but-not-yours message for an unentitled one — the vector rung inherits the discrimination seal.
- **Abstain-on-uncovered pinned.**

### 5. Explicitly out of v1

- **Doc editing through the UI** — docs change by PR like all ratified config.
- **Auto-generated doc stubs from verb registrations** — tempting, but a generated stub that satisfies the coverage gate is the **decorative-seal problem as documentation**: the gate exists to force a human to write *meaning*; a stub-generator defeats its purpose.
- **Per-paragraph anchoring** — doc-level `explains` is v1; finer granularity wakes on evidence it's needed.

## Scope note — what this ADR is *not*

This is the **help/explanation** surface (docs that describe the system). It is **not** the data-plane authoring assistant (ingesting existing dbt/pipeline/code assets and guiding practitioners) — that is a separate, larger program (a future ADR, 0032's analyst-loop ambition transposed to the data plane, evidence-gated and staged). The two share the ratified-config + provenance rails but are different deliverables; keep them separate so this packet-sized help design ships without waiting on the program.

## Consequences

- **The help system is true by construction for "what exists"** and honest by construction for "what it can't answer" — it cannot claim a capability the graph doesn't have, or explain an IRI that doesn't exist.
- **Docs stop drifting silently** — the bidirectional coverage gate makes an undocumented capability a build failure, not a latent lie.
- **Explanations are personalized** without a per-user docs fork — the capability layer is computed against the asker's entitlements; only the *meaning* layer is authored.
- **One new predicate, one new class** — the blast radius is a vocabulary file, an ingest mapping, a compose rule, and the gates. Everything else is existing rails.
- **The semantic layer can't drift** — the vector index is a *projection of the governed corpus*, re-derived on corpus change; the classic vector-DB failure (confidently retrieving descriptions of things that no longer exist) is structurally closed. This is the most defensible use of the Weaviate machinery in the system: embedded text and graph truth share one validation boundary.
- **The vector store is used, never load-bearing for truth** — it nominates; graph-validation disposes. Its role (intent → capability, a semantic-distance problem) is exactly what it's good at and exactly what deterministic matching can't do, so both stores are necessary, not redundant.

## Non-goals

- A search-index-first help system (rejected — search-and-hope is the failure mode this replaces).
- Baking explanations into prompts (rejected — the whole point is graph-derived + ratified-doc-authored, not model-improvised).
- Specifying the elicitation/render schema for help answers (reuses the existing citation + abstain surfaces; ADR-0033's elicitation archetype).

## Open questions

1. **`internal/DOCS` graph class** — confirm manifest-class (seed, never prime-wiped) against the reproducibility convention before wiring the partition. *(A builder verification against the graph-convention doc — not a design question.)*

*(Two questions from the initial draft were resolved in review and folded into the Decision: **`doc_kind` routing** → default to `concept`, never ask on kind; the `how-to` surfaces as a linked affordance (§3, "Kind routing"). **Coverage-gate granularity** → verbs only in v1, gate expands per-kind on evidence (§1, "Gate granularity").)*

## The one-sentence model

The graph is the index, the docs are the leaves, `mesh:explains` is the edge, and the same three disciplines that govern everything else — **cited-or-refused, covered-or-red, abstain-over-improvise** — govern what the system says about itself.
