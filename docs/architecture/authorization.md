# Authorization Architecture — the cross-repo map

**Status:** living map. **Owns:** the topology, the boundary contracts, and
the invariants — the connective tissue that lives in *no single repo* and is
where every auth bug has lived (`sub`-vs-email, empty `user_id`, three-way
payload misalignment: each was two repos disagreeing about a contract no doc
owned).

**Does NOT own:** how each piece is implemented (rego evaluation, payload
schemas, sync `plan_diff`). Code is authoritative for *how*; this doc points
at code for that. Duplicated detail is the thing that drifts and lies — so
every claim here is anchored to a `file:line` and, where one exists, the
probe that proves it. **If the referenced probe is green, the claim is
currently true; if the code moved, the anchor breaks — drift surfaces
instead of hiding.** (Same derive-and-diff discipline as the rest of the
system, applied to this doc.)

Read this once to get the end-to-end picture; jump to the anchors for
implementation. This exists so the auth topology is not reconstructed from
fragments every time someone touches a seam.

---

## 0. The governing invariant (read first)

**Access control is the OUTER gate; persona and domain are INNER
refinements that operate only on what access already released. Access
regulates persona/domain — never the reverse.**

- **Deny-by-default.** A subject may read an asset ONLY via an *explicit,
  asserted, auditable, per-asset* grant (owner, or an explicit `reader`
  relation a human asserts). Entitlement / persona / domain establish
  *eligibility to be granted* (necessary); they are NEVER the grant
  (sufficient). "Cleared for the domain" ≠ "granted this asset" — need-to-know.
- **Why (threat model):** this system holds TS/SCI, government-owned,
  proprietary, and PII data. An over-grant is a *spill* — unrecoverable,
  reportable. The only safe error direction is deny-until-granted. So
  `owner-OR-entitled` (entitlement-implies-read) is **rejected as a model**,
  not deferred — with no per-dataset domain it degenerates to "any
  DATA_ENGINEER reads all PII", the compartment-collapse need-to-know exists
  to prevent.
- **`permission` is the ENCLOSING gate, not a peer.** The routing eligibility
  intersection `(domain ∩ arity ∩ argument-fit)` is inner-layer relevance;
  the access gate *wraps* it. Neither layer can become the other: routing
  has no authorization code; authorization requires more than persona/domain.
- **Authorize first, present second.** Persona shapes the *voice* (ADR-0009)
  of already-granted content; it can never surface ungranted content.

Full statement + reasoning: memory `access-regulates-persona-domain`;
ADR-0025 (instance-plane access control as provenance).

---

## 1. Topology — who DECIDES, who ASKS, who INFORMS

Single-decider model. Exactly one component decides; everything else either
supplies facts to decide on (informs) or calls the decider and honors the
answer (asks). No policy predicate is ever evaluated in application code.

```
            INFORMS (facts → directory)                DECIDES
  ┌───────────────────────────────────────┐      ┌──────────────────┐
  │ DataHub  ──owner relations──►          │      │  TOPAZ           │
  │ git YAML ──persona/cell/group/member──►│─────►│  (Aserto ReBAC)  │
  │ (policy/*.yaml)                        │ seed │  Directory 9393  │
  └───────────────────────────────────────┘      │  Authorizer 8383 │
                                                  └────────▲─────────┘
            ASKS (call + honor, never evaluate)            │ is(...)
  ┌───────────────────────────────────────┐               │
  │ central_gateway   ──can_read (DA-read)─┼───────────────┤
  │ query_metadata    ──can_view (catalog)─┼───────────────┤
  │ cortex-bff        ──entitlements matrix┼───────────────┘
  └───────────────────────────────────────┘
```

### DECIDES — Topaz
- Directory (`topaz-svc:9393` REST / `9292` gRPC), Authorizer
  (`topaz-svc:8383` REST / `8282` gRPC). Config + policies + ReBAC schema:
  `helm/invincible-agent/templates/topaz-configmap.yaml`.
- **ReBAC schema** (`manifest.yaml` in that configmap): `user`;
  `dataset{owner:user, reader:user}` with `can_read: reader | owner`;
  `persona`, `domain` (bare); `group{member:user}`;
  `cell{assumable_by: user | group#member}` with `can_assume: assumable_by`.
  Cell key = `"<PERSONA>:<DOMAIN>"`.
- **Policies** (mounted into `/policies` — a key absent from the deployment's
  `items:` list is DORMANT, never loaded):
  - `data_broker.rego` — pkg `data_mesh.GET.api.v1.assets.__asset_key.authorize`
    — the **DA-read** gate (`can_read` on a dataset). Mounted.
    [topaz-configmap.yaml] · deny-by-default, owner/explicit-reader only.
  - `catalog_domain_view.rego` — pkg `invincible_agent.catalog.can_view` —
    the **catalog-metadata** gate (hop 2). Mounted. Deep-derives domain
    entitlement from the caller's seeded cells.
  - `persona_entitlement.rego` — pkg `invincible_agent.persona.can_assume` —
    **DORMANT** (NOT in `items:`). cortex-bff does persona checks via the
    Directory client (§2), not this policy.
