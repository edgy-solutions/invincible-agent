# Slice 2 design — the SPO interview (re-aim the interrogator pattern at the WorkflowDefinition model)

**Status:** design (2026-07-15). Follows the ADR-0029 Slice-2 line (Decision 3: supersede the
BPMN-fused interview machinery, keep the mesh-informed select-from-authorized-set *pattern*,
**add the verb question**). Sequencing (proven by Slice 1): survey → design doc → build.
The old BPMN interrogator is **left in place** (staged retirement, same discipline as the
inline-task path) — this slice builds the SPO interview *alongside* it.

## 0. What the survey found (the ground this design stands on)

The current `ProcessInterviewer` (`agent_fleet/restate_analyst/main.py:1410-1518`, BAML
`IterateBPMNGraph` in `baml_shared/baml_src/interview_contracts.baml:42-119`):

- **KEEPER — the select-from-authorized-set pattern.** `fetch_catalogs()` injects an
  authorized set (ontology classes from Engine O `GET/POST /classes`; data sources) into the
  BAML prompt; the interview constrains the user to exact matches, suggest-closest on no-match.
  Durable per-thread VirtualObject turn mechanics (history + graph state keyed by `thread_id`).
- **SUPERSEDE — the BPMN machinery.** `IterateBPMNGraph` + `BPMNInterviewState`/`BPMNNode`/
  `BPMNEdge`/`BPMNNodeType` (BAML-only types); prompt-only graph validation; the `BpmnCatalog`
  Postgres table + `compile_bpmn` write path + Dagster auto-compile (`gateway.py:2886-2948`).

Three weaknesses the SPO rebuild fixes (each becomes a *strengthening*, §3):
1. **No verb question.** `BPMNNode` carries `ontology_class` (subject) + `data_source` (object)
   but **no predicate/verb field** (`interview_contracts.baml:16-22`). The interview never asks
   *what action* a step performs — the exact gap ADR-0029 Decision 3 names.
2. **The exact-match constraint is prompt-only** — no server-side validation of the LLM's pick
   against the injected set (`interview_contracts.baml:76-81`). A hallucinated class/source is
   caught by nothing but the model's good behavior.
3. **Termination is an LLM flag** (`is_ready_to_compile`) and the output **auto-compiles** to
   Dagster via `BpmnCatalog` — the bot writes the artifact, no human assertion in the loop.

## 1. The emit target — a git-asserted `WorkflowDefinition`

The interview produces a `WorkflowDefinition` (`agent_fleet/restate_analyst/workflow_definition.py`),
the same git-asserted YAML Slice 1 executes. Required fields (these ARE the completeness
predicate — see Decision B):

- `WorkflowDefinition`: `id`, `name`, `steps` (≥1). Optional: `classification`, `participants`,
  `domain_stages`, `observable_state`.
- `spo_operation` step: `subject`, `verb` (+ optional `expected_output`).
- `human_await` step: `audience` (+ optional `subject_ref`/`title`/`summary`).
- `direct_call` step: `endpoint`, `capability` (min_length 1).

## 2. The three design questions (RULED on the survey's evidence + the ADR-0029 leans)

### Decision A — whose eligibility does the interview constrain against? (the load-bearing call)

**RULED: constrain STRUCTURALLY to the WORKFLOW's declared domain (domain ∩ arity ∩
argument-fit); surface PERMISSION as advisory; never bind the definition to the author's
personal grants.**

The SPO interview adds the verb question by calling Engine O
`POST /find_compatible_verbs {subject_uri, max_hops, entitled_domains}` for the chosen subject,
which returns the verbs structurally compatible with that subject, domain-filtered by
`entitled_domains`. The question is *which domains to pass*:

