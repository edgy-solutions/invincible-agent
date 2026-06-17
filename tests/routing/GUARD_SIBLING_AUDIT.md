# Source-guard / substrate-sibling audit (Step 0, 2026-06-17 overnight)

**Date:** 2026-06-17 evening. **Status:** audit only — gaps identified, **siblings NOT built tonight** per the architect's "decision-free enumeration, scoped follow-up for the missing ones."

## Why this audit exists

Per the standing rule banked at the close of the 2026-06-17 UI-incident session (state doc):

> Every source-level guard needs a substrate-level sibling, because source-clean does NOT imply runtime-clean. Registration is what crosses the layer boundary; substrate edges outlive the source-time defaults they were minted from. When you add a source guard, ask: "what's the substrate version of this property, and is it guarded too?"

The rule was earned three times: compact-form classes, mesh-registrar chart-vs-cluster, legacy DNS in substrate edges. Each case had a source-clean guard while runtime carried the bad state, and dispatch died in production before the cheap-venue noticed. This audit applies the question — *for every source-level guard the project has today, does a substrate sibling assert the same property on materialized state?* — and produces a punch list for the missing ones.

## Method

For each test file under `tests/routing/`, classified each test by:

- **Layer**: SOURCE (scans source files / behavior of pure code), SUBSTRATE (queries Neo4j / Weaviate), MIXED (both), BEHAVIORAL (live API).
- **Property guarded**: the invariant the test asserts.
- **Counterpart at the other layer**: does a sibling assert the same property?

Out of scope for this audit: tests that are inherently single-layer (e.g. substrate phantom-class checks; substrate is the only place phantoms can exist). The audit targets pairs where source-clean ≠ substrate-clean is structurally possible.

## Results

### A. Source-guards WITH substrate siblings (the model the rule prescribes)

| Property | Source guard | Substrate sibling |
|---|---|---|
| No legacy `*-svc.default.svc.cluster.local` DNS references | [`test_no_live_legacy_dns_references`](test_no_legacy_dns_references.py) | [`test_no_legacy_dns_in_substrate_verb_edges`](test_substrate_invariants.py) (shipped 2026-06-17 after the UI incident) |
| Provider-agnostic `resolveInstance` fan-out | [`test_engine_o_discovery_cypher_is_provider_agnostic`](test_b3_engine_o_unchanged.py) + [`test_engine_o_files_contain_no_resolveinstance_provider_names`](test_b3_engine_o_unchanged.py) | [`test_mesh_resolve_instance_has_one_edge_per_provider`](test_substrate_invariants.py) |
| No compact-form URIs in queries (post 2026-06-15 canonicalization) | [`test_no_engine_hardcodes_a_migrated_compact_uri_in_a_query`](test_b3_engine_o_unchanged.py) | [`test_no_compact_form_for_migrated_subjects`](test_substrate_invariants.py) + [`test_no_compact_form_ontology_classes`](test_substrate_invariants.py) |
| Domain not derived from path | (writer behavior — `ingest_ontology_to_jena` errors on missing `extra_metadata['domain']`, covered by [`test_explicit_domain_override_lands_at_intended_domain`](test_canonical_pipeline.py)) | [`test_no_path_derived_domains`](test_substrate_invariants.py) |
| Verb edges include a v0.2 saga `_tool_urn` for every routing pair | (n/a — this is an architectural property, not source-scannable) | [`test_substrate_covers_routing_via_v02_saga_edges`](test_substrate_invariants.py) |
| No pseudo-class as verb input/output | (n/a — pseudo classes were architecturally retired in source) | [`test_no_verb_inputs_against_fixed_pseudo_class`](test_substrate_invariants.py) + [`test_no_verb_outputs_against_pseudo_class`](test_substrate_invariants.py) + [`test_pseudo_class_debt_matches_known_set`](test_substrate_invariants.py) |

**Count: 6 properties** at full source+substrate coverage.

### B. Source-guards LACKING substrate siblings (the gaps banked tonight)

These are source-only guards where a substrate sibling could exist but doesn't. Each is **banked, not built** per Step 0 scope.