- Deployment mount + `items:` list: `topaz-deployment.yaml`.

### ASKS — the enforcement points
| point | asks | policy | repo · file |
|---|---|---|---|
| `central_gateway.check_topaz_authz` | `can_read` (DA data rows) | data_broker | **dag-tools** · `dag_tools/central_gateway/main.py` |
| `query_metadata` | `can_view` (catalog metadata) | catalog_domain_view | invincible-agent · `agent_fleet/datahub_wrapper/main.py` |
| cortex-bff `get_current_user` | entitlement matrix (cells) | Directory walk | invincible-agent · `src/iagent/auth.py`, `src/iagent/authz/topaz_client.py` |

Flag gating: `query_metadata`'s ask is behind `ENABLE_AGENTIC_AUTH` (dark
launch; flips LAST). `central_gateway`'s ask is **live** (no flag,
fail-closed, `ALLOW_MOCK_AUTH` fail-open removed — dag-tools `60cf283`).

### INFORMS — the directory syncs (facts, never decisions)
| source | asserts | fact type | file |
|---|---|---|---|
| DataHub | `dataset` objects + `owner` relations | RESOURCE | `policy/sync/datahub_topaz_sync.py` |
| git YAML | `persona`/`cell`/`group`/`member` + `user` | SUBJECT entitlement | `policy/sync/topaz_sync.py` (from `policy/{personas,groups,users,domains}.yaml`) |

Both run, readback-gated, from the seed CronJob
`helm/invincible-agent/templates/topaz-seed-cronjob.yaml` (default-disabled).
DataHub supplies *resource* attributes; git supplies *subject* attributes;
the request supplies *environment* — Topaz decides on all three. No source
decides.

---

## 2. Flow across boundaries — the CONTRACTS (where every bug lived)

### Identity: the directory is keyed by EMAIL
A JWT carries `sub` (opaque UUID) **and** `email`. **The Topaz directory
keys subjects by EMAIL** (`policy/users.yaml` ids are emails; DataHub owners
are emails), selected by `USER_ENTITLEMENT_CLAIM` (`auth.py`, default
`email`). Therefore **the EMAIL, not the sub, must reach every enforcement
point.** Sending the sub matches no subject → deny-all (this was the
`central_gateway` bug).

### Subject is passed EXPLICITLY in `resourceContext`
This Topaz has **no `identity→user` resolution objects seeded**, so
`input.user.id` is always EMPTY. Enforcement points pass the subject key
explicitly as `resourceContext.user_id`; policies read `input.resource.user_id`.
`identityContext` must still be present (authorizer request validation
rejects its absence, `E30008`) but does not carry the decision subject.

### The DA-read contract (central_gateway ⇄ data_broker) — MUST agree
| central_gateway sends | data_broker reads |
|---|---|
| `resource_context.user_id` = caller **email** | `input.resource.user_id` |
| `resource_context.asset_key` = dataset URN | `input.resource.asset_key` |
| `policy_context.path` = `data_mesh.GET.api.v1.assets.__asset_key.authorize` | (the package) |
| `decisions: ["allowed"]` | rule `allowed` |

Anchors: sender `dag-tools/dag_tools/central_gateway/main.py`
(`authz_payload`); reader `topaz-configmap.yaml` (`data_broker.rego`
`allowed`). **Historical bug (fixed):** these disagreed three ways at once
(`sub`≠email, subject in `identity_context`, field `asset` not `asset_key`)
→ silent deny-all. If you change either side, check the other against this
table.

### The config contract (enforcement point ⇄ helm) — env var NAMES must agree
An enforcement point's Topaz URL comes from an env var *the chart provides*;
code and chart must agree on the **name**. `central_gateway` reads
`TOPAZ_AUTHORIZER_URL` (the mesh convention — also `auth.py`,
`datahub_wrapper`), falling back to legacy `TOPAZ_URL`, defaulting to
`http://topaz-svc:8383`; helm sets `TOPAZ_AUTHORIZER_URL`
(`values.yaml`). **Historical bug (fixed, `cb47d63`):** code read `TOPAZ_URL`
(bad default `https://localhost:8383`) while helm set `TOPAZ_AUTHORIZER_URL`
— a NAME mismatch, so the gate was unreachable and fail-closed denied every
read (broken-closed at the config layer — invisible deny-all). This is a
cross-repo *config*-contract, distinct from the payload contract above and
the same class: two internally-consistent repos disagreeing at the boundary.
Anchor: `central_gateway/main.py` (`TOPAZ_URL = os.getenv(...)`) ⇄
`helm/invincible-agent/values.yaml`.

