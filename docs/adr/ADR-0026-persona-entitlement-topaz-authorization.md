---
status: Proposed
date: 2026-07-01
deciders: Platform team
---

# ADR-0026 — Persona & entitlement authorization via Topaz (matrix, git-asserted, per-prompt declared)

## Status

Proposed (2026-07-01).

This ADR **records the decision and the plan**. It supersedes the
interim Keycloak `persona`-attribute-mapper workaround (see
"Interim mechanism retirement" below) and joins the existing Topaz
policy store established by ADR-0025.

Two things activate together with this ADR:

1. **The `policy/` directory** at the top of `invincible-agent`, with
   `personas.yaml` / `groups.yaml` / `users.yaml`, becomes the
   authoritative source for who can assume which persona in which
   domain. It is git-tracked and PR-reviewed; every entitlement is a
   named human's assertion, not a machine's inference.
2. **A CI sync tool** applies the YAML to Topaz on merge, with
   readback verification per `[[verification-must-fail]]`.

Enforcement in the request path is staged across small PRs; see
"Rollout" below.

## Related

- [ADR-0009 — Sunset classification axes](ADR-0009-sunset-classification-axes.md):
  the caller-vs-answerer persona split this ADR operationalizes.
  ADR-0009 said **"User persona… Source: identity provider claims
  (PingSSO), not the user's query text."** This ADR completes that
  contract by moving the *source* from JWT claims (interim) to Topaz
  (durable), because persona is *authorization data*, not
  *authentication data*, and putting it in the JWT was authz smuggled
  into the authn substrate.
- [ADR-0025 — Instance-plane access control as provenance](ADR-0025-instance-plane-access-control-as-provenance.md):
  establishes Topaz as the authz store for instance-plane access.
  This ADR **joins that store** rather than adding a second — one
  authorization truth for both persona entitlement and data-instance
  access. ADR-0025's `entitlement_source` fidelity-flag pattern is
  reused here (Capture A shape) so per-answer observability can
  distinguish user-picker from default-fallback from auth-unavailable.
- [ADR-0023 — iagent AnswerArtifact as a graph-native CQRS object](ADR-0023-iagent-answer-artifact-graph-cqrs.md):
  the artifact substrate the routing card and answer projection
  land on. Persona/domain travel through the artifact as
  `produced_for.user_persona` (existing field) + a new
  `produced_for.active_domains` slot (reserved-slot pattern).
- [ADR-0008 — Routing fallback policy](ADR-0008-routing-fallback-policy.md):
  the fallback path this ADR partially closes. MECHANIC fallback
  currently fires because `persona` claim is absent; after this ADR,
  fallback fires *only* when Topaz is unreachable and no cached
  matrix exists — and that path terminates in a distinct 503, not a
  silent downgrade.
- `[[pingsso-claim-gap]]` — the confirmed claim gap. This ADR is
  the durable resolution: `persona` never enters the JWT. Keycloak
  emits identity only; Topaz answers policy.
- `[[optimistic-defaults-are-dishonest]]` — the design rule this ADR
  hardens across every persona/entitlement path: no silent downgrade
  when picker override is invalid, no fail-open when Topaz is
  unreachable, no default persona hiding an absent claim. The
  `entitlement_source` field (`picker | default | fallback | denied |
  unavailable`) makes the fidelity of every persona value auditable.
- `[[verification-must-fail]]` — the CI sync tool must be shown
  FAILING against an empty Topaz before it is trusted to pass. Same
  discipline: readback assertions must be able to fire red before
  green.
- `[[pre-written-fixtures-must-fail-first]]` — the picker + chat
  contract's positive controls (cell entitled → 200; cell not entitled
  → 403; Topaz down + cache miss → 503) are written and shown red
  BEFORE the implementation lands.
- `[[integration-probe-per-contract]]` — cortex-bff ↔ Topaz is a
  cross-component agreement; this ADR ships an integration probe
  asserting the client correctly serializes/deserializes the
  entitlement matrix, not just unit tests around the client class.
