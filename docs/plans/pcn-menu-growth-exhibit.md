# PCN menu-growth — the sourced menu, proven live (exhibit)

Ran 2026-07-24 on sandbox `edge`. Proves the **sourced-menu** design: registering ONE verb edge in the
capability graph makes the SPO interview offer it — with **zero menu/UI/interview code touched**. The menu
is not authored; it is *derived* from registered verb edges. This is the design's first live test, and it
was deferred to exactly this moment by `setup/ontologies/pcn_extension.ttl:10`, which registered the pcn
subject classes but NO disposition verbs, with the standing rule: *"they wake per-endpoint as each serving
endpoint becomes real (registering a verb against a stub endpoint would recreate a dead-end menu)."*
`PcnReviewStarter.start_review` is now real and proven end-to-end (the five-beats loop), so the precondition
is met — we woke exactly one verb.

## The verb woken
`mesh:proposeDisposition`, `input_uri = pcn:SustainmentNotice` (the PARENT), `output_uri =
mesh#DispositionReview`, `endpoint_url = …/PcnReviewStarter/start_review`, domain SUSTAINMENT. Registering
on the parent means the `subClassOf` walk in `/find_compatible_verbs` offers it for BOTH concrete
subclasses (PCN, PDN) — one edge, whole-family coverage.

## Mechanism (the real one, declared twice — not hand-surgery)
- **Work-authoritative:** a `register_engine_to_mesh(...)` block in `restate_analyst/main.py`'s lifespan
  (engine-a's self-registration path, ADR-0006 source-authoritative). First user of ADR-0008
  `verb_anti_synonyms` — repels pure-lookup intents ("what does the notice say") so a read never routes to
  an action.
- **Sandbox mechanism:** the same entry added to `scripts/seed_sandbox_predicates.py` (the sandbox verb seed
  — the verb analogue of `task_grant_sync` for grants; sandbox has no DataHub-emit env, so the seed is how
  verbs reach Neo4j here). The live edge was written by that seed's own idempotent `MERGE` +
  `apoc.merge.relationship` (which also creates the `output_uri` OntologyClass node — no Contract-D prep).
  NON-destructive: only the seed's *Weaviate* path drops-and-recreates (guarded); the Neo4j MERGE does not.
  Declaring in BOTH places mirrors the discrimination-seal pattern: source declaration + the deployment's
  real seed, live==source.

## Evidence — BEFORE (red) → AFTER (green), zero menu code between

| interview query (engine-o, what the SPO interview reads) | BEFORE | AFTER |
|---|---|---|
| `POST /operable_subjects {SUSTAINMENT}` | `subjects:[] count:0` | `count:1` → `pcn:SustainmentNotice` |
| `POST /find_compatible_verbs {SustainmentNotice}` | `verbs:[]` | `mesh:proposeDisposition` → endpoint `…/start_review`, output `mesh#DispositionReview` |
| `POST /find_compatible_verbs {ProcessChangeNotification}` (IPCN25300X's type) | `verbs:[]` | `mesh:proposeDisposition` — **input_uri still `SustainmentNotice`: INHERITED via subClassOf** |
| `POST /find_compatible_verbs {ProductDiscontinuationNotice}` (PDN) | `verbs:[]` | `mesh:proposeDisposition` inherited |

The BEFORE column is the positive control: the assertion could fail (and did, before the edge). The only
change between columns is one graph edge — no code in `spo_interview.py`, engine-o, or any UI. The SPO
interview's menu funnel (`authorized_operation_subjects` → `/operable_subjects`;
`authorized_verbs` → `/find_compatible_verbs`, spo_interview.py:133/163) reads exactly these endpoints, so
the interview now offers the verb for a PCN/PDN notice with nothing authored.

## Bonus assertion — parent-registration inheritance
One edge on `pcn:SustainmentNotice` is offered for the concrete `ProcessChangeNotification` and
`ProductDiscontinuationNotice` via the `subClassOf*0..max_hops` walk. The menu grows for a whole class
family from a single registration — the eligibility intersection (domain ∩ arity ∩ argument-fit ∩
permission) computing over the class hierarchy, not a flat table.

## Boundary (honest — named, not smuggled)
- **endpoint** points at the REAL, proven `start_review` ingress — NOT a stub (satisfies the ttl's
  anti-dead-end rule: woken per-endpoint as the endpoint became real). The router→`start_review` payload
  ADAPTER (mesh envelope → `{notice_id, impacted_parts, …}`) is a DISPATCH concern of a later window; this
  exhibit proves the MENU is sourced, not that the router yet invokes it. End-to-end invocation is already
  proven directly (the five-beats loop drove `start_review`).
- **Weaviate `Predicate` row** (the `/search_predicates` NL-routing sibling) was NOT written — the seed's
  Weaviate path is drop-based (guarded), and the menu-growth assertion reads Neo4j. FOLLOW-UP: a
  non-destructive single-row Weaviate upsert so the NL path ("act on this PCN") also resolves the verb.
  Deny-by-default holds: absent the row, NL-search just doesn't surface it — no misroute.
