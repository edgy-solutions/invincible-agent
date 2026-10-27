to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-22
re: "overnight 10-23 ... docs support, the pool leg", items 1-3, via Chris
freeze: observed. No roll, no prime, no fire, no cluster read.

Committed on lane/01-207. This report carries no secret and no infra detail.

# READY TO ROLL MONDAY: lane/01-207. Two images change: engine-o for the pool leg, cortex-bff for the HUD name

**`lane/01-207`**, pushed. It is `360fbeb6` (master, chart 0.4.65) plus these commits:

| commit | what | image |
| --- | --- | --- |
| `054e0a82` | LEG 3 reads the `universal_referent` node flag, not Jena (10-17 ruling) | engine-o |
| `a65df31a` | seal: an ordinary cost ask gains EXACTLY `mesh:explain` (10-19 amendment) | tests |
| `7662829d` | the HUD names engine-docs, engine-cost and engine-safety; before this all three read "Unknown engine" | cortex-bff |
| `b02b81a2` | the verb coverage gate (item 3); the engine question walked to its card (item 2) | tests |
| `20ca91c5` | comment corrections only (a constant's name, the measurement dates) | none |

- **No helm change.** Rolling it means a merge to master (gated; Chris's OK), the build on that sha, and a chart bump. A lane branch builds nothing, so **207 has no image yet.**
- **Already in master, so not on 207:**
  - the needs-you work: cortex `c390a03`, pinned at `9d1dfdf1`, with `9be5963` riding along;
  - 205's bbox (`ad564907`);
  - the `awaiting_kind` seal (`42f9945c`).
- **7f's sync needs nothing pinned here.**
  - 7f measured `7ac6caa` as an ancestor of the sandbox's doc-tools code (`133714c`) and of work's (`809963c`). Their report: `2026-10-22-report-from-7f-overnight-10-23-ready-to-roll-monday.md`, item 2.
  - doc-tools is a separate release, so this chart pins no doc-tools image.
- **The one Monday check that nothing offline can stand in for.** After engine-o rolls, run one read-only Cypher:

  ```
  MATCH (c:OntologyClass) WHERE coalesce(c.universal_referent, false) = true RETURN c.uri
  ```

  - Expect exactly `…/mesh#Thing`.
  - This is the first time LEG 3's predicate runs on a real Neo4j. Every arm so far has used scripted fake drivers.
  - If it returns nothing, the pool leg admits nothing. `mesh:explain` then reaches DOCS askers only through LEG 1, and the cost ask loses nothing. That is a quiet failure, not a red.
  - It needs your approval for the read, the same as any cluster read.

## Item 1: the pool leg on master's base

- **"Rebase" was done as cherry-picks onto a new branch, 207.** 193 is pushed, and a rebase would rewrite it. Both picks applied without conflict.
  - The LEG 3 suites pass, one file at a time: pool 19, find-compatible 55, person-route 54.
  - Seven neighbouring routing files: 95 passed.
- **The seal you asked for already exists**, in `tests/routing/test_the_pool_reaches_the_universal_referent.py`:
  - `test_EVERY_DOCS_CENSUS_QUESTION_REACHES_mesh_explain_THROUGH_LEG_3` is parametrized over the census docs rows. These include "how do I add an engine", asked by agent-user as DATA_ENGINEER under DOCS, plus the MESH-domain variant. It asserts `mesh:explain` enters the pool with compatibility `universal`.
  - `test_THE_POOL_GAINS_ONLY_mesh_explain_FOR_AN_ORDINARY_COST_ASK` asserts `with_leg - without == {"mesh:explain"}` and `without <= with_leg`. That is the 10-19 amendment.
- **The property name differs from the directive.**
  - The directive writes `coalesce(c.universalReferent, false)`. `universalReferent` is the RDF predicate (`mesh:universalReferent`).
  - The writer stores snake_case `universal_referent` (`doc_tools/assets/ontology_assets.py:152 UNIVERSAL_REFERENT_PROPERTY`). The leg reads that, as ruled 10-17.
  - With camelCase, every node would coalesce to false, the leg would admit nothing, and nothing would go red. **I kept snake_case.**
- **"Puts DocPage in the candidates":** the pool holds verbs, not classes.
  - **The verb:** `mesh:explain` enters the pool (above).
  - **The class:** `DocPage` enters as `/resolve`'s subject class. `test_resolve_binds_a_DOCS_question_to_its_page` covers that, and `test_the_bound_subject_reaches_explain_and_its_page` joins the two.
  - If you meant something else, say so.

## Item 2: the walk, offline. Here is the card, and what is missing

**The route.** Three new arms in `tests/docs/test_the_docs_subject_pool_binds_the_page.py` pass each real piece's output to the next:
1. engine-o's real `resolve` and `fill_slots` run over the real corpus in its named graph.
2. engine-docs' own `OntologyDocPageReader` calls engine-o's real `/page_for_subject`, in process.
3. `/explain` reads the body, asserts its sha, and renders the card.
4. The presentation composer passes the card through as structure.
5. The HUD names the engine from the endpoint engine-docs registers.

**Stood in:**
- Jena (the corpus in its named graph);
- the body store (git's committed bytes, which is what the prime uploads);
- the slot-filler LLM;
- **the pool leg** (no Neo4j; see above).

**The card for "how do I add an engine":**

| field | value |
| --- | --- |
| page | `docs:runbook-adding-an-engine`, "Runbook — adding an engine" |
| doc_kind / audience_hint | `how-to` / `ARCHITECT` |
| explains | `mesh:resolveInstance`, `mesh:enumerateInstances`, `mesh:InstanceResolution`, `mesh:InstanceEnumeration` |
| body | the committed `docs/runbooks/adding-an-engine.md`: 77,761 bytes, 1,266 lines; sha `c2535939…`, which matches the corpus |
| cited seals, in page order | `tests/test_engine_names.py`, `tests/test_agent_modules_survive_flat_layout.py`, `tests/test_transport_auth_applied_everywhere.py`, `tests/test_subject_coverage.py`, `tests/finance/test_engine_f_contracts.py`, `tests/test_mirror_covers_the_build_matrix.py`, `tests/test_lock_coherence.py`, `tests/test_endpoint_gating_manifest.py`, `tests/test_service_enumerations_agree.py`. **All nine are in the tree**; an arm asserts it. |
| HUD | **"Unknown engine" before `7662829d`; "Engine Docs" after** |

**What was missing between the pool and the card:**

1. **The HUD could not name the engine. Fixed on 207.**
   - `engine_name_from_endpoint` named only one- or two-letter components. This is the regex that missed engine-fin on 09-01.
   - A census of every default endpoint in the fleet found two more engines missing the same way: engine-cost and engine-safety.
   - The fix names any component of three or more letters by its word. Ruled names such as engine-fin's still win.
   - The seal censuses every `iagent-engine-<x>` default the fleet's own code names. The next engine reds on the day its URL is written. On the unfixed resolver 7 arms are red: exactly those three engines, in both release forms. Fixed: 47 pass.
   - **The display names are mine** ("Engine Docs", "Engine Cost", "Engine Safety"). If you want different labels, they go in `_NAMED_COMPONENTS`.
2. **Named, not fixed:** the provider branch of the HUD name matches on prefixes.
   - A provider `engine_fin_…` would read "Engine F", which is the presentation agent's name.
   - `engine_cost_…` would read "Engine C".
   - `engine_docs_…` falls through as the raw string.
   - The gateway's own comment says the provider is usually empty, so the endpoint path above is the one that renders. Whether a provider reaches it live is unmeasured.
3. **The pool leg's Cypher has never executed against a Neo4j.** That is the Monday check above.
   - A local Neo4j would mean running a database server on the dev box, which I have not done. That is Chris's call.
4. **Not walked:** the supervisor choosing `mesh:explain` from the pool, and the BFF's dispatch envelope to engine-docs. The walk starts at the subject and ends at the composer.
5. **The audience does not match the asker.**
   - The card says `ARCHITECT`. The census asker is DATA_ENGINEER.
   - The reader sends `audience: null` on purpose, so the page is served anyway.
   - When `ENABLE_AGENTIC_AUTH` turns on, the asker must hold `can_invoke` on every verb the page explains. I have not checked agent-user's grants for `resolveInstance` and `enumerateInstances`.
6. **The card carries the whole 77 KB runbook.** That is the contract as written. Whether cortex should draw all of it is cortex's question.

## Item 3: the docs corpus, and the coverage gate

**The gate:** `tests/docs/test_every_registered_verb_has_a_page.py`.
- **One arm per registered verb.** It is red unless some DocPage in `setup/ontologies/docs_corpus.ttl` `mesh:explains` that verb. Today's 50 are allowlisted by name.
- **The population is derived.** `registration_sites.scan` is the same population the re-register and compact-verb seals use.
  - Seven files register a computed verb. Each gets a named resolver: a `"verb":` table, `policy/graphs/*.yaml`, or `notice_parts.VERB`.
  - A computed-verb file with no resolver reds, so it cannot shrink the population.
- **The allowlist is guarded both ways.** A covered entry reds as stale, and a name that is not a registered verb reds as a typo.
- **Six mutants, six named reds:**
  - an entry dropped from the allowlist;
  - a typo in the allowlist;
  - a resolver removed;
  - a covered verb added to the allowlist;
  - a resolver that yields nothing;
  - a leftover resolver.
- 19 pass and 50 skip. The 9 neighbouring docs files and `test_docs_corpus_drift.py` pass, one at a time.
- **Undecided, and yours to rule.** ADR-0037 §1 says "a `concept` doc"; the directive says "a page". The gate counts any DocPage. All six pages that cover a verb are `how-to`, and none is a `concept`.

**Pages with an `explains` edge** (56 registered verbs; 6 are covered):

| page | explains (verbs in bold) |
| --- | --- |
| runbook-adding-a-canvas-template | **seedCanvas**, **seedPortfolioCanvas** |
| runbook-adding-a-graph | **finProgramBrief**, **costLotCostingReview**, StatefulSupportResponse, cost:LotCostingReview, fin:Program, cost:ProductionLot |
| runbook-adding-an-engine | **resolveInstance**, **enumerateInstances**, InstanceResolution, InstanceEnumeration |
| runbook-adding-a-task-kind | DispositionReview |
| runbook-adding-an-archetype | Archetype |

**Pages with no edge:** backfilling-the-vector-space, pinning-the-fleet-sdk, rolling-a-service, writing-a-walk-sheet.

- **And one page outside the corpus:** `docs/corpus/cortex-capabilities-primer.md`.
  - Its front-matter claims 7 targets, among them `queryKnowledgeGraph` and `retrieveKnowledge`.
  - `generate_docs_corpus.py` reads only `docs/runbooks/`, so none of its claims is an edge. The gate does not count them.

**Verbs with no page (50):**

| registering engine | verbs |
| --- | --- |
| planning_agent | 14 `plan*` verbs |
| restate_analyst | analyzeWithCodeAgent, assessImpact, checkFreshness, describeAsset, enumerateCatalog, filterByTag, findSchema, lookupOwnership, proposeDisposition, traceLineage |
| cost_agent | costCategoryBreakdown, costLaborComposition, costLotBreakdown, costPriceComposition, costRateAssumptions, costRateComparison, costSupplierConcentration, costUnitPriceTrend, packageExport |
| finance_agent | finBurnRate, finEacCalculation, finEacComparison, finFundingStatus, finPerformanceIndices, finVarianceAnalysis, finVarianceDrivers |
| safety_agent | assessDeferralRisk, draftRiskAssessment, failureTrendForThisPlatformByMonth, findOrphanedHazards, whatFailedOnThisPart |
| one each | analyzeDataset (data_analyst), explain (docs_agent), queryKnowledgeGraph (neo4j_expert), retrieveKnowledge (weaviate_expert), whichPartsDoesThisNoticeAffect (ontology_service) |

- **`mesh:explain` itself has no page.**
- **Eight `explains` targets are classes, not verbs.** The verbs-only v1 gate allows them and does not count them.

## Also from the inbox

- **7f asks for a ruling** on capping the retry sensor's RunRequests per tick at about the slot count.
  - Lane 1's view: cap it.
  - The BFF's 600 s received-timeout counts queue time, and a queued run reads as a dead one. If the cap goes in, the timeout should start when the run starts, not when it is relaunched.
  - That is a cross-lane contract, so it is yours to rule.
- **Two reds I saw that 207 did not cause:**
  - `tests/test_every_commit_names_its_lane.py` reds on `26274c52` (trailer `ia74sp/lane/74-smoke-persona`, unregistered). That commit has been on master since 10-15.
  - `tests/finance/test_fin_package_export.py::test_gate_5_a_disagreeing_scope_is_409_naming_the_derived_one`: 207 touches no finance file, and this test does not use the resolver. I have not run it on master.
