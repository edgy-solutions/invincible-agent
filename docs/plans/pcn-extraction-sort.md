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
| endpoint `POST /pcn_parts_by_state` | `POST /instances` `{domain, class, filter_property, filter_value}` | SHAPE violation, not just naming: "parts, by state" is a specialization of the generic capability the arch already claims — "query instances of class C in domain D filtered by property P" over the read-union + typed CONSTRUCT. Subsumes `/pcn_parts_by_state` the way `/policy_rules` subsumed the pcn rules fetch. `parameterize-and-promote`, not just rename. |
| cortex-ui `PcnDispositionDashboard` component (to be built) | generic **instances-by-property TABLE archetype** | UI SHAPE violation: not a feature component but a generic "instances-by-property" table whose columns/filters/target-query come from CONFIG (`rendersAs` triples, E-list). Build it archetype-SHAPED even while its payload is hand-assembled (generic renderer, specific feeder) so M2 touches the FEEDER only. See [[feedback_graph_derives_whole_stack]]. |
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

## Armed wakes (named, so they're triggers not re-litigations)

- **Shared policy-lib wake (second-consumer trigger).** The rules loader + validator live in
  `restate_analyst` (with the proposer, their only consumer). engine-o's `/policy_rules` deliberately
  does NOT host them — it serves Turtle, the consumer interprets (option 1). If a **second service**
  ever needs to load/validate rulesets, THAT is the trigger to promote the loader+validator into a
  shared lib both build contexts vendor — the second-consumer rule, same shape as the second-domain
  trigger. Armed by this decision, not pre-empted by it. Don't build the shared-lib vendoring
  mechanism until the second consumer exists.
- **Raw-Turtle convention → structure wake.** Today "raw `/policy_rules` Turtle is not a rules API;
  consumers go through the loader/validator" is a CONVENTION (AGENTS.md). Safe because nothing consumes
  the raw triples. If a second consumer of `/policy_rules` appears, the shared-lib wake fires and the
  convention becomes structure (the loader/validator is the only sanctioned path).
- **Presentation-generalization wake (SECOND-VIEW trigger — likely fires SOONEST).** Pile 1 now covers
  the presentation layer, but its trigger differs from the engine files' (second-domain). The natural
  trigger: **the second view that wants a table of instances filtered by a property** — the observation
  view, the review-batch listing, any M2 dashboard variant, within weeks. When that second consumer
  appears and a dev reaches to COPY the dashboard component, that is the parameterize-and-promote moment
  for BOTH the endpoint (`/instances`) and the archetype — same second-consumer rule as the shared
  policy lib, applied to presentation. Arm it now so the second view isn't built by copy-paste during a
  demo week (the queue growing instead of draining).
- **Replacement-IRI named wake (known-bad input to a LIVE rule path).** The live graph has 2 parts with
  MANGLED multi-MPN `hasReplacement` (`SNSR01F30NXT5G,_NSR20F40NXT5G`) — the doc-tools replacement-IRI
  bug did NOT land. Harmless for the demo (IPCN25300X is a PCN; form/fit/function proposes via
  `RuleFormFitFunctionChange`, which does not consult replacement) — BUT `RuleDiscontinuedWithReplacement`
  / `RuleDiscontinuanceCategoryWithReplacement` (PDN) DO test replacement, so the FIRST PDN through the
  chain meets mangled data at exactly the field its rule reads. Wakes on **first PDN OR the doc-tools
  fix, whichever first**. Not a demo blocker; a named wake, not a "flagged."
- **PRODUCER follow-up filed to doc-tools (their side of the fence).** Per-part `needs_review` is
  persisted to NEITHER graph — only the `review.json` + Neo4j DOC-LEVEL flag. The safety chain rides a
  field the mesh substrates drop. Ask: **persist per-part `needs_review` into the instance graph** so
  the projection stops being lossy on the one field five sealed laundering layers depend on. Until it
  lands, "extraction is authoritative for review-state" is the recorded rule and the
  `REVIEW_STATE_UNSOURCED` tripwire (`start_review`, `0cc406e`) is its enforcement.

