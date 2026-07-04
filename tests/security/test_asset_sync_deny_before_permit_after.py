#!/usr/bin/env python3
"""ADR-0025 enforcement HOP 1 — the red-first integration probe.

The whole point of the DataHub→Topaz directory sync is that Topaz can only
answer `can_read(user, dataset)` if its directory HOLDS the owner relation.
This probe proves the seam end-to-end against a LIVE Topaz directory:

  DENY-BEFORE-SEED  — can_read(user, dataset) is FALSE before the owner
                      relation exists (empty directory → deny-all, the
                      state the enforcement arc must not ship blind).
  PERMIT-AFTER      — after sync_assets seeds `dataset#owner@user`,
                      can_read is TRUE.

That before/after flip IS the proof the sync makes the decider decide.
Uses a SYNTHETIC test URN + user so it never touches real data and cleans
up after itself. Deploy-gated (needs a running Topaz), like the real-token
entitlement probe — the assertion is inherently about a live directory.

Run (port-forward or in-cluster):
    kubectl port-forward -n sandbox svc/iagent-neo4j ... (no)
    TOPAZ_DIRECTORY_URL=http://localhost:9393 \
    PYTHONPATH=policy/sync:src python tests/security/test_asset_sync_deny_before_permit_after.py

Exit 0 = deny-before-seed AND permit-after both held. Non-zero = the seam
is broken (either the directory permits without the relation — a bypass —
or the relation doesn't grant can_read — the sync is inert).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parents[2] / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

import httpx  # noqa: E402
from topaz_sync import TopazClient, DirObject, DirRelation  # noqa: E402
from datahub_topaz_sync import AssetRecord, sync_assets  # noqa: E402

TOPAZ_URL = os.getenv("TOPAZ_DIRECTORY_URL", "http://localhost:9393")
TEST_URN = "urn:li:dataset:(urn:li:dataPlatform:probe,__hop1_probe_asset,PROD)"
TEST_USER = "__hop1_probe_user"


def _can_read(user: str, dataset_urn: str) -> bool:
    """General can_read permission check (the cell-specific one in
    topaz_sync is hardcoded to cells; hop 1 checks the dataset type)."""
    r = httpx.post(
        f"{TOPAZ_URL.rstrip('/')}/api/v3/directory/check/permission",
        json={
            "object_type": "dataset",
            "object_id": dataset_urn,
            "permission": "can_read",
            "subject_type": "user",
            "subject_id": user,
        },
        timeout=10.0,
    )
    r.raise_for_status()
    return bool(r.json().get("check", False))


def main() -> int:
    print("=== HOP 1 deny-before-seed / permit-after ===")
    client = TopazClient(TOPAZ_URL)
    # Ensure a clean slate for the synthetic ids.
    try:
        client.delete_object(DirObject("dataset", TEST_URN))
    except Exception:
        pass

    failures = 0
    try:
        # DENY BEFORE SEED — no owner relation yet.
        client.set_object(DirObject("user", TEST_USER))  # subject must exist
        before = _can_read(TEST_USER, TEST_URN)
        if before:
            print(f"  [FAIL] can_read TRUE before seeding — the directory "
                  f"permits without an owner relation (a bypass).")
            failures += 1
        else:
            print("  [PASS] deny-before-seed: can_read is FALSE with no relation.")

        # SEED via the real sync path.
        sync_assets(client, [AssetRecord(urn=TEST_URN, owners=(TEST_USER,))])

        # PERMIT AFTER.
        after = _can_read(TEST_USER, TEST_URN)
        if not after:
            print(f"  [FAIL] can_read FALSE after seeding — the owner "
                  f"relation didn't grant can_read (the sync is inert).")
            failures += 1
        else:
            print("  [PASS] permit-after: can_read is TRUE once seeded.")
    finally:
        # Cleanup synthetic ids (never leave probe data in the directory).
        try:
            client.delete_relation(DirRelation(
                object_type="dataset", object_id=TEST_URN, relation="owner",
                subject_type="user", subject_id=TEST_USER,
            ))
            client.delete_object(DirObject("dataset", TEST_URN))
            client.delete_object(DirObject("user", TEST_USER))
        except Exception as exc:  # noqa: BLE001
            print(f"  (cleanup warning: {exc})")
        client.close()

    print(f"=== {2 - failures}/2 checks passed ===")
    if failures:
        print("The deny-before-seed/permit-after seam is broken — the sync "
              "either doesn't gate (bypass) or doesn't grant (inert).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