- **NOT the author's entitlements.** A definition is authored **once** and run by **many**
  initiators; binding the offered-verb set to the author's grants would bake one person's
  permissions into a reusable artifact (and mislead — alice authoring for bob's runs). Steps
  execute as the **initiator** (the sealed precedent), so the author's grants are the wrong
  scope by construction.
- **The WORKFLOW's declared domain.** The interview elicits the workflow's `classification` /
  domain early (a workflow *is for* a domain); verb sets are scoped to that domain via
  `entitled_domains=[<workflow domain>]`. Any initiator entitled to the workflow's domain can
  run it. If no domain is declared, fall through to structural-only (arity ∩ argument-fit, all
  domains) — fully advisory.
- **Permission is ADVISORY at authoring.** Each offered verb is annotated with its permission
  requirement (`owner_persona`, the `can_invoke` capability / `can_<verb>`) — "*the initiator
  will need this grant*". The actual permission check happens where it belongs: **pre-flight
  per-run** (the just-filed ADR-0029 Decision 5 advisory-fail-fast) and **dispatch per-step**
  (the authoritative gate), both evaluated against the *actual initiator*, never the author.

**The consequence — un-doomable BY CONSTRUCTION for the structural failure modes.** Because the
interview only *offers* verbs structurally-compatible-and-domain-coherent for the subject, a
workflow authored via the interview **cannot contain a step that is structurally ineligible**
(wrong verb for the subject, wrong arity, wrong domain). It *can* still contain a step whose
eventual initiator lacks *permission* — which is precisely what pre-flight (per-run) and
dispatch (per-step) catch. This slots every layer into the same shape the whole system uses:

| Layer | Catches | Where |
|---|---|---|
| **Inexpressible at authoring** | structurally-ineligible verb (never offered) | this interview (Decision A) |
| **Refused at validation** | phantom subject / malformed definition | `validate_policy` + schema (Slice-1 + phantom-subject gate) |
| **Failed-fast at start** | a statically-doomed permission on the initiator | pre-flight (ADR-0029 Decision 5) |
| **Enforced at dispatch** | the authoritative per-step permission | stage-2 verifier + engine gate |

Four layers, each catching what the earlier one structurally can't. The interview is the
*first* layer — it makes the structural failure modes inexpressible, so the later layers are
left to guard only permission (per-initiator, per-run), which is the only thing that legitimately
varies between authoring and execution.

**Secrecy vs entitlement — the two-layer resolution (sharpened by review).** "Author over the
workflow's domain, not the author's grants" raises: *how does an author author well in a domain
whose vocabulary they cannot see?* The answer resolves ruling A tighter than a blanket "authoring
is ungated":

- **Secrecy (compartments) gates the menu AUTOMATICALLY — via the author's threaded identity.**
  The subject menu comes from Engine O, whose candidate pool is compartment-gated per-caller by
  the sealed `can_view` filter (the ontology-visibility gate that drops Procedure from bob's
  pool). Thread the author's identity into the subject-source and the menu becomes *the author's
  visible slice of the ontology* — the interview can only author over what the author can SEE.
  An author with no grant on a compartment gets a menu without that compartment's classes: not
  forbidden, just uninformed — the honest outcome, because *showing* the vocabulary would be the
  existence-oracle the gate exists to prevent. **No separate `can_author` gate is needed for the
  compartmented case — the existing `can_view` gate already bounds the offering.**
- **Entitlement (domains) intentionally does NOT gate authoring.** Domain-entitlement is a
  routing/persona concern, not a secrecy one; releasable-by-definition vocabulary reveals nothing
  by being seen. So alice (DATA_ENGINEERING) authoring over *releasable* MAINTENANCE vocabulary in
  a domain she is not entitled to is fine — the definition is a reusable artifact, and the
  *initiator's* entitlements are what get checked at run (pre-flight + dispatch).

**Load-bearing implementation requirement (now an ENFORCEMENT property, not a nicety):** the
interview MUST thread the author's identity to its subject-source calls (`authorized_subjects`
takes `caller_email`), or the self-gating silently vanishes and the interview leaks compartmented
vocabulary into menus. **The composed-path seal must prove it** — an author *without* a compartment
grant gets menus *without* that compartment's classes (the interview's own discriminating seal,
same shape as Engine O's; both sides non-empty: a granted author sees the class, an ungranted one
does not).

**FINDING — this is a next-increment requirement, not a done thing (design §7):** the current
`/classes` endpoint does **NOT** apply `can_view` (it returns raw SPARQL rows, ignoring identity),
so a `/classes`-based subject source would leak compartmented classes the moment the store is
populated. The subject-source the next increment picks must be **`can_view`-applying** (route
through the same filtered candidate-pool path the `/resolve` seal uses, or add the filter), not
just live-ontology-derived. Identity is threaded in `authorized_subjects` now so the property holds
the moment the source is correct.

### Decision B — when is the interview done? (termination)

**RULED: the interview terminates when the accumulated steps assemble into a `WorkflowDefinition`
that VALIDATES — server-side, against the schema — NOT when an LLM sets a flag.**

