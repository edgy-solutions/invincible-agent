import os
import jwt
import httpx
from functools import wraps
from fastapi import Request, HTTPException, status, Depends
from typing import Callable, Any

# Environment configuration
#
# POSTURE ANNOUNCEMENT (2026-08-07). This flag DARK-LAUNCHES the enforcement arc
# (ADR-0025): default OFF, and it flips LAST, after every enforcement point has migrated.
# That default is deliberate and recorded — but a disabled gate that says nothing is
# indistinguishable from an absent one, so the resolved posture is ANNOUNCED at import.
#
# The announcement names its SOURCE, not just its state, per the admitted_by pattern: after
# the ADR-0025 flip, "DISABLED (DEFAULT)" must be impossible, and a log line that cannot
# distinguish "nobody configured this" from "someone chose this" cannot show that. It also
# makes the fresh-deploy posture assertion readable in a log as well as in a suite.
#
# ONE FLAG, THREE ENFORCEMENT POINTS (here, datahub_wrapper's can_view ask, weaviate_expert's
# per-chunk can_read filter) — DELIBERATE, not a three-jobs defect. It means the system can
# never occupy a PARTIAL enforcement state (door verified but chunks unfiltered, etc.), which
# is the multiple-heads configuration ADR-0025 exists to kill. Staging the migration would
# require SPLITTING the flag first; see the flip packet.
_AGENTIC_AUTH_RAW = os.getenv("ENABLE_AGENTIC_AUTH")
ENABLE_AGENTIC_AUTH = (_AGENTIC_AUTH_RAW or "false").lower() in ("true", "1", "yes")
print(
    f"agentic auth: {'ENFORCING' if ENABLE_AGENTIC_AUTH else 'DISABLED'} "
    f"({'explicit config' if _AGENTIC_AUTH_RAW is not None else 'DEFAULT'}, "
    f"dark-launch ADR-0025) [core.authz]",
    flush=True,
)
TOPAZ_AUTHORIZER_URL = os.getenv("TOPAZ_AUTHORIZER_URL", "http://localhost:8282")
TOPAZ_POLICY_PATH = os.getenv("TOPAZ_POLICY_PATH", "invincible_agent.authz")

def require_topaz_auth(resource_type: str, action: str) -> Callable:
    """
    FastAPI dependency that validates the user's intent against Topaz.
    
    Usage in a FastAPI route:
    @app.post("/query")
    async def query_endpoint(
        request: Request,
        user_jwt: str = Depends(require_topaz_auth(resource_type="global", action="query"))
    ):
        ...
    """
    async def auth_dependency(request: Request) -> str | None:
        # Extract the Authorization header
        auth_header = request.headers.get("Authorization")
        
        if not ENABLE_AGENTIC_AUTH:
            # If auth is disabled, just return the token if present, otherwise None
            if auth_header and auth_header.startswith("Bearer "):
                return auth_header.split(" ")[1]
            return None

        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header"
            )

        token = auth_header.split(" ")[1]
        
        try:
            # Decode the Keycloak JWT to get the sub (User ID)
            # We don't verify the signature here as the API Gateway/BFF handles that
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub")
            if not user_id:
                raise ValueError("JWT missing 'sub' claim")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            )

        # Send authorization request to Topaz
        topaz_payload = {
            "identityContext": {
                "identity": f"user:{user_id}",
                "type": "IDENTITY_TYPE_SUB"
            },
            "resourceContext": {
                "resource": resource_type
            },
            "action": f"agent_mesh.{action}",
            "policyContext": {
                "path": TOPAZ_POLICY_PATH,
                "decisions": ["is"]
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                # Topaz v2 authz endpoint
                response = await client.post(
                    f"{TOPAZ_AUTHORIZER_URL}/api/v2/authz/is",
                    json=topaz_payload,
                    timeout=5.0
                )
                response.raise_for_status()
                result = response.json()
                
                # Extract the 'is' decision from Topaz response
                decisions = result.get("decisions", {})
                is_allowed = False
                
                if isinstance(decisions, dict):
                    is_allowed = decisions.get("is", False)
                elif isinstance(decisions, list):
                    for d in decisions:
                        if isinstance(d, dict) and d.get("name") == "is":
                            is_allowed = d.get("value", False)
                            break
                else:
                    is_allowed = result.get("is", False)
                    
                if not is_allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied by Topaz: Insufficient permissions for this action."
                    )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Topaz authorization request failed: {str(e)}"
            )

        # If approved, return the token so it can be injected into the route handler
        return token

    return auth_dependency

def require_topaz_auth_decorator(resource_type: str, action: str):
    """
    Alternative Python decorator implementation.
    Injects 'user_jwt' into the kwargs of the route.
    Note: Ensure the route function accepts **kwargs or user_jwt explicitly.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find Request object
            request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if not request:
                if not ENABLE_AGENTIC_AUTH:
                    kwargs["user_jwt"] = None
                    return await func(*args, **kwargs)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Request object not found in route arguments for Topaz auth"
                )

            # Re-use the dependency logic
            dependency = require_topaz_auth(resource_type, action)
            token = await dependency(request)
            
            kwargs["user_jwt"] = token
            return await func(*args, **kwargs)
            
        return wrapper
    return decorator
