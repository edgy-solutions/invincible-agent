---
status: Accepted (architecture) — single-dimension built, composable deferred
date: 2026-07-09
deciders: Platform team
---

# ADR-0027 — Composable multi-dimensional approval policy (grant-issuance governance over the single decider)

## Status

**Accepted** for the *architectural decision* (2026-07-09); the composable
multi-dimensional capability is **designed, not built**.

This ADR records **where the approval-policy layer lives and how it composes** —
the boundaries and invariants that constrain any future build. It does NOT author
the policy engine, a policy language, or a dimension set. Per the lifecycle
protocol (status tracks the *decision*, the Rollout section tracks the *build*):
what EXISTS today is **single-dimension approval** — one git-asserted approver
(`task_audience` `can_act`, a domain steward) resolves one access request, proven
live in the HITL Case-1 flow ([[project_hitl_grant_dashboard_spec]]). The
**multi-dimensional, composable** version (`owner AND safety-officer AND
domain-owner`; `clearance AND need-to-know AND location AND device`) is the
deferred build, with triggers named in "Deferred" below.

Written NOW, while the enforcement arc is fresh, so the future build opens onto
**decided ground** — the hard-won invariants (single-decider, grant-as-primitive,
fail-closed) become constraints handed to whoever builds the engine, rather than
constraints they must re-derive (and might get wrong — e.g. a parallel approval
engine that breaks single-decider). Same "decide the architecture, defer the
build, so it opens onto prepared ground" pattern the project runs on.

## Context

The HITL access-grant flow (ADR-0025 enforcement + the HumanTask substrate)
routes a denied access request to an approver and, on approval, writes a
git-asserted grant that opens the gate. A question surfaced the seam: **what is
the source of truth for who approves?** That question separates cleanly into
**three layers**, each in a different state of built-ness:

- **Layer 1 — facts about data (DataHub → Topaz).** Who owns/manages a dataset,
  and what-sort-of-data-it-is (classification, sensitivity, domain). **Built for
  ownership** (`datahub_topaz_sync` → `dataset owner` relations); the
  **classification/compartment facts are the filed work-deploy model-extension**
  (see [[project_ontology_visibility_compartment_scoped]] for the compartment
  overlay pattern; the dataset-classification sync is its sibling).
- **Layer 2 — the gate (Topaz).** The single decider gates access on those
  facts, deny-by-default. **Built and sealed** — the whole enforcement arc
  (ADR-0025, four content namespaces + the query DSL + the HITL fifth namespace).
- **Layer 3 — the policy for HOW a grant is issued.** Multi-dimensional,
  composable approval: this grant requires the safety officer AND the data owner
  AND the domain owner to approve; or the requester must satisfy clearance AND
  need-to-know AND be on an approved device AND from an approved location. **This
  ADR's concern.** What exists is single-approver / single-dimension; the
  composable multi-dimensional engine is not built.

The honest state: **Layers 1 and 2 are built** (ownership facts → Topaz gate →
deny-by-default access). **Layer 3 is architecture-supported but only built to
single-dimension.** This ADR decides Layer 3's architecture so the composable
version — which classification WILL require — is built on settled ground.

A note the arc already forces: at TS/compartmented classification,
**approval-authority is not data ownership**. Owning a dataset ≠ authority to
admit people to its compartment; a compartment security officer approves
compartment access regardless of who owns individual datasets. So the
git-asserted-approver model (a *deliberately assigned* authority, not a
derived-from-ownership fact) is the classification-appropriate shape — and its
current disconnection from DataHub ownership is *correct* for classified data,
not a gap. The gap is only that the policy does not yet *consume* the facts
DataHub owns (owner, classification) to *choose* the approver per-classification.

## Decision — the settled boundaries (decide now)

1. **The approval-policy layer sits ON the single decider, not beside it.**
   Multi-dimensional approval is authored as **Topaz policy (rego)**, evaluated
   by the SAME single decider — it introduces NO second policy engine. This is
   forced by the ratified single-decider invariant ([[feedback_single_authz_decider]]):
   two policy heads is the two-authz-truths drift. **No parallel approval
   service.** An approval-policy engine that lived outside Topaz would be exactly
   the second decider the arc rejects.

2. **Grants remain the enforced primitive; approval-policy governs how a grant is
   ISSUED, not how access is gated.** The gate still checks "is there a grant"
   (deny-by-default, ADR-0025 — `reader | owner`, `can_view`, `can_act`). The
   approval policy governs the *process that produces the grant*. This is the
   load-bearing boundary: **grant-issuance-governance ≠ access-gating.** Keeping
   them separate is what lets the gate stay simple (grant-or-not) while the
   issuance policy grows rich (N approvers, attribute conditions). Do not fold
   approval conditions INTO the gate; the gate reads grants, the policy writes
   them.

