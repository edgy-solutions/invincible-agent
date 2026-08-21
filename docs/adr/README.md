# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) for the
Invincible Agent fleet — short, immutable documents that capture
architectural decisions, their context, what we considered, and the
indicators that would lead us to revisit.

## Why ADRs

Commit messages explain *what changed*. ADRs explain *what we decided*
and *why* — particularly for decisions that have long half-lives, span
multiple commits, or could plausibly be re-litigated by future contributors
who don't have the original context. An ADR's job is to let a colleague
six months from now answer the question *"why did we do it this way?"*
without spelunking through Slack archives or PR threads.

If a decision is purely local (renamed a variable, picked a library
because it's the obvious one, fixed a bug) — commit message. If a decision
shapes how future work gets done — ADR.

## Layout

Each ADR is a single Markdown file named `ADR-NNNN-short-slug.md`, where
`NNNN` is a zero-padded sequence number. Numbers are assigned at merge
time and never reused. ADRs are immutable once accepted — if a decision
is reversed or superseded, write a new ADR that links back to the old
one and update the old one's *Status* field accordingly.

Template skeleton:

```
# ADR-NNNN — Short imperative title

**Status:** Proposed | Accepted | Superseded by ADR-XXXX | Deprecated
**Date:** YYYY-MM-DD
**Deciders:** name(s)
**Related:** ADR-XXXX, ADR-YYYY  (cross-links if applicable)

## Context

What's the situation, what problem does this decision address, what
constraints are in play.

## Decision

The thing we decided to do, stated declaratively.

## Consequences

What follows from this decision — both the wins and the costs we accept.

## Alternatives considered

Other options we evaluated and why we rejected them. Short bullets are
fine.

## Indicators for revisiting

The conditions under which we'd reopen this ADR. If we can't write any,
the decision probably isn't ADR-worthy — it's permanent.
```

## Index

| # | Title | Status |
|---|---|---|
| [0001](ADR-0001-mem0-llm-decouple.md) | Decouple mem0's internal LLM from the agent reasoning LLM | Accepted |
| [0002](ADR-0002-mem0-monkeypatches.md) | Carry two upstream-mem0 monkey-patches in `utils/mem0_utils.py` | Accepted |
| [0003](ADR-0003-llm-rightsizing.md) | Right-size LLMs per workload class on the agent mesh | Accepted |
| [0004](ADR-0004-predicate-graph-routing.md) | Predicate-graph routing for the agent mesh (SPO/verb model) | Accepted |
| [0005](ADR-0005-verb-and-concept-namespaces.md) | Two-class namespacing for verbs and concepts (domain vs platform) | Accepted |
| [0006](ADR-0006-verb-registry-location.md) | DataHub as proposal inbox, Neo4j as runtime substrate | Accepted |
| [0007](ADR-0007-survey-before-mint.md) | Survey existing ontologies before minting `mesh:` concepts | Accepted |
| [0008](ADR-0008-routing-fallback-policy.md) | Routing fallback policy (LLM as generalist fallback) | Accepted |
| [0009](ADR-0009-sunset-classification-axes.md) | Sunset persona / domain / intent as classification axes | Proposed |
| [0010](ADR-0010-distributed-tracing-strategy.md) | Distributed tracing strategy (OpenTelemetry at the HTTP boundary) | Proposed |
| [0011](ADR-0011-multi-spo-routing.md) | Multi-SPO routing in NL (design exploration) | Proposed |
| [0012](ADR-0012-ui-archetype-rigidity.md) | UI archetype rigidity vs. data-shape diversity — six fixed archetypes vs. the questions whose answers do not fit them; `MetricUI` is the worst pain point. Records the tension and the options rather than resolving it | Proposed — **decision deferred**, workaround in place; recommended direction is dynamic columns first (Option 1), re-evaluate on real usage data |
| [0013](ADR-0013-engine-d-capability-surface.md) | Engine D capability surface vs. DataHub GraphQL richness — the hand-picked field subset cannot answer questions that touch fields outside it; grow capability tools alongside `search_datahub` rather than refactoring it | Proposed — **decision deferred**, workaround in place; recommended direction is incremental (Option 1), one PR at a time, no big-bang |
| [0014](ADR-0014-no-hardcoded-urn-hints.md) | **No hardcoded URN hints in agent prompts**; broker/catalog separation. A prompt MUST NOT enumerate catalog URNs, tables or schemas as "assets the user might want" — the agent DISCOVERS them through a tool and treats the tool result as authoritative. Three rules, effective immediately | Accepted |
| [0015](ADR-0015-router-regression-L1.md) | Router regression testing at the `/search_predicates` layer — engines declare their behavioral contract at registration (`expected_questions`), so the regression corpus is generated from what each engine CLAIMS rather than hand-maintained beside it | Phase 1 Accepted (2026-06-04); Phase 2 (Postgres table + canary cron + drift detection) deferred |
| [0016](ADR-0016-mem0-fact-vs-inference-boundary.md) | Fact-storage authority — **read from the system-of-record, don't manufacture memory**. An authority map fixes which class of fact lives where (world-state → DataHub/Neo4j, ontology → Fuseki, predicates → Neo4j+Weaviate, caller facts → Mem0 with `infer=False`, intermediate reasoning → discarded). r1's two-collection Weaviate split withdrawn | Accepted (r2, 2026-06-04) — Tier 0(b) shipped (`infer=False` on both engines) |
| [0017](ADR-0017-presentation-as-predicate.md) | Presentation-as-predicate, and **the end of generic `output_uri`** — Engine A decomposes into one registration per question shape (same pod, same image, N `register_engine_to_mesh` calls), so the output type is a property of the verb rather than a runtime choice. Re-confirmed under ADR-0029 by ADR-0030 | Proposed |
| [0018](ADR-0018-symmetric-spo-routing.md) | Symmetric SPO routing — **restore the symmetry**: the verb side adopts the same vector-recall + LLM-precision pattern the subject side has used since ADR-0009. `VerifyVerbChoice` and the yellow-zone threshold band are RETIRED; Engine O gains `/classify_predicate` mirroring `/resolve` | Accepted |
| [0019](ADR-0019-ontology-routing-substrate.md) | **The ontology IS the routing substrate** — routing is noun-resolution over it. The three Engine O legs are normative: `/resolve` (1 LLM) → `/find_compatible_verbs` (**Cypher, 0 LLM**) → `/classify_predicate` (≤1 LLM). The middle leg is the graph, not a model; the object is RESOLVED, not classified; definitions ≠ verbs is a category boundary | Proposed |
| [0020](ADR-0020-structural-disambiguation-at-weak-anchors.md) | Structural disambiguation at weak vocabulary-anchor boundaries — `/find_compatible_verbs` gains a **second traversal axis**: declared composition edges (`mil:hasContent`, `mil:hasPart`, …) alongside the existing `subClassOf*` inheritance walk, so a weak anchor reaches verbs through what a thing CONTAINS as well as what it IS | Proposed |
| [0021](ADR-0021-deterministic-content-kind-selection-at-ingest.md) | **Deterministic content-kind selection at ingest** — the kind is NEVER produced by the LLM. Precedence: `manifest.metadata.content_kind` declared wins → path-derived → **HALT**. The kind selects the extractor-config; the LLM enters only afterwards, to extract that kind's fields; ingest stamps `INSTANCE_OF` so routing can reach the instance through its class chain | Proposed |
| [0022](ADR-0022-datahub-integration-owned-wrapper-mining-mcp-reference.md) | DataHub integration — **keep the owned wrapper; mine the MCP server as reference, not as a dependency**. The MCP server is DataHub's own documentation of how to call DataHub correctly (entity_type enums, edge cases), so port its handling systematically **by reading, not by adopting** | Proposed |
| [0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md) | iagent AnswerArtifact as a graph-native CQRS object (Neo4j write + Electric read) | Proposed |
| [0024](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md) | Standards composition (BPMN / CALM / ODPS / ODCS) + publish/promotion (one-way emit; PublishedArtifact thin reference; SUPERSEDES chain; honest dangling) | Partially Proposed (publish 2026-06-27); Reserved (standards) |
| [0025](ADR-0025-instance-plane-access-control-as-provenance.md) | Instance-plane access control as provenance (ABAC over Topaz; captured on Source/CITES; carried by Artifact) | Proposed (+ amendments) |
| [0026](ADR-0026-persona-entitlement-topaz-authorization.md) | Persona & entitlement authorization via Topaz (matrix, git-asserted, per-prompt declared) | Proposed |
| [0027](ADR-0027-composable-approval-policy.md) | Composable multi-dimensional approval policy (grant-issuance governance over the single decider; auto-checked attributes vs human approvals; multi-approval extends HITL) | Accepted (architecture) — single-dimension built, composable deferred |
| [0028](ADR-0028-canvas-answer-composition-workspace.md) | The canvas as an answer-composition workspace (SPO eligibility made spatial; cards carry SPO provenance from v1; Q&A→workflow bridge — aggregation v2, workflow-seeding v3 coupled to ADR-0024) | Accepted (v1 forward-compat constraints) — deeper canvas directional/deferred |
| [0029](ADR-0029-process-workflow-model-spo-steps-restate.md) | The process-workflow model (SPO-native steps + human-await on Restate, git-asserted definitions, superseding BPMN→Dagster; standard→substrate mapping) | Accepted (model shape + process→Restate seam); build deferred to slices |
| [0030](ADR-0030-verb-output-is-a-fixed-type.md) | Re-confirms ADR-0017 §1 (fixed output type per verb) under ADR-0029, and RECORDS THE REJECTION of result-dependent output (it breaks the spo_operation verifier + Slice-4 seeding). ~70% re-derivation; the kept 30% is the dated rejection + edgeless-topology honesty. Presentation transforms marked directional-not-required; content-based render selection left an open question | Accepted |
| [0031](ADR-0031-instance-resolution-ladder.md) | Instance-resolution ladder (exact → containment → LLM-candidate → abstain); LLM demoted from classifier to candidate generator ("proposes, phone-book disposes"). Rungs 1–2 built (`87fe361`); rung 3 (LLM) deferred pending real telemetry (recall_override / no_instance / RESOLVE_INSTANCE_ALIAS logs); descriptor list defended as a frozen closed grammatical class; v2 alias-persistence growth loop scoped | Accepted (rungs 1–2; rung 3 deferred) |
| [0032](ADR-0032-goal-oriented-analytical-queries-catalog-analyst-loop.md) | Goal-oriented analytical queries / the catalog-analyst loop ("the LLM authors, enforcement disposes"); evaluation set banked red-first | Proposed — model shape + build order; build staged |
| [0033](ADR-0033-interrogative-disambiguation-ask-from-the-phonebook.md) | Interrogative disambiguation — the third behavior between route and abstain (`ask` from the phone-book); bounded at one turn; gated on resolution provenance; confirmed picks are alias training data | Proposed — deferred (evidence-gated, post-demo) |
| [0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) | The trust lifecycle: **admission policy** (trust table keyed on vendor-format × pipeline-version; supervised/monitored/trusted, born-supervised), **decision records** as emitted schema-validated artifacts carrying every check's inputs+thresholds (so "why was this NOT reviewed?" is answered from an artifact, not a re-run), and **the autonomous path** as a second workflow definition — the grouped review minus exactly one step. Trust rung and `mesh:dispatchDispositions` are one authority ratified once; escalation back to the human path is mandatory (mechanism = M3-time). Supplies M3.2's acceptance customer | Proposed — Phase 1 (records + table + starter consultation) M3-independent; workflow 2 M3-coupled |
| [0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) | Two planes — PROCESS (BPMN-like, authored by domain experts) vs DATA (ingestion, authored by data engineers), split by the AUTHORSHIP criterion; substrate is input/output never a step; provenance is a FIELD never a join (write-side mandatory); source authority is DISTANCE FROM TRUTH (one mirror, N degradation paths) with freshness reusing ADR-0034's rungs; stopgaps instrumented to argue for their own retirement | Accepted (boundary + provenance doctrine) |
| [0036](ADR-0036-config-layering-seed-overlay-composition.md) | Config layering — the Topaz seed/overlay pattern generalized to ALL ratifiable config (statuses, rules, trust table, mappings, definitions, grants). Mechanism + seed ship open; work overlays deltas. Composition AT THE REPO (not at ingest — that would break content-hash refs covering a readable artifact; not per-mechanism — two-escapers at config scale). Composed result passes the SAME validation; provenance carries the LAYER; DELETION must be expressible or the overlay forks. Restricted boundary holds by construction | Accepted (pattern + composition site); tool is work |
| [0037](ADR-0037-ratified-docs-corpus-help-surface-grounding.md) | Ratified-docs corpus + help-surface grounding — **the graph is the index, docs are the leaves, `mesh:explains` is the edge**. The environment already describes itself (verbs, ontology, workflow definitions, trust table, decision records); markdown carries only what the graph cannot (intent, conventions, the *why*). Keying is ordinary triples validated at ingest (the invented-IRI rule), NOT search/paths/frontmatter-as-database; coverage enforced bidirectionally so a verb with no concept doc is a build failure. OKF v0.2 cut ruled pre-authoring: TAKE sources-with-signals, keyed footnotes, `generated` vs `verified`, absolute `stale_after`; REFUSE identity-by-path and untyped links | Proposed — design settled, zero open questions (2026-08-15); NOT started and deliberately not next. **Scope correction 2026-08-15:** first task is cross-repo (doc-tools), gated on that repo's silent-CI board item |
| [0038](ADR-0038-telemetry-as-provenance-projection-langfuse-standard.md) | Telemetry as **provenance projection** (extends ADR-0010) — the design question is not Langfuse-shaped. The risk in "maximize what we send" is a second parallel vocabulary for describing what the system did; the standard worth publishing is which EXISTING provenance fields (`resolved_via`, `ruleset_ref`, `admitted_by`, `era`, `obtained_via`, `authz_id`, `doc_ref`) map onto observability primitives, **never renamed for Langfuse** — so a trace and a decision record tell the same story in the same words, and an SDK adopter inherits the vocabulary rather than the plumbing | Proposed — standard defined; rollout staged (helper + env, doc-tools artifact-keyed tracing, prompt-hash, v3/OTEL), each sealed |
| [0039](ADR-0039-workflow-definition-authoring-schema-and-bpmn-export.md) | Workflow definitions — **YAML is authoritative, the schema is a committed artifact generated from the executor models with a drift test, BPMN is an export-only projection** (extends ADR-0029; changes nothing about what a definition MEANS, only how it is authored and viewed). BPMN-as-source is refused because it would destroy the property that definitions are reviewed like grants. ADR-0034's no-mode-branch ruling is the load-bearing constraint | Proposed — decision recorded; the three deliverables (schema, scaffold, exporter) land separately, each sealed |
| [0040](ADR-0040-board-as-generated-index-status-in-headers-markers-in-code.md) | Work tracking — **the board is a GENERATED index, status lives in the item's own header, code-sited items carry a marker at the site**. Diagnostic symptom: "where are we?" was repeatedly answered by an agent reconstructing the board from conversation context — the one place it cannot live, because it evaporates between sessions and is invisible to everyone else. Applies ADR-0036's generated-not-hand-written discipline (plus its drift test) to the board itself | Proposed — decision recorded; the migration it implies is substantial and is scoped rather than assumed away |
| [0041](ADR-0041-user-contributed-documents-ingest-on-arrival-provenance-gated-truth.md) | User-contributed documents — **ingest on arrival, truth granted later** (quarantine is a STATUS, not a PLACE). The drop box processes immediately through a dedicated door that mechanically stamps `obtained_via: user-drop` (a fifth rung on ADR-0035's degradation ladder) on **every** assertion the document produces; promotion APPENDS a decision record + promotion fact rather than rewriting the frozen `standing`; rejection is a property-keyed sweep. Classifier suggests → human confirms → `manifest.metadata.content_kind` declares (ADR-0021's channel, unamended). The label rides the answer envelope. Rules R1 visibility (domain-entitled, labelled), R2 include-and-label, R3 duplicate identity | Proposed — decision recorded; build deferred (cross-repo: backend seam → doc-tools threading → UI label) |
| [0042](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md) | Live view-artifacts — a **recomputing card species declared as an ARCHETYPE, never a new artifact kind** (`Artifact` has no `kind` discriminator and gains none; AnswerArtifact untouched). The card holds `{output_uri, params}` and never a view name: the intent nominates the subject, `select_presentation` disposes the shape per caller's registered menu, so `archetype-chosen-before-data` cannot re-open in a new subsystem. Measures are VERBS running where verbs run — mock what sits behind an interface, never the interface's location. Content is state-master / arrangement is UI-master / `valid_as_of` is stamped **per evaluation** (a live view may not inherit its mint-time stamp). Gates assert `presentation_source == "registered"`, because `union_menu()` turned the unidentified-caller failure from loud to silent. Archetype names structural (`PERIOD_SERIES`, not `COST_CURVE`); a typed intent catalog is a RESTRICTION of ADR-0032, not a second analyst loop. **Ruling 9 (added post-drafting):** live-view archetypes never enter the anonymous union — a one-shot's mis-render is BOUNDED, a subscription's COMPOUNDS — and the refusal is emitted by `select_presentation` as a fourth `presentation_source` state (`refused-anonymous-live`), never as a component `refusalReason`, because the component never reaches it and an unemittable published reason makes the backend wait on a discriminant that never arrives | Proposed — written before the build it governs; Open questions separates settled from directional |
