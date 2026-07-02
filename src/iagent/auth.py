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

# Per ADR-0009 the user persona is sourced from identity-provider claims, not
# from query-text classification. PingSSO does not currently carry a `persona`
# claim; we read whichever claim *is* present (in priority order) and fall back
# to a sane default so engines can boot without claim expansion. Override via
# env if the IdP team wires a different claim name.
USER_PERSONA_CLAIM = os.getenv("USER_PERSONA_CLAIM", "persona")
USER_PERSONA_FALLBACK = os.getenv("USER_PERSONA_FALLBACK", "MECHANIC")
USER_DOMAINS_CLAIM = os.getenv("USER_DOMAINS_CLAIM", "entitled_domains")

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
# on produced_for".
#
# The persona / entitlements VALUE the User carries is the same value
# downstream code uses today (fallback when the claim is absent, claim
# value when present). The new `entitlement_source` field records WHICH
# ORIGIN the value came from — information that exists ONLY at the
# moment the JWT is read, and is unrecoverable later
# (capture-or-lose-forever per `[[verify-subtle-acceptance-by-inspection]]`).
#
# Vocabulary:
#   "claim"    — both persona and domains claims were present.
#   "fallback" — neither was present (the PingSSO production baseline
#                per `[[pingsso-claim-gap]]`).
#   "partial"  — exactly one was present, the other fell back
#                (transitional / misconfigured state).
#
# Per `[[optimistic-defaults-are-dishonest]]`: the field is REQUIRED on
# the User model — no default. Defaulting to "claim" would silently
# mask the fallback path (which is the production baseline) and
# convert silence into a success signal. Required input forces
# get_current_user to compute the value at the moment the JWT is read.
EntitlementSource = Literal["claim", "fallback", "partial", "topaz"]


class User(BaseModel):
    id: str
    email: str
    roles: List[str] = []
    # Per ADR-0009: caller-side persona. Drives entitlements, scope filtering,
    # UI defaults, and (when the matched predicate is persona-agnostic) the
    # answerer persona. Sourced from JWT claims with a documented fallback.
    persona: str = USER_PERSONA_FALLBACK
    # Per ADR-0009: domain scopes the caller is entitled to query. Empty list
    # means no entitled-domains claim was present in the JWT; downstream code
    # should treat that as "no scope filter applied" rather than "no access"
    # until the IdP team expands the claim set.
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

        # Capture A per ADR-0025: record WHICH ORIGIN the persona /
        # entitlements came from, BEFORE the fallback is applied. After
        # `or USER_PERSONA_FALLBACK` runs, the information that the
        # claim was absent is gone — capture-or-lose-forever per
        # `[[verify-subtle-acceptance-by-inspection]]`. The presence
        # check must happen on the raw payload dict, not on the
        # post-fallback value.
        persona_claim_present = USER_PERSONA_CLAIM in payload
        domains_claim_present = USER_DOMAINS_CLAIM in payload

        # Per ADR-0009: try the configured persona claim; default to the
        # fallback if the IdP doesn't issue it yet. Normalize to upper-case
        # to match the answerer-persona vocabulary engines already use.
        persona_claim = payload.get(USER_PERSONA_CLAIM)
        persona = (persona_claim or USER_PERSONA_FALLBACK).upper()

        # Per ADR-0009: entitled domains list — defaults to empty when the
        # IdP doesn't issue the claim. Downstream `/find_tool` callers treat
        # an empty list as "no domain scope filter" until claim expansion.
        entitled_raw = payload.get(USER_DOMAINS_CLAIM, [])
        if isinstance(entitled_raw, str):
            entitled_raw = [s.strip() for s in entitled_raw.split(",") if s.strip()]
        entitled_domains = [str(d).upper() for d in entitled_raw if d]

        # Capture A: compute entitlement_source from the presence
        # checks captured above. Three legitimate values; per
        # `[[optimistic-defaults-are-dishonest]]` the User model
        # REQUIRES this explicitly — a forgotten value would be a
        # ValidationError, not a silent default.
        if persona_claim_present and domains_claim_present:
            entitlement_source: EntitlementSource = "claim"
        elif not persona_claim_present and not domains_claim_present:
            entitlement_source = "fallback"
        else:
            entitlement_source = "partial"

        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing 'sub' or 'email'",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # ADR-0026 step 3: enrich with topaz entitlement matrix.
        # Per-token cache keyed by (sub, jti) with TTL = token exp.
        # When TOPAZ_DIRECTORY_URL is unset (legacy cluster), skip
        # topaz and return the User with an empty Entitlements — the
        # JWT-claim path above still populates persona + entitled_domains
        # for downstream code that hasn't switched to the matrix yet.
        entitlements = Entitlements()
        cache = _get_entitlement_cache()
        if cache is not None:
            jti = payload.get("jti") or user_id  # fall back to sub if
                                                  # IdP doesn't issue jti
            exp = float(payload.get("exp") or 0)
            # Topaz lookup identifier — the human-legible claim (email
            # by default) that policy/users.yaml keys on, NOT the sub.
            # See USER_ENTITLEMENT_CLAIM. Falls back to sub if the
            # configured claim is absent so a missing email doesn't
            # blank every user's entitlements silently.
            lookup_key = payload.get(USER_ENTITLEMENT_CLAIM) or user_id
            try:
                entitlements = cache.get(
                    sub=user_id, jti=jti, exp=exp, lookup_key=lookup_key
                )
                # When topaz did return a real matrix (not empty),
                # override the entitlement_source flag to record
                # topaz as the authoritative source. Empty matrix from
                # topaz means the user isn't seeded — leave the JWT-
                # claim provenance flag in place.
                if entitlements.cells:
                    entitlement_source = "topaz"
            except AuthorizationUnavailable:
                # ADR-0026 posture: on cache-miss + topaz-unreachable
                # we DENY, not fall back to legacy claim path. Cache
                # itself served a stale-but-valid matrix under a
                # cached token, so this branch only fires for FRESH
                # tokens during a topaz outage. Distinct 503 lets the
                # caller distinguish "auth is down" from "you're
                # denied" per the ADR.
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
