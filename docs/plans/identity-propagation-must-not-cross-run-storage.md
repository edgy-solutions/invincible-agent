---
id:         identity-propagation-must-not-cross-run-storage
status:     open
owner:      unassigned
blocked-on: a Keycloak realm decision — may a service client impersonate a user, and scoped to which target?
closed-by:  
code-site:  src/iagent/defs/dynamic_supervisor.py:948, agent_fleet/utils/service_identity.py:54, src/iagent/gateway.py (canvas_seed)
repo:       invincible-agent
summary:    THE OBVIOUS FIX IS A CREDENTIAL DISCLOSURE, and it works on the first try. Dispatch discards the caller's identity, so the seeding phrase ran as svc:supervisor and was correctly refused 403 cell_not_entitled x5 — the first live casualty of sdk-discards-caller-identity. The natural repair is to thread the user's JWT through the Dagster run config; MEASURED, that config is 2306 chars of durable Postgres readable over GraphQL and rendered in the Dagster UI, so the repair writes a live bearer credential into browsable storage for a defense-adjacent customer. A 403 is a contained authorization gap; a credential at rest is a disclosure. What travels must be an ASSERTION, not a CREDENTIAL. Keycloak 26.6.4 runs standard RFC 8693 exchange (requested_subject REJECTED, tested); delegation works but needs the user's token as input; legacy impersonation would be clean but is not enabled — so the owner is a realm decision, not the supervisor or SDK lanes.
---

# Naive identity propagation through Dagster run config is a credential disclosure

**Filed 2026-08-28 by Lane 2, from a live failure.** The obvious fix works, and shipping it
would write live user credentials into browsable durable storage. **Read this before
implementing dispatch identity propagation** — the naive version is the natural one, it
functions, and every signal says it landed.

## The failure that got here

The seeding phrase routed correctly and returned **0 of 5**. All five inner asks were refused:

    subject_email: 'svc:supervisor'
    requested: {persona: PORTFOLIO_LEAD, domains: [PORTFOLIO_PLANNING]}
    entitled_cells: []   entitlement_source: 'none'
    -> 403 cell_not_entitled  x5

`/canvas/seed` forwards its caller's `Authorization` header. Under the BUTTON path the caller is
the browser, so it forwards alice's token and works (measured 5/5, 17.2 min, twice). Under the
PHRASE path the caller is the supervisor, which dispatches with `mint_supervisor_token()` — a
service identity holding zero entitlement cells.

**The 403 is the system refusing an escalation that was accidentally requested.** A service
identity could not borrow a user's entitlements by proxy. This is the confused-deputy case, and
the entitlement layer caught it.

This is the first live casualty of `sdk-discards-caller-identity`: the caller's identity dies at
dispatch, and the seed is the first capability that needed it to survive.

## THE STOP: what the obvious fix would do

**Ruled direction (correct):** dispatch propagates the original caller's identity; downstream
authorizes against the user, not the intermediary.

**Naive implementation:** thread the user's JWT into the Dagster run config, supervisor forwards
it. It would work on the first try.

**Measured, not assumed** — a completed run's config pulled over the Dagster GraphQL API:

    runsOrError(...) { runConfigYaml }
    -> 2306 chars, persisted in Postgres, contains user_email
    -> rendered in the Dagster UI, readable by anyone who can reach the webserver

So the naive fix writes **a live bearer credential into durable, browsable storage** for a
defense-adjacent customer.

> **A 403 is a contained authorization gap. A credential in run storage is a disclosure.**
> The trade is strictly worse than the defect it repairs.

**What travels must be an ASSERTION, not a CREDENTIAL.** That is the whole design constraint, and
it is what separates the correct fix from the obvious one.

## Which mechanisms are actually available — measured 2026-08-28

Keycloak **26.6.4**, launched `start-dev` with **no `--features` flags**.

| mechanism | available? | why it does / does not solve this |
|---|---|---|
| `requested_subject` impersonation | **NO** | Legacy exchange feature, not enabled. Tested: `400 invalid_request — Parameter 'requested_subject' is not supported for standard token exchange` |
| RFC 8693 **delegation** (`subject_token` + `actor_token`) | **YES**, default in 26.x | Produces subject=alice with an **`act`** claim naming the supervisor — exactly the audit shape wanted. **But it needs alice's token as INPUT**, so the BFF must exchange at launch and put the *delegated* token in run config. Shorter-lived and scoped, still a bearer credential in browsable storage. |
| Legacy exchange (`--features=token-exchange`) | not enabled | Would mint act-as-alice from the supervisor's OWN credentials plus a subject identifier — **no user credential anywhere**. The clean version. Cost: an impersonation capability granted to a service client. |

**The supervisor's client is `iagent-supervisor`** (client-credentials via
`agent_fleet/utils/service_identity.py:mint_supervisor_token`).

## So the owner is neither lane that has been working on this

Not supervisor-plumbing, not the SDK. **It is a Keycloak realm decision:** may a service client
impersonate a user, and if so, scoped to which target?

* If **yes** → enable the legacy exchange feature, scope the exchange permission to
  `iagent-supervisor` alone, and the mint call gains a subject parameter. Small change, real
  security weight, correct outcome: nothing long-lived lands anywhere and the supervisor becomes
  what it always claimed to be — a router that acts on behalf of, never a principal.
* If **no** → the delegation path is the fallback, and it needs a separate ruling on whether a
  short-lived scoped token in run config is acceptable. It is materially better than a user's own
  token and it is still a credential at rest.

**Not attempted here:** enabling the feature to see whether it works. It is a security-relevant
change to shared infrastructure, and "impersonation was enabled to test a canvas" is not a
defensible entry in this log.

## Rider for whoever builds it

The on-behalf-of token must be **distinguishable from a user's own token in the audit trail**.
"alice did this" and "the supervisor did this for alice" are different provenance facts, and the
DecisionArtifact ancestry this platform sells depends on recording which one happened. RFC 8693's
**`act`** claim carries exactly that; whichever mechanism is chosen must mirror it.

**And do not hand-roll it.** A local on-behalf-of token minted outside the identity authority is
the forgeable-actor shape wearing better clothes — the same defect the commit route closed with
*a field that cannot be sent cannot be spoofed*. The actor must be a claim the minting authority
asserts, never a value a caller supplies.

## Also worth keeping: the two things that went right

**The partial-seed refusal paid for itself on its first live failure.** 0 of 5 succeeded, the
refusal branch returned `artifact_ids: []`, and the card said *"0 out of 5 total assets were
seeded… No portfolio canvas artifacts were created."* Had it compacted, the result would have
been an empty-but-plausible canvas and a much longer diagnosis. The honest failure is the reason
this was one message of work.

**The security model held.** The escalation was refused by the layer designed to refuse it,
before it could do anything, and the denial named the subject, the requested cell, and the empty
entitlement set — enough to diagnose without a second run.

## Cross-references

* `sdk-discards-caller-identity` — this is its first live casualty and constrains its
  implementation
* `da-sends-no-user-token` — same architecture arriving from another direction; Engine DA's
  manual `user_email` threading is the workaround this would retire
* The seed's own plan item — the phrase path waits on this; the **button path is whole**
  (5/5, verified twice) and the demo's seeding beat is intact triggered from the UI
