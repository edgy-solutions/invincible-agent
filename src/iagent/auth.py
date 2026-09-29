import logging
import os
import threading

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import List, Literal, Optional

from iagent.authz import (
    AuthorizationUnavailable,
    EntitlementCache,
    Entitlements,
    TopazDirectoryClient,
)


logger = logging.getLogger(__name__)


# Configuration
# The Keycloak Realm URL is retrieved from environment variables, defaulting to a standard local path.
KEYCLOAK_URL = os.getenv("KEYCLOAK_REALM_URL", "http://localhost:8080/realms/invincible-agent")

# OAuth2 Scheme
# This tells FastAPI how to extract the Bearer token from the Authorization header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{KEYCLOAK_URL}/protocol/openid-connect/token")

# 2026-07-03 — ADR-0026 step 6: the JWT-claim persona path is RETIRED.
# Persona + entitled_domains are now sourced SOLELY from Topaz
# (the entitlement matrix, keyed by USER_ENTITLEMENT_CLAIM below).
# The old `USER_PERSONA_CLAIM` / `USER_PERSONA_FALLBACK` /
# `USER_DOMAINS_CLAIM` machinery is deleted — it manufactured an
# identity claim (MECHANIC) from an ABSENT fact, which is exactly the
# `[[optimistic-defaults-are-dishonest]]` shape that caused the
# original persona confusion. A user with zero Topaz entitlements now
# gets HONEST-EMPTY (persona=None, entitled_domains=[]) — least
# privilege, never a fabricated persona. The empty state stays
# representationally distinct (None, not a coalesced string default)
# all the way to the artifact's produced_for. See ADR-0026 step 6
# + `[[single-authz-decider]]`.

# Topaz Directory service URL for ADR-0026 entitlement enrichment.
# When set, `get_current_user` fetches the caller's (persona, domain)
# matrix from topaz and attaches it to the returned User. When unset
# (empty), topaz enrichment is skipped and the returned User carries
# an empty `entitlements` object — the ADR-0009 legacy claim path
# continues to populate `persona` + `entitled_domains`.
TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "").strip()

# Which JWT claim identifies the user in the topaz Directory / policy/
# users.yaml. Defaults to `email`, NOT `sub`, deliberately:
#
#   * ADR-0026's whole premise is human-asserted entitlements in git.
#     A `users.yaml` keyed by Keycloak `sub` (an opaque UUID) is not
#     human-authorable — nobody can read or review "is
#     c405218e-a25c-... entitled to DATA_STEWARD?". Keyed by email it
#     IS reviewable, which is the entire point of the git-assertion
#     discipline.
#   * The ADR's own users.yaml examples key by email; the earlier
#     "id MUST match sub" line was an over-specification, reconciled
#     here to "id matches USER_ENTITLEMENT_CLAIM (email by default)".
#
# Caveat: the IdP must issue a verified, stable `email` claim, and
# entitlements re-key if a user's email changes. For IdPs where email
# is absent or mutable, set USER_ENTITLEMENT_CLAIM=sub and key
# users.yaml by sub (accepting the readability cost). The token's
# `sub` is still the CACHE key regardless — this env only controls
# the topaz LOOKUP identifier.
USER_ENTITLEMENT_CLAIM = os.getenv("USER_ENTITLEMENT_CLAIM", "email")

# ── THE DELEGATE CLAIM: RECORDED, AND GATED ON BY NOTHING ────────────────────
# Which token claim names the principal a DELEGATE is acting for. The name and
# its default are READ FROM THE SDK's contract (iagent_mesh delegate_identity:
# DELEGATE_ON_BEHALF_OF_CLAIM, default "on_behalf_of"), not invented here — the
# two halves of one delegation have to agree on the claim name, and this
# codebase has already paid for three providers independently inventing the
# same constant and none of them being the fleet's.
#
# WHY THIS VALUE REACHES NO AUTHORIZATION DECISION, EVER. `on_behalf_of` is the
# fleet's NAMED laundering shape: a subject a caller can name is not an
# identity, it is a request field, and a gate keyed on it checks who the asker
# CLAIMED asked (helm values.yaml on serviceClients; register-caller-
# enumeration.md; lock 2 at 0555620). So this claim is recorded for AUDIT and
# TRACE only. Every authorization decision continues to key on `authz_id`,
# which for a delegate is the DELEGATE's own identity — the credential that was
# actually authenticated — never the principal it names.
#
# That is also why the realm change accompanying this is a HARDCODED claim
# mapper, one delegate client per principal: a mapper that let the client
# choose `on_behalf_of` per token request would be the laundering shape with an
# IdP signature wrapped around it. See docs/runbooks/delegate-credential.md.
DELEGATE_ON_BEHALF_OF_CLAIM = os.getenv(
    "DELEGATE_ON_BEHALF_OF_CLAIM", "on_behalf_of"
)