3. **Two categories of dimension — a taxonomy, decided now.** A grant's
   requirements are a composable expression over two kinds of dimension:
   - **Auto-checked attributes** — facts about the requester/context evaluated by
     the policy WITHOUT human action (clearance, need-to-know, location, device).
     Mechanism: **attribute check** (ABAC subject/resource/environment attributes,
     which the single-decider model already expresses).
   - **Human approvals** — decisions routed to a person (data owner, safety
     officer, domain owner). Mechanism: **HITL task routing** (the built
     substrate).
   The distinction is forced by the nature of the dimension (a fact vs a
   decision) and it determines the mechanism. Decide the taxonomy now even if the
   specific dimensions come later.
   **PRECEDENCE (decided now): auto-checked necessary-conditions gate FIRST, human
   approvals are routed ONLY for requests that pass them.** Two reasons, one of
   them a classification requirement: (a) fail-fast — don't route a task to the
   safety officer for a request that already auto-fails clearance; (b) EXISTENCE-
   ORACLE — routing a task that reveals "<subject> requested <compartmented-thing>"
   to an approver is itself a disclosure, so a request that auto-fails need-to-know
   must be DENIED BEFORE any human-approval task is created (the task's very
   existence would leak; see [[project_ontology_visibility_compartment_scoped]] /
   [[feedback_deny_by_construction_calibration]]). Auto-checks are the cheap,
   silent, deny-before-routing gate; human approvals are sought only on the
   surviving set.

