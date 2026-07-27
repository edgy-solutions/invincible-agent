"""Seal server-side canvas persistence: PUT then GET /me/canvases round-trips a
user's canvases through the gateway + Postgres. Run with the keycloak (18083) +
cortex-bff (18090) port-forwards open."""
from __future__ import annotations

import asyncio
import json

import httpx

import mesh_client as mc


async def token(client, user, pw):
    r = await client.post(
        f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token",
        data={"client_id": mc.CLIENT_ID, "grant_type": "password",
              "username": user, "password": pw}, timeout=15.0)
    r.raise_for_status()
    return r.json()["access_token"]


async def main() -> None:
    canvases = [
        {
            "id": "seal-canvas-1",
            "name": "Persistence Seal",
            "use": "relationship",
            "items": [{"id": "answer-abc", "x": 120, "y": 240}],
        }
    ]
    async with httpx.AsyncClient() as client:
        tok = await token(client, "alice", "alice")
        h = {"Authorization": f"Bearer {tok}"}

        put = await client.put(f"{mc.BFF_URL}/me/canvases", headers=h,
                               json={"canvases": canvases}, timeout=30.0)
        print(f"PUT status={put.status_code} body={put.text[:200]}")
        put.raise_for_status()

        got = await client.get(f"{mc.BFF_URL}/me/canvases", headers=h, timeout=30.0)
        print(f"GET status={got.status_code}")
        got.raise_for_status()
        back = got.json().get("canvases", [])
        print(f"GET canvases={json.dumps(back)[:400]}")

    ok = (
        isinstance(back, list)
        and len(back) == 1
        and back[0].get("id") == "seal-canvas-1"
        and back[0].get("use") == "relationship"
        and back[0].get("items", [{}])[0].get("id") == "answer-abc"
    )
    print(f"\nSEAL: {'GREEN' if ok else 'RED'} (round-trip {'preserved' if ok else 'MISMATCH'})")


if __name__ == "__main__":
    asyncio.run(main())