# Capture A per ADR-0025 § "Capture A — entitlement_source fidelity flag
# on produced_for". Records WHERE the persona / entitlements came from,
# captured at token-read time (capture-or-lose-forever per
# `[[verify-subtle-acceptance-by-inspection]]`).
#
# Post ADR-0026 step 6 (2026-07-03) the JWT-claim origins are gone;
# there are exactly two truthful states:
#   "topaz" — Topaz returned a non-empty entitlement matrix for this
#             caller. persona/domains derive from it.
#   "none"  — Topaz returned an EMPTY matrix (unseeded user). HONEST-
#             EMPTY: persona=None, entitled_domains=[]. NOT a fabricated
#             default — least privilege, representationally distinct.
#
# Per `[[optimistic-defaults-are-dishonest]]`: REQUIRED on the User
# model — no default. A forgotten value is a ValidationError, not a
# silent "topaz". (The legacy "claim"/"fallback"/"partial" values are
# retired with the JWT-claim path.)
EntitlementSource = Literal["topaz", "none"]


class User(BaseModel):
    id: str
    # DISPLAY / AUDIT only — never an authorization key (use authz_id). OPTIONAL:
    # a service account (no mailbox) or a deployment whose entitlement claim
    # isn't email carries none. Stays `None` — never defaulted to a non-mailbox
    # value, so no consumer can mistake it for a real address.
    email: Optional[str] = None
    # The AUTHORIZATION identity — the key Topaz/policy is seeded by, resolved
    # from USER_ENTITLEMENT_CLAIM (email by default; employee-ID at work-deploy),
    # falling back to `sub` when the claim is absent. This is what every
    # authorization decision keys on (Topaz subject, projection filters, can_act).
    # Separating the two roles — authorize on the stable/authoritative/IdP-native
    # identifier, show humans the email — is what makes the identity key a single
    # overlay parameter: at work-deploy only USER_ENTITLEMENT_CLAIM changes (to the
    # PingSSO employee-ID claim) and every authz decision re-keys with it, no
    # per-site edits. In the sandbox authz_id == email, so the abstraction is
    # behaviourally transparent today.
    authz_id: str
    # THE PRINCIPAL A DELEGATE CREDENTIAL SAYS IT IS ACTING FOR — AUDIT ONLY.
    # `None` for every ordinary caller: a human login and a plain service
    # credential both act as themselves, and the absence is meaningful rather
    # than a missing value to fill in.
    #
    # NOTHING GATES ON THIS. Not the Topaz subject, not the entitlement lookup
    # key, not can_act, not a projection filter. It exists so that a delegated
    # write can be ATTRIBUTED in a trace — "svc:reporting-delegate, for
    # alice@example.com" — while the authorization answer stays keyed on
    # `authz_id`, which is the credential that was actually authenticated.
    #
    # The field is deliberately NOT called `user_email`, `originator` or
    # `authz_id`-anything: tests/test_subject_derivation.py (lock 2) forbids the
    # acting subject being nameable by a caller under any of those spellings,
    # and a claim that LOOKS like the acting subject is how that guarantee gets
    # inverted by someone reaching for the nearest identity-shaped field.
    on_behalf_of: Optional[str] = None
    roles: List[str] = []
    # Per ADR-0009: caller-side persona. Post ADR-0026 step 6, sourced
    # SOLELY from the Topaz entitlement matrix (the default cell's
    # persona, else the first cell's). `None` — NOT a fabricated
    # default — when the caller has zero Topaz entitlements. The
    # None stays representationally distinct all the way to
    # produced_for; no layer coalesces it to a string default.
    persona: Optional[str] = None
    # Per ADR-0009: domain scopes the caller is entitled to. Derived
    # from the Topaz entitlement matrix; empty list = no entitled
    # domains (honest-empty), not "no filter". Downstream gates treat
    # empty as least-privilege (deny privileged, allow generalist).
    entitled_domains: List[str] = []
    # Capture A per ADR-0025: which origin did the persona / entitlements
    # come from? REQUIRED — no default per
    # `[[optimistic-defaults-are-dishonest]]`. A forgotten value here is a
    # ValidationError at construction, not a silent fallback-to-"claim".
    entitlement_source: EntitlementSource
    # ADR-0026 step 3: full (persona, domain) matrix from topaz. Empty
    # `cells` when TOPAZ_DIRECTORY_URL is unset OR the user has no
    # entitlements seeded. Chat request validation (step 4) consumes
    # this to gate per-prompt persona/domain overrides.
    entitlements: Entitlements = Entitlements()


