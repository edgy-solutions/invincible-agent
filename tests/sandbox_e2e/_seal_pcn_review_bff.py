"""PCN review through the BFF — composed-path seal (the five-beats spine via cortex-bff, not raw ingress).

Proves the BFF review wiring end to end on the live cluster:
  alice POST /pcn/reviews {extraction payload}     -> start_review -> STARTED + workflow_id
  alice GET  /me/human_tasks                        -> grouped review task carries workflow_id (the blocker fix)
  alice POST /human_tasks/{grouped}/act approved    -> BRIDGE -> submit_decision -> fan-out (review_dispatched)
  bob   GET  /me/human_tasks                        -> the dispatch tasks landed in the qualification queue
NEGATIVE (proves it bites): a doc_needs_review=true request with no part carrying it -> 422
  REVIEW_STATE_UNSOURCED (the tripwire fires THROUGH the BFF; the BFF forwards the extraction fields, and
  never reconstructs impacted_parts from a graph).

Uses a FRESH notice_id (SEAL-<n>) so the durable workflow key doesn't collide with prior IPCN25300X runs —
the residue ruling in practice: fresh key = fresh run. Requires the personas from the loop seal
(alice=pcn_disposition:SUSTAINMENT reviewer, bob=qualification) already granted.
"""
from __future__ import annotations
import asyncio, json, os, httpx
import mesh_client as mc

NOTICE = os.getenv("SEAL_NOTICE", "PCNBFFSEAL01")
DOMAIN = "SUSTAINMENT"
# Real MPNs that resolve exact via engine-o /resolve_pcn_instance (score 1.0).
MPNS = ["NSR01L30NXT5G", "NSR02F30NXT5G", "NSR05F20NXT5G"]
PARTS = [{"affected_mpn": m, "replacement_mpn": m + "-R", "needs_review": False} for m in MPNS]


async def token(client, user, pw):
    r = await client.post(f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token",
        data={"client_id": mc.CLIENT_ID, "grant_type": "password",
              "username": user, "password": pw}, timeout=15.0)
    r.raise_for_status(); return r.json()["access_token"]


async def main():
    async with httpx.AsyncClient() as c:
        al = await token(c, os.getenv("ALICE_USER", "alice"), os.getenv("ALICE_PASS", "alice"))
        bo = await token(c, os.getenv("BOB_USER", "bob"), os.getenv("BOB_PASS", "bob"))
        H = lambda t: {"Authorization": f"Bearer {t}"}
        print(f"NOTICE = {NOTICE}, parts = {MPNS}\n")

        print("=== LEG 1: alice POST /pcn/reviews (start via BFF) ===")
        r1 = await c.post(f"{mc.BFF_URL}/pcn/reviews", headers=H(al), timeout=60.0,
            json={"notice_id": NOTICE, "doc_type": "PCN", "categories": ["Process"],
                  "impacted_parts": PARTS, "in_scope_mpns": MPNS,
                  "doc_needs_review": False, "domain": DOMAIN})
        print(f"  status={r1.status_code} body={r1.text[:240]}")
        started = r1.status_code == 200 and r1.json().get("status") == "STARTED"
        wf_from_start = r1.json().get("workflow_id") if r1.status_code == 200 else None
        leg1 = started and bool(wf_from_start)
        print(f"  STARTED + workflow_id: {leg1} ({wf_from_start})")

        print("\n=== LEG 2: alice GET /me/human_tasks (grouped review carries workflow_id) ===")
        rows = (await c.get(f"{mc.BFF_URL}/me/human_tasks", headers=H(al), timeout=30.0)).json().get("tasks", [])
        grouped = next((t for t in rows if t.get("kind") == "pcn_grouped_review"
                        and t.get("workflow_id") == wf_from_start), None)
        leg2 = grouped is not None and bool(grouped.get("workflow_id"))
        print(f"  grouped review present with workflow_id: {leg2}"
              + (f" (task_id={grouped['task_id']})" if grouped else ""))

        print("\n=== LEG 3: alice POST /act approved (BRIDGE -> submit_decision -> fan-out) ===")
        leg3 = False
        if grouped:
            a = await c.post(f"{mc.BFF_URL}/human_tasks/{grouped['task_id']}/act", headers=H(al),
                json={"decision": "approved", "comment": "bff review seal"}, timeout=90.0)
            print(f"  act status={a.status_code} body={a.text[:240]}")
            leg3 = a.status_code == 200 and a.json().get("review_dispatched") is True

        print("\n=== LEG 4: bob GET /me/human_tasks (dispatch tasks reached the qualification queue) ===")
        brows = (await c.get(f"{mc.BFF_URL}/me/human_tasks", headers=H(bo), timeout=30.0)).json().get("tasks", [])
        mine = [t for t in brows if t.get("kind") == "pcn_disposition" and NOTICE in json.dumps(t)]
        leg4 = len(mine) == len(MPNS)
        print(f"  bob sees {len(mine)} dispatch task(s) for {NOTICE} (expect {len(MPNS)}): {leg4}")

        print("\n=== NEG: unsourced request -> 422 REVIEW_STATE_UNSOURCED (tripwire through BFF) ===")
        rn = await c.post(f"{mc.BFF_URL}/pcn/reviews", headers=H(al), timeout=60.0,
            json={"notice_id": NOTICE + "-UNSRC", "doc_type": "PCN", "categories": ["Process"],
                  "impacted_parts": [{"affected_mpn": m, "replacement_mpn": "", "needs_review": False} for m in MPNS],
                  "in_scope_mpns": MPNS, "doc_needs_review": True, "domain": DOMAIN})  # doc-level set, no part carries it
        detail = rn.json().get("detail", {}) if rn.headers.get("content-type", "").startswith("application/json") else {}
        neg = rn.status_code == 422 and (detail.get("status") == "REVIEW_STATE_UNSOURCED")
        print(f"  status={rn.status_code} -> {neg} (body={rn.text[:160]})")

        print("\n================ PCN-REVIEW-BFF VERDICT ================")
        for name, ok in [("1 start via /pcn/reviews", leg1), ("2 grouped carries workflow_id", leg2),
                         ("3 /act bridges to submit_decision", leg3), ("4 dispatch reached bob", leg4),
                         ("NEG tripwire 422 through BFF", neg)]:
            print(f"  {name}: {'PASS' if ok else 'FAIL'}")
        print(f"SEAL: {'GREEN' if all([leg1, leg2, leg3, leg4, neg]) else 'RED'}")


if __name__ == "__main__":
    asyncio.run(main())