### The catalog-metadata contract (query_metadata ⇄ catalog_domain_view)
`query_metadata` sends `resourceContext.user_id`=email +
`resourceContext.domain`=served domain; `catalog_domain_view.rego` reads
`input.resource.user_id` + `input.resource.domain` and deep-derives whether
the caller holds any `cell:<persona>:<domain>`. Proving probe:
`tests/security/test_catalog_can_view_ask.py` (exercises the REAL helper
against the live authorizer, discriminating).

### Identity reaches the point through ALL dispatch paths
`query_metadata` is reached by **two** supervisor dispatches — the
**generalist fallback** and the **specialist dispatch**. Every field the gate
needs (`entitled_domains`, `caller_email`) must thread through **both**;
verify by exercising both (a permitted AND a denied user tend to route
differently). Threading path: `src/iagent/gateway.py` →
`src/iagent/defs/dynamic_supervisor.py` (both payload sites) →
`agent_fleet/restate_analyst/main.py` → `agent_fleet/datahub_wrapper/main.py`.
Memory: `identity-reaches-enforcement-point` (multi-path corollary).

---

## 3. Invariants — the constitution (checked by every hop)

1. **Access regulates persona/domain** (§0). Outer gate releases; inner
   routing refines what it released; no inner cleverness reaches what the
   outer gate didn't release.
2. **Single decider.** Topaz decides; others inform or ask; no policy
   predicate in application code. Interim in-code gates retire by becoming a
   Topaz *call*, not by changing predicate. Memory `single-authz-decider`.
3. **Deny-by-default, explicit per-asset grants; entitlement necessary-not-
   sufficient.** Grants asserted, auditable, per-subject-per-asset.
4. **Broken-closed hides brokenness → prove the ALLOW path.** A gate broken
   in the deny direction is invisible (denial doesn't alarm). "Denies
   everyone" is consistent with a working AND a non-functional gate. Every
   deny-gate ships with a DISCRIMINATING allow-side proof: authorized-subject
   allowed on the granted asset, same subject DENIED on a non-granted asset
   (per-asset), other subject DENIED on the granted asset (per-subject).
   Memory `broken-closed-hides-brokenness`. Bitten 3×.
5. **Topaz v2→v3 platform fact.** Use `ds.check` / `/api/v3/directory/check`,
   NEVER `ds.check_permission` / `/check/permission` (dead — REST 404s loud,
   Rego builtin silently returns false). Memory `topaz-v2-v3-api-split`.
6. **Identity reaches the enforcement point** — the directory's key form
   (email), through ALL dispatch paths (§2).
7. **Fail-closed everywhere.** Any error/timeout/unreachable → DENY, loud log
   ("TOPAZ AUTHZ DENIED"). No mock/fallback fail-open.
8. **Authorize first, present second.** Persona styles already-granted
   content only.

---

## 4. Deferred gaps — with triggers (deliberate, not rediscovery)

- **Per-dataset domains are null in DataHub** (all seeded datasets
  `domain:null`). The finer reader-derivation (readership from
  *entitlement ∩ domain*) has no domain operand and is deferred behind a
  TWO-step prerequisite: (1) assign DataHub Domains to datasets (upstream
  governance), (2) extend `datahub_topaz_sync.py` to capture them (it fetches
  tags, not domains). When present, domain is a **guardrail** on grant
  validity (no cross-compartment reader) — an ABAC attribute the decision may
  consult — **never** access-sufficient.
- **HITL grant flow = the PRIMARY data-access mechanism.** Deny-by-default
  means people get data access via explicit grant: deny → request →
  human-asserts → grant, recorded auditable (git-asserted `reader` relations,
  or the HITL dashboard writing the relation + provenance). First manual
  rehearsal done (alice → `reader` → customers_gold, proven discriminating).
  Spec of a grant assertion (gathered from the rehearsal): subject (email),
  asset (URN), relation (`reader`), asserter (human), recorded-where
  (directory + provenance). Memory `project_hitl_grant_dashboard_spec`.
- **`access_decision` provenance capture** (ADR-0025) = the legally-required
  audit trail ("why was this subject permitted to read this asset, when").
- **`ENABLE_AGENTIC_AUTH` flips LAST**, after all enforcement points migrate
  and the directory is current. It is COUPLED with the `query_metadata`
  in-code fallback: they retire together at the flip (the flag chooses
  between in-code gate and Topaz ask; deleting the fallback while the flag is
  off would strand flag-off with no gate). Memory
  `coupled-interim-mechanisms-retire-together`.

---

## 5. Enforcement-arc status (2026-07-06)

| gate | policy | caller | state |
|---|---|---|---|
| catalog metadata | catalog_domain_view | query_metadata | migrated, sealed both verdicts, flag-gated (off) |
| DA data-read | data_broker | central_gateway | fixed deny-by-default + aligned + deployed; proven discriminating incl. allow-side (grant); full-e2e DA-read drive is the remaining seal |
| verb-invoke | (future) | routing | not yet — the eligibility intersection is routing; permission wraps it |
| auth-blind engines | (future) | per-engine | not yet — each inherits invariants §3, esp. #4 |

Directory seeded + kept current by the CronJob (both syncs, readback-gated).

---

## 6. Deploying with a REAL access-control overlay (fixed engine vs swappable overlay)

The sandbox's access control (the configmap rego, the seeded alice/bob/
customers_gold relations, the Keycloak `@example.com` users) is **test data**,
not the model. A real deployment (corporate IdP, real DataHub, real
governance, classified data) swaps the OVERLAY and does NOT touch the ENGINE.
Single-decider is what makes this a config+policy swap, not a rewrite:
because no enforcement point evaluates policy (they only ASK), the policy is
an overlay in one place. **This boundary is a verified property, not an
assumption — checked by inspection 2026-07-06.**