# Global JWKS Client for caching public keys
jwks_url = f"{KEYCLOAK_URL}/protocol/openid-connect/certs"
jwks_client = PyJWKClient(jwks_url)

# ADR-0026 step 3: lazy singletons for the Topaz client + cache.
# Instantiated on first request rather than at import time so cortex-bff
# can boot even if topaz is briefly unavailable during rollout.
_topaz_client: Optional[TopazDirectoryClient] = None
_entitlement_cache: Optional[EntitlementCache] = None
_topaz_init_lock = threading.Lock()


def _get_entitlement_cache() -> Optional[EntitlementCache]:
    """Lazy-init the Topaz client + cache. Returns None when
    TOPAZ_DIRECTORY_URL is unset (ADR-0026 not wired for this
    cluster) — callers should fall back to the legacy claim path."""
    global _topaz_client, _entitlement_cache
    if not TOPAZ_DIRECTORY_URL:
        return None
    if _entitlement_cache is not None:
        return _entitlement_cache
    with _topaz_init_lock:
        if _entitlement_cache is None:
            _topaz_client = TopazDirectoryClient(TOPAZ_DIRECTORY_URL)
            _entitlement_cache = EntitlementCache(_topaz_client)
    return _entitlement_cache

def resolve_token_identity(
    payload: dict,
) -> "tuple[Optional[str], str, Optional[str]]":
    """Resolve (sub, authz_id, email) from an already-verified JWT payload.

    AUTHENTICATE ON THE AUTHORIZATION IDENTITY, never on email. `authz_id` is the
    USER_ENTITLEMENT_CLAIM claim (email in the default deployment; a different
    claim where an operator sets it) with `sub` as the fallback — the SAME value
    every enforcement gate keys on. `email` is DISPLAY/AUDIT only and MAY BE
    ABSENT (a service account with no mailbox, or a deployment whose entitlement
    claim isn't email); it is returned as-is, possibly None, and NEVER defaulted
    to a non-mailbox value.

    Raises ValueError only when NO authz identity resolves (neither the
    entitlement claim nor `sub` is present) — the sole genuine "who is this?"
    failure. The prior gate hard-required `email` here, which contradicted the
    display-only contract and wrongly rejected mailbox-less tokens.
    """
    sub = payload.get("sub")
    authz_id = payload.get(USER_ENTITLEMENT_CLAIM) or sub
    if not authz_id:
        raise ValueError(
            "no authorization identity (neither the USER_ENTITLEMENT_CLAIM "
            "claim nor 'sub' is present)"
        )
    return sub, authz_id, payload.get("email")


