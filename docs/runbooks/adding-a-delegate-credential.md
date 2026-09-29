---
# EXPLAINS IS EMPTY, for the reason rolling-a-service.md established (register R-015) and
# pinning-the-fleet-sdk.md repeated: creating an IdP client is an infrastructure act. The mesh
# declares four lowercase verbs and none concerns identities, credentials or realms, so there is
# no contract-depth target, and minting `mesh:createDelegate` is exactly the move the invented-IRI
# gate (ADR-0037 §1) refuses.
iri: docs:runbook-adding-a-delegate-credential
explains: []
doc_kind: how-to
audience_hint: ARCHITECT
---

# Runbook — adding a delegate credential

**You want this when** something must call the fleet *on a person's behalf* — a scheduled report,
a batch writer, an agent acting for a named user — and you need the call to be **attributable to
that person** without the credential **becoming** them.

> ⚠ **THIS PAGE IS WRITTEN, NOT YET RUN.** Every value below is derived from the chart and the
> realm template with a `file:line` beside it, and the fleet-side half is covered by a seal that
> passes and has been mutation-tested. But **no delegate client exists in any realm yet**, so no
> line here has been corrected by a run, and the template's own rule says a reader must be able to
> tell those apart. Expect §5's verification to find something. The `⛔ UNRUN` marks below are the
> specific steps nobody has executed.
>
> Written 2026-09-28 alongside the fleet-side change (`src/iagent/auth.py`), which is the half
> that could be done and sealed without touching a cluster.

**Scope.** One delegate client, acting for **one** named principal, over the client-credentials
grant. It does **not** cover a credential that acts for *many* principals — see §0, which is the
reason, not a deferral.

**Order of work.** §0–§2 need no cluster and are where the expensive mistakes are cheap. §3–§4 are
the realm change. §5 needs a running fleet.

---

## §0 — The irreversible-ish thing: `on_behalf_of` MUST BE HARDCODED PER CLIENT

**The temptation is a delegate that can act for anybody, choosing the principal per token
request.** Do not build it. It is not a scaling limitation that got left out; it is the thing this
design exists to refuse.

The chart mints service-client claims with **`oidc-hardcoded-claim-mapper`**
([`keycloak-configmap.yaml:104`](../../helm/invincible-agent/templates/keycloak-configmap.yaml)) —
a **fixed** value, baked into the client. To let a caller vary `on_behalf_of` per request you would
need a mapper that reflects a client-supplied parameter, and at that moment the principal becomes
**a string the caller chose**, signed by the IdP. That is this codebase's named **laundering
shape**, stated at
[`values.yaml:1810`](../../helm/invincible-agent/values.yaml) and
[`register-caller-enumeration.md:19`](../plans/register-caller-enumeration.md): *a subject the
caller names is not an identity, it is a request field*. An IdP signature around it does not
change what it is — it makes it harder to see.