The old interview ended on the LLM's `is_ready_to_compile` (prompt-gated, model-authored). The
SPO version's completeness predicate is the schema's own required fields: every `spo_operation`
has `subject`+`verb`, every `human_await` has `audience`, every `direct_call` has
`endpoint`+`capability`, and there is ≥1 step with `id`+`name` set. `try_finalize(state)` runs
`WorkflowDefinition.model_validate(assembled)` and returns either the validated definition or the
list of what's still missing (which drives the next question). **Termination = schema validity**
— deterministic, server-side, un-gameable by a confident model. (The LLM may still *propose*
"I think we're done"; the server confirms by validating, and if it doesn't validate, the
missing-field list is exactly the next thing to ask.)

### Decision C — how does the definition enter git? (authorship vs assertion)

**RULED: the interview PRODUCES a `policy/workflows/<id>.yaml` file; the HUMAN commits it. No
auto-write to git, no auto-compile.**

Definitions are git-asserted policy files (Slice-1 ruling Q4), reviewed like the grant files,
git-blame = the audit trail. An interview that auto-committed (or auto-compiled, as the old
`BpmnCatalog`→Dagster path does) would be **the bot-authored-grant problem in workflow clothing**
— an unauditable assertion the whole grant core forbids. So: *the interview authors, the human
asserts.* The interview emits the YAML (to a review/PR path or a scratch location the author
commits); a human's commit is what makes it real. This also cleanly supersedes the old
auto-compile — the `BpmnCatalog` write path is *not* reused.

## 3. What the SPO interview STRENGTHENS over the old one (each weakness → a gate)

| Old (BPMN interview) | SPO interview |
|---|---|
| No verb question; subject+object only | **Verb elicited from `/find_compatible_verbs`** (Decision A) — the predicate the model always needed |
| Exact-match constraint is PROMPT-ONLY | **Server-side pick validation** — a pick not in the computed authorized set is REFUSED and re-prompted (select-from-authorized-set *enforced*, [[feedback_select_from_authorized_set]]) |
| Termination = LLM `is_ready_to_compile` flag | **Termination = the definition VALIDATES** (Decision B) — server-side, deterministic |
| Data sources = hardcoded placeholder string | **Real Engine D enumeration** via `GET /tables` (survey §2/§5) |
| Auto-compiles to Dagster via BpmnCatalog | **Emits a YAML file; human commits** (Decision C) — no bot-authored artifact |

## 4. The flow (per step kind)

The interview accumulates steps toward a `WorkflowDefinition`. Per turn: the LLM maps the user's
NL to a candidate pick, the server validates the pick against the computed authorized set, and
`try_finalize` checks whether the definition validates yet.

- **`spo_operation`:** (1) SUBJECT — pick from the ontology-class set (Engine O `/classes`) +
  data instances (Engine D `/tables`), validated server-side. (2) VERB — fetch
  `/find_compatible_verbs {subject, entitled_domains=[workflow domain]}`, present the eligible
  set with advisory permission annotations, validate the pick. (3) OUTPUT — the chosen verb's
  `output_uri` IS `expected_output` (auto-derived from the `CompatibleVerb`; usually not a
  question).
- **`human_await`:** elicit `audience` from the seeded task-audiences (`task_grants.yaml` /
  Topaz), + `subject_ref`. The audience is itself a select-from-authorized-set pick.
- **`direct_call`:** the transitional escape hatch (Slice-1 ruling Q3). The interview steers
  toward `spo_operation`; a `direct_call` requires the author to name an `endpoint` + a
  `capability` (which Topaz will gate). Flagged in-interview as "prefer a registered verb."

## 5. The build shape (this slice)

**Additive, unwired, old interrogator untouched.** Mirrors the Slice-1 split (a pure, testable
core module + a thin driver), so the enforceable innovation is unit-tested without the LLM:

- **`agent_fleet/restate_analyst/spo_interview.py` — the PURE core** (no Restate, no live LLM;
  the analogue of `spo_step_executor.py`):
  - `authorized_subjects(engine_o_url, domain)` — fetch the class set (+ later, D instances).
  - `authorized_verbs(subject_uri, workflow_domain, engine_o_url)` — call
    `/find_compatible_verbs`; return the structural set + per-verb advisory permission annotation.
  - `validate_pick(pick, authorized_set)` — server-side exact-match enforcement (REFUSE
    out-of-set).
  - `InterviewState` (accumulated steps + declared id/name/domain) + `try_finalize(state)` →
    `(WorkflowDefinition | missing_fields)` via `model_validate` (termination = validity).
  - `emit_definition_yaml(definition)` → the `policy/workflows/<id>.yaml` content for human
    commit (round-trips through `load_workflow_definition`).
