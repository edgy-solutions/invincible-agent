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
    email: str
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
        
        user_id = payload.get("sub")
        email = payload.get("email")
        realm_access = payload.get("realm_access", {})
        roles = realm_access.get("roles", [])

        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing 'sub' or 'email'",
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
            # Topaz lookup identifier — the human-legible claim (email
            # by default) that policy/users.yaml keys on, NOT the sub.
            # Falls back to sub if the configured claim is absent.
            lookup_key = payload.get(USER_ENTITLEMENT_CLAIM) or user_id
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
            id=user_id,
            email=email,
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
