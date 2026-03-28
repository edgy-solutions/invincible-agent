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

class User(BaseModel):
    id: str
    email: str
    roles: List[str] = []

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
        
        if not user_id or not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing 'sub' or 'email'",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        # Return the verified user object to the dependent endpoint.
        return User(id=user_id, email=email, roles=roles)
        
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
