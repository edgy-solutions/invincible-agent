---
id:         work-deploy
status:     blocked-on-human
owner:      human
blocked-on: your go — nothing technical
closed-by:
repo:       invincible-agent
summary:    Deploy to the work cluster in OBSERVE, behind three reads. Not gated on further build work.
---

# Work deploy — OBSERVE, behind three reads

Sandbox rehearsal is complete: six identities minting, gauge witnessed clean at a fresh log
boundary, transport auth applied fleet-wide in OBSERVE. **This item is blocked on a decision,
not on engineering** — which is why it is separated from `transport-flip`, whose blocker is
genuinely downstream. Marking both "blocked-on-human" alike hid which one was ready.

## The three reads

1. **Deploy in OBSERVE.** Safe by construction — unminted callers are logged, never refused, so
   comms and data fetches work regardless of migration state. OBSERVE was designed precisely so
   deploys never wait on the migration.
2. **`scripts/env_audit.py` against the work-rendered chart.** Runnable only once deploying with
   the work values in hand — which is why it could not be a pre-flight read. It caught
   `svc:engine-a` declared-but-unwired in sandbox, and the work values file is a different file.
3. **Work-Keycloak `USER_ENTITLEMENT_CLAIM` decode, BEFORE trusting DA fetches.** Sandbox
   resolves `email`; work uses employee-id. A null subject means fetches that **succeed while
   scoping to nobody** — a data-correctness failure independent of the transport flip, which is
   why this gate sits before the DA path rather than before the flip.

## FOURTH PRECONDITION — capability grants must be seeded, or reviews refuse

**Added 2026-08-10 after a grep found this packet mentioned grants ZERO times.** It is a
deploy-day break, in a packet about to be executed.

`policy/capability_grants.yaml` grants `can_invoke` on `mesh:startReview` to
`svc:review-starter`. Verified present in-repo and load-bearing:

- the grant file exists and names the verb (`policy/capability_grants.yaml:63`)
- the refusal is real: `review_starter.py:412` returns
  `{"status": "NOT_ENTITLED_TO_INITIATE", ...}`

**If that grant is not seeded in the work cluster's Topaz, every auto-started review refuses
with `NOT_ENTITLED_TO_INITIATE`.** Not an outage — a *refusal*, which is worse to diagnose
because the system is behaving exactly as designed and the deny is correct given the directory
it can see.

### Whose act this is

Seeding a capability grant is a **directory mutation**, so it serializes through the human under
the standing rule — the agent diagnoses and prepares, the human executes. This packet records
the precondition; it does not authorise the write.

### The check, before trusting auto-started reviews

Confirm `svc:review-starter` holds `can_invoke(mesh:startReview)` in the work Topaz — the same
readback shape the realm-reconcile job uses. A review that refuses on day one and a review that
was never triggered look identical from the outside.

## Scoping caution

Sandbox green proves the wiring **against sandbox Keycloak**. It says nothing about the work
realm's claim shape or the work values file's wiring. Two greens, neither implying the other,
both run against real work state because neither can be faked earlier.

## Do not

Flip `REQUIRE_TRANSPORT_AUTH` — that is downstream of this item. See
`enable-agentic-auth-flip-packet.md`.
