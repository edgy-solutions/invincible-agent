"""Direct HITL-postgres seal: prove human_task_projection register->see->act on
PG17 WITHOUT depending on the flaky LLM router to produce a denial (LEG 1 of the
full-loop seal is a ROUTER test; this isolates the Postgres/Restate HITL path).

  agent-user POST /access_requests {asset, domain}  -> human_task_projection rows
  alice      GET  /me/human_tasks                    -> sees it (reads projection)
  alice      POST /human_tasks/{id}/act approved     -> resolve + grant_sync
"""
from __future__ import annotations
import asyncio, json, os, httpx
import mesh_client as mc

ASSET = os.getenv("SEAL_ASSET",
    "urn:li:dataset:(urn:li:dataPlatform:dagster,mesh_demo_customers,PROD)")
DOMAIN = "DATA_ENGINEERING"

async def token(client, user, pw):
    r = await client.post(f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token",
        data={"client_id": mc.CLIENT_ID, "grant_type": "password",
              "username": user, "password": pw}, timeout=15.0)
    r.raise_for_status(); return r.json()["access_token"]

async def main():
    async with httpx.AsyncClient() as c:
        au = await token(c, "agent-user", "password")
        al = await token(c, os.getenv("ALICE_USER","alice"), os.getenv("ALICE_PASS","alice"))
        print(f"ASSET = {ASSET}\n")

        print("=== LEG A: agent-user POST /access_requests (register HumanTask) ===")
        rr = await c.post(f"{mc.BFF_URL}/access_requests",
            headers={"Authorization": f"Bearer {au}"},
            json={"asset": ASSET, "domain": DOMAIN, "reason": "hitl-direct seal"}, timeout=30.0)
        print(f"  status={rr.status_code} body={rr.text[:200]}")
        rr.raise_for_status()
        req_id = rr.json().get("request_id")
        print(f"  request_id={req_id} approvers={rr.json().get('approvers')}")

        print("\n=== LEG B: alice GET /me/human_tasks (read projection) ===")
        tasks = (await c.get(f"{mc.BFF_URL}/me/human_tasks",
            headers={"Authorization": f"Bearer {al}"}, timeout=30.0)).json()
        rows = tasks.get("tasks", [])
        print(f"  alice sees {len(rows)} task(s)")
        match = next((t for t in rows if t.get("task_id")==req_id), None) \
             or next((t for t in rows if ASSET in json.dumps(t)), None)
        legB = match is not None
        print(f"  found our task: {legB}")

        legC = False
        if match:
            print("\n=== LEG C: alice POST /act approved (resolve + grant) ===")
            act = await c.post(f"{mc.BFF_URL}/human_tasks/{match['task_id']}/act",
                headers={"Authorization": f"Bearer {al}"},
                json={"decision":"approved","comment":"hitl-direct seal"}, timeout=60.0)
            print(f"  act status={act.status_code} body={act.text[:200]}")
            legC = act.status_code == 200

        print("\n================ HITL-DIRECT VERDICT ================")
        legA = bool(req_id)
        print(f"  LEG A register (write projection): {'PASS' if legA else 'FAIL'}")
        print(f"  LEG B alice sees (read projection): {'PASS' if legB else 'FAIL'}")
        print(f"  LEG C alice acts (resolve): {'PASS' if legC else 'FAIL'}")
        print(f"SEAL: {'GREEN' if all([legA,legB,legC]) else 'RED'}")

if __name__ == "__main__":
    asyncio.run(main())