**FIXED — the engine (do NOT change per-deployment):**
- The enforcement points (`central_gateway`, `query_metadata`, cortex-bff
  entitlements) — they only ASK Topaz and honor the answer; they contain no
  policy. Verified: no hardcoded domain/persona literals in the DA-read path.
- `data_broker.rego` — **fully generic**: `ds.check(dataset, can_read, user)`
  over whatever relations are in the directory. No baked vocabulary. The
  data-read gate is pure overlay-evaluator.
- The ReBAC schema TYPES (`manifest.yaml`) and the single-decider / ABAC
  plumbing.

**SWAPPABLE — the overlay (per-deployment config):**
- **Directory CONTENTS** — from the real DataHub (owner/tag/domain facts) and
  the real governance process (subject entitlements). Point the syncs at real
  sources; the same rego evaluates real relations.
- **Attribute-source configs** — `DATAHUB_GMS_URL`, the `policy/*.yaml` source
  (or its replacement), `ENGINE_D_SERVED_DOMAIN`.
- **IdP config** — `KEYCLOAK_REALM_URL` → the real IdP (e.g. PingSSO, note the
  `pingsso-claim-gap`), `USER_ENTITLEMENT_CLAIM` → whatever claim the real IdP
  issues as the stable entitlement key.
- **The rego POLICY** — swappable, but see the two test-isms below that must
  be cleaned for a *fully* generic overlay.

**TEST-ISMS to clean before a real overlay is fully generic** (found by
inspection — fix these so the fixed layer has zero deployment-specifics):
1. **`catalog_domain_view.rego` hardcodes the persona vocabulary**
   (`personas := ["DATA_STEWARD", …]`). At a deployment with different
   personas the *policy* changes. Interim (Option-A) tradeoff with a named
   trigger; the generic form derives the persona set from the directory
   rather than a literal list. (The DA-read gate `data_broker.rego` does NOT
   have this — only the catalog gate.)
2. **`central_gateway` hardcodes the claim name** `unverified_claims.get("email")`
   rather than reading a configurable claim (as `auth.py`'s
   `USER_ENTITLEMENT_CLAIM` does). At a deployment whose entitlement claim
   isn't `email`, this enforcement point needs a change. One-line fix: read
   the claim name from env, mirroring `auth.py`.

**MODEL-EXTENSION for a classified deployment (added within the same
plumbing, not a rewrite):** the current model evaluates *ownership +
domain-entitlement*. A TS/SCI/proprietary deployment adds
**classification / clearance / compartment** attributes — a `classification`
on the resource (from the real DataHub), a `clearance` on the subject (from
the real IdP/governance), a compartment relation — evaluated by the SAME
single-decider (a `can_read` that also requires clearance ≥ classification
AND compartment membership), fed by the SAME ABAC sources. Deny-by-default +
explicit-grant (§0) is unchanged; classification becomes an additional
necessary condition (a guardrail), never a substitute for the explicit grant.
This is *extend the model*, not *rebuild for classification* — which is only
true because the plumbing is decider-pluggable, and that is the property this
section verifies.

**The one-line deploy rule:** to deploy with a real overlay, swap the
**directory source** (real DataHub + real governance), the **attribute/IdP
config**, and the **rego policy** (cleaning the two test-isms) — and do NOT
touch the enforcement points. If a future change to an enforcement point is
needed to onboard a deployment, that is a test-ism leaking into the fixed
layer — fix it in the fixed layer, don't fork per-deployment.
