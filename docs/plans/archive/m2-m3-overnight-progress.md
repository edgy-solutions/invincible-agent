# M2/M3 overnight run — progress log (2026-07-25 → 26)

**Directive:** work M2 (extraction sort) + M3 (workflow-definition migration) overnight. Generic,
config/workflow-spec driven, NOT code-driven. ZERO pcn/pdn in mechanism. Per `pcn-extraction-sort.md`.

**Safety rules honored:** branch-only (`m2-extraction-sort` in both repos); NO push to master; NO
build/roll/deploy; test suites as the gate; behaviour-preserving renames. **The live M1 demo is on the
current master image, untouched.**

---

## M2 — DONE across all four surfaces (all gated, committed on branch `m2-extraction-sort`)

**Gates green:** engine-a 117 tests · engine-o 23 tests · py_compile (engine-o main, BFF gateway) ·
cortex-ui `tsc` 0 errors. Cross-service write/resolve URL contract re-verified by engine-a mock-URL tests.

**Deletion test result:** ZERO `pcn_*.py` files in engine-a or engine-o; ZERO pcn-named
routes/services/classes/kind in the mechanism (one docstring points at the `.ttl` data file). Remaining
`pcn` in our code = Pile-3 DATA (the `pcn#` ontology-namespace IRI, the `pcn_disposition` kind value,
`disposition_*` field names) + docstrings — all documented as build-on-trigger.

### Commits (invincible-agent)
- `19be112` — engine-a rename-and-promote: pcn_driver→dispatch_driver (PcnDispatchItem→DispatchItem),
  pcn_workflow→grouped_review_workflow (PcnGroupedReview→GroupedReview), pcn_review_starter→review_starter
  (PcnReviewStarter→ReviewStarter), pcn_dispatch→dispatch_plan, pcn_review_builder→review_composer,
  pcn_rules_loader→policy_rules_loader, pcn_disposition_proposer→policy_evaluator. All imports + tests.
- `c557396` — engine-o: pcn_state_sparql→state_sparql (build_item_state_update /
  build_instances_by_property_query), pcn_instance_provider→sustainment_instance_provider (Pile-2 plugin,
  honest domain name), pcn_instance_match→sustainment_instance_match; routes
  /write_pcn_disposition_state→/write_item_state, /pcn_parts_by_state→/instances_by_property,
  /resolve_pcn_instance→/resolve_instance; cross-service callers updated.
- `1dca369` — BFF: Restate call URLs → renamed engine-a services; own routes /pcn/reviews→/reviews,
  /pcn/parts_by_state→/instances_by_property; kind "pcn_grouped_review"→"grouped_review".

### Commit (cortex-ui, branch `m2-extraction-sort`)
- `efdbbea` — kind key pcn_grouped_review→grouped_review (archetype routing unchanged); fetchReviewBatch
  → /reviews/{wf}/batch. Renderers were already domain-free.

### M2 DEFERRED (documented, build-on-trigger — NOT rushed under pressure per the ruling)
- **`/instances` SHAPE parameterize-and-promote** ({domain,class,filter_property,filter_value} +
  predicate-config). Done as a NAME rename to `/instances_by_property` with the existing body; the full
  generic shape is the risky-schema redesign the ruling says build on the SECOND instances-by-property
  view (the presentation-generalization wake). Not invented overnight.
- **Pile-3 dissolve-to-data:** `_DISPOSITION_QUEUE` (disposition→queue map) → triples; the `pcn#` predicate
  IRIs + `disposition_*` fields → caller predicate-config. These are the SUSTAINMENT domain DATA; left as
  data with the vocabulary intact (works, consistent), dissolved on the owner-ratifies trigger.
- **`pcn_disposition` dispatch kind** left intact + consistent (engine-a mints it, UI registry matches) —
  renamed with the same coherent cross-service move when convenient; not touched to avoid a 2nd contract
  break tonight.
- **`/notices/{id}/provenance`** (evidence feeder) — domain-named, behind the evidence boundary; left.

---

## M3 — DESIGN only (correctly blocked; see `m3-grouped-review-definition-design.md`)
Not wired — M3 is genuinely gated on prerequisites (ADR-0029), and rushing its schema unsupervised is the
exact trap the ruling names. Delivered a design doc + a concrete DRAFT definition (embedded, not a
loadable *.yaml) expressing the grouped-review on the EXISTING Slice-1 `WorkflowDefinition` model.
Blockers documented: (1) Part/Notice/BOM ontology classes + verbs don't exist; (2) the executor +
runner-cutover is a separate SEALED increment on the sealed runner; (3) generic audience naming is a
git-rails/Topaz deploy change. `rendersAs` sketched, NOT finalized (presentation-trigger gated).

---

## For the human — review before merge/deploy
1. **Nothing is deployed.** Both branches are `m2-extraction-sort`; the running demo is untouched.
2. **Coherent deploy requires a coordinated roll** of engine-a + engine-o + cortex-bff + cortex-ui
   TOGETHER (the Restate service names, route paths, and the `grouped_review` kind are a cross-service
   contract now consistent ON THE BRANCH but different from the live master images). Deploying one without
   the others breaks the loop. Also: in-flight workflows keyed under old Restate names (`PcnGroupedReview`,
   `PcnReviewStarter`) would be orphaned by the rename — drain/clean before cutover.
3. **Re-registration on deploy:** engine-o self-registers `/resolve_instance` (was `/resolve_pcn_instance`)
   into the Neo4j capability graph — the live graph still has the old endpoint_url; reseed/re-register on
   deploy or the `/resolve` fan-out won't find the provider.
4. **Merge order:** engine-a + engine-o + BFF (invincible-agent branch) and cortex-ui branch are a set.

## Live demo: UNTOUCHED (no deploy performed this run)