- `[[coupled-interim-mechanisms-retire-together]]` — fires twice
  in this ADR. First: the Keycloak persona-attribute-mapper
  workaround retires in the same arc that lands the
  Topaz-authoritative path, not left as vestigial scaffolding.
  Second (added on second-agent review): the per-token cache and
  the revocation hook are ALSO coupled interims — they share the
  cause "single Topaz truth accessible with acceptable request
  latency" (cache addresses latency; hook addresses staleness).
  Shipping the cache without the hook is a deliberate but named
  interim choice that leaves a divergence window of up to token
  TTL; see Negative "Cache-without-revocation-hook is a
  known-stale authz window."
- `[[failure-mode-pluralism-in-fixes]]` — the canonical
  catalog-ownership end-to-end success criterion is a three-cause
  outcome (persona resolution + eligible-verb selection +
  citation-bearing specialist answer). This ADR owns cause 1
  only; the joint success criterion below is explicitly marked
  joint with ADR-0008 so a red result attributes correctly
  rather than bundling causes at the acceptance layer.
- `[[path-vs-semantic-domain]]` — the deferred domain-semantics
  question (`active_domains` filters *results* vs filters *eligible
  verbs*) is called out in "Deferred decisions" and does NOT block
  this ADR's landing.

## Context

### The gap this ADR closes

Today, cortex-bff extracts `persona` and `entitled_domains` from the
JWT (see `src/iagent/auth.py:44-119`). PingSSO/Keycloak does not emit
these claims in production. The result — confirmed live on a work
cluster on 2026-06-30 against a canonical catalog-ownership test
question ("who owns the X dashboard") — is:

- User logs in with real SSO identity.
- JWT has `sub`, `email`, no `persona`.
- cortex-bff falls back to MECHANIC persona.
- Router finds no compatible catalog verbs for MECHANIC + the query.
- Question falls through to Engine A (generalist fallback).
- Engine A produces an answer without citations. In the observed case
  the answer was plausible-shaped — email addresses that looked
  on-domain — with no way for the caller to distinguish grounded
  data from confabulation.

That failure has three separable causes stacked in one symptom, each
addressed by a different discipline this project has already ratified:

1. **Persona routing failed silently** — `[[optimistic-defaults-are-dishonest]]`.
   The MECHANIC fallback is a default value hiding the absent-claim
   fact.
2. **Router had no eligible verbs and fell back to a generalist** —
   `[[routing-fallback-policy]]` (ADR-0008). Fallback is intended;
   silent fallback is not.
3. **Generalist answered without positive-control evidence** —
   `[[abstention-needs-positive-control]]`. No citation, no audit
   trail; caller has to trust the answer looks right.

This ADR addresses cause 1 durably. Causes 2 and 3 are ADR-0008 and
existing project disciplines respectively — they benefit from this
ADR (correct persona → correct verb eligibility → citation-bearing
answer) but are not its subject.

### Why Keycloak-attribute + JWT-mapper is the wrong durable answer

The fastest path to a working `persona` claim today is a Keycloak
User Attribute + attribute mapper on the OIDC client. The claim
lands in the JWT, cortex-bff reads it, the fallback stops firing.
For a single demo user, this is a 5-minute unblock and the right
tactical move.

For the durable answer it is wrong, on three grounds:

1. **Authz in the authn substrate.** Persona is an authorization
   fact (which verbs is this caller allowed to invoke, in which
   scope). Putting it in the JWT — the identity token — conflates
   authn (identity) with authz (capability). Rotating a user's role
   (adding DATA_ENGINEER, removing MECHANIC) then requires
   re-authentication to propagate. ADR-0009 already established
   persona-source as "identity provider claims"; that framing was
   correct at the time (no policy store existed) but is superseded
   by ADR-0025's Topaz commitment.
2. **Two authz truths that can diverge.** ADR-0025 puts data-instance
   access in Topaz. If persona lives in Keycloak, we have two authz
   stores. A user's `persona` in Keycloak and their capability in
   Topaz can drift silently — the single-authoritative-source
   discipline this project applies everywhere else applies to
   authz itself.
3. **Multi-persona is representationally awkward.** A JWT claim is
   either single-valued (which persona?) or multi-valued as a flat
   list (which loses the persona × domain matrix — see "Decision"
   below). Both are wrong shapes for the reality that a user is
   *entitled* to multiple persona × domain cells but *acts as* one
   at a time. The picker + matrix model requires a store that can
   answer "given this user, what are the cells they can occupy?"
   and "is this specific cell entitled?" — Topaz's Rebac model is
   exactly this; a JWT claim is not.

### Why the JWT gets identity only

