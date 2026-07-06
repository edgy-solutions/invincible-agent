---
status: Proposed
date: 2026-06-27
deciders: Platform team
---

# ADR-0025 — Instance-plane access control as provenance (ABAC over Topaz, captured on Source/CITES, carried forward by Artifact)

## Status

Proposed (2026-06-27).

This ADR **records the decision and the map**. It does NOT activate
enforcement. Enforcement is a separately gated session that follows
after the architect signals — see "Non-goals" below for the explicit
list of work-not-done in this session.

Two **capture-or-lose-forever** field additions land alongside this
ADR (Capture A: `entitlement_source` fidelity flag on `produced_for`;
Capture B: reserved `access_decision` slot on `Source` / `CITES`).
These captures are not enforcement — they record evidence whose
absence at decision time is unrecoverable later, per
`[[verify-subtle-acceptance-by-inspection]]`'s capture-at-creation
discipline applied at retrieval call sites the substrate already
touches.

## Amendment 2026-07-02 — two scope expansions, triggered by a live exploit

The fenced enforcement session (below) had its trigger fired early
and loudly: an honest agent probe **demonstrated a working access-
control bypass on PII-tagged catalog metadata**. A
`DATA_ENGINEER·DEFENSE` user's routing "denial" was laundered by
Engine A's generalist fallback, which re-queried Engine D's
`query_metadata` with a **hardcoded `persona=DATA_STEWARD`**; the
catalog enforced nothing (confirmed: any persona incl. a garbage
`NOBODY`, any/no domain → full owner + PII-tag + lineage at 0.9
conf), and the UI presented the leaked data with **"No citations"**
— sensitive real data with no provenance trail, the exact inversion
the honesty regime exists to prevent. See
`[[project_adr0026_topaz_authz]]` for the full trace. A domain-
granularity **stopgap** shipped 2026-07-02 (gate `query_metadata` on
the caller's real `entitled_domains`; kill the hardcoded steward;
thread real identity through the supervisor→Engine A fallback). The
stopgap stops the bleed; it does NOT replace the enforcement session.

The exploit proved **two scope expansions** this ADR must record —
both are enforcement-session scope, not new decisions:

