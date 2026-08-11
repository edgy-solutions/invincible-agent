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
3. **Work-Keycloak `USER_ENTITLEMENT_CLAIM` decode — VERIFIED GREEN 2026-08-10.**
   A real work user's token was decoded against the claim the chart names, and the value
   **matched that user's id in the overlay's `users.yaml`**. This was the one precondition
   sandbox structurally could not rehearse, and it is now measured rather than assumed.
   Original statement of the risk, kept because it is why the read was run: Sandbox
   resolves `email`; work uses employee-id. A null subject means fetches that **succeed while
   scoping to nobody** — a data-correctness failure independent of the transport flip, which is
   why this gate sits before the DA path rather than before the flip.

## RETRACTED — steps 2 and 4 as originally written

**`env_audit.py` is NOT run at work.** Its per-input sentinels are hardcoded to sandbox's three
values files, so against a work render it either refuses on a good render or passes without
verifying the work overlay reached it — the exact defect the sentinels exist to prevent, wearing
the tool's own name. And its purpose is finding hand-seeded state; this cluster's policy plane is
git-managed and reconciled every 10 minutes by the topaz-seed CronJob, which is the strongest
available answer to "is this hand-seeded?". Wrong tool for this cluster in its current form.

**The manual validator run was redundant.** `topaz-seed-cronjob.yaml:249` runs
`validate_policy.py` BEFORE any write and line 287 runs `capability_grant_sync.py`. The step was
prescribed without reading the seeding path it was prescribed against.

## FOURTH PRECONDITION — capability grants (ALREADY SATISFIED, kept as a failure mode)

**Not a gap. Reviews already work at work**, and `review_starter.py:412` returns
`NOT_ENTITLED_TO_INITIATE` when the capability check fails — so a working review IS the evidence
that `svc:review-starter` holds `can_invoke(mesh:startReview)`. That direct observation outranks
the inference below, which was reasoned forward from a README file-list omission.

Kept because it names a real failure MODE and where to look if reviews ever start refusing:

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

## A FIFTH read, added 2026-08-10 — which identity a notebook session carries

**Jupyter is at work, so this is only answerable there — and analysts open notebooks.**

The claim-shape is the one already run for `USER_ENTITLEMENT_CLAIM`, pointed one seam further out:
*not* "is the decode green" but **"whose identity reaches Topaz when a human reads data?"**

What the code side already settles (`dag-tools`, read 2026-08-10) — `CortexDataClient` resolves
its credential in this order:

1. `jwt_token=` constructor arg → bearer
2. else `MESH_DEV_TOKEN` env → bearer
3. else `CORTEX_CLIENT_ID`/`_SECRET` → M2M service-account token → bearer
4. else `ValueError`

**There is no user-token path distinct from step 1**, and nothing in the client logs which branch
it took. The Dagster IO manager (`cortex_io_manager.py:147`) constructs it with *only* the M2M
credentials.

Worse, the *subject* is not carried by the token at all: the gateway prefers the
`X-Originator-Email` **header** over any token claim, and never verifies the bearer's signature —
see `[[dag-tools-gateway-unverified-subject]]`. So "which identity a session carries" is currently
**whatever the session asserts**.

**The read to run at work:** does JupyterHub's OIDC access token reach the single-user
environment, and does `CortexDataClient` receive it as `jwt_token`? The answer decides whether
work data access is **per-user or per-service** — and a per-service answer gives every analyst the
service's entitlements, which is `[[select-from-authorized-set]]`'s confused deputy on the data
plane.

Target design and its configuration: `docs/plans/jupyter-user-token-data-access.md`.

**Not a blocker for OBSERVE**, which is why it is a fifth read and not a fourth precondition. It
*is* a blocker for telling an analyst their notebook sees only their data.

## Do not

Flip `REQUIRE_TRANSPORT_AUTH` — that is downstream of this item. See
`enable-agentic-auth-flip-packet.md`.
