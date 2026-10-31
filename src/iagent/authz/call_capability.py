"""Call policy for a door client (policy rail `capability_grants`, `can_call:<tag>`).

A DOOR is a front-end client whose token `azp` the deployment names in the comma-separated env var
`CAN_CALL_DOOR_CLIENTS` (the MCP server's client is the first). A caller arriving through a door may
call a route only if it holds Topaz `can_invoke` on `capability:can_call:<t>` for EVERY tag `t` on
that route (AND: a tag added to a route can only narrow who may call it, never widen it). Tags are
checked in sorted order and the first missing one refuses (403 `not_entitled_to_call`).

DENY BY DEFAULT: a tag with no row has no `capability:can_call:<t>` object; Topaz answers 404, which
`human_tasks.can_invoke_or_unavailable` maps to False, so nobody may call it through a door. A route
with no tags is refused too, naming the binding `can_invoke can_call:` with no tag; nothing lifts it.

A non-door caller (a browser token, an engine) is untouched: no Topaz call at all. The env var is
read at call time; unset or empty means no caller is a door client and the dependency is a no-op.
A Topaz failure is 503 (`authorization_unconfigured` / `authorization_unavailable`), never a deny,
the same mapping as the BFF's `_may_export_profile`.

No tag, group, persona or client id is named in this module (standing rule, 2026-10-30): tags come
from the route, door clients from the env, grantees are rows in policy/capability_grants.yaml.
One audit line per door decision; never a token.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, HTTPException, Request

from ..auth import User, get_current_user
from .refusal import policy_refusal

logger = logging.getLogger(__name__)

CALL_PREFIX = "can_call:"
DOOR_CLIENTS_ENV = "CAN_CALL_DOOR_CLIENTS"


def door_clients() -> frozenset[str]:
    """The `azp` values that are doors, read from the env now (not at import)."""
    raw = os.getenv(DOOR_CLIENTS_ENV) or ""
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


async def require_call_capability(request: Request,
                                  current_user: User = Depends(get_current_user)) -> None:
    azp = current_user.azp
    if not azp or azp not in door_clients():
        return None
    from starlette.concurrency import run_in_threadpool

    from .. import human_tasks

    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    tags = sorted(set(getattr(route, "tags", None) or []), key=str)
    tags = [str(t) for t in tags]
    who = current_user.authz_id

    def _audit(decision: str, missing: str = "-") -> None:
        logger.info("can_call who=%s via=%s route=%s tags=%s decision=%s tag=%s",
                    who, azp, path, tags, decision, missing)

    if not tags:
        _audit("deny", "-")
        raise policy_refusal(
            "not_entitled_to_call", policy_id=f"capability_grants:{CALL_PREFIX}",
            missing_binding=f"can_invoke {CALL_PREFIX}",
            message=f"You are not entitled to call this operation through {azp} "
                    f"(it carries no tag, so no {CALL_PREFIX}<tag> can admit it).")
    for t in tags:
        capability = f"{CALL_PREFIX}{t}"
        try:
            ok = bool(await run_in_threadpool(
                lambda c=capability: human_tasks.can_invoke_or_unavailable(c, who)))
        except human_tasks.AuthorizationUnconfigured as exc:
            _audit("deny", t)
            raise HTTPException(status_code=503, detail={
                "error": "authorization_unconfigured",
                "message": "the deployment declares no authorization directory"}) from exc
        except human_tasks.AuthorizationUnavailable as exc:
            logger.warning("call capability check unavailable: %s", type(exc).__name__)
            _audit("deny", t)
            raise HTTPException(status_code=503, detail={
                "error": "authorization_unavailable",
                "message": "could not verify the caller against the call capability"}) from exc
        if not ok:
            _audit("deny", t)
            raise policy_refusal(
                "not_entitled_to_call", policy_id=f"capability_grants:{capability}",
                missing_binding=f"can_invoke {capability}",
                message=f"You are not entitled to call this operation through {azp} "
                        f"(it needs {capability}).",
                extra={"tag": t})
    _audit("allow")
    return None
