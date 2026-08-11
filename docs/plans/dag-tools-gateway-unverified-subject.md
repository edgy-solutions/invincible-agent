---
id:         dag-tools-gateway-unverified-subject
status:     open
owner:      agent
blocked-on: THE READING — the OBSERVE gauge is built and wired (2026-08-11); it must run on the live gateway and be counted before step 2 is scoped. Verification/header-override work waits on that number.
closed-by:  
code-site:  dag_tools/central_gateway/main.py
repo:       dag-tools
summary:    HIGH — the DA data gateway never verifies a bearer and takes its authz subject from a request HEADER, so per-user scoping is advisory. THE DELIVERABLE IS THE SUBJECT-SOURCE GAUGE — how many live requests ASSERT a subject vs PROVE one. Verification is the easy part; the gauge decides whether killing the header override is a config change or a coordinated migration.
---

# The data-plane gateway's authz subject is caller-asserted, and its bearer is never verified

**Found 2026-08-10** while answering a design question — *how does a notebook user's identity
reach the data plane?* — not while looking for a vulnerability. The answer is that it does not
have to.

## FIRST — WHICH GATEWAY. Two components are now both called "the gateway"

**This finding is about `dag-tools/central_gateway`, on the DA data path. It is NOT about the
platform's cortex-bff gateway, and it does not contradict that component's verification witness.**

| | **cortex-bff gateway** | **dag-tools `central_gateway`** |
|---|---|---|
| repo / path | `invincible-agent` — `src/iagent/gateway.py` | `dag-tools` — `dag_tools/central_gateway/main.py` |
| plane | control / agentic | **DA data path** |
| verifies bearers? | **YES** — RS256 pinned, JWKS live | **NO** — `verify_signature: False` |
| witnessed? | yes, this month — forged-token pair: attacker-signed → 401, known-key → identity resolves | n/a — nothing to witness |

**Read without this table, the finding looks like a retraction of the forged-token witness. It is
not.** That witness stands, on the component it was run against.

The two are in fact the **two ends of one seam**: this is the *receiving* end of the DA
impersonation path whose *sending* end lock 2 already closed. Closing a sending end and leaving
the receiving end asserting-is-believing is a coherent state to arrive at and an incoherent one to
stay in — which is the argument for this item, and it is a stronger argument than "a gateway is
unverified" would have been.

**Whenever this finding is cited, cite the path, not the word "gateway."**

## The premise this corrects

The transparent-Jupyter design was being scoped on this sentence:

> *CortexDataClient reads that, sends it as the bearer, and **the gateway's existing verification
> does the rest**: same JWKS check, same `USER_ENTITLEMENT_CLAIM`, same Topaz scoping as a UI
> session.*

**There is no existing verification.** Not a weaker one — none. Passing the user's token would be
necessary and *not sufficient*, and building on the sentence as written would have produced a
design that looks per-user and is not.

## What is actually true — read 2026-08-10

Four facts, each a single line of the file.

| # | fact | site |
|---|---|---|
| 1 | app has **no middleware and no global dependencies** — `FastAPI(lifespan=lifespan, title="Central Gateway")` | `main.py:55` |
| 2 | `security = HTTPBearer()` — validates the header's **form**, never the token | `main.py:56` |
| 3 | `jwt.decode(token, options={"verify_signature": False})` — **both** decode sites | `main.py:110`, `:269` |
| 4 | `subject_key = (originator_email or "").strip() or unverified_claims.get("email")` — the **header wins** over the token's own claim | `main.py:121` |

There is no `PyJWKClient`, no `algorithms=`, no `audience=`, no `issuer=`, and **no auth module
anywhere in `dag_tools/`**. The lone import is `import jwt  # For basic decoding of the Keycloak
JWT` — and "basic decoding" is exactly and only what it does.

### Three consequences, in severity order

1. **The bearer is never authenticated.** Any well-formed JWT is accepted, including one the
   caller minted themselves with no signing key. `HTTPBearer` requires the header to *exist*.