Keycloak's job here is proving the caller is who they say. Once
identity is established, everything else — persona, domain
entitlement, per-source-instance authorization (ADR-0025) — is
policy, and policy belongs in the policy engine. This is the
standard authn/authz split; ADR-0025 committed to Topaz as the
policy engine; this ADR extends that commitment to persona.

## Decision

### 1. Persona × domain is a matrix, not a flat list

A user's authorization is a set of (persona, domain) cells:

```
                    AVIATION   DEFENSE   ENTERPRISE
DATA_STEWARD           ✓          .          .
DATA_ENGINEER          ✓          ✓          .
ARCHITECT              ✓          ✓          ✓
MECHANIC               .          .          .
ANALYST                .          .          .
```

Flat lists (`entitled_personas: [DATA_STEWARD, DATA_ENGINEER, ARCHITECT]` ×
`entitled_domains: [AVIATION, DEFENSE, ENTERPRISE]`) imply the
cross-product — that the user is DATA_STEWARD for DEFENSE, which the
matrix above denies. Flat lists cannot represent this truth; they
collapse a two-dimensional fact into a shape that lies. This is the
same class of representational-collapse bug this project has killed
in `[[resolution-discard-pattern]]` and elsewhere.

The matrix is the authoritative representation. Every downstream
consumer (picker options, chat-request validation, routing-card
display) reads cells, never independent lists.

### 2. Topaz is the single authz store

Persona entitlements live in the **same Topaz policy store** as
ADR-0025's instance-plane access control. Object types:

- `persona` — canonical set from ADR-0009 (DATA_STEWARD, MECHANIC,
  DATA_ENGINEER, ARCHITECT, ANALYST — expandable via `personas.yaml`).
- `domain` — canonical set from ADR-0009 domain enum (AVIATION,
  DEFENSE, ENTERPRISE, DATA_ENGINEERING, MAINTENANCE — expandable via
  `personas.yaml`).
- `group` — org-defined grouping (aviation-stewards,
  defense-engineers, enterprise-architects) that maps to cells.

**Abstract semantics.** A user assumes a `(persona, domain)` cell iff
they are a member of at least one group whose grants include that
cell. Formally:

```
can_assume(user, persona, domain) :=
  ∃ group . member_of(user, group) ∧ grants(group, persona, domain)

entitled_cells(user) := { (p, d) | can_assume(user, p, d) }
```

**Concrete Topaz manifest representation** (see
`helm/invincible-agent/templates/topaz-configmap.yaml`): the
matrix is expressed via **cell reification** — each granted
`(persona, domain)` pair is a synthetic `cell` object with key
`<PERSONA>:<DOMAIN>`. Two relations carry the model:

- `group.member` : group → user (a user is a member of a group).
- `cell.assumable_by` : cell → user | group#member (a cell is
  assumable by a specific user OR by any member of a group,
  expressed via Rebac userset rewrite).

The abstract `can_assume` maps directly to Topaz's native permission
evaluation:

```
is(user:<sub>, "can_assume", cell:<PERSONA>:<DOMAIN>) → bool
```

Cells are created on-demand by the CI sync tool — a cell exists in
the store iff at least one group grants it. Cells never granted do
not exist and evaluate false, which is the honest default: an
unpicked-from-nowhere combination is not silently assumable. `persona`
and `domain` are declared as bare types so the sync tool can enforce
that every cell key's components are in the canonical vocabulary — a
Topaz-side positive control complementing the YAML validator on the
git side per `[[verification-must-fail]]`.

The reification is an implementation choice that makes `can_assume` a
native permission check rather than a graph walk cortex-bff would
have to reimplement client-side. The abstract semantics above are
unchanged; direct-to-user grants (rare, for one-off exceptions) and
group grants both flow through the same permission evaluation.

Groups are the scaling primitive. Adding a new defense engineer is
one line under `users.yaml`; changing what defense engineers can do
is one edit under `groups.yaml`. Direct user → cell assignment is
supported but discouraged for anything beyond one-off testing.

### 3. Entitlements are asserted in git, never inferred from directory

Per the correction from the second-agent review of this design:
**every entitlement is a human's asserted claim recorded in a
PR-reviewed YAML file.** No automated process converts an AD/LDAP
group membership into a live Topaz entitlement.

