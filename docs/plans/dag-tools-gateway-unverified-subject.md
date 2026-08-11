---
id:         dag-tools-gateway-unverified-subject
status:     open
owner:      human
blocked-on: gate-class ruling — same column as dag-tools-broker-register-unauthenticated
closed-by:  
code-site:  dag_tools/central_gateway/main.py
repo:       dag-tools
summary:    HIGH — the data-plane gateway never verifies a token signature, and prefers a request HEADER over the token's own claim as the authz subject. Per-user data scoping is advisory. Found answering the notebook-identity question.
---

# The data-plane gateway's authz subject is caller-asserted, and its bearer is never verified

**Found 2026-08-10** while answering a design question — *how does a notebook user's identity
reach the data plane?* — not while looking for a vulnerability. The answer is that it does not
have to.

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

## Remediation shape (not yet ruled)

Three things, and the first two are not optional if the notebook design proceeds:

1. **Verify the bearer** — JWKS against Keycloak, with `algorithms`, `audience` and `issuer`
   pinned. This is the missing precondition, not an enhancement.
2. **Stop preferring the header over the token.** `X-Originator-Email` may only be honoured when
   the *verified* caller holds an explicit delegation capability; otherwise the subject is the
   token's own entitlement claim. A user-token session must never be overridable by a header.
3. **Announce the subject on the allow path.** Today only denials name a subject
   (`TOPAZ AUTHZ DENIED`, `AUTHZ_DENIED`); an allow logs nothing about *who*. A data plane that
   records only its refusals cannot answer "who read this."

## Acceptance

- A request with a forged/unsigned bearer is **rejected**, witnessed.
- A request whose `X-Originator-Email` disagrees with a verified user token does **not** get the
  header's subject, witnessed.
- One allow-path log line naming the decided subject, witnessed on a real read.