2. **The authz subject is a request header.** `X-Originator-Email` is read straight off the
   request (`main.py:259`) and **preferred over** the token's `email` claim. So a caller sends
   `X-Originator-Email: <anyone>` and Topaz decides for that person — masking, row filters and
   all, correctly applied to a subject the caller chose.
3. **The deny-list is bypassable in one move.** `effective_sub = originator_sub or token_sub`
   (`main.py:273`) — omit `X-Originator-Sub`, forge a token with a sub that is not on the list.

**Net: per-user data scoping on the data plane is advisory.** Any caller who can reach the gateway
can read any user's slice.

## The pattern is right; its precondition is missing

This is not sloppiness, and the code says so. The `X-Originator-Email` design was deliberate and
it *fixed a real bug* — the comment at `main.py:112-120` records that reading email off the token
denied everyone, because the token is a service-account M2M JWT with no user email
(`broken-closed: allow-path never functioned`).

**On-behalf-of is a sound pattern.** It has one precondition: *the delegating caller must be
authenticated, and authorized to delegate.* Neither happens here. The gateway trusts the assertion
without ever establishing who is asserting.

That is the same shape as the SDK finding filed the same evening — the seam is built, the binding
that makes it mean anything is absent. Here the unbound half is the authentication the delegation
depends on.

## Why this surfaced now and not during the DA-read seal

The seal proved the gate **bites** — that a denied user is denied. It could not prove the gate
binds the *right subject*, because a correct-looking allow and a caller-asserted allow are
identical from outside. `[[seals-must-be-proven-to-bite]]` covers the deny direction; nothing
covered *whose* deny it was.

## What this does NOT say

* **Not an entitlement escalation past Topaz.** Topaz still decides, and its answer for the
  asserted subject is honoured, masking included. The defect is *which subject it is asked about*.
* **Not externally reachable today.** `centralGateway.ingress.enabled` defaults to `false`, so it
  is in-cluster only — the same mitigation as `approval-bypass-bpmn-runner` and
  `dag-tools-broker-register-unauthenticated`, carrying the same caveat: **it does not travel to
  the work cluster**.
* **Not a `transport-flip` blocker.** dag-tools binds no transport auth at all; the flip neither
  fixes nor worsens this.

## THE DELIVERABLE IS THE SUBJECT-SOURCE GAUGE — read this before scoping the work

**Whoever builds this should know the verification is the easy part.** Pinning JWKS is a known
quantity. The thing this item exists to produce is a number nobody currently has:

> **How many live requests ASSERT a subject (via `X-Originator-Email`) versus PROVE one (via a
> verified token claim)?**

That number decides whether stopping the header override is a **config change** or a **coordinated
migration** — and there is no way to know which without measuring first. Build the gauge, read it,
*then* choose the shape of step 2.

### Why this gauge is not the transport-auth gauge repeated

The transport migration's gauge measured **whether callers minted** — a yes/no per caller,
answering *is a credential present*. This one measures **how identity arrives**, which is strictly
richer: a request can carry a perfectly valid credential and still name its subject in a header
that overrides it. **The earlier work has no analogue for that**, so nothing here can be inferred
from the transport gauge's shape or its numbers.

That is also why the gauge outranks the fix in this packet: the transport arc could scope its
remediation from a census it already had, and this one cannot.

## Remediation shape — RULED 2026-08-11

> **Build it as verify-if-present with posture logging first. Never a direct flip.**

**The blast radius is why, and it is not the severity.** Every caller today arrives with a
self-minted token and an asserted header — turning verification on refuses *all of them at once*.
Same migration shape as transport auth, same treatment: verify what arrives, log the posture **and
the subject-source** per request, **refuse nothing**, then read who would break before anything
starts breaking.

**Ordering:** OBSERVE → read the subject-source gauge → decide the migration's shape → REQUIRE. A
direct flip would refuse the DA data path wholesale, and that path is live at work.