The failure mode this rule blocks is the confabulation-as-authorization
pattern: if we preload guesses ("this user is in AD group
`aviation-eng`, so guess they're DATA_ENGINEER for AVIATION"),
those guesses look authoritative once they land in Topaz — the
router trusts them — but they were *inferred*, not *asserted*. This
is the same shape as `[[optimistic-defaults-are-dishonest]]` (the
`a.status = 'complete'` default) applied to authorization, and the
blast radius is *access*: over-grant is a security problem, under-grant
is an invisible-failure problem for the affected user.

The reconciliation with directory data: AD/LDAP membership is a
**draft input** to the human's decision, never the decision itself.
A separate tooling path (`policy/sync/draft_from_ad.py`, out of scope
for this ADR) can emit a proposed diff to `users.yaml` — "here are the
people in `aviation-eng`, here's a proposed mapping to
`aviation-engineers` group" — which a human reviews and merges via
PR. The PR is the assertion. The git commit is the audit trail. Never
let a directory-derived inference land in Topaz without a named
human's approval on the PR.

This applies equally to `personas.yaml` (which personas exist) and
`groups.yaml` (which cells a group grants). No auto-derivation from
existing verb registry, existing scope filters, or existing tenant
membership.

### 4. YAML shape (source of truth)

`policy/personas.yaml` — cell catalog:

```yaml
personas:
  - DATA_STEWARD
  - DATA_ENGINEER
  - ARCHITECT
  - MECHANIC
  - ANALYST

domains:
  - AVIATION
  - DEFENSE
  - ENTERPRISE
  - DATA_ENGINEERING
  - MAINTENANCE
```

`policy/groups.yaml` — group → cells:

```yaml
groups:
  aviation-stewards:
    grants:
      - { persona: DATA_STEWARD, domain: AVIATION }
  aviation-engineers:
    grants:
      - { persona: DATA_ENGINEER, domain: AVIATION }
  defense-engineers:
    grants:
      - { persona: DATA_ENGINEER, domain: DEFENSE }
  aviation-mechanics:
    grants:
      - { persona: MECHANIC, domain: AVIATION }
  enterprise-architects:
    grants:
      - { persona: ARCHITECT, domain: AVIATION }
      - { persona: ARCHITECT, domain: DEFENSE }
      - { persona: ARCHITECT, domain: ENTERPRISE }
```

`policy/users.yaml` — user → group memberships + default cell:

```yaml
users:
  - sub: user@example.com
    display_name: Example User
    groups:
      - aviation-engineers
      - defense-engineers
      - enterprise-architects
    default:
      persona: DATA_ENGINEER
      domains: [AVIATION]
```

The `default` cell is the picker's starting selection on login. It
must be a cell the user is entitled to (validated at CI time —
sync tool refuses to apply a user with a `default` outside their
entitled cells; this is a `[[verification-must-fail]]` gate).

### 5. Per-prompt picker attached to each request

The picker is a **per-prompt attachment**, not a session lock. Each
outgoing chat request carries the persona/domain values that were
selected in the picker at send-time. History renders each message
with the persona/domain it was sent under, so scrolling back shows
the context each answer was produced in.

**cortex-ui UX (verbatim binding of the architect's requirement):**

- Two dropdowns sit **immediately below the message input**:
  - **Persona** (single-select) — options from `entitled_cells`.
  - **Domain(s)** (multi-select) — options filtered by chosen persona.
- Default selection on login = user's `default` from
  `/me/entitlements`.
- Sticky per session in localStorage (keyed by `sub`) so page reload
  preserves the last choice.
- **Per-prompt authoritative:** the picker value at the moment of
  send is what gets attached to that request. Change mid-conversation
  → next prompt uses the new value. Prior prompts' recorded values
  are not retroactively rewritten.
- **Current-acting-as badge** sits under the prompt input at all
  times: `Acting as DATA_ENGINEER · AVIATION`. Clicking opens the
  dropdowns inline. The badge is the always-visible signifier of
  "what am I about to send this question as?"
- Message bubbles in history carry a small chip: `Sent as
  DATA_ENGINEER · AVIATION`. Different bubbles in the same
  conversation can have different chips.

**Request contract** (`POST /chat`, extends existing):

```json
{
  "question": "...",
  "active_persona": "DATA_ENGINEER",
  "active_domains": ["AVIATION"]
}
```

**Cortex-bff validation:**

- Both fields omitted → use user's `default`.
- Cell entitled → 200, route with `(active_persona, active_domains)`.
- Cell not entitled → **403 with `cell_not_entitled` code + body
  listing entitled cells**. Not a silent downgrade to default. Not a
  bare denial. Honest: "you asked for X; you're entitled to Y."
- Topaz unreachable + cached matrix hit → 200 (matrix was validated
  at token-issue time; still valid).
- Topaz unreachable + cache miss (new session during outage) →
  **503 with `authorization_unavailable` code**. Distinguishable
  from 403. Client shows "auth service temporarily unavailable,
  retry in a moment" not "you're denied."

### 6. Denial is honest; unavailability is distinct from denial

Per the second-agent review's correction: authorization is a *gate*,
not a trailing step. `[[trailing-steps-nonfatal]]` does not apply to
authz — that rule is about post-answer delivery steps, not gates.
Fail-open on unreachable authz would be a silent policy violation
and a security hole.

Therefore:

- **Deny on Topaz-unreachable + no cached matrix** — closed-fail.
- **Distinguish denial from unavailability** — 403 vs 503 with
  distinct codes. The failing party can tell whether they're locked
  out or the auth service is down.
- **Per-token cache with deny-on-cache-miss-and-unreachable** — the
  compromise that keeps demos robust to Topaz blips. A validated
  session (matrix cached at token-issue time) survives a mid-session
  Topaz hiccup; a new session that starts during an outage cannot
  proceed. This is the honest sweet spot: never fabricate an
  authorization, but don't invalidate one that was correctly issued.

Cache TTL = token TTL. Cache eviction on token expiry, logout, or
explicit revocation event (out of scope for this ADR — hook exists,
consumer is a follow-up).

### 7. Interim mechanism retirement

The Keycloak `persona` User Attribute + attribute mapper on the OIDC
client (call this "Tier 3a" per the design conversation) is
explicitly interim. It exists to unblock the 2026-07-01 work
deployment while this ADR's durable path is built.

**Retirement is part of this arc, not a separate follow-up.** Per
`[[coupled-interim-mechanisms-retire-together]]`, when the Topaz
path lands in cortex-bff (step 3 of the rollout below), the JWT
`persona` claim becomes vestigial. The Keycloak attribute mapper
must be deleted, the User Attribute schema removed, and the JWT-read
code path in `src/iagent/auth.py` deleted — not commented out, not
`if MIGRATED else`, deleted. Verified by grep for `persona` claim
reads returning zero hits outside the Topaz client module.

## Rollout

Small PRs, each independently deployable, each with its own
`[[pre-written-fixtures-must-fail-first]]` gate.

1. **Topaz manifest + permission definition.** No runtime consumer.
   Merge → apply to Topaz → `topaz check` from CLI returns real
   answers for a hand-populated test cell. Verified by asserting the
   check returns TRUE for an inserted relation, then FALSE after
   removal.
2. **`policy/` YAML files + CI sync tool.** Seeded with just the
   initial rollout user in the groups matching their actual role.
   Sync tool has readback verification; refuses to green if any
   YAML row is absent from Topaz post-apply. Positive control: run
   sync against an empty Topaz, then re-run readback, confirm it
   flags divergence red before the apply and green after.
3. **cortex-bff Topaz client + `/me/entitlements` endpoint.** No
   chat-path change yet. `curl /me/entitlements` with your JWT
   returns your real cells. Auth middleware caches on token verify.
   Positive control: with Topaz reachable + your JWT, endpoint
   returns your cells; with Topaz killed after cache warm, endpoint
   returns cached cells; with Topaz killed + fresh JWT, endpoint
   returns 503 with `authorization_unavailable`.
4. **Chat request contract extension.** `POST /chat` accepts
   `active_persona` / `active_domains`; validates against cached
   matrix; routes with the resulting cell. Omitted fields → use
   `default`. Old clients (no fields) continue to work via default.
   Positive controls: entitled cell → 200 with matching routing
   card; non-entitled cell → 403 `cell_not_entitled`; omitted →
   200 with default; Topaz-down + cached hit → 200; Topaz-down +
   cache miss → 503.
5. **cortex-ui picker + per-prompt attachment.** Two dropdowns under
   the message input, dependent (domain options refresh on persona
   change), sticky per session, per-prompt attached. Current-acting-as
   badge under input. History chips on message bubbles. Positive
   control fixture: user with ≥3 distinct cells so dependent-dropdown
   filter is actually exercised (`[[fixture-must-exercise-paths]]`).
6. **Retire Keycloak persona attribute + mapper.** Delete User
   Attribute schema in Keycloak. Delete attribute mapper on OIDC
   client. Delete JWT `persona`-reading code paths in cortex-bff.

   **Verification must be broader than a cortex-bff grep.** Per
   ADR-0025's access-control survey, identity claims flow AS
   DATA into the supervisor → engine path — `user_persona` is
   threaded into op config; engines receive it via the
   propagated request context. A grep in cortex-bff only proves
   cortex-bff stopped *reading* the JWT claim; it does not
   prove no downstream consumer depends on the JWT *carrying*
   it. If an engine reads persona from the propagated claim
   data rather than from cortex-bff's Topaz-resolved value,
   deleting the JWT claim silently breaks the engine, cortex-bff's
   grep is green, and the failure surfaces only at runtime under
   a persona-less JWT. This is the local-attestation failure
   mode `[[verify-subtle-acceptance-by-inspection]]` calls out —
   local green that a downstream consumer falsifies.

   Required verifications, all three:

   - **Local grep** (necessary, not sufficient): no reads of JWT
     `persona` claim outside `topaz_client.py` in cortex-bff.
   - **Cross-repo grep** (broader): grep `agent_fleet/`,
     `src/iagent/`, and the supervisor code for reads of
     `user_persona`. For each read, trace it back to its source.
     Every read must resolve to a value originating from
     cortex-bff's Topaz-resolution path (propagated through op
     config, request context, etc.), NOT from a directly-read
     JWT `persona` claim. If any engine reads the claim from a
     forwarded token, that's a code fix owned by this retirement
     step, not a "someone else's problem."
   - **End-to-end integration probe**
     (`[[integration-probe-per-contract]]`): full request
     lifecycle with a Keycloak session whose JWT has NO
     `persona` claim. Assert (a) cortex-bff resolves persona via
     Topaz and does not 500, (b) the resolved value reaches the
     specialist engine intact through the supervisor, (c) the
     engine's response `produced_for.user_persona` matches the
     Topaz-resolved value. This is the positive control that
     catches a downstream reader the greps missed —
     `[[integration-positive-controls]]` applied to the retirement
     boundary.

## Deferred decisions

These are called out explicitly so future work doesn't rediscover
them:

1. **Domain-semantics: filter results vs filter eligible verbs.**
   The `active_domains: [AVIATION]` value could mean "only route to
   verbs registered for AVIATION" or "route freely, then filter
   results to AVIATION-scoped sources." Probably both. Ties into
   `[[path-vs-semantic-domain]]`. Decision deferred to the router
   wire-in step; does not block persona-store landing.
2. **Revocation propagation (coupled interim with the per-token
   cache).** Cache TTL = token TTL is the initial choice; the
   revocation hook that evicts the cache on Topaz change events
   is deferred. This is a coupled interim per
   `[[coupled-interim-mechanisms-retire-together]]` — the cache
   and the hook share the cause "single Topaz truth accessible
   with acceptable request latency" (cache addresses latency;
   hook addresses staleness). Shipping the cache without the
   hook knowingly leaves a divergence window of up to token TTL
   in the security-dangerous direction (removals delayed). See
   Negative "Cache-without-revocation-hook is a known-stale
   authz window" for the risk framing and interim mitigations.
   When the hook lands, it closes the divergence window; the
   cache mechanism itself stays. Hook shape reserved but not
   built.