## Archetype payload schema = the hand-assembled version of the future `rendersAs` declaration

Write this BEFORE the dashboard session (the schema is the contract nobody was assigned — and it'd get
designed under demo pressure otherwise). The instances-by-property archetype's payload shape — **columns,
filter spec, row identity, state vocabulary** — must NOT be invented; it is the PROJECTION of what
`rendersAs` will someday declare (class → columns, property → filter, verb-output-type → row shape).
Writing it down as "this is the hand-assembled version of the future triple declaration" means the M3
`rendersAs` layer lands on a schema BORN pointing at it, and the M2 feeder-swap is mechanical. Skip it
and the renderer's payload contract becomes an accident `rendersAs` later has to contort to match — the
rushed-schema trap through the side door the generic-renderer/hand-fed-feeder split left open.

**WRITTEN (the dashboard window's precondition, done up front):** `docs/plans/pcn-dashboard-payload-schema.md`
— the `INSTANCES_BY_PROPERTY` archetype payload, each field mapped to the `rendersAs` triple it
projects, the generic-renderer / hand-fed-feeder split spelled out, and an acceptance (feed the renderer
a NON-pcn payload → it must still draw a correct table). The dashboard session builds against it.

## Horizons

- **M2 (extraction):** execute the sort above — now including the PRESENTATION layer (the endpoint
  parameterize-and-promote to `/instances` + the dashboard as a generic archetype). The sort previously
  stopped at engine/BFF; it does not anymore. Deletion test is the acceptance seal, extended: every
  `pcn_*.py` gone from the engines AND no pcn-named presentation surface (endpoint or UI component).
- **M3 (definition migration) — INCLUDES PRESENTATION.** Re-express the PCN process as a **workflow
  definition** consumed by `_run_definition` (ADR-0029), retiring the hand-coded `PcnGroupedReview`
  class — likely needs ONE new step kind (a fan-out / grouped human step) for bulk-resolve, generic
  mechanism arriving with its first real consumer (exactly when ADR-0029 said step kinds should be
  added). AND: the definition carries its **presentation** — `rendersAs` per step/verb (the E-list
  triple shape). A workflow-as-data whose UI is still code-per-feature is only TWO-THIRDS of the
  original intent ([[feedback_graph_derives_whole_stack]]): the whole stack — process, capability,
  presentation — must derive from the graph. PCN becomes a process the system *runs* and *renders*, not
  a feature it *contains*.

## Vision layers (the paydown map)

The full vision is three layers, each a different maturity — the exemplar sprinted through all three in
specific form; this sort is the paydown:
- **PROCESS** — M3 workflow-as-data (the original BPMN intent). Not started.
- **CAPABILITY** — verbs + generic endpoints parameterized by ontology. Mostly built (`/policy_rules`,
  `/resolve`); needs the parameterize-and-promote pass (`/instances`).
- **PRESENTATION** — cortex-ui archetypes driven by `rendersAs` triples. HALF-built: cortex-ui already
  renders by archetype (GROUPED_REVIEW / WORKFLOW_OBSERVATION / honest UI-COMPONENT-NOT-FOUND) — a
  config-driven UI in embryo — but archetypes are chosen by CODE PATHS, not DECLARED by the graph. The
  missing step is `rendersAs` (E-list): a verb's output type declares its archetype; a class declares
  its table columns.
**Ruling (governs new UI/BFF):** demo on the specific shape; generalize on the trigger — but TIGHTEN the
trigger. Do NOT build `/instances` or the declarative dashboard under demo pressure — a rushed
archetype-declaration SCHEMA becomes the contract every future feature writes to and is far harder to
walk back than a rushed endpoint name. File + shape now (this doc); build on the trigger.