def resolve_on_behalf_of(payload: dict) -> Optional[str]:
    """Read the delegate's `on_behalf_of` claim from an already-verified payload.

    A SEPARATE FUNCTION, NOT A FOURTH RETURN VALUE from
    `resolve_token_identity`, and that is on purpose twice over. Mechanically,
    five call sites unpack that function's 3-tuple. Substantively, this value is
    NOT part of the identity triple: `(sub, authz_id, email)` is who the caller
    IS, and widening that tuple would put a self-described principal in the same
    shape as two authenticated facts, next to the field every gate keys on.

    Returns None when the claim is absent — the ordinary case for every human
    login and every plain service credential.

    Raises ValueError when the claim is PRESENT BUT BLANK. That is not a caller
    acting for nobody, it is a misconfigured claim mapper, and the honest
    outcome is a refusal rather than recording `""` — an empty string would read
    as "delegated" in a trace while naming no principal, which is worse than
    either true state. The SDK's half refuses the mirror case (a delegate minted
    with no claim at all) for the same reason.
    """
    if DELEGATE_ON_BEHALF_OF_CLAIM not in payload:
        return None
    value = payload.get(DELEGATE_ON_BEHALF_OF_CLAIM)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"the {DELEGATE_ON_BEHALF_OF_CLAIM!r} claim is present but empty "
            f"(got {value!r}) — a delegate credential that names no principal "
            f"is a misconfigured claim mapper, not a caller acting for nobody"
        )
    return value.strip()


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    FastAPI dependency to validate the incoming OIDC token.
    Decodes the JWT using Keycloak's public keys (JWKS) and verifies the signature.
    """
    try:
        # 1. Fetch Keycloak Public Keys (JWKS)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        
        # 2. Decode and Verify JWT
        # We verify the RS256 signature against the public key.
        # Audience check is relaxed (verify_aud=False) to ensure compatibility across client types.
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        
        realm_access = payload.get("realm_access", {})
        roles = realm_access.get("roles", [])

        # AUTHENTICATE on the AUTHORIZATION identity, not on email. authz_id is the
        # USER_ENTITLEMENT_CLAIM claim (`sub` fallback) — the same value every
        # enforcement gate and the entitlement matrix below key on, so they never
        # diverge when the claim is switched. `email` is display/audit only and
        # may be None. The only genuine failure is no identity resolving at all.
        try:
            user_id, authz_id, email = resolve_token_identity(payload)
            # Read in the SAME try, so a malformed delegate claim is a 401 on the
            # identical path as an unresolvable identity. A separate, later read
            # would let a token with a broken claim mapper reach the entitlement
            # lookup and be authorized as an ordinary caller, with the delegation
            # silently dropped — a delegated write recorded as a direct one.
            on_behalf_of = resolve_on_behalf_of(payload)
        except ValueError as ve:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token payload: {ve}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # ADR-0026 step 6: Topaz is the SOLE source of persona +
        # entitled_domains. Fetch the matrix first, then DERIVE
        # everything from it. No JWT-claim persona reads remain.
        # Per-token cache keyed by (sub, jti), TTL = token exp.
        entitlements = Entitlements()
        cache = _get_entitlement_cache()
        if cache is not None:
            jti = payload.get("jti") or user_id  # fall back to sub if
                                                  # IdP doesn't issue jti
            exp = float(payload.get("exp") or 0)
            # Topaz lookup identifier == the authorization identity (authz_id):
            # the claim policy/users.yaml keys on, NOT the sub. Same value the
            # enforcement gates key on, so matrix + gates never diverge.
            lookup_key = authz_id
            try:
                entitlements = cache.get(
                    sub=user_id, jti=jti, exp=exp, lookup_key=lookup_key
                )
            except AuthorizationUnavailable:
                # Authz is a GATE, not a trailing step: on cache-miss +
                # topaz-unreachable we DENY (503), never fall back to a
                # fabricated persona. Distinct 503 lets the caller tell
                # "auth is down" from "you're denied" per ADR-0026.
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "authorization_unavailable",
                        "retryable": True,
                        "message": (
                            "Topaz Directory is unreachable and no "
                            "cached entitlement matrix exists for "
                            "this token. Retry after the authz "
                            "service is restored."
                        ),
                    },
                )

        # Derive persona + entitled_domains from the matrix. HONEST-
        # EMPTY when the user has zero cells: persona=None (NOT a
        # fabricated default — null stays null all the way to
        # produced_for), entitled_domains=[]. Least privilege.
        if entitlements.default is not None:
            persona: Optional[str] = entitlements.default.persona
        elif entitlements.cells:
            persona = entitlements.cells[0].persona
        else:
            persona = None  # honest-empty — never MECHANIC/ANALYST/etc.

        # All domains the caller is entitled to across their cells.
        entitled_domains = sorted(
            {c.domain for c in entitlements.cells}
        )

        # Capture A: two truthful states now — topaz (has cells) or
        # none (unseeded, honest-empty). Required on the User model.
        entitlement_source: EntitlementSource = (
            "topaz" if entitlements.cells else "none"
        )

        return User(
            id=user_id or authz_id,   # `sub` normally; authz_id if a token omits sub
            email=email,
            authz_id=authz_id,
            # Recorded here and read by no gate. The entitlement matrix above was
            # already fetched with lookup_key=authz_id, BEFORE this value was
            # placed on the model — the ordering is not incidental: there is no
            # point in the function where a delegate's principal could have
            # influenced the authorization answer.
            on_behalf_of=on_behalf_of,
            roles=roles,
            persona=persona,
            entitled_domains=entitled_domains,
            entitlement_source=entitlement_source,
            entitlements=entitlements,
        )
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        import logging
        logging.error(f"JWT Validation Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        import logging
        logging.error(f"Authentication System Error (JWKS fetch or parsing): {str(e)}")
        # Catch-all for network errors to JWKS or unexpected parsing issues.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
