"""Diagnostic: fire the customer query as agent-user, dump EVERY event so we can
see whether it (a) got data, (b) errored, (c) routed away from the DA, or (d)
was denied without surfacing access_denied."""
from __future__ import annotations

import asyncio
import json
import os

import httpx

import mesh_client as mc

QUERY = os.getenv("SEAL_QUERY", "show me data about customers")
USER = os.getenv("DIAG_USER", "agent-user")
PW = os.getenv("DIAG_PASS", "password")


async def main() -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token",
            data={"client_id": mc.CLIENT_ID, "grant_type": "password",
                  "username": USER, "password": PW}, timeout=15.0)
        r.raise_for_status()
        tok = r.json()["access_token"]
        ent = (await client.get(f"{mc.BFF_URL}/me/entitlements",
               headers={"Authorization": f"Bearer {tok}"}, timeout=15.0)).json()
        print(f"USER={USER} email={ent.get('email')} "
              f"domains={sorted({c['domain'] for c in ent.get('cells', [])})}")
        print(f"QUERY={QUERY!r}\n")
        res = await mc.orchestrate(client, tok, QUERY, session_prefix="diag",
                                   print_status=False, timeout_s=600.0)

    print("---- EVENT SUMMARY ----")
    from collections import Counter
    kinds = Counter(e["event"] for e in res["events"])
    for k, n in kinds.most_common():
        print(f"  {k}: {n}")
    print("\n---- EVENTS (event : data head) ----")
    for e in res["events"]:
        head = json.dumps(e["data"])[:220]
        print(f"  [{e['t']:5.1f}s] {e['event']}: {head}")
    print(f"\nFINAL TEXT ({len(res.get('text') or '')} chars): "
          f"{(res.get('text') or '')[:300]!r}")


if __name__ == "__main__":
    asyncio.run(main())
