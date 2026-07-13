"""Bug 2 FULL-LOOP live seal: deny -> request -> approve -> granted -> works.

Subjects (Keycloak seed: passwords match usernames):
  - agent-user (agent@example.com) : DATA_ENGINEERING, NOT granted the asset
  - alice      (alice@example.com)  : approver for access_grant:DATA_ENGINEERING

Legs:
  1. agent-user queries -> DA-read 403 -> typed access_denied event (denied asset)
  2. agent-user POST /access_requests {asset, domain} -> pending HumanTask (=alice's)
  3. alice GET /me/human_tasks, finds it, POST /act approved -> grant_sync writes reader
  4. agent-user RE-queries -> NO denial, real data (the grant took effect)

Run with port-forwards: keycloak 18083, cortex-bff 18090.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx

import mesh_client as mc

# LEG 1 IS A ROUTER TEST, NOT A POSTGRES/HITL TEST — and it is inherently flaky on
# gpt-oss. Getting a DA-read denial requires the LLM to BOTH resolve a gated dataset
# INSTANCE and classify the analyzeDataset VERB. Naming the dataset (below) improves
# the odds vs a generic phrasing, but does NOT make it deterministic: gpt-oss still
# fumbles instance-resolution (subject falls back to the "Dataset" CLASS) and verb-
# classification (no_verb_classified -> Engine A generalist fallback -> no gate ->
# no denial). That brittleness is banked (resolve_phrasing_sensitivity,
# resolve_instance_provider_gap, recipe_v2_preemption) and is ORTHOGONAL to Postgres.
#
# => For a DETERMINISTIC proof of the HITL/human_task_projection Postgres path
#    (register -> alice-sees -> act -> grant), use _seal_hitl_direct.py, which
#    injects a known gated asset and does NOT depend on the router. This full-loop
#    seal remains the ROUTER-INCLUSIVE end-to-end happy path; treat a LEG-1 RED as
#    "the router didn't route today", not a HITL/Postgres regression, and confirm
#    via _seal_hitl_direct.py.
QUERY = os.getenv(
    "SEAL_QUERY",
    "show me the data in the mesh_demo_customers dataset",
)


async def token(client, user, pw):
    r = await client.post(
        f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token",
        data={"client_id": mc.CLIENT_ID, "grant_type": "password",
              "username": user, "password": pw}, timeout=15.0)
    r.raise_for_status()
    return r.json()["access_token"]


def denials(res):
    return [e for e in res["events"] if e["event"] == "access_denied"]


async def main() -> None:
    print(f"QUERY = {QUERY!r}\n")
    async with httpx.AsyncClient() as client:
        au = await token(client, "agent-user", "password")
        al = await token(client, os.getenv("ALICE_USER", "alice"),
                         os.getenv("ALICE_PASS", "alice"))

        # ---- Leg 1: DENY ---------------------------------------------------
        print("=== LEG 1: agent-user query (expect DENY) ===")
        r1 = await mc.orchestrate(client, au, QUERY, session_prefix="loop-deny",
                                  print_status=False, timeout_s=600.0)
        d1 = denials(r1)
        print(f"  access_denied events: {len(d1)}")
        if not d1:
            print("  LEG 1 FAIL: no access_denied event -> abort")
            print("SEAL: RED")
            return
        denial = d1[0]["data"]
        asset = (denial.get("denied_assets") or [None])[0]
        domain = denial.get("domain") or "DATA_ENGINEERING"
        print(f"  denied asset = {asset}")
        print(f"  domain       = {domain}")

        # ---- Leg 2: REQUEST ------------------------------------------------
        print("\n=== LEG 2: agent-user POST /access_requests ===")
        rr = await client.post(
            f"{mc.BFF_URL}/access_requests",
            headers={"Authorization": f"Bearer {au}"},
            json={"asset": asset, "domain": domain,
                  "reason": "full-loop seal"}, timeout=30.0)
        print(f"  status={rr.status_code} body={rr.text[:200]}")
        rr.raise_for_status()
        req = rr.json()
        req_id = req.get("request_id")
        print(f"  request_id={req_id} approvers={req.get('approvers')}")

        # ---- Leg 3: APPROVE (as alice) ------------------------------------
        print("\n=== LEG 3: alice approves ===")
        tasks = (await client.get(
            f"{mc.BFF_URL}/me/human_tasks",
            headers={"Authorization": f"Bearer {al}"}, timeout=30.0)).json()
        rows = tasks.get("tasks", [])
        print(f"  alice sees {len(rows)} task(s)")
        match = next((t for t in rows if t.get("task_id") == req_id), None)
        if match is None:
            # fall back: match by asset in payload/subject_ref
            match = next((t for t in rows
                          if asset in json.dumps(t)), None)
        if match is None:
            print("  LEG 3 FAIL: alice does not see the access request -> abort")
            print("SEAL: RED")
            return
        tid = match.get("task_id")
        print(f"  approving task_id={tid}")
        act = await client.post(
            f"{mc.BFF_URL}/human_tasks/{tid}/act",
            headers={"Authorization": f"Bearer {al}"},
            json={"decision": "approved", "comment": "full-loop seal"},
            timeout=60.0)
        print(f"  act status={act.status_code} body={act.text[:250]}")
        act.raise_for_status()

        # give the grant_sync a moment to land in Topaz
        await asyncio.sleep(5)

        # ---- Leg 4: RE-QUERY (expect WORKS) -------------------------------
        print("\n=== LEG 4: agent-user RE-query (expect DATA) ===")
        r4 = await mc.orchestrate(client, au, QUERY, session_prefix="loop-allow",
                                  print_status=False, timeout_s=600.0)
        d4 = denials(r4)
        txt = r4.get("text") or ""
        print(f"  access_denied events: {len(d4)}")
        print(f"  answer text length: {len(txt)}")
        print(f"  answer head: {txt[:200]!r}")

    print("\n================ FULL-LOOP VERDICT ================")
    leg1 = bool(asset)
    leg2 = bool(req_id)
    leg3 = act.status_code == 200
    leg4 = len(d4) == 0 and len(txt) > 100
    print(f"  LEG1 deny w/ asset      : {'PASS' if leg1 else 'FAIL'}")
    print(f"  LEG2 request created    : {'PASS' if leg2 else 'FAIL'}")
    print(f"  LEG3 alice approved     : {'PASS' if leg3 else 'FAIL'}")
    print(f"  LEG4 re-query works     : {'PASS' if leg4 else 'FAIL'}")
    print(f"SEAL: {'GREEN' if all([leg1, leg2, leg3, leg4]) else 'RED'}")


if __name__ == "__main__":
    asyncio.run(main())
