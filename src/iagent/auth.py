import os
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import List, Optional

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

# Global JWKS Client for caching public keys
jwks_url = f"{KEYCLOAK_URL}/protocol/openid-connect/certs"
jwks_client = PyJWKClient(jwks_url)

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

        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing 'sub' or 'email'",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return User(
            id=user_id,
            email=email,
            roles=roles,
            persona=persona,
            entitled_domains=entitled_domains,
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
