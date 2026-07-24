# PCN extraction sort — the three-pile annotation (decided, waiting for its window)

The PCN/PDN M1 exemplar moved fast and let *mechanism* pick up domain names while *content* stayed
correctly in data. This doc is the decided sort so the extraction milestone (M2) is a mechanical
execution, not a fresh analysis. It pairs with the **generic-at-birth rule** (AGENTS.md): new surface
is generic from now on; this sorts the surface that already exists.

**Three piles:**
- **RENAME-AND-PROMOTE** — generic mechanism that merely wears a domain name. Rename to the
  workflow-model noun; the domain becomes a parameter/config. Nothing about the logic is PCN-specific.
- **PLUGIN-RESIDUE** — genuinely domain-specific knowledge (vocabulary, extraction quirks). Does NOT
  dissolve to data and must NOT be promoted to generic; it lives behind a declared domain-plugin
  boundary so the generic core never imports it.
- **DISSOLVE-TO-DATA** — business knowledge frozen in code (a dict, a map). Becomes triples/config the
  owner ratifies; the code reads it, never encodes it.

**Acceptance for M2 = the deletion test (grep-able, therefore a seal, not an aspiration):**
> every `pcn_*.py` gone from engines A and O, and the PCN loop still runs — via generic mechanism +
> the domain plugin + data.

---

## Pile 1 — RENAME-AND-PROMOTE (generic mechanism, domain-named)

| Current | Becomes | Note |
|---|---|---|
| `restate_analyst/pcn_driver.py` · `VirtualObject("PcnDispatchItem")` | `dispatch_driver.py` · `DispatchItem` | Two-write convergence is workflow-model generic; nothing in it is PCN. |
| `restate_analyst/pcn_workflow.py` · `Workflow("PcnGroupedReview")` | grouped-review lifecycle (generic) | 1-approval-resolves-N is the fan-OUT dual of the Slice-5 join — a generic step lifecycle. See M3. |
| `restate_analyst/pcn_review_starter.py` · `Service("PcnReviewStarter")` | generic review starter | Composition entry; notice-ref is a parameter. |
| `restate_analyst/pcn_dispatch.py` | dispatch plan (generic) | `plan_dispatch` is generic; the queue map is Pile 3. |
| `restate_analyst/pcn_review_builder.py` | review composer (generic) | Chains generic cores; domain enters via injected seams. |
| `restate_analyst/pcn_rules_loader.py` | `policy_rules_loader.py` | Block-pass loader over a named graph — domain-blind already. |
| `restate_analyst/pcn_disposition_proposer.py` | policy/decision-table evaluator | `evaluate_rules` is generic all-match-must-agree; ruleset is injected data. |
| `ontology_service/pcn_state_sparql.py` | state SPARQL w/ **predicate config** | The `pcn:` predicates become config the caller supplies. |
| endpoint `POST /write_pcn_disposition_state` | `POST /write_item_state` (+ predicate config) | Generic "stamp state onto a node in a named graph." |
| endpoint `POST /pcn_parts_by_state` | `POST /items_by_state` | Generic read-union "items in a state." |
| (new, born generic) rules fetch | `POST /policy_rules` `{graph, ruleset_label}` | Built generic per the birth rule — never a pcn-named version. |
| (new, born generic) authz type | Topaz `disposition_item`, domain as attribute | Never `pcn_disposition`; the entitlement model stays domain-free. |

## Pile 2 — PLUGIN-RESIDUE (genuinely domain-specific; behind a plugin boundary)

| Current | Note |
|---|---|
| `ontology_service/pcn_instance_match.py` — `_PCN_DESCRIPTOR_TOKENS`, the pcn/pdn/ptn identifier-fragment trap | Real domain vocabulary (which prose nouns are strippable; pcn/pdn are id-fragments not descriptors). Belongs at the domain-plugin boundary the generic resolveInstance core calls — NOT promoted, NOT dissolved. |
| `ontology_service/pcn_instance_provider.py` — the SUSTAINMENT-graph resolveInstance provider | Domain-specific provider registered into the generic capability graph. The generic `/resolve` ladder already discovers it; keep it as the plugin, drop the pcn-name from any generic route. |

## Pile 3 — DISSOLVE-TO-DATA (business knowledge frozen in code → triples)

| Current | Note |
|---|---|
| `pcn_dispatch.py` · `_DISPOSITION_QUEUE` (disposition→persona-queue map) | Code-as-policy: which persona handles which disposition is an owner decision, not a mechanism. Becomes triples (disposition → audience) the loader reads — same policy-as-data move the rules TTL already made. |
| category→change-class classification | Already data (`pcn_disposition_rules.ttl`). No action; noted for completeness. |

---

## Horizons

- **M2 (extraction):** execute the sort above. Deletion test is the acceptance seal.
- **M3 (definition migration):** re-express the PCN process as a **workflow definition** consumed by
  `_run_definition` (ADR-0029), retiring the hand-coded `PcnGroupedReview` class — with the honest
  caveat surfaced now: the definition model likely needs ONE new step kind (a fan-out / grouped human
  step) to express bulk-resolve, and that addition is generic mechanism arriving with its first real
  consumer — exactly when ADR-0029 said step kinds should be added. PCN becomes a process the system
  *runs*, not a feature it *contains*.