- **`tests/test_spo_interview.py`** — red-first: verb-set-from-eligibility, pick-validation
  (out-of-set refused), termination (incomplete→missing-fields, complete→validates), YAML emit
  round-trip.
- **The LLM conversational shell (BAML) — SPEC'd here, built next.** A new BAML function
  (`InterviewSPOWorkflow` — replaces `IterateBPMNGraph`) that, given history + the current partial
  definition + the *computed authorized sets*, returns the next question or a candidate pick.
  Deferred in-build because BAML needs `baml-cli generate` (a deploy seam, [[project_baml_deploy_seam]])
  which can't be live-tested here; the pure core is the enforceable part and is fully testable now.
  Signature spec: `InterviewSPOWorkflow(chat_history, partial_definition_json, available_subjects,
  available_verbs, available_audiences) -> SPOInterviewTurn{agent_reply, candidate_pick?}` — note
  the sets are COMPUTED and passed in (the model picks *from* them; the server validates the pick),
  and there is NO `is_ready_to_compile` (termination is server-side).

## 6. Scope + deferred

- **In this slice:** the pure core + tests + this design doc. The enforceable machinery
  (authorized-set computation, server-side pick validation, verb-from-eligibility,
  termination-on-validity, YAML emit).
- **Next (own increment):** the BAML conversational shell + a `ProcessInterviewerV2` VirtualObject
  wiring the core to the LLM + a live seal (author a real promotion-shaped definition end-to-end,
  confirm it validates and matches the Slice-1 hand-written YAML). Needs `baml-cli generate`.
- **Deferred:** retiring the old BPMN interrogator + `BpmnCatalog` (staged, after the V2 interview
  runs); the interview later authoring ODCS/ODPS models (the greenfield future, ADR-0029 Decision 2).

## 7. Live-integration findings (2026-07-15, sandbox — composed-path probe + store-vs-query discrimination)

The pure core is unit-tested (12/12); a live probe of the two Engine O seams, plus a
store-vs-query discrimination on the empty subject menu, found:

- **VERB question — LIVE + correct.** `POST /find_compatible_verbs {subject_uri:mesh#AgentTask}`
  → `["mesh:analyzeWithCodeAgent"]` with the full annotation (`output_uri`, `endpoint_url`,
  `owner_persona`, `domains`) `_parse_verbs` consumes. The novel half — the predicate the old
  interview never asked — works end-to-end against the real engine.