Three things, and the first two are not optional if the notebook design proceeds:

1. **Verify the bearer** — JWKS against Keycloak, with `algorithms`, `audience` and `issuer`
   pinned. This is the missing precondition, not an enhancement.
2. **Stop preferring the header over the token.** `X-Originator-Email` may only be honoured when
   the *verified* caller holds an explicit delegation capability; otherwise the subject is the
   token's own entitlement claim. A user-token session must never be overridable by a header.
3. **Announce the subject on the allow path.** Today only denials name a subject
   (`TOPAZ AUTHZ DENIED`, `AUTHZ_DENIED`); an allow logs nothing about *who*. A data plane that
   records only its refusals cannot answer "who read this."

## THE GAUGE IS BUILT — 2026-08-11, OBSERVE only

`dag_tools/central_gateway/subject_gauge.py`, wired at two points in `main.py`: `announce()` in
the lifespan, `observe()` in `authorize_asset` on the same two inputs the gate itself uses.

**Behaviourally inert by construction.** No refusal, no altered subject, no header removed, no
REQUIRE path — the module contains none. The call site discards the return value and is wrapped
in a blanket `except`, because **measuring must never be able to break the thing being measured**;
a gauge defect degrades to a warning and the request proceeds exactly as it does today.

### The buckets it emits

```
subject-source: source=header-only       agreement=-          token_verified=False token_reason=no-verification-key …
subject-source: source=header-override   agreement=agreeing   …
subject-source: source=header-override   agreement=divergent  …
SUBJECT-SOURCE DIVERGENT: header names 'bob@…', token claims 'alice@…', token_verified=False —
  removing the X-Originator-Email override would change this request's subject. urn=…
```

**The agree/diverge split is the deliverable, not a refinement.** `header-override` alone answers
the wrong question: a thousand *agreeing* overrides is a one-line config change, ten *divergent*
ones is a negotiation with ten callers. Only divergent rows warn, so the migration-sizing number
is greppable without knowing the schema.

`header-only` is expected to dominate today and is not a defect: the bearer is an M2M service
token with no user email, so the end user's identity can only arrive by header. That is what the
header is for. The question is how many callers *also* carry a subject in the token.

### Verify-if-present

Signatures are checked when a token carries one **and a key is configured** (`GATEWAY_JWKS_URL`,
else `GATEWAY_JWT_PUBLIC_KEY`/`KEYCLOAK_PUBLIC_KEY`); the entitlement claim follows the mesh's
`USER_ENTITLEMENT_CLAIM` so the gauge measures the subject the gate would authorize on. Anything
unprovable is reported `verified=False` with the reason **named**, never silently trusted and
never refused. A JWKS failure latches and degrades to honest-unverified rather than adding a
network dependency that could wedge a live read path.

### Two announcements that exist to prevent false readings

* **`subject-gauge verification: NONE CONFIGURED`** — because a gauge reading `unverified` on
  every request *because no key is set* looks identical to one reading `unverified` *because
  every caller is forging tokens*. Startup separates them instead of leaving it to be inferred.
* **A set `REQUIRE_GATEWAY_AUTH`/`REQUIRE_TRANSPORT_AUTH` is loudly IGNORED**, because an
  operator who sets a require-shaped flag and gets silence would reasonably believe the gateway is
  enforcing. A false belief in enforcement is worse than the absent enforcement.

### The visibility lesson, inherited rather than relearned

`ensure_gauge_visible()` mirrors the SDK's, for the reason the SDK's exists: twelve mesh services
announced OBSERVE and then observed nothing, because nothing configured logging and the records
fell through to `logging.lastResort` and were discarded. **Zero-because-silent and
zero-because-clean are the two states this instrument exists to separate**, and a migration
precondition of "the divergent count reads zero" is satisfied perfectly and falsely by a silent
gauge. Additive and deferential: it does nothing when logging is already configured.

