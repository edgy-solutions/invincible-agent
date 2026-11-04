"""The Keycloak seam: refresh a person's own access token near its expiry.

Ruled 2026-11-03 in ``docs/plans/identity-propagation-must-not-cross-run-storage.md``. The
identity vault (``identity_vault.py``) never mints and makes no network call, so when the
token it holds nears its ``exp`` somebody else has to ask the issuer for a fresh one. This
module is that somebody, and the only place that talks to Keycloak for the purpose.

WHAT IS CALLED. The STANDARD RFC 8693 token exchange and nothing else: the person's own
access token goes in as ``subject_token`` and a token for the SAME person comes out. Legacy
exchange and impersonation are ruled out permanently, so this request never carries
``requested_subject`` and never goes without a ``subject_token``; a test seals both.

UNSET BY DEFAULT, AND THAT IS THE POINT. Any of ``IDENTITY_EXCHANGE_TOKEN_URL``,
``IDENTITY_EXCHANGE_CLIENT_ID`` or ``IDENTITY_EXCHANGE_CLIENT_SECRET`` missing makes
``exchange`` return None, and the chart sets none of them. Token exchange needs a realm
permission, which is a human's act that an agent cannot verify live. Under the default,
near-expiry goes straight to ``awaiting_reauth`` and the person re-authenticates.

ERA RIDER. Whether a given realm honours this exchange differs by deployment and by era
(see the plan's "Era rider" section). It must be re-probed at any deployment before its
settings are believed; a green unit test against a double says nothing about a realm.

EVERY FAILURE IS None. The caller cannot do anything different with a timeout than with a
refusal, so both are None and both log the exception TYPE or the HTTP status only: a
response body, a request body and the token never reach a log line.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["exchange", "entitlement_of"]

_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"
_TIMEOUT_SECONDS = 10.0

_unset_logged = False


def _settings() -> Optional[tuple]:
    url = os.getenv("IDENTITY_EXCHANGE_TOKEN_URL", "").strip()
    cid = os.getenv("IDENTITY_EXCHANGE_CLIENT_ID", "").strip()
    secret = os.getenv("IDENTITY_EXCHANGE_CLIENT_SECRET", "").strip()
    if not (url and cid and secret):
        return None
    return url, cid, secret


def _claims_of(token: str) -> Optional[dict]:
    """The payload of a JWT, read WITHOUT verifying it. The answer came straight from the
    issuer's token endpoint over the authenticated call; what is read here decides whether
    to accept it as the SAME person's, and the engines verify the signature on use."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims if isinstance(claims, dict) else None
    except Exception:  # noqa: BLE001 -- unreadable means unusable
        return None


def entitlement_of(token: str) -> Optional[str]:
    """The entitlement identity of a token, named exactly as the gateway names it: the
    ``USER_ENTITLEMENT_CLAIM`` claim with ``sub`` as the fallback (``auth.resolve_token_identity``).
    None when unreadable or absent."""
    claims = _claims_of(token)
    if claims is None:
        return None
    from .auth import resolve_token_identity  # lazy: auth pulls the authz stack
    try:
        return str(resolve_token_identity(claims)[1])
    except ValueError:
        return None


async def exchange(subject_token: str) -> Optional[str]:
    """Ask Keycloak for a fresh access token for the person who holds ``subject_token``.

    Returns the new token, or None when the exchange is not configured, fails, or answers
    with a token that is not for the same entitlement identity or does not outlive the one
    presented."""
    global _unset_logged
    cfg = _settings()
    if cfg is None:
        if not _unset_logged:
            _unset_logged = True
            logger.info("identity_exchange: not configured (IDENTITY_EXCHANGE_TOKEN_URL / "
                        "_CLIENT_ID / _CLIENT_SECRET); near-expiry goes to awaiting_reauth")
        return None
    url, cid, secret = cfg
    if not subject_token:
        return None

    form = {
        "grant_type": _GRANT,
        "subject_token": subject_token,
        "subject_token_type": _ACCESS_TOKEN,
        "requested_token_type": _ACCESS_TOKEN,
        "client_id": cid,
        "client_secret": secret,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, data=form)
    except Exception as exc:  # noqa: BLE001 -- any failure is None; log the type only
        logger.warning("identity_exchange: failed (%s)", type(exc).__name__)
        return None
    if resp.status_code != 200:
        logger.warning("identity_exchange: refused (HTTP %s)", resp.status_code)
        return None
    try:
        new = resp.json().get("access_token")
    except Exception:  # noqa: BLE001
        logger.warning("identity_exchange: answer was not JSON")
        return None
    if not isinstance(new, str) or not new:
        logger.warning("identity_exchange: answer carried no access_token")
        return None

    # The answer must be for the SAME person and must outlive what it replaces.
    if entitlement_of(new) is None or entitlement_of(new) != entitlement_of(subject_token):
        logger.error("identity_exchange: REFUSED the answer — its entitlement identity "
                     "differs from the subject token's")
        return None
    old_claims, new_claims = _claims_of(subject_token) or {}, _claims_of(new) or {}
    new_exp, old_exp = new_claims.get("exp"), old_claims.get("exp")
    floor = float(old_exp) if isinstance(old_exp, (int, float)) else time.time()
    if not isinstance(new_exp, (int, float)) or float(new_exp) <= floor:
        logger.warning("identity_exchange: REFUSED the answer — it does not outlive the "
                       "token presented")
        return None
    return new
