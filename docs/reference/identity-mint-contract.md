# The identity mint contract — how `authz_id` is minted, per species

**Not a how-to for adding a service account. A CONTRACT.** Every identity in the system — human or
service — is a Topaz subject keyed by one value: `authz_id`. Deny-by-default, grants-as-commits, and
per-user isolation ALL derive from that key. So the load-bearing invariant is: **`authz_id` must be
minted identically-in-meaning across every identity species, however different their mint paths.** The
shared-sub incident (two humans briefly sharing an effective key) already taught the cost of mint-path
drift: identity-keyed isolation silently breaks. This doc is that forensic promoted from incident
response to STANDING PROCEDURE — for every species, which mapper chain produces `authz_id`, in what
format, and the one-line check that proves it.

`authz_id` is derived on the cortex-bff side, in `src/iagent/auth.py`:
- `USER_ENTITLEMENT_CLAIM = os.getenv("USER_ENTITLEMENT_CLAIM", "email")` (auth.py:72)
- `authz_id = payload.get(USER_ENTITLEMENT_CLAIM) or user_id` (auth.py:198) — the claim `USER_ENTITLEMENT_CLAIM`
  names, falling back to `sub`. That claim's VALUE is the Topaz lookup key and the stamped `approver`.

So the contract is: **whatever `USER_ENTITLEMENT_CLAIM` names, every species' token MUST carry it with
the intended `authz_id` value.** Sandbox names `email`; work names the employee-id claim.

## Species and their formats (decided — these strings are load-bearing)

| species | authz_id format | example | how the claim is minted |
|---|---|---|---|
| **human (sandbox)** | email | `alice@example.com` | Keycloak issues `email` natively for the seeded user |
| **human (work)** | employee-id | `E01234567` | Ping asserts the attribute → broker IdP mapper → client/protocol mapper → the claim `USER_ENTITLEMENT_CLAIM` names (TWO mapper hops) |
| **service (any env)** | `svc:<name>` | `svc:review-starter` | a LOCAL Keycloak client with a hardcoded-claim mapper emitting the claim `USER_ENTITLEMENT_CLAIM` names = `svc:<name>` (ZERO Ping hops) |

`svc:<name>` is the service-id convention (namespaced, unmistakably non-human, stable). It appears in
`users.yaml`, `capability_grants.yaml`, `requested_by` records, and the cortex-ui "(automated)" display
rule — renaming it later is expensive, so it is fixed now. **Services never carry a persona/domain**;
they hold CAPABILITY grants, not persona×domain cells.

---

## Section 1 — Sandbox reference implementation (config-as-description; this is BUILT)

The whole sandbox identity plane is declarative (Keycloak realm-import, no `kcadm`; git-rails for
grants). `svc:review-starter` — the extraction→review sensor — is the first service identity and the
pattern every future one copies.

**Keycloak client** (`helm/invincible-agent/templates/keycloak-configmap.yaml`, realm-import `clients[]`):
```json
{
  "clientId": "iagent-review-starter",
  "publicClient": false, "serviceAccountsEnabled": true,
  "standardFlowEnabled": false, "directAccessGrantsEnabled": false,   // client-credentials ONLY
  "secret": "<keycloak.reviewStarterClientSecret>",
  "protocolMappers": [{
    "name": "authz-id-svc", "protocolMapper": "oidc-hardcoded-claim-mapper",
    "config": { "claim.name": "email",              // == USER_ENTITLEMENT_CLAIM (sandbox default)
                "claim.value": "svc:review-starter", // the authz_id, minted at birth
                "jsonType.label": "String", "access.token.claim": "true" }
  }]
}
```
No browser, no redirect, no federation in its path. The mapper is the FIRST protocol mapper in the realm
— it establishes the pattern, it does not edit an existing one.

**Secret, single-sourced** (`values.yaml keycloak.reviewStarterClientSecret`) feeds BOTH the realm
client `secret` AND the Secret's `REVIEW_STARTER_CLIENT_SECRET` (`secrets.yaml`) — they must match. The
sensor mints a FRESH token per run (`mint_service_token`, `extraction_review_sensor.py`): POST
`{KEYCLOAK_REALM_URL}/protocol/openid-connect/token` `grant_type=client_credentials` with
`REVIEW_STARTER_CLIENT_ID` + `REVIEW_STARTER_CLIENT_SECRET`. No static JWT to expire; a mint failure is a
loud failed Dagster run.

