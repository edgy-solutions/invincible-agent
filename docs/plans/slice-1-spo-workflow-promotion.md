# Slice 1 design — the step call-shape + the promotion workflow as an SPO-native definition

**Status:** DESIGN for review — no code written. Implements ADR-0029 Slice 1
("re-express the sealed HITL promotion workflow as an SPO-native git-asserted
definition, proving the model against the one workflow known to work"). Grounded in
two code surveys (2026-07-12): the router call-shape and the promotion seal.

The purpose of this artifact is to answer, on paper, the questions that decide
whether the model survives contact with the sealed workflow — **before** any code
touches the sealed runner. Four load-bearing questions (flagged in review): (1) the
step call-shape; (2) *whose identity* a step executes as; (3) whether a step emits
an AnswerArtifact; (4) whether every sealed step is even SPO-shaped (the `publish`
question). Each is answered below with a citation to current code.

---

## 0. The two realities the design must respect

**Router reality** (`src/iagent/defs/dynamic_supervisor.py`):
- `_classify_route(context, user_query, entitled_domains, routing_domain,
  entity_refs, user_email)` is **already a pure function** — structured in →
  `(status, predicate, telemetry)` out, no HTTP/SSE/human-synthesis. It runs three
  stages: **(1)** `/resolve` NL→subject-class, **(2)** `/find_compatible_verbs`
  Neo4j **structural gate** (domain ∩ arity ∩ argument-fit), **(3)**
  `/classify_predicate` NL→verb.
- Dispatch is a plain `requests.post(endpoint, json=payload)` where `payload`
  threads `user_email` (authz_id), `entitled_domains`, `user_persona`,
  `predicate_verb_iri`, `resolved_subject_uri`, `resolved_instance_id`. The engine
  returns a structured `expert_response` (`rendered_output`, `sources`,
  `referenced_uris`, `status`).
- Everything a step must **bypass** is cleanly separable and lives *above*
  `_classify_route`: SSE streaming + keepalive, `session_id` dedup, Engine F
  `/render_ui` synthesis-for-human, typed-SSE projection, the fire-and-forget
  `AnswerArtifactBundle` write.

**Seal reality** (`agent_fleet/restate_analyst/main.py`, `src/iagent/human_tasks.py`,
`policy/task_grants.yaml`, `tests/sandbox_e2e/_seal_full_loop.py`):
- The **sealed mechanics** are the human-await loop: `_register_human_task` (durable,
  inside `ctx.run`, BEFORE suspend) → `await ctx.promise("approval_{task_id}").value()`
  → resume only after `human_tasks.check_can_act(audience, caller_authz_id)` passes
  at `/human_tasks/{id}/act` → `/BPMNWorkflowRunner/{wf}/approve` resolves the
  promise. Deny-by-default: unauthorized caller neither sees (recipient-filtered
  projection) nor acts (`can_act` → 403); workflow stays suspended (not torn down).
- `_seal_full_loop.py` proves this loop end-to-end (Case-1 access-grant): deny →
  request → **alice approves (`can_act` True)** → grant → re-query works; bob/carol
  denied. Case-2 (promotion) reuses the *identical* loop with audience
  `promotion:DATA_ENGINEERING` (alice granted `actor`; bob/carol not).
- **The current runner already executes every step as the initiator**: `run()` does
  `task = {**task, "user_jwt": user_jwt}` and `_execute_service_task` authenticates
  with that JWT, hitting **real** Topaz denials → `restate.TerminalError`
  (fail-and-release, Situation C). *Steps-run-as-initiator is the sealed precedent,
  not a new decision.*

---

## 1. The core insight — a step is PRE-RESOLVED (refines ADR-0029 Decision 5)

A **query** starts from natural language and must *resolve* to `(subject, verb)`: it
needs stage 1 (NL→subject) and stage 3 (NL→verb). A **step declares** its subject
and verb — it is already resolved. Therefore:

> **A step does NOT invoke the NL-resolution half of the router (stages 1 + 3). It
> invokes the STRUCTURAL ELIGIBILITY half (stage 2) as a *verifier*, then dispatches.**

Concretely, a step hands the router a declared `(subject_uri/instance, verb_iri)`.
The router runs `_find_compatible_verbs(subject_uri, entitled_domains)` +
arity/argument-fit filters + the permission dimension, and:
- **the declared verb IS in the eligible set** → return its Neo4j-authoritative
  `endpoint`/`domains`/`owner_persona`; the step dispatches.
- **the declared verb is NOT in the eligible set** (caller lacks permission, or
  domain/arity/arg-fit excludes it) → the step **FAILS** (Situation C:
  `TerminalError`, fail-and-release — a denial is a failure, never a suspend).

This is *better* than "invoke the router as if it were a query" in two ways: it
removes NL ambiguity (a step means exactly what it declares), and it **preserves
enforcement-by-construction** — a step can only execute a verb the caller is eligible
for, checked by the same `domain ∩ arity ∩ argument-fit ∩ permission` intersection
that gates queries ([[feedback_verb_eligibility_intersection]]). The permission
dimension is what makes "workflow steps are access-governed by construction"
(ADR-0029 Decision 5) *literally true* at the dispatch seam.

**Call-shape (design intent, not final code):**
```
step_execute(step, ctx_identity) ->
    # 1. structural eligibility (stage-2 verifier) — enforcement point
    eligible = find_compatible_verbs(step.subject_uri, ctx_identity.entitled_domains)
    predicate = eligible.match(step.verb_iri)  # None -> TerminalError (fail-and-release)
    # 2. dispatch (same payload shape as the query path's specialist dispatch)
    resp = POST(predicate.endpoint, {
        user_query:        step.rendered_intent,     # see §2 "input envelope"
        user_email:        ctx_identity.authz_id,     # WHOSE identity — see §3
        entitled_domains:  ctx_identity.entitled_domains,
        user_persona:      ctx_identity.persona,
        predicate_verb_iri: step.verb_iri,
        resolved_subject_uri:  step.subject_uri,
        resolved_instance_id:  step.subject_instance,
    })
    if resp.status in (401,403): raise TerminalError(...)   # Situation C
    return resp.json()   # structured expert_response — NOT rendered for a human
```

---

## 2. The step call-shape — the four questions answered

### (a) Input envelope — what a step hands the router
`{ subject_uri, subject_instance, verb_iri, expected_output?, rendered_intent?,
inputs_from? }`, plus the **identity context** (§3). Notes:
- `rendered_intent` — engines still take a `user_query` string; for a step this is a
  *templated* intent ("publish artifact {subject}"), not a user's NL question. It is
  NOT re-classified (the verb is already chosen); it is context for the engine's own
  execution.
- `inputs_from` — how step N+1 consumes step N's output. **Designed but NOT exercised
  in Slice 1** (the promotion workflow's publish step takes a *declared* `subject_ref`,
  not the approval's output — no chaining needed). Deferred to a slice that has a real
  data dependency, kept in the model so it isn't retrofitted.

### (b) WHOSE identity a step executes as — **initiator (preserves the seal)**
The step's identity context is the **workflow initiator** — `request["user_jwt"]` /
its `authz_id`, exactly as the runner threads today. Consequences, all intended:
- **No escalation:** starting a workflow cannot grant authority the initiator lacks;
  steps are bounded by the initiator's grants and hit real denials → fail-and-release.
- **This is the sealed behavior**, so re-expressing it changes nothing about identity
  — the safest choice for a slice whose job is "don't break the seal."

**Open question, deliberately deferred (§6):** for a *promotion*, the approver's
`can_act` is arguably the authority that should carry the subsequent publish
("approval confers authority"), i.e. a **delegated-authority** model where the
post-approval step runs as/with the approval rather than the initiator. That is a
*new* decision with its own seal; it must NOT ride in on the re-expression slice.
Slice 1 = initiator identity, matching today.

### (c) Does a step emit an AnswerArtifact? — **No (Slice 1)**
The `AnswerArtifactBundle` write is query-path wrapping (fire-and-forget after
`stream_end`), not part of the route+dispatch core. A step's output is the engine's
structured `expert_response`, captured in the **workflow journal / result**, not the
answer history. Rationale:
- Keeps the answer list meaning "questions the user asked," not "every automated step"
  (the flood worry). Workflow-step visibility belongs to the **observation model**
  (ADR-0029 Slice 3), gated by the 3-audience tiers — a different surface with
  different access rules than a user's personal answer history.
- The model MAY later mark a step `emit_artifact: true` for steps whose output *is* a
  user-facing answer; off by default. Not in Slice 1.

### (d) Which query-pipeline stages a step bypasses

| Pipeline stage | Query | Step | Why |
|---|---|---|---|
| SSE stream + keepalive | ✔ | **bypass** | no human stream; structured return |
| `session_id` dedup | ✔ | **bypass** | Restate journal/`ctx.run` replay IS the idempotency |
| Stage 1 — NL→subject resolve | ✔ | **bypass** | step declares the subject |
| Stage 2 — structural eligibility gate | ✔ | **KEEP (as verifier)** | the enforcement point; verb must be eligible for the caller |
| Stage 3 — NL→verb classify | ✔ | **bypass** | step declares the verb |
| Engine dispatch | ✔ | **KEEP** | the actual work; same payload shape |
| Engine F `/render_ui` synthesis-for-human | ✔ | **bypass** | no human; structured `expert_response` is the output |
| Typed-SSE projection | ✔ | **bypass** | no event stream to project into |
| `AnswerArtifactBundle` write | ✔ | **bypass** (Slice 1) | §2(c); observation model instead |

---

## 3. The promotion workflow as an SPO-native `WorkflowDefinition`

Git-asserted (reviewed like `asset_grants.yaml` / `task_grants.yaml`, so
classification + grants compose). Executed on the existing Restate runner (reused as
executor). Illustrative shape:

```yaml
# policy/workflows/promote_answer_artifact.yaml
id: promote_answer_artifact
name: "Promote an AnswerArtifact (DATA_ENGINEERING) before publish"
classification: DATA_ENGINEERING          # gates OBSERVERS (3-audience tiers)
participants:
  - role: initiator                       # identity all steps execute as (§3b)
  - role: approver                        # resolved from the audience
domain_stages: [awaiting_approval, publishing, published]

steps:
  - kind: human_await                     # maps 1:1 to today's user_task — SEALED mechanics
    id: approve_promotion
    audience: "promotion:DATA_ENGINEERING"   # Topaz task_audience; alice granted `actor`
    subject_ref: "{artifact_urn}"            # the artifact being promoted (the subject)
    title:   "Approve promotion of {artifact_label}"
    summary: "Promote this answer artifact to the published catalog"
    # verb is implicit (approve/promote); the audience IS the authorized set.
    # register-durable -> suspend on approval_{id} -> can_act -> resolve. UNCHANGED.

  - kind: <SPO-operation OR direct-call — see §4>   # the publish emit
    id: publish_artifact
    subject: "{artifact_urn}"
    verb:    "mesh:publishArtifact"
    expected_output: "mesh:PublishedProduct"
    # executes as the initiator (§3b); a denial fails-and-releases (Situation C).

observable_state:
  visible:  [domain_stages, approve_promotion.status]   # per 3-audience tiers (Slice 3)
  internal: [publish_artifact.result]
```

**The `human_await` step maps 1:1 onto the sealed mechanics** — it is a rename/
re-home of today's `user_task` (same `audience`/`title`/`summary`/`subject_ref`,
same register→suspend→`can_act`→resolve). This is why Slice 1 can preserve the seal:
the load-bearing, already-proven part is carried over verbatim; only the *definition
language* around it changes from an inline task list to a git-asserted SPO document.

---

## 4. The `publish` finding — is every sealed step SPO-shaped? (the predicted paper-learning)

**Finding:** the human-await step is trivially model-native (it was never SPO — it's
a human-await, its own step kind). The **publish emit is the SPO-vs-not question.**
Today it is a `service_task`: an opaque `POST agent_endpoint` with a `service_payload`
— **not** `(subject, verb)`. Two ways to express it:

- **(A) `publish` as a registered mesh VERB** — `mesh:publishArtifact` becomes a real
  predicate (Neo4j edge with an `endpoint_url`, an `owner_persona`, a declared
  `output_uri`). Then `publish_artifact` is a true `spo_operation` step routed through
  the stage-2 verifier — and **who may publish becomes the permission dimension on the
  publish verb**, i.e. publish comes under enforcement-by-construction like any verb.
  Model-pure; the right end state.
- **(B) `direct_call` step (escape hatch)** — a step kind that POSTs to a declared
  endpoint, preserving today's `service_task` exactly. Seal-preserving with zero new
  ontology work — but it is a **bypass of the eligibility intersection** (the very
  un-governed shape the model exists to leave), so it must be flagged, not adopted
  silently.

**Recommendation (failure-mode-pluralism — change one thing at a time):**
> Slice 1 expresses publish as a **`direct_call`** step (preserves the sealed POST
> exactly, so the re-expression is provably behavior-identical), **and files
> "register `publishArtifact` as a mesh verb" as the immediate follow-up** that closes
> the `direct_call` escape hatch and brings publish under enforcement-by-construction.

Rationale: Slice 1's job is to prove the *model shape* against the proven workflow
without breaking the seal. Re-homing the human-await into the SPO document + carrying
publish as a behavior-identical `direct_call` does exactly that and nothing else. The
verb-registration is a separate, independently-sealable change (does the publish emit
still fire, now gated by `can_publish`?). Bundling them would hide which one moved the
result. **The existence of `direct_call` is itself a finding to pin in the ADR:** the
model needs an explicit, discouraged, audited escape hatch for infrastructural actions
that are not (yet) mesh verbs — with the standing rule that any `direct_call` is a
candidate for promotion to a real verb.

---

## 5. Slice 1 scope + seal plan

**In scope:**
1. Define the git-asserted `WorkflowDefinition` schema (the YAML shape above) + a
   loader.
2. Teach the runner to execute a `human_await` step from that definition — **carrying
   the sealed register→suspend→`can_act`→resolve mechanics verbatim** (this is the
   whole point: prove the new definition language drives the *identical* sealed path).
3. Express publish as a `direct_call` step (behavior-identical to today's
   service_task).
4. **Re-run the sealed human-await loop through the SPO-native definition path** and
   show it still GREEN: alice (granted `actor` on `promotion:DATA_ENGINEERING`) sees +
   approves + the workflow resumes; bob/carol neither see nor act (403/absent) + the
   workflow stays suspended. This is the existing `_seal_full_loop.py` discipline
   pointed at the promotion audience through the new definition.

**Explicitly deferred (NOT Slice 1):**
- `spo_operation` for publish / registering `publishArtifact` as a verb (§4 follow-up).
- Delegated-authority identity for post-approval steps (§3b open question).
- Output-chaining `inputs_from` (§2a — no data dependency in this workflow).
- AnswerArtifact emission from steps (§2c — observation model, Slice 3).
- The re-aimed SPO interview (Slice 2), observation (Slice 3), seeding (Slice 4),
  multi-approval joins (Slice 5).

**Success = the seal stays GREEN through the re-expression.** If the SPO-native
definition *cannot* drive the sealed human-await path, that is the cheap early
learning the design-first sequencing exists to surface.

---

## 6. Open questions for review (decide before/with implementation)

1. **Delegated authority (§3b).** Slice 1 runs post-approval steps as the *initiator*
   (preserves the seal). Is "approval confers authority for the subsequent step"
   (approver-identity or a derived grant) a wanted future model, or should steps
   always be initiator-bounded? Recommendation: initiator-bounded for Slice 1; open a
   separate ADR amendment if delegated authority is wanted.
2. **`publish` as verb vs `direct_call` (§4).** Confirm the recommendation: ship
   `direct_call` in Slice 1, register `publishArtifact` as a verb as the immediate
   next change. (The alternative — do the verb registration *inside* Slice 1 — couples
   two changes; not recommended.)
3. **`direct_call` as a permanent model citizen?** Is an audited escape hatch for
   non-verb infrastructural actions acceptable in the model (with a "promote to verb"
   standing rule), or should the model forbid it and require every step be a real
   verb? Recommendation: allow it, discouraged + audited — real systems have
   lifecycle actions that aren't query verbs.
4. **Definition storage.** `policy/workflows/*.yaml` (git, reviewed like grants) —
   confirm this is the right home (vs a DB table). Recommendation: git, for the same
   auditability/classification-composition reasons grants are in git.
```