3. **`draft_from_ad.py`.** AD/LDAP → proposed users.yaml diff
   tooling. Out of scope for this ADR. Design shape called out in
   "Decision (3)" but implementation is a separate arc, after the
   git-asserted path is proven with hand-built entries.
4. **Multi-domain-selection UX beyond two dropdowns.** Users
   entitled to many domains under one persona (e.g., an ARCHITECT
   entitled to 8 domains) may want a search-filter UI rather than
   a raw multi-select. Cosmetic; not blocking.
5. **Direct user → cell assignment (bypassing groups).** Supported
   by the underlying model but discouraged. If it becomes common
   for exception-user reasons, we may need a `direct_grants:` field
   on `users.yaml`. Add when the concrete need surfaces; do not
   pre-build.

## Consequences

### Positive

- **Single authz store.** Persona + instance-plane access both in
  Topaz. One source of truth for authorization.
- **Multi-persona works honestly.** Users like the architect (data
  engineer + steward + architect across multiple domains) can
  declare context per prompt without any collapse of the matrix.
- **Persona changes without re-authentication (fully clean only
  once the revocation hook lands).** Rotating a user's cells is a
  git PR + Topaz sync. If the revocation hook has landed and evicts
  the per-token cache on Topaz change events, the user's next
  request picks up new entitlements immediately. Until the hook
  lands (Deferred #2), changes propagate on cache expiry (= token
  TTL) — see the corresponding Negative below for the divergence
  window this creates and why the dangerous direction is
  *removals*, not additions.