**Expansion 1 — the metadata catalog is an enforcement surface, not
just data rows.** This ADR's planning gated the *data plane*
(`CortexDataClient` → central-gateway → Topaz `can_read` on the
dataset). But an asset's owner, PII tags, lineage, and description
are facts *about the instance* — often as sensitive as the rows
(knowing a `customers_gold` PII table exists, who owns it, and what
feeds it is reconnaissance without a single row). Metadata IS
provenance (this ADR's own thesis), so the catalog path
(`query_metadata`, and by inspection `resolve_instance` / `find_tools`
which must be audited) is in scope. The durable model is per-asset
Topaz **`can_view`** on catalog reads — the same shape as `can_read`,
one surface over. The stopgap's domain-granularity gate is the
explicitly-interim predecessor.

*Ratified interim predicate (2026-07-02, deliberate — not a
fix-pressure side effect):* catalog access is gated **domain-based**
— the caller must hold a cell in the catalog's served domain
(`DATA_ENGINEERING`). This is coherent with the matrix + instance-
plane model: the DataHub catalog IS the `DATA_ENGINEERING` domain's
instance plane, and a user's cell is `(persona × domain)` — there is
no domain-less steward, so denying an aviation steward the DE catalog
is correct, not backwards. The persona *within* the domain (steward
vs engineer, view vs edit) is finer-grained access = the per-asset
`can_view` successor's job, not the coarse gate's. Catalog access is
granted by adding users to the `data-engineers` group in
`policy/users.yaml` (a chosen, PR-reviewed policy per
`[[optimistic-defaults-are-dishonest]]` + the assertions-are-asserted
discipline) — NOT by granting `DATA_ENGINEERING` reactively to
whoever hits a denial, which would let the gate's predicate launder
itself into the asserted entitlements file.

*How the gate retires (this is the important part):* the stopgap
gate is **decision logic living in the wrong layer** — a policy
predicate (`entitled_domains ∋ DATA_ENGINEERING`) hardcoded in
application code inside `query_metadata`. It does NOT retire by
changing its predicate; it retires by the predicate **becoming a
Topaz call**. The enforcement point survives — `query_metadata`
keeps guarding — but it stops *evaluating policy itself* and starts
*asking Topaz* (`is(user, "can_view", asset)`). Enforcement point
stays; decision logic migrates to the one place decision logic lives.
See "Single-decider principle" below — the stopgap is the single
grandfathered exception whose migration is the enforcement arc's
literal first workstream.

**Expansion 2 — enforcement requires a DENY primitive that survives
fallback (deny-overrides-allow).** The bypass exists because the
system cannot represent the difference between two routing misses:
*"no specialist knows this"* (fallback to generalist is correct) and
*"you are not permitted this"* (fallback is the bypass). Both
currently produce the same signal — no route — and the generalist
treats every no-route as the first kind. That is not a bug in the
fallback; it is a **missing concept in the policy model**: permission
(`can_read`, `can_view`, `can_assume`) exists, but there is no
**prohibition** primitive, so a denial can't propagate — it looks
like absence, and absence gets helpfully routed around. The
enforcement session must add a deny that follows the query through
**every** path, with an explicit **deny-overrides-allow** conflict
rule (rather than letting evaluation order decide which authority
wins — "which authority wins by accident of eval order" is the authz
version of the assumed-contract bug). This is the deontic prior art
banked pre-emptively in
`[[project_defeasible_freshness_deontic_conflict]]`; prohibitions
"arrived ahead of schedule," demonstrated by the leak.

*Enforcement-arc fold-in (implementation note):* the interim
`fallback_reason=domain_scope_excluded` capture (decision-path Part 0)
detects scope-exclusion CALLER-SIDE — when the scoped
`/find_compatible_verbs` walk returns empty, the supervisor re-asks
Neo4j UNSCOPED and compares. That is correct and honest but costs a
second query on every fallback and carries a tiny time-of-check gap
between the two walks. When the enforcement arc touches
`/find_compatible_verbs` anyway (it will, for the deny primitive), the
durable shape is the endpoint **reporting what it filtered in one
pass** (pre-filter vs post-filter verb sets, or an explicit
`excluded_by_domain` list) rather than the caller re-deriving it with a
second unscoped call. Fold the caller-side re-check into the endpoint
at that point; do not add it as separate work now.

Both expansions fold into the **same fenced, hop-by-hop enforcement
session** (Non-goals below) — this amendment records scope, it does
NOT license an emergency sprawl. The stopgap stopped the bleed so the
arc can be done properly.

### Single-decider principle — four heads become one head, three suppliers, many hands

The exploit exposed a **multiple-heads-of-authorization** hazard: at
least four places can each say yes/no to "may this caller see this
asset," each with its own model and drift surface —
(1) **DataHub's own access control** (per-asset policies, its own
users/roles); (2) **Topaz** (the declared policy engine: persona
cells, data-plane `can_read`, the coming catalog `can_view`);
(3) **the agent-tool gates** (the stopgap's in-code domain check, the
routing layer's `entitled_domains` scope, per-engine checks); and
implicitly (4) **the underlying data platforms** (warehouse grants,
S3 policies) that DataHub reflects. This is the **two-authz-truths
problem from ADR-0026** (why persona left Keycloak — "capability in
Keycloak and Topaz drift silently") scaled to N systems. Every pair
of heads is a divergence surface, and — worse — multiple heads *invite
the exact bypass just lived through*: enforcement assumed to be
"somewhere else" (routing thought it filtered, the fallback thought
the catalog checked, the catalog checked nothing). The
surely-someone-else-guards-this assumption is the project's signature
failure wearing a security badge.

The resolution — already implied by ADR-0025's ABAC thesis and
ADR-0026's single-authz-store rule, stated here explicitly for authz:

- **Topaz DECIDES.** One policy engine, one place "may this caller
  see this asset" is evaluated — the matrix, the relations, the deny
  primitive, the deontic conflict rules. Already decided by 0025+0026.
- **DataHub INFORMS — it does not decide for agent traffic.** DataHub
  is the **attribute source of record for resource attributes**
  (owner, tags incl. `pii`, domain, lineage). Its facts flow *into*
  Topaz via the DataHub→Topaz directory sync (the Zanzibar-relation
  seeding already in the enforcement arc's scope); Topaz evaluates
  policy *over* those facts. DataHub's own access control keeps
  guarding **DataHub's own UI users**; for the agent mesh, DataHub is
  upstream data, not a co-decider. The tempting-but-wrong move is to
  *also* enforce via DataHub's policies for agent traffic — that
  re-creates two deciders and the drift is live.
- **git-asserted YAML informs** (subject attributes) and **request
  context informs** (environment attributes). The ABAC three-category
  model: every source feeds the *one* evaluation.
- **Enforcement points only ASK.** An enforcement point is code that
  *calls* the decider and *honors* the answer (the FastAPI dep, the
  central-gateway check, per-engine guards). A *decider* is code that
  evaluates policy *itself*. The stopgap is currently the second kind
  (predicate hardcoded in `query_metadata`) — structurally a fourth
  head. It is **grandfathered as the single named exception** because
  it is labeled interim and its migration to a Topaz call is the
  enforcement arc's first workstream.

**Standing rule for the enforcement arc (and after):** *no new policy
predicate is ever written in application code.* Every new "may X do
Y" question becomes a Topaz check; every attribute it needs becomes a
directory sync or a request input. The stopgap is grandfathered;
anything after it that hardcodes a predicate is a new head and gets
rejected in review. See `[[single-authz-decider]]`.

Two sharp edges this creates, named so they don't surprise the arc:

- **The DataHub→Topaz sync becomes load-bearing; staleness is the new
  drift.** Once DataHub feeds Topaz, `pii` on Customer 360 matters
  only insofar as it's synced — an asset tagged at 2pm whose sync
  runs at 3pm is unguarded-by-that-tag for an hour. Not a reason to
  co-decide; a reason the sync gets the same disciplines as
  everything else: **readback verification, staleness visibility**
  (when did this asset's attributes last sync = `valid_as_of` for
  authz facts), and **honest failure** (sync broken ≠ silently
  permissive — an asset whose attributes are *unknown* evaluates
  conservatively, per deny-overrides-allow). The sync is the seam
  where two systems' truths meet; seams get probes.
- **The routing-layer `entitled_domains` filter stays, renamed as
  relevance scope, explicitly NOT an enforcement point.** It narrows
  what's worth searching; it guarantees nothing (the exploit proved
  it). Scope-exclusion and prohibition are different facts — which is
  why the deny primitive exists and why the
  `fallback_reason=domain_scope_excluded` capture (Part 0 of the
  decision-path visualizer) keeps its behavior visible without
  pretending it's a guard.

The one-sentence version: **one decider (Topaz), authoritative
attribute sources feeding it (DataHub for resource facts, git-asserted
YAML for subject facts, request context for environment), and
enforcement points that only ever ASK — with the stopgap grandfathered
as the single named exception whose retirement is the enforcement
arc's first act.** That is the only shape where "who is allowed to see
this" has exactly one true answer, and where the next exploit cannot
live in the gap between two deciders who each assumed the other was on
duty.

## Amendment 2026-07-03 — two identity namespaces + worksites-through-single-decider

Source: the **enforcement-surface eval** (the seven-worksite inventory
of where a resource is read or a verb is dispatched). Its job was to be
the enforcement arc's worksite map. Two things it *exposed* belong in
this ADR before the arc opens; two things it *raises* are recorded below
as named-deferred. After that the eval's job is done — the arc opens
against this amendment, **not a re-survey** (the standing survey risk:
"strengthen 0025 with the eval" must not become enumerate-everything-authz
v2 while the fenced-and-ready arc slips another cycle).

### Two identity namespaces — asset-URN and ontology-IRI

The eval half-shows a gap it doesn't flag: its Weaviate/Jena/resolver
worksites have **no DataHub URN to gate on**. The resolver-pool vectors
and the Jena TBox classes are ontology-level, not asset-level — they
don't correspond to a catalog asset, they *are* the vocabulary. So there
are two identity namespaces, and 0025's draft only covered one:

- **asset-resources** — have DataHub URNs (the customer data, catalog
  entries). Governed by catalog **`can_view`** (domain-granularity
  stopgap today; per-asset successor per the 2026-07-02 amendment). The
  **to-be-ingested-is-to-be-cataloged** rule resolves this side: anything
  that enters the mesh as data acquires a URN, so the asset namespace has
  no ungoverned holes to fall through.
- **ontology-resources** — classes, **verb IRIs**, resolver pools: the
  *vocabulary itself*. They carry IRIs but no catalog URN. **Identity** =
  their **IRI** (the verb IRIs *are* the operation-URNs this ADR already
  established); **granularity** = the **domain** the persona×domain matrix
  already provides. "Who may traverse the ontology / see which verbs
  exist / resolve against which classes" is a *different* governance
  question from "who may see Customer 360."

  **Enforcement is the arc's WORK, not today's behavior — say so
  explicitly so it isn't silently assumed.** Today the routing layer's
  `entitled_domains` verb-scoping is a **relevance filter**: it narrows
  what's worth searching and *guarantees nothing* (the same status the
  single-decider section pins for `entitled_domains` generally — the
  exploit proved relevance-scope is not a guard). The arc's job is to
  turn ontology-resource access into a **real Topaz check at the resolver
  / routing enforcement point** — the enforcement point RESOLVES the verb
  to its IRI and ASKS Topaz (a `can_invoke`/`can_view`-shaped decision at
  domain granularity), then honors the answer, exactly like the asset
  side. The trap to refuse: *"the domain filter already does that."* The
  domain filter is precisely the thing that does **not** enforce; naming
  ontology-resource enforcement as arc work is what keeps it from being
  left as an assumed-already-handled hole (the routing-scope-is-relevance-
  not-enforcement gap the exploit taught). This is the read-time verb
  dimension; the *write*-time verb dimension waits for the mutating-verb
  trigger below.

Naming both means the enforcement arc, when it reaches the Jena/resolver
worksites, finds an identity to key on (**the IRI**) instead of either
inventing a second identity scheme on the spot (a new head) or leaving
the vocabulary permanently ungoverned under "routing-scope-is-relevance-
not-enforcement." **Two namespaces, both URN/IRI-keyed, both named — not
one namespace that silently doesn't cover half the worksites.**

### The seven worksites are enforcement POINTS, not deciders

The eval lists seven worksites as a flat inventory, which reads as "seven
places to add checks" — the **multiple-heads disease waiting to happen**
(seven hands that could each drift). `[[single-authz-decider]]` (above)
is the cure, but the eval doesn't *apply* it to the worksite list, so a
well-meaning implementer builds seven independent gates and rebuilds the
disease. Restated through single-decider, each worksite's job is exactly
three steps — and **not a fourth**:

1. **resolve** its local object to canonical identity — a **URN** for an
   asset-resource, an **IRI** for an ontology-resource;
2. **ask** the one decider (Topaz): `can_view(user, asset)` for
   asset-resources, the persona×domain cell check for ontology-resources;
3. **honor** the answer.

**No worksite evaluates policy locally.** The catalog stopgap is the
**grandfathered exception** (in-code predicate, retiring to a Topaz call
as the arc's first workstream); every *other* worksite is born ask-only.
The inventory is seven hands that resolve-and-ask, not seven heads that
decide.

### Named-deferred (recorded with triggers, NOT built now)

- **Verb-dimension governance is a TRIGGER, not a task.** The eval is
  right that verbs should be governable (they carry IRIs; they're the
  operation-URNs). But that is the *destination*, premature as immediate
  scope. **Trigger = the first MUTATING verb / the publish arc.** Until
  then the enforcement arc scopes to the **resource dimension** and does
  NOT fan out into per-verb read-granularity — read-time verb visibility
  is the ontology-resource domain-check above; write-time verb authority
  waits for the mutating-verb trigger. Recording it as a trigger keeps
  the arc from expanding into per-verb work before it's earned.
- **Orphan-scrub seam (deny-on-dangling).** Sibling to the DataHub→Topaz
  staleness seam already named under single-decider (attribute sync with
  `valid_as_of` + deny-on-unknown). Its counterpart failure is a Zanzibar
  relation pointing at an asset or subject that **no longer exists** — a
  phantom grant that must evaluate **conservatively (deny)**, not linger.
  The scrub gets the same disciplines as every seam: readback,
  staleness/dangling visibility, honest-failure (a dangling reference is
  a denied one, never a silently-permissive one). Named here so it isn't
  under-specified into silent drift.

The eval was the map; **this amendment is the coordinate system.** The
next action is opening the enforcement arc against it (the sequence
stands: step 6 → abstention arc → visualizer → enforcement) — not
producing eval v2.

## Amendment 2026-07-06 — the governing invariant, made explicit by the classification

The enforcement arc reached the data plane (`data_broker` DA-read gate),
and a stated classification collapsed a design choice that had looked open:
**this system will hold TS/SCI, government-owned, proprietary, and PII
data.** That fixes the direction of the safe error — an over-grant is a
*spill* (unrecoverable, reportable) — and turns the arc's accumulated
instincts into a single governing invariant, recorded here as the sentence
every remaining hop checks against.

**Access control regulates persona and domain — the outer gate releases,
the inner routing layer refines what it released, never the reverse.**
Access is the enclosing boundary; persona/domain (routing, comprehension,
presentation) operate only on what access already cleared. Concretely:

- **Deny-by-default; grant-by-explicit-per-asset-assertion; never
  derive-by-entitlement.** A subject reads an asset ONLY via an explicit,
  asserted, auditable `owner`/`reader` relation. Entitlement / persona /
  domain establish *eligibility to be granted* (necessary), NEVER the grant
  (sufficient). "Cleared for the domain" ≠ "granted this asset" — need-to-know.
- **`owner-OR-entitled` is REJECTED as a model, not deferred.** Deriving
  data-read from domain-entitlement collapses need-to-know into
  clearance-level; with per-dataset domains null it degenerates to "any
  DATA_ENGINEER reads all PII." No point in time makes it safe at this
  classification. `alice`-can't-read-without-a-grant is *correct* behavior
  and the stronger demo (need-to-know enforced, not clearance-implies-access).
- **`permission` is the ENCLOSING gate, not a co-equal term.** The routing
  eligibility intersection is `(domain ∩ arity ∩ argument-fit)`; the access
  gate *wraps* it. Correction to the verb-eligibility framing that listed
  permission as a fourth peer constraint.
- **Domain, once per-dataset domains exist, is a GUARDRAIL on grant
  validity** (no cross-compartment `reader`) — an ABAC attribute the
  decision may consult — never a substitute for a grant.
- **Prove the NEGATIVE.** A gate broken in the deny direction is invisible
  (denial doesn't alarm) — "denies everyone" is consistent with a working
  AND a non-functional gate. Every data-plane gate ships with a
  DISCRIMINATING allow-side proof (authorized-subject allowed on the granted
  asset; same subject denied on a non-granted asset; other subject denied on
  the granted asset). This failure mode has bitten the arc three times
  (hop-1 readback, hop-2 builtin, `data_broker` misalignment).

*Landed under this amendment:* `data_broker.rego` rebuilt deny-by-default
(owner/explicit-reader, `ds.check`, subject from `resource_context.user_id`)
and its live caller `dag-tools/central_gateway` aligned to send the caller's
**email** as `resource_context.user_id` + `asset_key` (it had sent the `sub`
in `identity_context` with `asset` — three-way misalignment silently denying
everyone). Proven discriminating including the deny→grant→allow model (an
explicit per-asset `reader` grant flips only that subject on only that
asset). The **HITL grant flow** is therefore the PRIMARY data-access
mechanism (deny → request → human-asserts → grant), and the reserved
`access_decision` capture (Capture B) is its audit trail.

The cross-repo topology, boundary contracts (the seams where every auth bug
lived), and the full invariant list are mapped in
[docs/architecture/authorization.md](../architecture/authorization.md) —
anchored to code + probes so drift surfaces. Memory:
`access-regulates-persona-domain` (governing), `broken-closed-hides-brokenness`,
`topaz-v2-v3-api-split`, `identity-reaches-enforcement-point`.

## Related

- [ADR-0009 — Sunset classification axes](ADR-0009-sunset-classification-axes.md):
  the caller-vs-answerer persona split. This ADR's **subject-attribute**
  category builds on it — subject attributes are properties of the
  *asker*, distinct from the answerer's persona. The two never collapse.
- [ADR-0023 — iagent AnswerArtifact as a graph-native CQRS object](ADR-0023-iagent-answer-artifact-graph-cqrs.md):
  the artifact substrate this ADR's captures land on. ADR-0023 already
  establishes the **reserved-slot pattern** (slots reserved in the
  Artifact shape that are nullable today but kept open so a later
  landing doesn't need a second migration through writer + Neo4j +
  projector + Postgres + Electric + cortex-ui). The persona slot
  (`produced_for.user_persona`) and the standards edges
  (`PRODUCED_BY_PROCESS`, `CONFORMS_TO`, `IS`, `WITHIN`) are existing
  examples. Capture B's `access_decision` slot on Source/CITES
  follows the same shape.
- [ADR-0024 Part B — Publish / promotion](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md):
  promoted artifacts (PublishedArtifact) inherit Source/CITES
  provenance. The captured `access_decision` is therefore one of the
  inputs the *re-decision against a downstream viewer's identity*
  must consult.
- `[[pingsso-claim-gap]]` — the confirmed claim gap. Capture A is the
  per-artifact observability the gap memory called out as missing:
  "Flag the claim gap explicitly in any user-facing observability (so
  when a user reports 'wrong persona,' ops can see whether the JWT
  contained the claim or the fallback fired)." Today the persisted
  `produced_for` records the *final value* but not the *origin*; that
  information is gone the moment `get_current_user` returns.
- `[[verify-subtle-acceptance-by-inspection]]` — both captures'
  five-layer survival (writer JSON → Neo4j → projector → Postgres
  JSONB → Electric hydration → cortex-ui Source object) is the
  subtle acceptance to inspect at each boundary. Each layer is a
  potential silent drop.
- `[[optimistic-defaults-are-dishonest]]` — Capture A's
  `entitlement_source` default is constrained by this rule.
  Defaulting to `"claim"` would silently mask the fallback path
  (the production PingSSO baseline) and convert silence into a
  success signal. The honest default is `"fallback"` (or
  required-explicit at the Pydantic-model layer).
- `[[coupled-interim-mechanisms-retire-together]]` — Capture B's
  reserved slot is shaped to survive the Restate+topic successor
  transition: the slot's *content* survives, only its *write
  path* changes when enforcement lands.
- `[[pre-written-fixtures-must-fail-first]]` — both captures' probes
  RED-first against the predicted reasons listed in the
  Implementation notes below.

## Context

### Current state, by direct source inspection

The access-control survey (commissioned 2026-06-27 against master @
`5a4547f`) is the audit of current state this ADR honors. The
load-bearing facts, cited by file:line rather than paraphrased:

- **Authentication is real and uniform.** Every cortex-bff user route
  is gated by `get_current_user` at
  `src/iagent/auth.py:44-119`. JWT signature is verified against
  PingSSO/Keycloak JWKS (RS256); the resulting `User` object carries
  `id`, `email`, `roles`, `persona`, `entitled_domains`. No
  user-facing route bypasses this gate.
- **Authorization in the grounding path is NOT enforced today.** The
  per-engine `require_topaz_auth` decorator at
  `agent_fleet/core/authz.py:13-113` short-circuits to a no-op
  whenever `ENABLE_AGENTIC_AUTH` is unset:
  `agent_fleet/core/authz.py:9`'s default is `"false"`, and no
  cluster value sets it true. Even when enabled, the decorator is a
  request-time gate at the engine *entrypoint* — it does not
  authorize per-source-retrieval at the *instance plane*.
- **The decorator was removed from Engine DA** specifically because
  it was written for FastAPI and broke under Restate's handler-arg
  inspection. The comment at `agent_fleet/data_analyst/main.py:94-104`
  explains: "The central-gateway already enforces authz on the data
  path; engine-side authz can be re-added once the decorator is
  rewritten to be Restate-compatible." Engine DA's data path
  authorization is therefore handled OUTSIDE iagent, by an
  external `central-gateway` service in dag-tools.
- **The Zanzibar directory is unseeded.** The Topaz manifest at
  `helm/invincible-agent/templates/topaz-configmap.yaml:49-59` declares
  a `dataset` type with `owner`/`reader` relations and a `can_read`
  permission, but no code in iagent or any banked-known-component
  populates that directory from DataHub (the natural source of
  resource ownership/reader relations). With the Rego policy's
  `default allowed = false` at `topaz-configmap.yaml:66`, every
  Topaz check against the empty directory would deny.
- **The Rego policy is shaped for the external gateway, not iagent.**
  The package path at `topaz-configmap.yaml:62` is
  `data_mesh.GET.api.v1.assets.__asset_key.authorize` — shaped to
  match `central-gateway`'s REST path. `agent_fleet/core/authz.py:11`'s
  `TOPAZ_POLICY_PATH` defaults to `invincible_agent.authz`. **The
  two are different.** Even if iagent enabled the decorator and the
  directory were seeded, the policy path lookup would fail.
- **The PingSSO claim gap is confirmed by code inspection.** At
  `src/iagent/auth.py:71-72`, persona falls back to `"MECHANIC"`
  when the JWT lacks the configured claim. At
  `src/iagent/auth.py:77-80`, `entitled_domains` falls back to `[]`
  when the JWT lacks the configured claim. Per `[[pingsso-claim-gap]]`,
  the sandbox Keycloak workaround does NOT extend to production.
- **Caller vs answerer persona split is enforced at one site.**
  `src/iagent/defs/dynamic_supervisor.py:1009` is the persona-split
  application; engines accept a single `persona` field with no
  audit of whether the value came from the caller (PRODUCED_FOR
  side) or the answerer (verb edge's `owner_persona`).
- **The mock Rego anticipates CLS/RLS.** The example policies at
  `topaz-configmap.yaml:78-87` model column-level redaction
  (`allowed_columns`) and row-level filtering (`row_filters`) keyed
  by user role. The shape is there; the decision-capture surface
  is not.

### What the current state implies

There are **two distinct access vectors** the substrate must close.
Naming them separately matters because they require structurally
different fixes:

1. **Sharing vector.** Viewer V tries to see asker U's artifact. The
   Hop 3 per-user-scoped Electric subscription closes this — V's
   subscription is keyed on V's identity; V cannot fetch U's
   projection row. **Necessary for sharing safety, addressed at the
   read-projection layer.**

2. **Grounding vector.** Asker U's artifact is built from sources U
   was not entitled to. The artifact faithfully records what was
   retrieved; if retrieval ignored access control, the artifact
   records sources-the-asker-shouldn't-have-seen as if they were
   legitimately U's grounding. **This is the gap this ADR closes
   when enforcement lands.** It cannot be closed at the projection
   layer; per-user-scoping the projection doesn't stop the
   un-entitled source from being inside the artifact in the first
   place.

**The Hop 3 per-user scoping is necessary but not sufficient.** It
closes the sharing vector; the grounding vector is open until
access-aware retrieval lands. The ADR names access-aware retrieval
as the fix for vector 2.

### Capture-or-lose-forever motivation

Per `[[verify-subtle-acceptance-by-inspection]]`: an access decision
considers the asker's attributes *at that moment*, the resource's
attributes *at that moment*, the environment *at that moment*. After
the decision is finalized:

- the asker's attributes may have changed (a new claim issuance, a
  role rotation, a clearance expiry);
- the resource's attributes may have changed (re-classified,
  re-owned, contract expired);
- the environment is gone entirely (a specific moment in time, a
  specific source IP — not reconstructible).

If the decision isn't captured at the moment it's made, the artifact
cannot be safely re-decided later against a downstream viewer's
identity (per-viewer derived viewability becomes impossible), and
audit cannot answer "why was this grounding permitted at that time"
(the answer depends on inputs no longer available).

This is why this ADR is **two captures plus a decision**, not just
a decision. The captures land the evidence that would be lost; the
enforcement session that follows can light up the decisions on top
of evidence already being recorded.

## Decision

The iagent system MUST treat instance-plane access control as
**attribute-based, decided per retrieval, and captured as
provenance**. Every retrieval of source content (DataHub assets,
Weaviate chunks, Neo4j nodes, document chunks, query results)
passes a Topaz authorization decision; the decision's inputs and
outcome are recorded onto the `Source` node and/or the `CITES`
edge per ADR-0023's typed-edge discipline.

### ABAC over Topaz — three attribute categories

The decision considers three attribute categories, named explicitly
so the attribute *set* stays open-ended by design (later additions
do not require this ADR to be amended):

- **Subject attributes** — properties of the asking user. Examples
  (illustrative, not exhaustive): projects-worked, clearance/secret
  level, contract/license entitlements, organizational affiliation.
- **Resource attributes** — properties of the source object.
  Examples: source-of-truth provenance, classification, owning
  contract/license, dataset URN, owner.
- **Environment attributes** — decision-time inputs about *when /
  where / how* the asking is happening. Examples: location,
  time-of-day, source-of-request (which engine routed it),
  out-of-band signals (deal status, customer relationship state).

**Subject↔resource attributes are Zanzibar directory relations.**
For example, `user.has_clearance(secret)` is a *relation* in the
directory; `dataset.has_owner(user)` is a *relation* in the
directory. The directory is the source of truth for the
who-can-see-what facts that hold across time.

**Environment attributes are policy input at decision time.** They
are not stored in the directory; they are computed at the Topaz
call site and passed in `policyContext`. `time_of_day` is computed
when the Topaz call happens, not pulled from a relation.

### Access-as-provenance — the captured shape

Every instance-plane retrieval passes a Topaz decision. The
decision's **inputs** (which attributes were considered) and
**outcome** (allow / deny / filter, including any column-level
redactions or row-level filters applied) are captured onto the
`Source` and/or `CITES` edge per ADR-0023's typed-edge discipline.
Derived assets — the AnswerArtifact, and anything promoted from
it via ADR-0024 Part B — **carry the provenance forward**.

The captured shape (see Capture B below for the field definition):

- `outcome` — `"allow"` / `"deny"` / `"filter"`. (A `"deny"`
  decision implies the source is NOT in the artifact's CITES; the
  field exists to record *why* a candidate source was excluded,
  for audit. A `"filter"` decision means the source IS in CITES
  but with CLS/RLS applied.)
- `policy_version` — the Topaz policy bundle version the decision
  was made under. Required because policy itself changes; a
  decision under v1.3.2 may not reproduce under v1.4.0.
- `attributes_considered` — the *keys* (not values) of subject /
  resource / environment attributes the policy consulted. Keys,
  not values, because the values may be sensitive (a clearance
  level, a contract id); the audit question is "what was
  consulted," not "what was the asker's clearance."
- `filters_applied` — the column-level redaction set and the
  row-filter expression Topaz returned (mirrors the mock Rego at
  `topaz-configmap.yaml:78-87`'s `allowed_columns` /
  `row_filters` shape).
- `decided_at` — epoch milliseconds of the decision moment.
  Required because environment attributes (time-of-day) and
  policy version are time-bound.

### Why capture rather than just decide

The captured provenance enables two follow-on capabilities that
are the reason for capturing rather than just deciding:

#### Per-viewer derived viewability

A downstream viewer V (not the original asker U) can have the
artifact re-decided against V's identity because the original
decision's *dependencies* were recorded. The re-decision is
**structural**: replay the decision against V's subject attributes,
using the **recorded resource attributes** (still valid — recorded
at decision time) and the **recorded environment attributes** (a
specific moment in time — what was true then).

This is what makes the artifact safely shareable beyond the
original asker. Without the capture, sharing an artifact requires
either (a) trusting that the viewer is entitled to whatever the
original asker was entitled to (almost never correct — different
clearances, different contracts), or (b) refusing to share at all
(closes the workspace metaphor ADR-0023 enables). The capture
makes (c) possible: share with re-decision.

#### Audit

"Why was this grounding permitted?" is answerable by reading the
captured provenance. Not a separate audit log; **the artifact IS
the audit trail**. This dovetails with ADR-0023's freshness model
(the artifact captures what it was grounded in) — the artifact
already captures *what* it was grounded in; access-as-provenance
extends that to *why those groundings were permitted*.

## Rationale

The decision picks ABAC over Topaz with capture-as-provenance,
specifically, because:

1. **Topaz is already the chosen authorization substrate.** The
   helm chart deploys it
   (`helm/invincible-agent/templates/topaz-configmap.yaml`); the
   per-engine decorator anticipates it
   (`agent_fleet/core/authz.py`); the external `central-gateway`
   uses it. Introducing a *second* authorization substrate (OPA
   standalone, Cedar, hand-rolled) would fragment the policy story
   without solving the gaps this ADR names.

2. **Attribute-based, not role-based.** Roles are a degenerate
   case of attributes (a role IS an attribute), but the converse
   doesn't hold. A clearance level, a contract entitlement, a
   time-of-day check — none of these are usefully expressible as
   roles alone. The substrate must support the richer model from
   day one; RBAC-only would force a re-modeling when the first
   genuinely-attribute-based requirement landed.

3. **Per instance-plane retrieval, not per request.** A request
   may retrieve from multiple sources; each source's decision is
   independent. Decision-per-request would force "the request"
   into a single allow/deny, collapsing per-source CLS/RLS into
   a coarse-grained decision and erasing the per-source audit
   trail.

4. **Captured-as-provenance, not separately logged.** The audit
   trail's natural home is the artifact's own provenance graph
   (ADR-0023's `CITES`/`Source` shape). A separate audit log
   would force two-place reasoning ("which decisions concern
   this artifact") and risk drift between the two stores. The
   artifact already captures *what* it was grounded in; this is
   an extension of that capture, not a parallel system.

5. **Decision recorded at the substrate of record, not in the
   read projection.** The decision lives on the Source node /
   CITES edge in Neo4j; the read projection (Postgres → Electric
   → cortex-ui) flows it through. Recording the decision on the
   read projection would lose it when the projection is rebuilt;
   recording it at the substrate of record makes it durable.

## Consequences

### What this unlocks

- **Sharing safety beyond the original asker** — per-viewer
  derived viewability becomes structurally possible once the
  decisions are captured. Without capture, sharing an artifact is
  either trust-everyone or refuse-to-share.
- **Audit** — "why was this grounding permitted?" is answerable
  from the artifact's own provenance graph. No separate audit
  log; the artifact IS the audit trail.
- **CLS/RLS visibility** — when a source is filtered (specific
  columns redacted, specific rows filtered), the artifact
  records what was filtered. Downstream readers see the
  filter, not just the post-filter result.
- **PingSSO claim gap blast-radius queryability** — Capture A
  makes "which artifacts were built under the fallback
  persona/entitled_domains" a query against the substrate of
  record. Today, the gap is real but invisible per artifact;
  with the capture, ops can answer "are we currently producing
  artifacts under the fallback? how many? for whom?"

### What this costs

- **Discipline at retrieval call sites.** Every retrieval that
  cites a Source MUST call Topaz and record the decision. A
  retrieval that skips the call is a silent gap — the artifact
  records its grounding but not the decision authorizing it.
  This is the capture-or-lose-forever discipline at retrieval
  call sites, work the enforcement session adds.
- **Policy authoring.** The Rego policies must express the
  attribute-based decisions and return the
  `outcome`/`policy_version`/`attributes_considered`/`filters_applied`
  shape the substrate records. The mock at
  `topaz-configmap.yaml:78-87` is a sketch, not the production
  shape.
- **Zanzibar directory population.** The directory must be
  seeded from DataHub (the natural source of resource
  ownership/reader relations). This is one of the enforcement
  session's load-bearing pieces of work-not-done.
- **PingSSO claim coordination.** Real subject attributes
  require the IdP to actually issue them; the sandbox Keycloak
  workaround per `[[pingsso-claim-gap]]` does not extend to
  production. This is enforcement-session coordination work.

### What stays deferred (named, not built)

The enforcement-session scope is enumerated as **non-goals for
this ADR** so they don't accidentally get built in this session:

- **DataHub → Topaz directory sync.** No code in iagent or any
  banked-known-component populates the Topaz Zanzibar directory
  from DataHub. The directory stays empty; with `default
  allowed = false`, every Topaz check would deny. The
  enforcement session adds the sync.
- **Policy package path reconciliation.** The Rego policy at
  `topaz-configmap.yaml:61-87` uses package
  `data_mesh.GET.api.v1.assets.__asset_key.authorize`, shaped
  for `central-gateway`'s REST path. `TOPAZ_POLICY_PATH` in
  `agent_fleet/core/authz.py:11` defaults to
  `invincible_agent.authz`. The two are different. The
  enforcement session reconciles this (likely by introducing a
  second policy bundle scoped to instance-plane decisions, with
  its own package path).
- **Environment-attribute input plumbing.** No code path passes
  `time_of_day`, `source_ip`, `location`, etc., as Topaz
  `policyContext`. The enforcement session adds this at the
  retrieval call sites.
- **PingSSO claim expansion.** Per `[[pingsso-claim-gap]]`:
  production PingSSO does not carry `persona` /
  `entitled_domains` claims today. The sandbox Keycloak
  workaround (Declarative User Profile attributes + protocol
  mappers) does not extend to production. The enforcement
  session coordinates with PingSSO/identity-team to land real
  claims.
- **`ENABLE_AGENTIC_AUTH` flip.** The dormant decorator at
  `agent_fleet/core/authz.py:13-113` stays dormant. The
  enforcement session decides whether to flip it as-is, rewrite
  it Restate-compatibly first, or move enforcement out of
  central-gateway into each engine.
- **Central-gateway vs engine-side enforcement reconciliation.**
  Today the live Topaz consumer is `central-gateway` on Engine
  DA's data path; iagent engines are otherwise auth-blind. The
  enforcement session decides whether the per-engine decorator
  comes alongside central-gateway (defense in depth) or
  replaces it (single point of enforcement).
- **Verb-dimension governance (TRIGGERED, not scheduled).** Per the
  2026-07-03 amendment: verbs are governable by IRI, but the trigger
  is the **first mutating verb / the publish arc**, not a task in the
  enforcement session. The session scopes to the resource dimension;
  it does not build per-verb read-granularity.
- **Orphan-scrub seam (deny-on-dangling).** Per the 2026-07-03
  amendment: the dangling-reference counterpart to the DataHub→Topaz
  staleness seam. A Zanzibar relation to a deleted asset/subject
  evaluates conservatively (deny). Named seam, disciplines attached;
  built in the enforcement session, not before.

## Open questions

These are the questions the enforcement session opens with; they
are NOT decided here:

1. **When does `ENABLE_AGENTIC_AUTH` flip cluster-wide?** The
   directory must be populated and the policy path reconciled
   first; flipping the flag against an unseeded directory denies
   all retrievals.
2. **Who owns the DataHub → Topaz directory sync?** The natural
   source of `dataset.has_owner(user)` and
   `dataset.has_reader(user)` relations is DataHub. The
   enforcement session decides whether the sync lives in iagent,
   in DataHub, or in a dedicated sync service.
3. **Central-gateway-vs-engine-side enforcement.** Does the
   enforcement session move enforcement OUT of central-gateway
   INTO each engine (single point of policy, multiple call
   sites), or turn on the per-engine decorator ALONGSIDE
   central-gateway (defense in depth, redundant decisions)?
4. **PingSSO claim coordination.** Per `[[pingsso-claim-gap]]`,
   real claims require coordination with the PingSSO/identity
   team. The enforcement session opens that coordination; the
   timeline is not in iagent's gift.
5. **Filtered-source representation.** When Topaz returns a
   `"filter"` outcome (CLS/RLS applied), does the artifact's
   CITES edge point at the pre-filter Source URN or a
   post-filter view-shaped Source URN? The shape choice has
   implications for de-duplication across artifacts and for
   re-decision against a downstream viewer.

## Non-goals (do NOT build in this session)

This list is duplicated from the "What stays deferred" section
for emphasis. **None of these are built in the session that
lands this ADR.** They are enforcement-session work.

- Do NOT flip `ENABLE_AGENTIC_AUTH`.
- Do NOT seed the Topaz Zanzibar directory.
- Do NOT add Topaz calls anywhere in iagent (no client wiring,
  no decorator activation, no per-engine middleware).
- Do NOT add per-engine enforcement decorators or middleware.
- Do NOT add the policy-path reconciliation.
- Do NOT add environment-attribute plumbing.
- Do NOT modify the central-gateway integration in
  `agent_fleet/data_analyst/main.py`.
- Do NOT coordinate with PingSSO for claim expansion.
- Do NOT modify `agent_fleet/core/authz.py`.

The ADR is **the decision and the map**. Enforcement is the
separately-gated session that follows.

## Implementation notes

### What this session lands alongside this ADR (the two captures)

Two **capture-or-lose-forever** field additions land alongside
this ADR as part of the same commit set. Neither is enforcement;
both record evidence whose absence at decision time would be
unrecoverable later.

#### Capture A — `entitlement_source` fidelity flag on `produced_for`

**Where the evidence is captured.** At
`src/iagent/auth.py:71-80`, the JWT claim-read logic falls back
to `MECHANIC`/`[]` when the persona/entitlements claims are
absent. The fact of whether the claims were present is available
**at that moment** (the JWT was just read); after that moment,
the persisted `produced_for` records the *final value* but not
the *origin*.

**Shape.** A new `entitlement_source` field with vocabulary
`"claim" | "fallback" | "partial"`:

- `"claim"` — both the persona claim and the domains claim were
  present in the JWT.
- `"fallback"` — neither was present (the production PingSSO
  baseline).
- `"partial"` — one was present, the other fell back
  (transitional / misconfigured state).

**Honest-default rule.** Per
`[[optimistic-defaults-are-dishonest]]`: the Pydantic model
requires the field explicitly (no default). Defaulting to
`"claim"` would silently mask the fallback path (the production
baseline) and convert silence into a success signal. Required
input forces the auth code to compute the value at the moment
the JWT is read.

**Five-layer survival.** The field rides through:
1. `src/iagent/auth.py` (`User` Pydantic model)
2. `src/iagent/gateway.py` (`produced_for` dict construction at
   line 1366)
3. `src/iagent/answer_artifact_writer.py` (`PRODUCED_FOR`
   edge / Actor node properties; the writer destructures the
   `produced_for` dict so the new field is added explicitly to
   the destructuring)
4. `src/iagent/projector/apply_loop.py` (Cypher map projects
   the `:Actor` properties into the `consumers` array)
5. `cortex-ui/src/api/types.ts` (`Artifact.produced_for`)
6. `cortex-ui/src/store/useCanvasStore.ts` (`createPendingArtifact`
   pending seed defaults `entitlement_source` to `"fallback"` —
   the client truly doesn't know at pending-creation time; the
   Electric-synced server value overwrites on first apply)

**Hop 3 baseline interaction.** `produced_for` is **inline-typed**
in `Artifact` (lines 363-368 of `cortex-ui/src/api/types.ts`).
Adding `entitlement_source` therefore changes the Artifact body
and the Hop 3 byte-identical-diff probe's `BASELINE_REF` (literally
`496fd8c` in `cortex-ui/tests/hop3/test_artifact_type_byte_identical.mjs`)
must shift to this ADR's commit. This is the **second sanctioned
modification** to the Artifact shape (the first was Hop 1's
addition of `durability_status` + `watermark`, which set the
current baseline). The Hop 3 probe's load-bearing comment is
updated to record the new baseline reason.

**Probe.** `tests/test_capture_a_entitlement_source_recorded.py`,
RED-first per `[[pre-written-fixtures-must-fail-first]]`:

- **Leg 1 (fallback)**: synthesize a `User` with no persona /
  domains claims; assert `entitlement_source == "fallback"`.
  Predicted RED reason: `AttributeError: 'User' object has no
  attribute 'entitlement_source'`.
- **Leg 2 (claim)**: synthesize a `User` with both claims;
  assert `entitlement_source == "claim"`. Proves the field is
  genuinely two-valued, not constant-fallback.
- **Leg 3 (partial)**: synthesize a `User` with exactly one
  claim; assert `entitlement_source == "partial"`. Proves the
  partial state is reachable and labeled correctly.

#### Capture B — Reserved `access_decision` slot on `Source` / `CITES`

**Reserved-slot pattern, per ADR-0023.** The slot is part of
the type today, null in all writes, no consumer reads it. Its
purpose is to ensure the enforcement session that follows does
not need a second migration through writer + Neo4j + projector
+ Postgres + Electric + cortex-ui to land the captured decision.

**Shape.** A nullable substructure on `Source` (TypeScript
interface in `cortex-ui/src/api/types.ts`):

```typescript
access_decision?: {
  outcome: "allow" | "deny" | "filter";
  policy_version: string;
  attributes_considered: {
    subject: string[];    // attribute KEYS, not values
    resource: string[];
    environment: string[];
  };
  filters_applied?: {
    columns_redacted?: string[];
    rows_filtered_by?: string;
  };
  decided_at: number;   // epoch ms
} | null;
```

Field-by-field rationale:
- **outcome**: three values, not two, because a `"filter"`
  decision is distinct from `"allow"` — the source IS in CITES
  but with CLS/RLS applied; readers must know.
- **policy_version**: required because policy changes; a
  decision under v1.3.2 may not reproduce under v1.4.0.
- **attributes_considered**: KEYS not values — the audit
  question is "what was consulted," not "what was the asker's
  clearance" (values may be sensitive).
- **filters_applied**: mirrors the mock Rego's `allowed_columns`
  / `row_filters` shape at `topaz-configmap.yaml:78-87`.
- **decided_at**: required because environment attributes
  (time-of-day) and policy version are time-bound.

**Five-layer survival (six inspection points).** Each layer is
a potential silent drop; each is verified by inspection per
`[[verify-subtle-acceptance-by-inspection]]`:

1. **Writer JSON serialization** (`answer_artifact_writer.py`).
   The writer's CITES MERGE picks specific fields by name; the
   `access_decision` field is added explicitly to the CITES
   edge property set. Verified by inspection: the source dict's
   `access_decision` is read and stored on the edge.
2. **Neo4j round-trip.** Neo4j edge properties are typed
   primitives, not nested dicts; the writer serializes the
   substructure to a JSON string and stores it as
   `c.access_decision_json`. Verified by inspection: the
   Cypher MERGE sets the property.
3. **Projector re-parse** (`projector/apply_loop.py`). The
   projector's source projection adds `access_decision`
   explicitly to the Cypher map, parses the JSON string back
   to a dict, and includes it in the `sources` JSONB written
   to Postgres. Verified by inspection: the Cypher RETURN map
   names the field; `_parse_json` is applied.
4. **Postgres JSONB.** `sources` is JSONB; the field rides
   through automatically once it's in the dict the projector
   writes. Verified by inspection: the column type is JSONB.
5. **Electric hydration** (`cortex-ui/src/lib/electric.ts`).
   The conversion path uses `parseJsonbOrDefault(row.sources,
   [])` — Electric delivers the whole `sources` array as
   JSONB; the substructure rides through automatically.
   Verified by inspection: no per-field destructuring.
6. **cortex-ui Source type acceptance.** The `Source`
   interface now declares `access_decision`; the type accepts
   the field. Verified by inspection: the type compiles
   against fixtures populating the slot.

**Probe.** `tests/test_capture_b_access_decision_slot_reserved.py`,
RED-first per `[[pre-written-fixtures-must-fail-first]]`:

- Write a bundle with a Source carrying a populated
  `access_decision`. Read it back through writer → Neo4j →
  projector → Postgres. Assert the field survives every layer
  as expected.
- Predicted RED reasons:
  - At layer 1 (writer): the writer's CITES MERGE does not
    set the property; Cypher write succeeds but the property
    is missing.
  - At layer 3 (projector): the Cypher RETURN map omits the
    field; the projector writes a `sources` JSONB without
    `access_decision`.
- Predicted GREEN: the populated `access_decision` round-trips
  through Postgres unchanged; an unpopulated (null) decision
  also round-trips as null (the reserved slot's default
  state).

### Plan accounting

`docs/plans/projector-build-plan.md` §3.6 gate list gains a
footnote that this ADR + its two captures landed on top of the
projector substrate. No new gate is added — this is a
follow-up ADR + captures, not a new hop.

### What this session does NOT do (one more time, for emphasis)

No `ENABLE_AGENTIC_AUTH` flip. No Topaz calls anywhere. No
engine-side decorators. No Zanzibar directory writes. No
policy-path changes. No PingSSO coordination. The reserved
`access_decision` slot is **reserved, not populated** — production
writes set it to `null` always. The enforcement session populates
it; this session lands the slot.