4. **Multi-approval EXTENDS the HITL substrate; it does not replace it.** "Safety
   officer AND data owner AND domain owner must approve" = **N HumanTasks that
   jointly gate ONE grant** — the grant is written only when all required
   approvals land. This is the built substrate ([[project_hitl_grant_dashboard_spec]],
   the one-abstraction-two-fulfillments design) plus a **join** ("all required
   approvals gathered"), NOT a new system. The join is new logic; the task
   substrate, the fifth namespace, and the fulfillment dispatch are reused.
   **The join-completion decision is a TOPAZ POLICY EVALUATION, not an external
   orchestrator.** "Are all required approvals present" is decided by the single
   decider reading the approval relations (each approval a relation Topaz holds),
   NOT by a separate service that tracks partial state and decides when to issue.
   This closes the seam Decision 1 forbids: a "grant-issuance orchestrator" that
   tracks approvals and decides completion IS a second decider wearing a different
   name — reject it. The individual approvals are captured as durable facts (the
   HumanTask records + the approval relations); the *decision that the set is
   complete and the grant is authorized* is Topaz evaluating those facts. What
   lives outside Topaz is only the plumbing (route tasks, write approval
   relations, trigger a re-evaluation) — never the completion *decision*.

5. **DataHub is the source of truth for the facts the policy consumes.** Owner
   and classification/compartment come from DataHub → Topaz (Layer 1). The
   approver-selection policy and the attribute checks CONSUME these facts; they do
   not re-assert them. The **request carries the dataset's owner (DataHub-derived)
   for the approver's context** even when a *different* authority approves —
   DataHub-drives-context-and-inputs, the policy-decides-authority. This ADR
   **depends on the classification/compartment model-extension** feeding those
   facts (cross-referenced below).

6. **Fail-closed applies to the policy engine itself.** An approval policy that
   cannot be evaluated — a required approver unresolvable, an attribute source
   unreachable — **fails closed: no grant**, never fails open. The arc's governing
   invariant ([[access-regulates-persona-domain]], [[broken-closed-hides-brokenness]])
   applied to the new layer. A missing dimension is a DENY, not a skip.
   **Distinguish an INCOMPLETE-PENDING join from an INCOMPLETE-UNSATISFIABLE one**
   (both yield no grant, but they are different states): incomplete-PENDING is the
   NORMAL in-progress state — 2 of 3 approvals gathered, waiting on the third — no
   grant YET, correctly, and BOUNDED (it must have an expiry, per Decision 4's
   deferred join semantics). Incomplete-UNSATISFIABLE is an ERROR state — a
   required approver can never approve (left the org, revoked authority, an
   auto-condition became permanently false) — the join can NEVER complete, so it
   must **fail-closed AND TERMINATE + release** (no grant, cleaned up), NOT sit
   pending forever. A join that can never complete but parks state indefinitely is
   the held-state / DoS surface the HITL work spent its rigor eliminating
   ([[hitl-suspend-vs-fail-ruling]], [[lifecycle-state-observable]]) — an
   unsatisfiable join is the multi-approval analogue of a mid-workflow denial:
   fail-and-release, never park.

## What this does NOT decide (deferred, with triggers)

These need real requirements; specifying them now would be premature over-design
(locking in decisions we'd regret on contact with real approval workflows).

- **The composable policy LANGUAGE** — how `owner AND safety-officer AND
  domain-owner` is expressed (and evaluated on the single decider). *Trigger:* a
  real deployment with a real multi-approver requirement.
- **The specific attribute dimensions and their SOURCES** — clearance and
  need-to-know ride the filed classification extension; **location and device
  have NO attribute source today** (the facts don't flow). Wiring an attribute
  requires a source. *Trigger:* a requirement for location/device-gated access
  (likely a specific classified deployment).
- **The approver-selection policy** — owner-approves vs steward-approves vs
  compartment-authority-approves. **Settled that it is a policy CONSUMING DataHub
  facts** (owner, classification), not the current hardcoded single steward; the
  *specific* policy (per-classification routing: unclassified → owner; classified
  → compartment authority) is deferred. *Trigger:* the classification/compartment
  model-extension landing.
- **The join semantics for multi-approval** — all-of? threshold (2-of-3)? ordered
  vs parallel? expiry of a partially-gathered set? *Trigger:* a real
  multi-approval requirement.

## Rollout / current state

- **Built (single-dimension):** one git-asserted approver (`task_audience`
  `can_act`) resolves one access request; approval writes one git-asserted grant
  through the sealed `grant_sync`; deny-by-default, fail-closed, sealed live
  (Case-1 HITL, [[project_hitl_grant_dashboard_spec]]).
- **Deferred (composable multi-dimensional):** the join over N approvals, the
  auto-checked attribute dimensions, the composable policy language, the
  per-classification approver-selection — all buildable on the built primitives
  (single decider, DataHub fact sync, HITL substrate, single approval), none
  built. Each has its trigger above.
- **Audit note carried from Case-1:** a grant that enforces without a
  git-blame-auditable, approver-attributed record is the unauditable grant the
  core forbids at classification — the approver-attributed commit is an
  audit-completing REQUIREMENT before classification use, and it applies per-
  approval in the multi-approval case (each approval attributable).

## Consequences

- The gate stays simple (grant-or-not) as the issuance policy grows rich —
  because they're separated (Decision 2). A future engineer adding a fifth
  approval dimension touches the *policy*, not the *gate*.
- No parallel approval service can be built without violating this ADR (Decision
  1) — the constraint is recorded so a future session doesn't stand one up.
- The capability arrives onto decided ground: when a real multi-approver /
  attribute-gated requirement lands (the triggers), the build composes the
  existing primitives under these invariants rather than re-deriving them.
- **The approval history and policy state are THEMSELVES governed viewability
  surfaces**, gated by the enforcement model like everything else — "who approved
  what, when, why" (the audit trail) and "what approval policies are in effect"
  are access-controlled reads (an auditor sees approval history; a requester sees
  only their own request's status; a task's existence is need-to-know per Decision
  3's existence-oracle point). The approval *records* are not an ungoverned log —
  they are a resource under the same deny-by-default model. Naming it so the future
  build doesn't leave the approval trail open by default.

## Non-goals (this session)

Building the policy engine, authoring any composable policy, wiring
location/device attribute sources, implementing the multi-approval join, or
changing the single-dimension flow that exists. This ADR is the decision about
the layer; the build is triggered separately.

## Related

- **[[project_adr0026_topaz_authz]]** / ADR-0026 — persona/entitlement Topaz
  authorization (the single decider this policy layer sits on).
- **ADR-0025** — instance-plane access control (the enforcement gate; grants are
  its primitive — this ADR governs their issuance, not their gating).
- **ADR-0024** — standards composition / publish-promotion (the workflow-ack HITL
  case's source; the approval substrate is shared).
- **[[feedback_single_authz_decider]]** — why the policy is authored ON Topaz, not
  a second engine.
- **[[access-regulates-persona-domain]]**, **[[broken-closed-hides-brokenness]]** —
  fail-closed applied to the policy engine.
- **[[project_hitl_grant_dashboard_spec]]** — the HumanTask substrate the
  multi-approval join extends; the one-abstraction-two-fulfillments design.
- **[[project_ontology_visibility_compartment_scoped]]** — the compartment-overlay
  pattern; the dataset-classification fact sync (the filed model-extension) is its
  sibling and this ADR's dependency for classification-driven approver-selection.
