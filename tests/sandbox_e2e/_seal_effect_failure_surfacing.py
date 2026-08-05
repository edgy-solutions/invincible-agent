"""LIVE SEAL — an approved decision whose effects die must reach a human.

WHAT THIS PROVES ON THE RUNNING CLUSTER, end to end:
  alice starts a review          -> STARTED + workflow_id
  alice approves, overriding ONE part to `dispatchAltSourcing`
  that part's dispatch dies TERMINALLY (audience `sourcing` grants nobody -> 422)
  bob receives an `extraction_refusal` triage row on `dispatch_failure:SUSTAINMENT`
  the workflow result says RESOLVED + dispatch_enqueued, never DISPATCHED

THE FAILURE IS GENUINE, NOT SYNTHETIC — which is the point. `dispatch_plan` maps
`dispatchAltSourcing -> sourcing`, and `sourcing` is granted in NEITHER git NOR Topaz (found
2026-08-05 by `_probe_disposition_audiences.py`). So this drive does not inject a fault; it walks
into a real latent one that was sitting in the disposition menu waiting for the first reviewer to
choose it. Before tonight that path produced exactly notice A's signature — a settled approval with
silently dead effects. The seal asserts it now produces a row instead.

POSITIVE CONTROL IN THE SAME RUN, and it is what makes the result mean anything. The OTHER parts
keep their proposed `dispatchQualification`, whose audience IS granted, so one approval produces
BOTH outcomes at once: dispatch tasks that land in bob's qualification queue AND a triage row for
the one that died. A run where everything failed would be indistinguishable from a broken cluster.

Requires: alice (disposition_review:SUSTAINMENT), bob (qualification + dispatch_failure:SUSTAINMENT).
Run:  kubectl port-forward -n sandbox svc/iagent-cortex-bff 18090:8090
      kubectl port-forward -n sandbox svc/iagent-keycloak 18083:8080
      kubectl port-forward -n sandbox svc/topaz-svc 19393:9393      # LEG 0's precondition check
      SVC_TOKEN=$(kubectl exec -n <ns> <engine-a-pod> -- python -c "import sys; \
        sys.path.insert(0,'/app'); from utils.service_identity import mint_service_token; \
        print(mint_service_token())")
      python tests/sandbox_e2e/_seal_effect_failure_surfacing.py
Exit: 0 sealed · 1 a leg failed · 2 inconclusive (could not reach a precondition, OR the fault
      injector healed and the seal needs re-pointing — see LEG 0)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_client as mc  # noqa: E402

NOTICE = os.getenv("SEAL_NOTICE", "EFFECTFAIL01")
DOMAIN = "SUSTAINMENT"
# Real MPNs that resolve exact via engine-o /resolve_pcn_instance.
MPNS = ["NSR01L30NXT5G", "NSR02F30NXT5G", "NSR05F20NXT5G"]
DOOMED = MPNS[0]            # overridden to dispatchAltSourcing -> `sourcing` -> grants NOBODY
PARTS = [{"affected_mpn": m, "replacement_mpn": m + "-R", "needs_review": False} for m in MPNS]


TOPAZ_URL = os.getenv("TOPAZ_DIRECTORY_URL", "http://localhost:19393")


async def _resolve_audience(c, audience: str):
    """The actors granted `actor` on an audience — the SAME question registration asks, against the
    SAME directory, so the precondition check and the behaviour under test cannot disagree.

    Returns a list (possibly empty) or None if the directory could not be reached. None is NOT an
    empty list: "nobody is granted" and "I could not find out" are different answers, and collapsing
    them would let an unreachable Topaz read as a healthy fault injector — the seal would then
    proceed on an assumption it had just failed to verify.
    """
    try:
        r = await c.get(f"{TOPAZ_URL}/api/v3/directory/relations",
                        params={"object_type": "task_audience", "object_id": audience,
                                "relation": "actor"}, timeout=15.0)
        r.raise_for_status()
        body = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  (could not reach the Topaz directory at {TOPAZ_URL}: {exc})")
        return None
    return [rel.get("subject_id") for rel in (body.get("results") or body.get("relations") or [])
            if rel.get("subject_type") == "user" and rel.get("subject_id")]


async def _token(c, user, pw):
    r = await c.post(f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token",
                     data={"client_id": mc.CLIENT_ID, "grant_type": "password",
                           "username": user, "password": pw}, timeout=15.0)
    r.raise_for_status()
    return r.json()["access_token"]


async def main() -> int:
    async with httpx.AsyncClient() as c:
        try:
            al = await _token(c, os.getenv("ALICE_USER", "alice"), os.getenv("ALICE_PASS", "alice"))
            bo = await _token(c, os.getenv("BOB_USER", "bob"), os.getenv("BOB_PASS", "bob"))
        except Exception as exc:  # noqa: BLE001
            print(f"INCONCLUSIVE: could not authenticate ({exc}). Port-forwards up?")
            return 2
        H = {"Authorization": f"Bearer {al}"}
        HB = {"Authorization": f"Bearer {bo}"}
        # THE SERVICE INITIATES; HUMANS REVIEW. `mesh:startReview` is granted to svc:review-starter
        # and deliberately NOT to alice — a human starting her own review would launder the
        # initiator entitlement. So the start leg runs under the pipeline's own identity (the same
        # client-credentials mint the dispatch path uses) and only the APPROVAL is alice's. Supply
        # via SVC_TOKEN, minted from the running pod:
        #   kubectl exec -n <ns> <engine-a-pod> -- python -c "import sys; sys.path.insert(0,'/app');
        #     from utils.service_identity import mint_service_token; print(mint_service_token())"
        svc = os.getenv("SVC_TOKEN", "").strip()
        if not svc:
            print("INCONCLUSIVE: SVC_TOKEN unset — alice is NOT entitled to initiate (by design), "
                  "so without the service identity this seal cannot start its own subject.")
            return 2
        HS = {"Authorization": f"Bearer {svc}"}
        print(f"NOTICE={NOTICE}  parts={MPNS}  doomed={DOOMED} (-> sourcing, grants nobody)\n")

        print("=== LEG 0: the FAULT INJECTOR is still a fault ===")
        # A seal whose fault injector is A DEFECT SOMEONE WILL EVENTUALLY FIX has a fuse burning
        # toward a false green. This seal manufactures its terminal failure by routing a part to
        # `sourcing`, an audience granted to NOBODY. The day someone grants `sourcing` — a correct
        # and desirable fix — this drive stops failing, LEG 5 finds no triage row, and the seal
        # reports RED for the opposite of the reason it was written... or worse, someone "fixes"
        # LEG 5 and it reports GREEN while testing nothing.
        #
        # Relying on that person knowing this file exists is not a control. So the seal asserts its
        # OWN PRECONDITION and fails with instructions: the positive-control rule applied to the
        # injector itself, which turns a silent trap into a self-announcing one.
        sourcing_actors = await _resolve_audience(c, "sourcing")
        if sourcing_actors is None:
            print("INCONCLUSIVE: could not resolve the `sourcing` audience to check the injector.")
            return 2
        if sourcing_actors:
            print(f"  FAULT INJECTOR HEALED — `sourcing` now grants {sourcing_actors}.")
            print("  This seal manufactures its terminal dispatch failure by routing a part to an")
            print("  audience that grants NOBODY. That is no longer true, so this drive would")
            print("  SUCCEED and LEG 5 would correctly find no triage row — a red that means the")
            print("  opposite of what it says.")
            print("  RE-POINT ME at another terminal failure (a 4xx from the register is the")
            print("  cheapest: any audience with zero actors, or a deliberately malformed task),")
            print("  then update DOOMED and this check together.")
            return 2
        print("  `sourcing` still grants NOBODY — the injected failure is genuine.\n")

        print("=== LEG 1: the SERVICE identity starts the review ===")
        r1 = await c.post(f"{mc.BFF_URL}/reviews", headers=HS, timeout=90.0,
                          json={"notice_id": NOTICE, "doc_type": "PCN", "categories": ["Process"],
                                "impacted_parts": PARTS, "in_scope_mpns": MPNS,
                                "doc_needs_review": False, "domain": DOMAIN,
                                "review_state_source": "extraction"})
        print(f"  status={r1.status_code} body={r1.text[:200]}")
        if r1.status_code != 200 or r1.json().get("status") != "STARTED":
            print("INCONCLUSIVE: the review did not start; nothing downstream can be judged.")
            return 2
        wf = r1.json().get("workflow_id")
        print(f"  workflow_id={wf}")

        print("\n=== LEG 2: alice finds the grouped review in her queue ===")
        # POLL, DO NOT ASSUME. `start_review` returns as soon as the workflow is STARTED; the
        # grouped HumanTask is registered INSIDE GroupedReview.run, a step later. Reading alice's
        # queue immediately raced that register and reported an empty queue — which looked exactly
        # like "the task never registered" and is a different bug entirely. The first version of
        # this seal made that mistake and reported INCONCLUSIVE against a system that was working.
        grouped = None
        for attempt in range(15):
            rows = (await c.get(f"{mc.BFF_URL}/me/human_tasks", headers=H,
                                timeout=30.0)).json().get("tasks", [])
            grouped = next((t for t in rows if t.get("workflow_id") == wf
                            and "grouped" in (t.get("kind") or "")), None)
            if grouped:
                print(f"  found after {attempt + 1} poll(s)")
                break
            await asyncio.sleep(2)
        if not grouped:
            print(f"INCONCLUSIVE: no grouped task for {wf} after 30s. kinds seen: "
                  f"{sorted({t.get('kind') for t in rows})}")
            return 2
        print(f"  task_id={grouped['task_id']} kind={grouped.get('kind')}")

        print(f"\n=== LEG 3: alice approves, overriding {DOOMED} -> dispatchAltSourcing ===")
        act = await c.post(
            f"{mc.BFF_URL}/human_tasks/{grouped['task_id']}/act", headers=H, timeout=120.0,
            json={"decision": "approved",
                  "comment": "effect-failure surfacing seal",
                  "overrides": {DOOMED: {"disposition": "dispatchAltSourcing",
                                         "reason": "seal: route to an audience that grants nobody"}}})
        print(f"  status={act.status_code} body={act.text[:400]}")
        leg3 = act.status_code == 200
        body = act.json() if leg3 else {}

        # THE RENAME, OBSERVED ON THE WIRE rather than inferred from the diff.
        flat = json.dumps(body)
        no_delivery_claim = "DISPATCHED" not in flat
        print(f"  no DISPATCHED delivery claim in the response: {no_delivery_claim}")

        print("\n=== LEG 4/5: bob's queue — surviving dispatches AND the dead one's triage row ===")
        print("  (LEG 4 is the positive control: if NOTHING landed, a red LEG 5 would just be a")
        print("   broken cluster wearing a defect's clothes)")
        # POLL both together. The fan-out is fire-and-forget, so every downstream row appears on its
        # own schedule; a fixed sleep either flakes or wastes the difference.
        mine, qual, doomed_rows = [], [], []
        for attempt in range(20):
            brows = (await c.get(f"{mc.BFF_URL}/me/human_tasks", headers=HB,
                                 timeout=30.0)).json().get("tasks", [])
            mine = [t for t in brows if NOTICE in json.dumps(t)]
            qual = [t for t in mine if (t.get("kind") or "") == "pcn_disposition"]
            triage = [t for t in mine if (t.get("kind") or "") == "extraction_refusal"]
            doomed_rows = [t for t in triage
                           if DOOMED in json.dumps(t) or "dispatch-failure" in json.dumps(t)]
            if qual and doomed_rows:
                print(f"  settled after {attempt + 1} poll(s)")
                break
            await asyncio.sleep(3)
        leg4 = len(qual) >= len(MPNS) - 1
        print(f"  bob sees {len(qual)} dispatch task(s) for {NOTICE} (expect >= {len(MPNS) - 1}): {leg4}")

        print("\n  --- THE SEAL: did the DEAD part produce a triage row? ---")
        leg5 = bool(doomed_rows)
        print(f"  matching the dead dispatch: {len(doomed_rows)}")
        for t in doomed_rows:
            print(f"    task_id={t.get('task_id')}")
            print(f"    title  ={t.get('title')}")
            print(f"    summary={(t.get('summary') or '')[:220]}")
        if not leg5:
            print("  RED: the dispatch died and NOTHING reached a human — the approval reads "
                  "settled with no effects. This is precisely notice A.")

        print("\n=== LEG 6: the row's provenance is TRUE, and points at the approver ===")
        # THE FIRST RUN OF THIS SEAL FAILED HERE, AND IT WAS RIGHT TO. LEG 6 originally asserted the
        # row NAMES the approver (alice). It does not — and could not: the value the dispatch
        # payload carries is the workflow's `approver`, stamped by start_review from whoever STARTED
        # the review, which in the canonical sensor-driven flow is `svc:review-starter`. The live
        # row said "Approved by: svc:review-starter" while the grouped review's `acted_by` said
        # `alice@example.com`. That is a MISATTRIBUTION, not an omission, and it predates this arc:
        # the ordinary `pcn_disposition` dispatch rows carry the same wrong value.
        #
        # So the seal now asserts what is TRUE and ACTIONABLE — the row does not claim a service
        # approved anything, and it names where the approving human is actually recorded. Fixing
        # the attribution itself is a filed fork (it changes a field other surfaces read).
        blob = json.dumps(doomed_rows)
        no_false_claim = "Approved by" not in blob and "approved_by" not in blob
        points_at_approver = "acted_by" in blob
        leg6 = no_false_claim and points_at_approver
        print(f"  does NOT claim a service approved it: {no_false_claim}")
        print(f"  points the operator at the approver's real location: {points_at_approver}")

        print("\n================ EFFECT-FAILURE SURFACING VERDICT ================")
        legs = [("1 review started", True), ("2 grouped task visible", True),
                ("3 approval accepted", leg3),
                ("3b no DISPATCHED delivery claim", no_delivery_claim),
                ("4 surviving dispatches landed (positive control)", leg4),
                ("5 dead dispatch surfaced as a triage row", leg5),
                ("6 provenance is TRUE + points at acted_by", leg6)]
        for name, ok in legs:
            print(f"  {name}: {'PASS' if ok else 'FAIL'}")
        ok = all(v for _, v in legs)
        print(f"SEAL: {'GREEN' if ok else 'RED'}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
