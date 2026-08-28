---
id:         identity-propagation-must-not-cross-run-storage
status:     open
owner:      supervisor + BFF lanes (no longer a realm decision — see THE RULED DESIGN)
blocked-on: nothing. Design ruled 2026-08-28; implementation is supervisor-plus-BFF work, sized small.
closed-by:  
code-site:  src/iagent/defs/dynamic_supervisor.py:948, agent_fleet/utils/service_identity.py:54, src/iagent/gateway.py (canvas_seed)
repo:       invincible-agent
summary:    THE OBVIOUS FIX IS A CREDENTIAL DISCLOSURE, and it works on the first try. Dispatch discards the caller's identity, so the seeding phrase ran as svc:supervisor and was correctly refused 403 cell_not_entitled x5 — the first live casualty of sdk-discards-caller-identity. The natural repair is to thread the user's JWT through the Dagster run config; MEASURED, that config is 2306 chars of durable Postgres readable over GraphQL and rendered in the Dagster UI, so the repair writes a live bearer credential into browsable storage for a defense-adjacent customer. A 403 is a contained authorization gap; a credential at rest is a disclosure. What travels must be an ASSERTION, not a CREDENTIAL. RULED 2026-08-28 — THE REFERENCE VAULT: run config carries only the run_id it already carried, and the supervisor redeems alice's own Ping-rooted token from the BFF over a live in-cluster hop at dispatch (reach verified, 200). No new credential, no realm permission, no federation question. Six invariants pinned below; legacy impersonation is RULED OUT PERMANENTLY on the federation argument.
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
| Legacy exchange (`--features=token-exchange`) | not enabled — **RULED OUT PERMANENTLY 2026-08-28** | Would mint act-as-alice from the supervisor's OWN credentials plus a subject identifier. Looked like the clean version; it is not. See *Ruled out permanently* below — the federation argument closes it, not the feature flag. |
| **Reference vault** (run config carries `run_id`; supervisor redeems alice's own token from the BFF at dispatch) | **YES — no identity-system change at all** | **THE RULED DESIGN.** Redeems the ORIGINAL Ping-rooted token rather than minting a new one. No realm permission, no exchange, no federation question. Requires only that the supervisor can reach the BFF at dispatch time — **verified**, `iagent-cortex-bff:8090` → 200 from the user-code pod. |

**The supervisor's client is `iagent-supervisor`** (client-credentials via
`agent_fleet/utils/service_identity.py:mint_supervisor_token`).

## First, the structural fact that eliminates most of the design space

**The supervisor is not a proxy in alice's request. It is a job launched by it.**

The BFF launches the supervisor through a Dagster **`launchRun` GraphQL mutation**, whose only
inbound channel is `runConfigData`. The run then executes asynchronously in the user-code pod;
the BFF streams step stats afterwards but holds no synchronous connection to the dispatch hop.
There is a genuine process boundary between alice's HTTP request and the eventual
`requests.post(endpoint, ...)`, and **the only channel across that boundary is persisted config.**

Two consequences, and they close off almost everything:

* **Every design that "just forwards the header" is fantasy.** Forwarding on a live hop is exactly
  right as a principle — it is what the BUTTON path does — but there is no live hop here to
  forward on.
* **Every design that puts a token in run config is a disclosure**, by the measurement above.

What is left is a design that crosses the boundary with something that is *not* a credential, and
then obtains the credential on a hop that *is* live. That is the vault.

**The plumbing was checked, not inferred.** The user-code pod has
`IAGENT_CORTEX_BFF_PORT_8090_TCP_PORT=8090` and reaches `iagent-cortex-bff:8090` with a **200**.
The supervisor cannot receive alice's token at launch, but it *can* ask for it at dispatch.

## THE RULED DESIGN: the reference vault