- **Entitlement is auditable.** Every cell is a named human's PR
  commit. `git blame` on `users.yaml` reveals who granted what,
  when, and (via PR body) why.
- **Fallback fires only for real reasons.** After this ADR, MECHANIC
  fallback fires only when Topaz is genuinely unreachable and no
  cache exists — and even then it terminates in a distinct 503, not
  a silent downgrade to a default persona.

### Negative / risks

- **Topaz becomes load-bearing on the request path.** A Topaz
  outage that outlasts cached-token TTL locks out new sessions.
  Mitigation: Topaz uptime becomes a first-class operational
  concern; per-token cache smooths mid-session blips.
- **Cache-without-revocation-hook is a known-stale authz window
  (dangerous direction).** Until the revocation hook lands
  (Deferred #2), the per-token cache is populated at
  token-verify time and NOT evicted until the token expires. If
  a user's entitlement is *removed* mid-token (git PR + Topaz
  sync), cortex-bff continues to authorize against the cached
  matrix for up to the token's remaining lifetime. The
  divergence direction is the security-dangerous one: an
  *over-grant that outlives its removal*. This is the same
  "two authz truths that can diverge" failure mode this ADR
  rejects Keycloak-attribute-in-JWT for (grounds #2 in "Why
  Keycloak-attribute is the wrong durable answer") — via a
  different mechanism (stale cache instead of stale claim) but
  with the same shape. The ADR chooses to land the cache
  without the hook because the alternative (per-request Topaz
  lookup, no cache) is operationally worse and the divergence
  window under a short-TTL token is bounded, but this is a
  deliberate, named trade-off, not a solved problem. Interim
  mitigations: (a) keep access token TTL short — 1h at work is
  the current baseline (helm commit `0856b0f`); consider 15m
  for security-sensitive rollouts until the hook lands; (b)
  treat cache and revocation hook as coupled interims per
  `[[coupled-interim-mechanisms-retire-together]]` — the pair
  must land together to close the divergence window; shipping
  the cache alone is an interim posture with a known unpatched
  authz gap in the dangerous direction.
- **Adds a runtime call to token verification.** Per-request cost
  is one Topaz call for cache miss (once per token TTL). Warm
  caches serve zero-cost. Acceptable for the values delivered.
- **YAML is toil at first.** Hand-asserting users.yaml is
  deliberate friction — the correct posture per "assertions, not
  guesses" — but it does mean an operator hand-edits when a new
  user needs access. Draft-from-AD tooling (deferred) mitigates
  when scale requires.
- **Picker UX is a real design surface.** Two dependent dropdowns +
  sticky + per-prompt-attached + current-acting-as badge + history
  chips is several visible affordances that must be well-composed.
  Not one-day work.

### Neutral

- **Deferred domain-semantics.** `active_domains` filter meaning is
  a router-side decision. This ADR passes the values through; the
  router decides what to do with them at wire-in time.

## Alternatives considered

**A. Full Keycloak-attribute path (persona in JWT, no Topaz for
persona).** Rejected: authz-in-authn-substrate; two-truth divergence
with ADR-0025's Topaz; multi-persona matrix not representable in a
JWT claim. Accepted only as tactical Tier 3a interim.

**B. Flat `entitled_personas` + `entitled_domains` in Topaz.**
Rejected: implies cross-product entitlement which lies about real
access. Same class as `[[resolution-discard-pattern]]` — collapses
a two-dimensional fact into a one-dimensional shape that cannot
express the truth. Would produce silent over-grant or under-grant
bugs the moment a user's real access is asymmetric.

**C. First-login persona picker with self-selection (no Topaz).**
Rejected: entitlement is self-assertion, unverifiable, security
posture is "trust me, I'm a data steward." Fine for internal
prototypes; wrong for production.

**D. AD/LDAP auto-populated Topaz entitlements.** Rejected per the
second-agent review's correction: confabulation-as-authorization.
An inferred entitlement looks authoritative to the router but was
never asserted by a human. Blast radius is access, over-grant is a
security problem. Reconciliation: AD is a draft input to a human's
PR, not a decision.

**E. Fail-open on Topaz unreachable.** Rejected: authorization is a
gate, not a trailing step. Fail-open policy engine = silent policy
violation = security hole. `[[trailing-steps-nonfatal]]` does not
apply. Correct posture is per-token cache + honest 503 on cache
miss.

**F. Serve last-known-good matrix from persistent cache on Topaz
outage.** Rejected: same shape as fail-open with extra steps. The
"last-known-good" was validated at some prior time, but if it's
been evicted from the per-token cache, we've lost the token-issue
context and are guessing. Deny is the honest posture.

## Success criteria

- [ ] `topaz check` from CLI answers `can_assume(user@example.com,
      DATA_ENGINEER, AVIATION)` = TRUE and
      `can_assume(user@example.com, DATA_STEWARD, DEFENSE)` = FALSE
      for a hand-seeded user with matching group memberships.
- [ ] CI sync tool refuses to green if any `users.yaml` row is
      absent from Topaz post-apply (readback-must-fail-first verified).
- [ ] `GET /me/entitlements` with real JWT returns actual cells;
      empty JWT returns 401; Topaz-down + no cache returns 503.
- [ ] `POST /chat` with entitled cell routes correctly; with
      non-entitled cell returns 403 `cell_not_entitled`; with
      omitted fields uses `default`; with Topaz-down + cache-miss
      returns 503 `authorization_unavailable`.
- [ ] cortex-ui picker: two dropdowns visible under prompt input,
      persona-change refreshes domain options, selection is sticky
      per session, per-prompt attached, current-acting-as badge
      always visible, history bubbles carry chips.
- [ ] Keycloak persona attribute + mapper deleted; grep for JWT
      `persona` claim reads returns zero hits outside `topaz_client.py`.
- [ ] **This ADR's half of the catalog-ownership test:** persona
      resolves to DATA_ENGINEER + AVIATION via Topaz for the
      test user, the resolved cell reaches the router intact,
      and the routing card shows `Persona: DATA_ENGINEER · Domain:
      AVIATION · Source: {picker | default}`. This is the
      persona-resolution slice this ADR owns end-to-end.
- [ ] **Joint criterion with ADR-0008 (routing fallback) and the
      specialist citation discipline:** the canonical
      catalog-ownership test question end-to-end returns an
      Engine-D-routed answer with real DataHub citations. Per
      `[[failure-mode-pluralism-in-fixes]]`, this is a
      three-cause outcome (persona resolution + eligible-verb
      selection + citation-bearing specialist answer). A red
      result here does not attribute cleanly to this ADR alone.
      Investigation order: verify persona resolution first (this
      ADR's success criterion above); if that's green, the
      residual failure attributes to ADR-0008 (verb selection
      falling to Engine A generalist) or to the specialist's
      citation discipline (Engine D returning without sources).
      Scoping this criterion as joint prevents bundle-fixing
      three causes under one ADR's failure attribution.

## Non-goals (out of scope for this ADR)

- Instance-plane access enforcement (that's ADR-0025's enforcement
  session, gated separately).
- Domain-semantics decision for `active_domains` (deferred; see
  "Deferred decisions").
- `draft_from_ad.py` tooling (deferred; hand-built YAML is the
  starting posture).
- Real-time revocation propagation (cache TTL = token TTL is the
  initial simplification).
- Persona-picker richness beyond two dependent dropdowns (search
  filter, group-view, etc. deferred until scale surfaces the need).
- Retirement of ADR-0008's fallback path — this ADR *narrows* when
  fallback fires (only Topaz-unreachable-no-cache), but the fallback
  path itself is ADR-0008's subject and continues to serve its
  documented purpose.