**The rails grants** (git-asserted, flowed by the seed CronJob — never hand-surgery):
- `users.yaml`: `svc:review-starter` seeded as the SERVICE species (no `groups`, no `default`).
- `capability_grants.yaml`: `can_invoke mesh:startReview` → `svc:review-starter` (the initiator gate —
  a CAPABILITY, because starting a review invokes a verb; it is NOT a task-audience membership, which
  would mean recipiency). `validate_policy` (network-free) confirms both parse.

**Verification (the mint→decode→confirm one-liner — the shared-sub forensic, standing):**
```
TOKEN=$(curl -s -X POST "$KEYCLOAK_REALM_URL/protocol/openid-connect/token" \
  -d grant_type=client_credentials -d client_id=iagent-review-starter -d client_secret=<secret> \
  | jq -r .access_token)
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '.email'   # MUST be "svc:review-starter"
```
Run this for EVERY species after any realm/mapper change: mint a token, decode it, confirm the claim
`USER_ENTITLEMENT_CLAIM` names carries the intended `authz_id`. A mismatch here is the shared-sub bug's
shape — catch it at the token, not at a broken isolation boundary.

### EXECUTED 2026-08-05 (ADR-0034 phase 1.3) — sandbox, `svc:review-starter`

Procedure converted to RECORD. Decoded from a live mint on the running engine-a pod:

```
email                svc:review-starter        <- the load-bearing claim (USER_ENTITLEMENT_CLAIM
                                                  is unset, so auth.py's `email` default applies)
sub                  0b9ad80d-3280-4579-…      <- the Keycloak UUID; NOT the authz_id
azp / client_id      iagent-review-starter
preferred_username   service-account-iagent-review-starter
```

**The contract above was already right — this is what "already right" looks like when checked rather
than assumed.** There is NO claim named `authz_id` in the token; the identity rides `email`, exactly
as §1 states. Recorded because the natural expectation is a claim named for the concept, and a
reader who inferred `authz_id` from the prose would have verified the wrong field and found nothing.

### THE WEIGHT OF THIS CLAIM DOUBLED ON 2026-08-05 — §2 inherits it

Until phase 1.3 this claim decided login and routing. It now ALSO decides whether the **autonomous
dispatch gate** resolves: the ceremony grants `can_invoke(mesh:dispatchDispositions)` to
`svc:review-starter`, and the gate checks the caller that arrives from this claim. Witnessed in the
Restate journal before the grant exists —

```
caller 'svc:review-starter' is not authorized (can_invoke) for capability
'mesh:dispatchDispositions' — failing and releasing.
```

— the deny→allow flip's before-picture, whose subject comes from `email`.

So the work-side risk is no longer "logins break." It is: **a Ping broker mapping that lands the
employee identity in a DIFFERENT claim than the local service mapper uses splits the identity
contract** — at exactly the seam the shared-`sub` bug taught us it breaks, except one side of the
split is now an autonomous effect gate rather than a queue filter.

**Verify BOTH species' tokens at work BEFORE the ceremony's grant is applied, not after.** A grant
keyed on a claim the other path does not populate is a grant that appears to land and never
resolves — the no-op's evil twin, in the identity plane, at the one moment nobody would be looking
for it.

---

## Section 2 — Work translation (PREDICTIVE — written against a Ping realm never seen)

> Everything in this section is an assumption with a check, not a known-good. The first hour at work
> validates it line by line; then this section converts from prediction to record. Labeled this way on
> purpose — asserting it as fact is exactly the drift the contract exists to prevent.

**The service account never touches the federation — that is the good news, architecturally.** Ping
federates HUMAN login (browser redirect, SAML/OIDC brokering). A client-credentials service account is a
LOCAL Keycloak client with its own secret: no browser, no redirect, no Ping in the path. So
`iagent-review-starter` at work is the SAME object as sandbox — a local confidential client — authenticating
directly against work's Keycloak. Federation and local service clients coexist by Keycloak design.