**Ruled 2026-08-28.** Run config carries a **reference**, never a credential. The reference is the
**`run_id`** — which run config *already carries*, and which was *never secret*. At dispatch the
supervisor redeems that reference from the BFF over the live in-cluster hop and receives alice's
own token, which it then forwards exactly as the browser does on the button path.

    BFF (alice's request)        holds alice's token in memory, keyed by run_id
        -> launchRun(run_id)     run config carries the run_id it already carried
    supervisor (async, later)    POST /internal/identity/redeem  {run_id}   [live hop, verified 200]
        <- alice's token         short-TTL, single-use, redeem-and-delete
        -> POST /canvas/seed     Authorization: Bearer <alice>   == the button path

**Why this dominates RFC 8693 delegation** (the fallback it replaces): delegation still **mints a
new credential** and still needs a realm permission and an exchange round-trip. The vault
**redeems the original Ping-rooted token**. Alice's own token authorizes — precisely as the button
path proves it should, since the button path is whole at 5/5 twice. No new credential exists to
scope, expire, or audit separately.

**And it satisfies the rule literally.** *What travels must be an assertion, not a credential* —
what travels is a `run_id`, which is not even an assertion about identity, merely a pointer. The
durable store gains nothing it did not already hold.

**This is a credential-dispensing surface**, and that is not free. The following are **invariants,
not suggestions.** A build that omits any one of them has reverted to the thing this replaced.

1. **Locked to the supervisor's service identity.** The redemption endpoint authenticates its
   caller as **`svc:supervisor` specifically** — not "any authenticated service." A second service
   redeeming a reference is the vault leaking sideways, and generic service auth would permit it.

2. **Single-use, enforced atomically.** Redeem-and-delete in **one operation**, so a replayed
   redemption finds nothing. Two redemptions of one reference is the tell of a compromised
   supervisor identity; it must **fail loudly**, never succeed quietly twice. (A read followed by a
   separate delete is not this invariant — it is a race that satisfies it only most of the time.)

3. **TTL bounded to the dispatch window.** The reference outlives its run's launch by **minutes,
   not the token's own lifetime**. An unredeemed reference expiring is the safe default. A
   reference valid for hours is a stored credential with extra steps.

4. **Launcher-match refusal.** The redeeming run's `run_id` must be the reference's key **and** the
   run's recorded launcher must match the token's subject. A reference redeemed for a run alice did
   not launch is the mismatch that refuses.

5. **The vault is memory, not storage.** An in-process map in the BFF, TTL-evicted. **The moment it
   is Redis or Postgres, a credential is durable again** and the design has quietly reverted to the
   thing it replaced. If a BFF restart orphans in-flight seeds, that is the honest cost — a failed
   redemption fails the seed **loudly** and the user re-asks. Same trade as engine-p's in-memory
   scenario store, and it earns the same B4a-shaped runbook note: *restarting the BFF kills
   in-flight seeds.*

6. **Redemption is audited.** One log line per redemption: `run_id`, subject, timestamp, outcome.
   The vault's whole legitimacy is that the token's journey is **visible**; an unlogged dispensing
   surface is worse than the exchange it replaced.

### Scope boundary — state it here so scope cannot creep

**The vault is for the launch-to-dispatch hop only.** It is not a general token store, not a
session cache, and **not the SDK's caller-identity answer**. `sdk-discards-caller-identity` remains
its own item with its own fix — injecting `CallerIdentity` into handlers — and the vault does not
substitute for it. **The moment someone proposes putting a second kind of token in the vault, this
paragraph is the refusal.**

## Ruled out permanently: legacy exchange / impersonation

**Not "not enabled." Ruled out.** Enabling `--features=token-exchange` would let the supervisor
mint act-as-alice from its own credentials — mechanically clean, and the reason it is refused has
nothing to do with mechanics:

> **Keycloak would be minting act-as-alice on its own authority for an identity that Ping owns**,
> with the corporate IdP never participating and never logging it. That is an end-run around the
> enterprise identity authority.

That fails review **categorically, not negotiably**, at the site where review is unforgiving. It is
written down here specifically so it cannot be re-proposed in six months when the flag looks
convenient: the objection is not "we did not turn it on," it is *federation does not permit a
downstream broker to impersonate an upstream-owned identity.* The vault needs no such capability,
which is the second reason it dominates.

## Era rider: work's Keycloak is a different era

Every exchange behaviour measured above — `requested_subject` rejected, standard RFC 8693 default,
the feature-flag surface — was measured against **sandbox's Keycloak 26.6.4**. Work runs a
different build (**2.6.3.0**). **Those are sandbox facts until re-verified at work.**

This is the `LLM_BASE_URL` law applied to identity infrastructure: *verified* means *verified in
the era I measured*, and a configuration read that is true in one era is a description, not a
guarantee. The vault is the design least exposed to this rider — it uses no exchange endpoint at
all — but any fallback that reaches for RFC 8693 must **re-run the probe at work before it is
believed.**

## Rider for whoever builds it

The on-behalf-of token must be **distinguishable from a user's own token in the audit trail**.
"alice did this" and "the supervisor did this for alice" are different provenance facts, and the
DecisionArtifact ancestry this platform sells depends on recording which one happened. RFC 8693's
**`act`** claim carries exactly that; whichever mechanism is chosen must mirror it.

**And do not hand-roll it.** A local on-behalf-of token minted outside the identity authority is
the forgeable-actor shape wearing better clothes — the same defect the commit route closed with
*a field that cannot be sent cannot be spoofed*. The actor must be a claim the minting authority
asserts, never a value a caller supplies.

### Reconciling this rider with the vault — the one place delegation WAS better

**State the cost plainly: the vault has no `act` claim, by construction.** It forwards alice's own
token, so downstream sees `sub=alice` and nothing distinguishes *"alice clicked the button"* from
*"alice said a phrase and the supervisor dispatched on her behalf."* RFC 8693 delegation would have
produced that distinction for free. This is the single dimension on which the ruled-out fallback
was the stronger design, and it is recorded here rather than argued away.

**It does not reverse the ruling**, because the rider's real requirement is that the provenance be
**recorded by an authority the caller cannot forge** — not specifically that it live in a JWT claim.
Under the vault it lives in two places the caller never touches:

* **The vault's own audit line (invariant 6)** — `run_id`, subject, timestamp, outcome, written by
  the BFF at redemption. That is the authoritative record that a dispatch, not a click, obtained
  this token.
* **The run itself** — the Dagster run exists, carries the phrase, and is durable. A button click
  produces no such run. The two provenance facts are already distinguishable in storage.

**What this obligates the builder to do:** the DecisionArtifact ancestry must read the *trigger*
from the run, not infer it from the token's subject. **If provenance is derived from the JWT alone,
the vault silently records a phrase-path seed as a button-path seed** — a wrong provenance fact
written confidently, which is the failure mode this platform sells against. Cross-check the
redemption log and the DecisionArtifact agree on which path fired, and treat a disagreement as a
defect in the artifact, not in the log.

**The hand-roll prohibition still binds in full.** The vault must never *mint* anything. It stores
and returns a token some other authority issued; the moment it constructs a token, or an actor
field, or an identity assertion of its own, it has become the forgeable-actor shape and invariant 5
has stopped being the only thing holding the design together.

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