| # | Property | Source guard | Substrate-sibling gap | Risk profile |
|---|---|---|---|---|
| B-1 | Info-code → content-kind classification is deterministic (no LLM in the mapping module) | [`test_g3_info_code_map_module_has_no_llm_imports`](test_b2_format_ingest_guards.py) + [`test_g3_info_code_map_is_pure_function`](test_b2_format_ingest_guards.py) + [`test_g3_info_code_ranges_cover_b0_spec`](test_b2_format_ingest_guards.py) | **No direct substrate check that each `INSTANCE_OF` edge derives from the deterministic map.** G2 checks "every instance has an INSTANCE_OF edge to a real class," but doesn't check *how the class was chosen*. A future regression where an ingest path uses an LLM to pick the kind (instead of the info-code → kind map) would leave G3-source green, G2-substrate green, but the deterministic-classification property silently broken. | **Medium** — manuals ingest currently uses the deterministic map; risk surfaces only if a future ingest path bypasses it. |
| B-2 | DMC canonicalizer is byte-identical across `agent_fleet` + `doc-tools` | [`test_dmc_canonicalizer_copies_are_byte_identical`](test_b3_canonicalizer_drift.py) | **No substrate check that every `:DataModule` instance URI matches the canonical DMC shape.** Drift in either canonicalizer would surface only when a DMC encountered the diverged code path; substrate would carry mixed-shape URIs the source guard couldn't see. | **Medium** — same shape as the legacy-DNS class: source-clean while substrate carries the residue. |
| B-3 | Router source contains no forbidden lexical → class mapping | [`test_no_lexical_class_mapping`](test_recipe_v2_invariants.py) | **No substrate check that no edge carries lexical-mapping-shape metadata.** If a future ingest accidentally writes a lexical hint into edge properties, source stays clean but routing could short-circuit on it. | **Low** — lexical-mapping shape isn't currently part of edge metadata model; the source guard's existence reflects that the constraint matters. |
| B-4 | Engine D's URL is not hardcoded in Engine O | [`test_engine_d_url_is_not_hardcoded_in_engine_o`](test_recipe_v2_invariants.py) | n/a — substrate doesn't materialize Engine O's URL knowledge; this is an architectural code-organization property. | **n/a** — single-layer property, no sibling possible. |
| B-5 | Engine O imports the decision table from a pure module | [`test_engine_o_imports_decision_table_from_pure_module`](test_recipe_v2_invariants.py) | n/a — import structure; not a substrate-materializable property. | **n/a** — single-layer. |

**Count: 3 real gaps** (B-1, B-2, B-3) + 2 single-layer properties (B-4, B-5) where no sibling is conceptually possible.

### C. Substrate-only guards (the reverse direction — also a potential gap class)

The architect's rule names source→substrate as the asymmetric direction. But substrate-only guards have the reverse problem: substrate-clean does not imply source-clean, because nothing prevents new code from re-introducing the pattern. These are noted for completeness.

| Substrate-only guard | Source-sibling gap |
|---|---|
| [`test_no_blank_node_ontology_classes`](test_substrate_invariants.py) | The writer-side fix is in [`sync_jena_ontologies_to_neo4j`](../../doc-tools/doc_tools/assets/ontology_assets.py) (Writer C blank-node filter); not directly source-scannable. Banked as a behavioral test ([`doc-tools/tests/test_ontology_assets_blank_node_filter.py`](../../doc-tools/tests/test_ontology_assets_blank_node_filter.py)) which is the source-side proof. **Functionally siblinged via behavioral test.** |
| [`test_no_phantom_input_classes`](test_substrate_invariants.py) + [`test_no_phantom_output_classes`](test_substrate_invariants.py) | Source-side equivalent is Contract D rejection at mesh-registrar (422 if URI doesn't pre-exist). Covered behaviorally by [`test_D_invalid_input_uri_rejected_no_phantom_created`](test_adr0019_pipeline_integrity.py). **Functionally siblinged.** |
| [`test_known_subjects_exist`](test_substrate_invariants.py) | Source-side is the ingest manifest declaring the subjects; the guard's failure mode is "ingest never ran" or "ingest dropped the class," both of which are operational, not source-scannable. **n/a.** |
| [`test_known_verbs_typed_correctly`](test_substrate_invariants.py) | Source-side is the engine's `register_engine_to_mesh()` call; the substrate is the materialization. The pair is functionally complete — source declares, substrate must match. **No additional sibling needed.** |

## Risk summary

**3 real gaps** identified (B-1, B-2, B-3). The architect's "don't build siblings tonight, audit only" framing holds — each gap is **banked for a follow-up session**, not closed.

Of the three:

- **B-2 (DMC canonicalizer)** is the closest in shape to the legacy-DNS incident — source-side identity check exists, but a divergence between the two copies would leave substrate residue the source check couldn't catch. **Highest priority of the three.**
- **B-1 (info-code determinism)** is medium-risk because the deterministic map is currently the only ingest path, but if a future LLM-based ingest were added, the source-side import check would catch it at the module boundary, while a substrate-side check would catch it at the edge layer. Adding the substrate sibling is defensive future-proofing.
- **B-3 (lexical class mapping)** is low-risk because the architecture doesn't currently materialize lexical hints in edge metadata; the source guard exists because the property matters even though substrate can't carry it today.

## Recommendation

Per the architect's "scoped follow-up for the missing ones, not tonight":

- B-2 (DMC canonicalizer substrate sibling) → next-session candidate, before the work deploy.
- B-1 (info-code determinism substrate sibling) → defensive, can wait.
- B-3 (lexical mapping substrate sibling) → defer until the architecture changes to materialize the relevant metadata, at which point the gap becomes real.

## What this audit doesn't cover

- Tests outside `tests/routing/` (the audit's scope is the standing routing-substrate guards).
- ADR-0019 pipeline-integrity tests in `test_adr0019_pipeline_integrity.py` — these are behavioral cross-layer tests, not source-vs-substrate guards in the narrow sense.
- doc-tools-side ontology assets tests — partially audited (Writer C blank-node filter case), but the doc-tools test suite is a separate audit scope.

## Status

Step 0 complete. 3 real gaps banked (B-1, B-2, B-3), none built tonight. The standing rule has its enumeration baseline; subsequent work on the deploy or on a new property can use this document as the "is the sibling here" reference.
