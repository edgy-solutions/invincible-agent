"""Call policy for a door client (policy rail `capability_grants`, `can_call:<tag>`).

A DOOR is a front-end client whose token `azp` the deployment names in the comma-separated env var
`CAN_CALL_DOOR_CLIENTS` (the MCP server's client is the first). `DoorGuard`, a pure-ASGI middleware
on the BFF app, applies this policy to a door caller before routing, so it covers every path the app
answers, `/docs`, `/openapi.json`, `/redoc` and an unmatched path included.

SURFACE. A door caller reaches ONLY the routes carrying the MCP tag (`ingest_api.MCP_TAG`, the MCP
surface's own definition); every other route is 403 `not_entitled_to_call`, app-wide (2026-10-31,
M3). A route tagged only for another surface is not reachable through a door, whoever the caller is.
Within the surface the caller must hold Topaz `can_invoke` on `capability:can_call:<t>` for EVERY
tag `t` on the route (AND: a tag added to a route can only narrow who may call it, never widen it).
Tags are checked in sorted order and the first missing one refuses.

ROWS. They live on the rail (policy/capability_grants.yaml). DENY BY DEFAULT: a tag with no row has
no `capability:can_call:<t>` object; Topaz answers 404, which `human_tasks.can_invoke_or_unavailable`
maps to False, so there is no row, then no call.

BENEATH THE DOOR. The caller's own persona x domain gate still runs inside the route (2026-10-31,
M2). The door only ever removes reach; it never grants.

A NON-DOOR caller (a browser token, an engine) is untouched: no Topaz call at all. A token that does
not verify is passed through too; the route then answers 401 or serves a public path.

ENV. Read at call time. Unset or empty means no caller is a door client and the guard is a no-op
with zero token work.

TOPAZ FAILURE is a 503 (`authorization_unconfigured` / `authorization_unavailable`), never a deny,
the same mapping as the BFF's `_may_export_profile`.

No tag, group, persona or client id is named in this module (standing rule, 2026-10-30): tags come
from the route, door clients from the env, grantees are rows. One audit line per door decision;
never a token.
"""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Match

from .. import auth
from ..ingest_api import MCP_TAG
from .refusal import policy_refusal

logger = logging.getLogger(__name__)

CALL_PREFIX = "can_call:"
DOOR_CLIENTS_ENV = "CAN_CALL_DOOR_CLIENTS"


def door_clients() -> frozenset[str]:
    """The `azp` values that are doors, read from the env now (not at import)."""
    raw = os.getenv(DOOR_CLIENTS_ENV) or ""
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def _identify(token: str) -> tuple[str, str | None] | None:
    """The verified `(authz_id, azp)` of a token, or None on ANY failure. No Topaz, no entitlements."""
    try:
        payload = auth.verified_claims(token)
        authz_id = auth.resolve_token_identity(payload)[1]
        return authz_id, payload.get("azp")
    except Exception:  # noqa: BLE001 -- bad signature, expired, no identity, JWKS down: not a door
        return None


async def _decide(route, who: str, azp: str) -> HTTPException | None:
    """The decision for a door caller on `route` (None when no route fully matched)."""
    path = getattr(route, "path", None)
    tags = sorted(set(str(t) for t in (getattr(route, "tags", None) or [])))

    def _audit(decision: str, missing: str = "-") -> None:
        logger.info("can_call who=%s via=%s route=%s tags=%s decision=%s tag=%s",
                    who, azp, path, tags, decision, missing)

    if route is None or MCP_TAG not in (getattr(route, "tags", None) or []):
        _audit("deny", "-")
        return policy_refusal(
            "not_entitled_to_call", policy_id=f"capability_grants:{CALL_PREFIX}",
            missing_binding=f"can_invoke {CALL_PREFIX}",
            message=f"You are not entitled to call this operation through {azp} "
                    f"(it is not on the door's surface; nothing grants it).",
            extra={"on_surface": False})
    from .. import human_tasks

    for t in tags:
        capability = f"{CALL_PREFIX}{t}"
        try:
            ok = bool(await run_in_threadpool(
                lambda c=capability: human_tasks.can_invoke_or_unavailable(c, who)))
        except human_tasks.AuthorizationUnconfigured:
            _audit("deny", t)
            return HTTPException(status_code=503, detail={
                "error": "authorization_unconfigured",
                "message": "the deployment declares no authorization directory"})
        except human_tasks.AuthorizationUnavailable as exc:
            logger.warning("call capability check unavailable: %s", type(exc).__name__)
            _audit("deny", t)
            return HTTPException(status_code=503, detail={
                "error": "authorization_unavailable",
                "message": "could not verify the caller against the call capability"})
        if not ok:
            _audit("deny", t)
            return policy_refusal(
                "not_entitled_to_call", policy_id=f"capability_grants:{capability}",
                missing_binding=f"can_invoke {capability}",
                message=f"You are not entitled to call this operation through {azp} "
                        f"(it needs {capability}).",
                extra={"tag": t})
    _audit("allow")
    return None


class DoorGuard:
    """Pure-ASGI middleware: confine a door client's token to the MCP surface and its `can_call` rows."""

    def __init__(self, app, router) -> None:
        self.app = app
        self.router = router

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not door_clients():
            await self.app(scope, receive, send)
            return
        token = ""
        for k, v in scope.get("headers") or []:
            if k.lower() == b"authorization":
                val = v.decode("latin-1").strip()
                if val[:7].lower() == "bearer ":
                    token = val[7:].strip()
                break
        if not token:
            await self.app(scope, receive, send)
            return
        ident = await run_in_threadpool(_identify, token)
        if ident is None or ident[1] not in door_clients():
            await self.app(scope, receive, send)
            return
        who, azp = ident
        route = None
        for r in self.router.routes:
            match, _child = r.matches(scope)
            if match == Match.FULL:
                route = r
                break
        exc = await _decide(route, who, azp)
        if exc is None:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                                headers=getattr(exc, "headers", None))
        await response(scope, receive, send)