So: **one client per principal.** If you need ten, you create ten, and the tenth is the moment to
ask whether you want token exchange (a different grant, with the principal's own token as input)
rather than a bigger list of hardcoded ones.

**What is already taken.** Four namespaces, all distinct strings — this is why grepping one finds
half the wiring:

| namespace | your candidate | check it |
|---|---|---|
| Keycloak `clientId` | `iagent-<name>-delegate` | `grep -n 'clientId:' helm/invincible-agent/values.yaml` |
| authz id (the gated identity) | `svc:<name>-delegate` | `grep -rn 'svc:<name>' helm/ policy/` |
| secret ref (a key under `keycloak:`) | `<name>DelegateClientSecret` | `grep -n 'ClientSecret' helm/invincible-agent/values.yaml` |
| Topaz subject, if it is ever granted anything | `svc:<name>-delegate` | see §2 — **usually nothing** |

---

## §1 — The fleet side is already done; confirm which claim name it reads

The gateway reads the principal from **one configurable claim**:

```bash
grep -n 'DELEGATE_ON_BEHALF_OF_CLAIM' src/iagent/auth.py
```

`DELEGATE_ON_BEHALF_OF_CLAIM`, default `on_behalf_of`
([`auth.py`](../../src/iagent/auth.py)). **DISCOVERED:** the name and its default are not this
repo's invention — they are read from the SDK's own half
(`iagent_mesh/delegate_identity.py`: `DELEGATE_SUBJECT_CLAIM`, `DELEGATE_ON_BEHALF_OF_CLAIM`), so
that the two ends of one delegation agree. **If you change the env var, change it on both sides**,
or the fleet records `None` while the SDK refuses the same token.

**DISCOVERED — the SDK module is NOT at the pinned sha.** `delegate_identity.py` exists on the
SDK's `lane/ca` at `1f7af84` and in no tag; the fleet pins `8e4a881`
([`pyproject.toml:62`](../../pyproject.toml)). So the fleet-side reader is written natively rather
than importing the SDK helper, deliberately, and they agree by **matching the claim contract**
rather than by sharing code. Do not "simplify" this into an import until the pin moves.

What the gateway does with the claim, and what it will never do:

* records it on `User.on_behalf_of` — audit and trace only;
* **401s** a claim that is present but blank, or present and not a string (a broken mapper is not
  a caller acting for nobody);
* keys **every** authorization decision on `authz_id` — the credential that authenticated.

Sealed by
[`tests/security/test_delegate_credential_is_recorded_and_gated_on_by_nothing.py`](../../tests/security/test_delegate_credential_is_recorded_and_gated_on_by_nothing.py).

---

## §2 — Decide what the delegate is entitled to (usually: nothing)

**The delegate's own `authz_id` is what gates. The principal's entitlements are NOT inherited** —
there is no code path that reads the principal and no plan to add one.

So a delegate that must read entitled data needs **its own** grant, seeded the way every other
subject is (the GROUP path — see the sandbox-entitlement notes; an agent diagnoses, a human
executes the live Topaz write). A delegate that only writes traces or calls ungated endpoints
needs **nothing**, and gets the honest-empty posture: `persona=None`, `entitled_domains=[]`,
`entitlement_source="none"`.

**Do not grant the delegate the union of its principals' entitlements as a convenience.** That
reproduces "acting as" through the back door, at the one layer where it is invisible: the token
would look narrow and the grant would be wide.

---

## §3 — The realm change ⛔ UNRUN

Two edits, both in the chart, because the realm is reconciled from it rather than clicked:

**3.1 — `values.yaml`, under `keycloak.serviceClients`**
([`values.yaml:1804`](../../helm/invincible-agent/values.yaml)):

```yaml
    - clientId: "iagent-reporting-delegate"
      authzId: "svc:reporting-delegate"
      secretRef: "reportingDelegateClientSecret"
      # NEW FIELD — see 3.2. One principal, fixed, per client (§0).
      onBehalfOf: "alice@example.com"
```

**3.2 — the mapper.** ⚠ **The `onBehalfOf` field above does not exist in the chart yet.**
`keycloak-configmap.yaml:101-114` emits exactly one protocol mapper per service client
(`authz-id-svc`) and has no second slot, so this runbook's realm change **requires a chart change
first**: a second `oidc-hardcoded-claim-mapper`, emitted only when `$c.onBehalfOf` is set, with

```json
{
    "name": "on-behalf-of-svc",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-hardcoded-claim-mapper",
    "config": {
        "claim.name": "on_behalf_of",
        "claim.value": "<the principal>",
        "jsonType.label": "String",
        "access.token.claim": "true",
        "id.token.claim": "false",
        "userinfo.token.claim": "false"
    }
}
```

`access.token.claim` is the only one that must be `true` — the gateway reads the **access** token.

⚠ **THE OTHER TWO DIFFER FROM THE SIBLING MAPPER ON PURPOSE, AND THE OBVIOUS WAY TO WRITE THIS
BLOCK GETS THEM WRONG.** `authz-id-svc` directly above it sets `id.token.claim` and
`userinfo.token.claim` to **`"true"`**
([`keycloak-configmap.yaml:111-112`](../../helm/invincible-agent/templates/keycloak-configmap.yaml)).
This one sets both to `"false"`. The difference is the difference between the two values: the authz
id **is** the identity, so carrying it in every token is consistent, while the principal is an
**audit note** — putting it in the id token and the userinfo response is the same value in two more
places that no gate reads and some future code might. So do not produce this mapper by copying the
one above and changing the name and value, which yields a block that disagrees with this page in
two fields and looks right because it matches its neighbour.

The reconcile job iterates the same list
([`realm-reconcile-job.yaml:131,199`](../../helm/invincible-agent/templates/realm-reconcile-job.yaml)),
so **it needs the same treatment or the mapper converges away** — a configmap that declares the
claim and a reconciler that removes it is the worst of the three states, because it works until
the job next runs.

**This chart change is not in this commit.** It is the item to route, and §0's constraint is the
reason it is small: a hardcoded value per client, not a template.

**3.3 — the secret.** `secretRef` names a key under `keycloak:` in the values, resolved by
`get $.Values.keycloak $c.secretRef` (`keycloak-configmap.yaml:99`). Put the real value in the
local, gitignored values file — **never in `values.yaml`**. `secrets.yaml:43` records that
`svc:engine-a` was declared as a client but its secret was verified in the cluster rather than
trusted from this list; do the same.

---

## §4 — DISCOVERED: the authz id lands in the `email` claim

`keycloak.authzClaim: "email"` ([`values.yaml:1776`](../../helm/invincible-agent/values.yaml)), and
the mapper writes `authzId` into whatever that names. So **your delegate's token will carry
`email: "svc:reporting-delegate"`** — a non-mailbox value in the email claim. That is intended and
is how every existing service client works; do not "fix" it by dropping the mapper, which would
make `authz_id` fall back to `sub` (a Keycloak UUID) and silently re-key every grant.

Two consequences worth knowing before you read a trace and disbelieve it:

* `User.email` will be `svc:reporting-delegate`, not an address. The model's comment says email is
  *"never defaulted to a non-mailbox value"* — true of the **code**, which never invents one, and
  not true of the **token**, because the IdP is told to supply exactly that. Filed as a finding
  rather than edited here.
* The **principal's** address (`alice@example.com`) appears only in `on_behalf_of`. A reader
  looking for "who is this for" in `email` will find the delegate and conclude the delegation was
  dropped.

---

## §5 — Verification: ask the authority, by name ⛔ UNRUN

**Never ask a component about itself, and never assert a count.** Four legs, in order:

**5.1 — the realm has the client, with both mappers.** Ask Keycloak, not the configmap:

```bash
# The configmap is what you INTENDED. The realm is what is true.
kubectl -n <ns> exec deploy/keycloak -- \
  /opt/keycloak/bin/kcadm.sh get clients -q clientId=iagent-reporting-delegate \
  --fields id,clientId,serviceAccountsEnabled
```

Expected **by name**: one client, `serviceAccountsEnabled: true`, `standardFlowEnabled` absent or
false. Then fetch its `protocol-mappers/models` and assert **both** `authz-id-svc` **and**
`on-behalf-of-svc` are present with the expected `claim.value`s. *Two mappers where you expect two*
— a count of one tells you which edit landed only if you read the names.

**5.2 — the token actually carries the claim.** Mint one and **decode it**. The claim being in the
realm is not the claim being in the token: `access.token.claim` decides that, and it is the field
most likely to be wrong on the first run.

This leg is not invented here — **it is the fleet's existing decode-witness rail**, and it is
already open: [`enable-agentic-auth-flip-packet.md:5`](../plans/enable-agentic-auth-flip-packet.md)
records eleven service clients remediated but **UNWITNESSED**, with two decode-witnesses still
outstanding by name (`svc:engine-a`, `svc:review-starter`). So a new delegate client that is
declared and never decoded joins a queue of clients whose claims nobody has seen, which is exactly
the state that packet exists to close. **Add the witness when you add the client**, and record it
where the other witnesses are recorded rather than in this page.

**5.3 — the gateway records it and gates on the delegate.** Call an endpoint that echoes identity.
Expected: the delegate's `svc:` id in every authorization-relevant field, the principal **only**
in `on_behalf_of`.

**5.4 — the negative leg, which is the one that matters.** Grant the **principal** an entitlement
the **delegate** does not have, and call an endpoint gated on it with the delegate's token.
**Expected: DENIED.** If it succeeds, the delegation is being honoured as authorization somewhere
and this whole design is not in force — and note that legs 5.1–5.3 would all still be green.

**PASTE, DO NOT RETRY.** A blind second run cannot distinguish "transient" from "the thing is
wrong", and it destroys the first run's evidence.

---

## §6 — Errors and constraints hit while writing this

| what happened | the general lesson |
|---|---|
| The SDK helper for exactly this (`delegate_initiator_from_token`) turned out **not to exist at the pinned sha** — it is on a lane branch, in no tag. A lookup reported it as available because it read the SDK's **working tree**. | **A dependency's capability is a property of the PINNED SHA, not the checkout next door.** Ask `git show <sha>:<path>`, never `ls`. |
| The chart emits exactly **one** mapper per service client, so "write the exact realm change" turned out to need a **chart change first**. The runbook could not be honestly written as realm-only. | A runbook that cannot be executed with the current templates has found a **missing chart affordance**, not a documentation gap. Say which, and stop. |
| `authzId` lands in the **`email`** claim, so a service token's email is `svc:...`. | A model comment can be true about the code and false about the system: *"never defaulted"* describes what the code does, while the IdP supplies the value the comment promises cannot appear. |
| The obvious design — let the caller pass the principal — is the fleet's already-named laundering shape. | When a design feels blocked by a constraint, check whether the constraint **is** the design. |
| My own seal's first control mutant was a **no-op** (`return {} or {...}` returns the dict — `{}` is falsy), so an "arm does not fire" reading was about the mutant. | **A mutation that will not die implicates the mutant before the arm.** Re-derive the mutation, then conclude. |

---

## Appendix — the complete change list

**In this commit (fleet side, no cluster):**

1. `src/iagent/auth.py` — `DELEGATE_ON_BEHALF_OF_CLAIM`; `User.on_behalf_of`;
   `resolve_on_behalf_of()`; read inside the identity `try` so a bad mapper shares the 401 path.
2. `tests/security/test_delegate_credential_is_recorded_and_gated_on_by_nothing.py` — the seal.
3. this page, and its row in [`README.md`](README.md).

**NOT in this commit — the named gaps, so the next person plans around them rather than
rediscovering them:**

4. `helm/.../keycloak-configmap.yaml` + `realm-reconcile-job.yaml` — the second mapper (§3.2).
   **Both, or the reconciler converges the claim away.**
5. `values.yaml` — the `serviceClients` entry and its `onBehalfOf` field (§3.1).
6. The client itself and its secret — **a live realm write, which is Chris's.**
7. A run of §5, especially **5.4**. Until 5.4 has been seen to DENY, "gates on nothing from it" is
   sealed at the unit boundary and unproven end to end.
