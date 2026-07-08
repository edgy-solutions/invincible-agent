"""Shared helpers for sandbox end-to-end mesh tests.

Defaults assume two background port-forwards are open:

    kubectl -n sandbox port-forward svc/iagent-keycloak  18083:8080 &
    kubectl -n sandbox port-forward svc/iagent-cortex-bff 18090:8090 &

Override via env if you're hitting the services another way.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

import httpx

KEYCLOAK_URL = os.getenv(
    "KEYCLOAK_URL", "http://localhost:18083/realms/invincible-agent"
)
BFF_URL = os.getenv("BFF_URL", "http://localhost:18090")
USERNAME = os.getenv("KC_USER", "agent-user")
PASSWORD = os.getenv("KC_PASS", "password")
CLIENT_ID = os.getenv("KC_CLIENT_ID", "cortex-ui")


async def get_token(client: httpx.AsyncClient) -> str:
    """Fetch a Keycloak password-grant token."""
    r = await client.post(
        f"{KEYCLOAK_URL}/protocol/openid-connect/token",
        data={
            "client_id": CLIENT_ID,
            "grant_type": "password",
            "username": USERNAME,
            "password": PASSWORD,
        },
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def decode_jwt_claims(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


async def orchestrate(
    client: httpx.AsyncClient,
    token: str,
    message: str,
    *,
    session_prefix: str = "e2e",
    print_status: bool = True,
    timeout_s: float = 900.0,
) -> Dict[str, Any]:
    """POST /orchestrate, stream SSE until done, return collected result.

    Returns ``{"final": ..., "text": ..., "elapsed_s": ..., "events": [...]}``.
    ``final`` is the last ``final_response`` / ``complete`` / ``result`` event
    payload if any was emitted, otherwise ``None``.
    """
    session_id = f"{session_prefix}-{uuid.uuid4().hex[:8]}"
    if print_status:
        print(f"[mesh] session_id={session_id}")
    t0 = time.time()
    final_payload: Optional[Dict[str, Any]] = None
    final_text: Optional[str] = None
    last_status_label: Optional[str] = None
    events: list = []

    async with client.stream(
        "POST",
        f"{BFF_URL}/orchestrate",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        json={"message": message, "session_id": session_id},
        timeout=httpx.Timeout(timeout_s, connect=10.0),
    ) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            raise RuntimeError(f"orchestrate failed: {resp.status_code} {body!r}")
        cur_event: Optional[str] = None
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                cur_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                raw = line[len("data:"):].strip()
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {"raw": raw}
                elapsed = time.time() - t0
                events.append({"event": cur_event, "data": payload, "t": elapsed})
                if cur_event == "status":
                    label = payload.get("label", "") if isinstance(payload, dict) else ""
                    if print_status and label and label != last_status_label:
                        last_status_label = label
                        print(f"  [{elapsed:5.1f}s] {label}")
                elif cur_event in ("final_response", "complete", "result", "final_payload"):
                    # `final_payload` is the CURRENT cortex-bff answer event
                    # (components[].markdown_content); the older
                    # final_response/complete/result names are kept for back-compat.
                    # (Stale-harness fix 2026-07-07: the suite was checking only the
                    # old names and reporting FALSE-NEGATIVE FAILs on correct answers.)
                    final_payload = payload
                    # Also surface the answer text so the len(text)>200 check works
                    # regardless of which event shape delivered it.
                    if isinstance(payload, dict):
                        for comp in (payload.get("components") or []):
                            md = comp.get("markdown_content") if isinstance(comp, dict) else None
                            if md:
                                final_text = (final_text or "") + md
                    if print_status:
                        print(f"  [{elapsed:5.1f}s] <{cur_event}>")
                elif cur_event in ("text", "delta"):
                    chunk = (
                        payload.get("content", "")
                        if isinstance(payload, dict)
                        else str(payload)
                    )
                    final_text = (final_text or "") + chunk
                elif cur_event and print_status:
                    print(
                        f"  [{elapsed:5.1f}s] event={cur_event}: "
                        f"{json.dumps(payload)[:140]}"
                    )

    elapsed_total = time.time() - t0
    if print_status:
        print(f"[mesh] total elapsed = {elapsed_total:.1f}s")
    return {
        "final": final_payload,
        "text": final_text,
        "elapsed_s": elapsed_total,
        "events": events,
        "session_id": session_id,
    }


async def fire(message: str, *, session_prefix: str = "e2e",
               print_status: bool = True, timeout_s: float = 900.0) -> Dict[str, Any]:
    """Top-level convenience: get a token, fire one orchestrate."""
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        claims = decode_jwt_claims(token)
        if print_status:
            print(
                f"[auth] user={claims.get('preferred_username')} "
                f"persona={claims.get('persona')} "
                f"domains={claims.get('entitled_domains')}"
            )
        return await orchestrate(
            client, token, message,
            session_prefix=session_prefix,
            print_status=print_status,
            timeout_s=timeout_s,
        )


def run(message: str, **kwargs) -> Dict[str, Any]:
    """Sync wrapper for one-shot scripts."""
    return asyncio.run(fire(message, **kwargs))