**Deltas from Section 1, each with its check:**
1. **Realm name** — `keycloak.realm` differs. *Check:* the token's `iss` names the work realm.
2. **`USER_ENTITLEMENT_CLAIM`** — work sets it to a NON-email claim, NOT `email`. The claim the human
   broker mappers AND the service client carry must be THAT claim name.
   *Check:* `USER_ENTITLEMENT_CLAIM` (cortex-bff env) == the identity claim on the service token == the
   claim the Ping broker mapper projects for humans. All three equal, or isolation drifts.
   **PER-ENVIRONMENT MAPPER COUNT (the simplification — state it so it's legible, not rediscovered):**
   whether the service account needs an identity mapper AT ALL depends on the claim:
   - If `USER_ENTITLEMENT_CLAIM` names a claim the service account populates NATIVELY — the OIDC-standard
     username claim, which equals the service-account's own username — then **ZERO identity mappers** are
     needed. The username IS the claim, carried in every client-credentials token for free; set the
     service-account username to `svc:<name>` and the entitlement identity is already present. The
     identity half was never broken in that case.
   - If it names a NON-native claim (e.g. an employee-id claim) — then **ONE hardcoded mapper** emits
     `<claim> = svc:<name>`.
   So the service-account identity-mapper count is env-dependent: **zero** when the entitlement claim is
   the native username, **one** otherwise. (The dummy `email` mapper in delta 6 is SEPARATE — an
   unconditional transitional artifact until the auth fix rolls, independent of this count.)
3. **Human mint = TWO mapper hops** (the tricky species): Ping asserts an attribute → Keycloak IdP mapper
   imports it → a client/protocol mapper projects it into the claim `USER_ENTITLEMENT_CLAIM` names, as the
   employee-id. *Check:* a real human logs in, decode their token, confirm the employee-id lands in that claim.
4. **Service mint = ZERO Ping hops** — the hardcoded-claim mapper on the local client emits
   `<employee-id-claim-name> = svc:review-starter`. *Check:* the Section-1 client-credentials decode, against
   the work realm.
5. **Admin access is the REAL critical path.** Standing up a local client needs Keycloak realm-admin. If
   that is a platform team's, not yours, the TICKET to create the client is the demo's gating item — file it
   THIS WEEK, not demo-week. *Check now, not later:* confirm who owns realm admin on work's Keycloak.
6. **The `email`-claim gate — RESOLVED, and a transitional workaround it forced (VALIDATED at the first
   live service mint).** When `USER_ENTITLEMENT_CLAIM` is a NON-email claim and the service account has no
   mailbox, `authz_id` resolves from that claim and `email` is legitimately ABSENT. cortex-bff `auth.py`
   USED to hard-require an `email` claim (`if not user_id or not email`) — contradicting its own model
   ("email: DISPLAY/AUDIT only — never an authorization key") and 401'ing the mailbox-less service token
   with `missing 'sub' or 'email'`.
   - **INTERIM — a transitional lie, retire on sight:** a SECOND hardcoded-claim mapper `email =
     svc:review-starter`, added purely to pass that gate. It puts a non-mailbox value in a claim consumers
     may read as an address — present ONLY to satisfy `auth.py`; NO consumer may parse it as a mailbox;
     DELETE it the moment the fix below deploys. (Left un-recorded, this workaround outlives its reason — a
     stale record in a claims payload.)
   - **FIX (branch `fix-auth-email-optional-service-identity`):** `auth.py` now authenticates on the AUTHZ
     identity (`resolve_token_identity`: `USER_ENTITLEMENT_CLAIM` → `sub` fallback), with `email` optional
     and NEVER defaulted to a non-mailbox value. After it rolls, a service account needs ONLY the
     entitlement-claim mapper. *Check:* decode the service token — `email` claim ABSENT, entitlement claim
     == `svc:review-starter`, `/reviews` authenticates. Then remove the dummy `email` mapper.
   - **Related, NOT on this path:** the data-plane read gate (central-gateway `can_read`) is separately
     email-keyed, threaded via `X-Originator-Email` (see `data_analyst/main.py`). Same email-as-identity
     class, different surface; banked for its own pass — it does not gate service-identity minting.

**Config-as-you-go — capture, don't reconstruct.** Every mapper you create by hand in an external realm
(claim name == `USER_ENTITLEMENT_CLAIM`; value `svc:<name>`; `access.token.claim=true`) goes into THIS
section AS you set it, not from memory later — so the NEXT service identity (dispatcher, analyst-loop) is
minted from the record, not tribal memory. And record WHO owns that realm's config long-term: if it is a
platform team's, the hand-created client is itself a documented hand-off request (a paste of this block),
not a meeting.

---

## Section 3 — The grants, per environment id-format

Grants are git-asserted (`task_grants.yaml` / `capability_grants.yaml` → the seed CronJob). The SUBJECT
string is the only per-environment difference — it is the `authz_id` in that env's format.

| grant | sandbox subject | work subject |
|---|---|---|
| `capability_grants.yaml` `can_invoke mesh:startReview` (INITIATE) | `svc:review-starter` | `svc:review-starter` (service format is env-independent) |
| `task_grants.yaml` `disposition_review:SUSTAINMENT` `can_act` (REVIEW) | `alice@example.com` | the reviewer's employee-id |
| `users.yaml` seed | `svc:review-starter` (+ human emails) | `svc:review-starter` (+ human employee-ids) |

The initiator (service) and the reviewer (human) are DIFFERENT subjects in DIFFERENT namespaces — the
split that this whole arc established. Both are needed; neither substitutes for the other.

---

## Forward-looking: this is instance-one of a species, not a one-off

`svc:review-starter` is the FIRST service identity; it will not be the last. The dispatcher acting
autonomously, and eventually the analyst loop, want the SAME shape: a local client-credentials client,
`authz_id` in `svc:<name>` format, seeded in `users.yaml` as the service species, capability-granted
through the rails, minted per-run. The second service identity COPIES this contract — it does not
improvise a sibling. That is generic-at-birth for identities: the species is `service`, the instances are
parameters. When you add the next one, the only new artifacts are: a client block (copy
`iagent-review-starter`), a `users.yaml` service entry, its capability grant, and the mint→decode→confirm
check. Everything else is already the pattern.

## IDENTITY GRANULARITY FOLLOWS GOVERNANCE, NOT TOPOLOGY (ruled 2026-08-07)

**A credential exists per GOVERNED SUBJECT. Ungoverned internals share their process's
credential, with per-module attribution in the payload.**

"Per-process identity" was shorthand for *don't mint identities that govern nothing* — never a
licence to dissolve subjects that do. The question came up because Engine A's process hosts
four callers of Engine O: three ungoverned helpers (`decision_record_writer`,
`review_composer`, `policy_rules_client`) and `review_starter`, which holds
`can_invoke(mesh:startReview)`.

### THE OPERATIONAL TEST — so the next boundary question answers itself
> **Would merging this identity change the answer to any `can_invoke` / `can_act` question,
> now or in a planned grant?**
> **Yes** → it is a governed subject; the identity survives as a boundary.
> **No** → it is an ungoverned helper; it shares the process credential.

Applied: `svc:review-starter` **survives**; the three helpers **merge** into `svc:engine-a`.

### Why this is a ruling, not a preference
1. **Merging silently rewrites a governed decision.** `svc:review-starter` was entitled because
   someone deliberately entitled *the review-starter role* — the grant's subject IS the point
   of the grant. Moving it to a process identity would make every module in that process able
   to start reviews, with no commit saying so: the stored-authz migration class, executed by
   refactor. The blast radius is already scheduled — the workflow-2 ceremony's grant targets
   `svc:review-starter` **by name**, and the empty-caller incident showed exactly what a grant
   aimed at a dissolved subject does: lands, denies forever, looks designed.
2. **Topology is a fact that changes; grants must not follow it silently.** `review_starter`
   living inside engine-a is a deployment detail — move it to its own service and, as a role
   identity, the governance layer never notices. As a process identity, that move becomes an
   identity migration with a grant transfer. Identity-follows-governance is what keeps deploys
   and grants independently evolvable.
3. **Audit legibility.** `requested_by: svc:review-starter` says *the review-starter acted* — a
   statement about a governed role. `requested_by: svc:engine-a` says a process did something
   and makes the reader reconstruct which resident. For the field the attribution arc spent a
   week making truthful, the role name is the honest grain.

### CAVEAT, stated so nobody mistakes it for more than it is
Within a single process, role identities are **audit and governance boundaries, not security
isolation**: any code in the process can reach the mint. The split buys legible grants and
honest attribution — it does not buy a privilege wall, and must never be cited as one.