- **SUBJECT source `/classes` returns EMPTY — and the discrimination says INGEST GAP, not
  query-wrong (fix = a doc-tools run, NOT code).** `/classes` returns count 0 for every
  query/domain. The store-vs-query check (run BEFORE touching code):
  - `/resolve('maintenance procedure')` recalls `MaintenanceReferenceOntology/Procedure` at
    **conf 0.96** → the ontology IS present in the VECTOR store (Weaviate).
  - Fuseki (via the working `/ds/sparql` endpoint) has **ZERO triples total** → the RDF/Jena
    graph the SPARQL queries is genuinely EMPTY. So it is present-in-vector, absent-in-Fuseki:
    a **partial ingestion** — the doc-tools RDF→Jena half never (re-)populated Fuseki (consistent
    with a substrate reset that wasn't re-primed). **The query is fine (querying an empty store);
    the fix is an ingest run, not a rewrite.**
  - The query name (`_SPARQL_MAINTENANCE_CLASSES`) is a **smell** but half-wrong: its WHERE clause
    is GENERIC (`?c a owl:Class ; rdfs:label ?l`), NOT maintenance-filtered — and it IGNORES the
    `domain` param entirely (no `?domain` binding). So a de-hardcode is a minor future cleanup;
    the *blocker* is the empty store.
  - **Secondary smell (not the blocker):** the pod's `JENA_SPARQL_ENDPOINT` seen was `/ds/query`,
    which 404s; the working endpoint is `/ds/sparql`. Worth a config check once the store is
    ingested (an empty store hides it today).
- **`/classes` does NOT apply `can_view`** (`ontology_service/main.py:2205` — raw SPARQL rows, no
  identity filter), and **nothing else consumes `/classes`** (the old interview was its sole
  reader — which is why nobody noticed it was subject-less). So `/classes` is doubly-inadequate
  as the SPO subject source: empty AND unfiltered.

**NEXT-INCREMENT ACTION (item 1, before wiring the LLM):** (a) run the doc-tools RDF ingest to
populate Fuseki (unblocks the menu); (b) route the subject menu through a **`can_view`-applying**
source (the `/resolve` candidate-pool path, or add the filter to a class-list endpoint) so
ruling A's self-gating holds — `authorized_subjects` already threads `caller_email` for this;
(c) optionally add Engine D `GET /tables` for dataset subjects. The verb half is unaffected (it
keys off a resolved `subject_uri`). Prove all of it with a composed-path seal: a granted author
sees a compartment's classes in the menu, an ungranted author does not, and a real
subject→verb→validating-definition round-trip matches the Slice-1 promotion YAML.

## 8. Decision D — the operation-subject menu source (RULED 2026-07-22)

Surfaced once Slice-2 was deployed and the ontology menu actually populated (see the
regression STATE, `tests/routing/STATE_2026_07_22_regression_baseline.md`): the subject
menu (`/classes`, the Fuseki IOF ontology vocabulary) and the verb-bearing subjects (the
Neo4j capability graph) are **not the same set**. Measured live on the stable state
(rev 59 / chart 0.3.26): menu = 122, verb-bearing = 14, overlap = 7. So **94% of menu
subjects carry no compatible verb** — an author browsing the menu hits mostly dead-ends.
(NB: this is a signal-to-noise issue, not a blocker — `spo_operation` is proven live on the
7, e.g. `TechnicalManual → mesh:retrieveKnowledge`. An earlier note calling the sets
"disjoint / blocked" was a mid-ingest snapshot and is retracted in the STATE file.)

**Ruling: SOURCE the operation-subject menu from the capability graph — do not filter
`/classes`.** These sound identical (both yield the 7) but differ in *where truth lives*:

- A *filter* keeps the ontology as the source and treats "has a verb" as a decoration
  subtracted from it. When verbs are later registered on new classes, someone has to
  remember the filter exists for the menu to grow.
- *Sourcing* says the operation-subject question's authorized set **is** "subjects the mesh
  can act on" — which lives in the Neo4j capability graph, intersected with `domain` and
  (post-ADR-0025-flip) `can_view`. When verbs are registered on a new class, the menu grows
  automatically. This is the same **consumer-derives-from-producer** rule the graph-name fix
  taught. It also means growing verb coverage is not a competing option — it is *how this
  menu gets richer*: the mechanism (source from capability graph) and the content (register
  more verbs) are the same decision from two ends.

Authorized operation-subject set = **`domain ∩ can_view ∩ has-a-compatible-verb`**.

**The role rule (this is the actual design, not a caveat): each interview question draws
from the authorized set *for its role*.**

| Question / role | Source | Contract |
|---|---|---|
| `spo_operation` subject | capability graph (verb-bearing subjects) | *actionable* — must have a compatible verb |
| `human_await` `subject_ref`, `participants`, `classification` | full ontology vocabulary (`/classes`) | *nameable* — any ontology class is fine |

This dissolves the "two-tier menu" idea: the tiers are not a UI treatment, they are different
questions with different sources. (Residual, out of scope for this ruling: whether the
operation-subject step should *show* the non-actionable classes greyed-out for discoverability.
Lean is no — 7 items is a menu; 122 with 115 disabled is a wall — but cheap to revisit.)

**Rejected — C (leave the full ontology menu, surface "no verbs" only when the pick fails):**
rejected on principle, not preference. A menu where 94% of choices dead-end *after* the author
has invested in the path is the human-facing form of silent degradation — the system knows at
question-time which subjects can't complete and withholds that until failure. The standing rule
is to surface constraints at the earliest point the system knows them; it applies to interviews
as much as to routing confidence.

**Rider for the ADR-0025 auth-flip checklist:** `can_view` is the unexercised term in the
intersection — it has never fired in any environment. Building the operation menu on
`domain ∩ can_view ∩ has-verb` means the auth flip will *change menu contents*. Expected, but
after the flip, confirm the operation menu still shows what an entitled user should see —
otherwise the flip's first symptom is "my subjects disappeared" and someone debugs the menu
instead of the entitlement.