Witnessed end-to-end with **no host logging configured at all** — announce plus all three buckets
plus the divergent warning reached the stream.

### Guarded by 23 pins — `dag_tools_tests/test_subject_source_gauge.py`

Including the two that matter most: **the gateway must not branch on the reading** (source-level,
so it cannot be satisfied by a runtime patch — the moment an outcome depends on it, this stops
being a gauge and becomes an unreviewed enforcement path), and **the gauge must be visible with
nothing configured**. The disable switch is exercised too: *a leg of a litany that has never gone
red is not yet a check.*

### Also fixed: an undeclared dependency that made the extra uninstallable

`redis` and `PyJWT` are **module-level imports** in `central_gateway/main.py` and neither was
declared, so `pip install "dag-tools[broker]"` produced a gateway that could not import. It worked
only where something else pulled them in transitively — the dependency equivalent of a test
passing for the wrong reason. Both added to the `broker` extra.

### THE PREDICTION — written down BEFORE the reading, on purpose

**Stated as a prediction so the reading can falsify it.** A number that arrives with no prior
expectation gets rationalised into whatever story the reader brought; one that arrives against a
written prediction either confirms it or *surprises*, and the surprise is only legible because
someone said what they expected first.

| bucket | predicted | why |
|---|---|---|
| `header-only` | **dominant** | the DA path's bearer is an M2M service token with **no user email claim**, so the end user's identity can only arrive by header. A design fact, not a defect. |
| `header-override / agreeing` | rare | requires a caller holding a user-subject token that *also* sets the header to the same value |
| `header-override / divergent` | **near zero, and this is the load-bearing guess** | if true, removing the override is a config change |
| `token-claim` | rare today | nothing currently sends a user token to this gateway |
| `none` | ~0 | fail-closed denies these already, so they would show as existing 403s |

**What would falsify it, and what each falsification means:**

* **`divergent` is non-trivial** → the override is load-bearing for real callers and step 2 is a
  coordinated migration, not a config change. This is the outcome that changes the plan.
* **`token-claim` appears at all** → something already sends user tokens here, and the
  transparent-Jupyter design may be half-built somewhere nobody has looked.
* **`header-only` is NOT dominant** → the stated model of the DA path is wrong, and the notebook
  identity question in `[[jupyter-user-token-data-access]]` needs re-asking before anything is
  designed on top of it.

**Do not tune the gauge to make the prediction come true.** If the reading disagrees, the reading
wins — the prediction exists to make disagreement visible, not to be defended.

### The JWKS branch witnesses itself on the work deploy

Static-key and no-key paths are proven by the pins; **the JWKS path is unwitnessed against a real
endpoint** (no work-realm JWKS was reachable from here). It needs no separate exercise: when the
gateway runs against work's Keycloak, **the first fetch is its own witness**, and
`verification_line()` announces at startup which of the three states it landed in — JWKS, static
key, or `NONE CONFIGURED`. A JWKS failure latches to honest-unverified rather than wedging the
read path, so the failure mode is a degraded gauge, never a degraded gateway.

**Read that announcement line first when the pod comes up.** If it says `NONE CONFIGURED`, every
`token_verified=False` in the run is an artifact of configuration and the verified/unverified axis
carries no information — the subject-source axis still does.

### What this session did NOT do, by instruction

No REQUIRE. No header removal. No JWKS pinned in the deployment. **The output is a running gauge,
not a fix** — the reading comes first, and it decides the shape of everything below.

## Acceptance

- **THE READING** — deploy, let it run, and count the buckets. `header-override/divergent` is the
  number that decides whether step 2 is a config change or a coordinated migration.
- A request with a forged/unsigned bearer is **rejected**, witnessed.
- A request whose `X-Originator-Email` disagrees with a verified user token does **not** get the
  header's subject, witnessed.
- One allow-path log line naming the decided subject, witnessed on a real read.
