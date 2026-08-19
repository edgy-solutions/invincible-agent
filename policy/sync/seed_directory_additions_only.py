"""Seed the Topaz directory from DataHub -- ADDITIONS ONLY (prune disabled).

WHY THIS EXISTS SEPARATELY FROM ``main()``. ``datahub_topaz_sync.main()`` calls
``sync_assets(prune=True)``. Measured against sandbox on 2026-08-18, that would DELETE
    urn:li:dataset:(urn:li:dataPlatform:dagster,mesh_demo_customers,PROD)
because DataHub no longer returns it -- and `policy/asset_grants.yaml` holds a grant that
REFERENCES it. `grant_sync` refuses the WHOLE file if any grant dangles, so a pruning seed
would trade one applied grant for none. Additions-only is the safe first pass: +4 objects
(the s3/publog datasets incl. p_cage), 0 deletions.

Once the grants are applied and the demo-fixture grant is either retired or its dataset is
back in DataHub, the normal pruning `main()` is the right steady-state entry point.

Run:  python seed_directory_additions_only.py
Env:  DATAHUB_GMS_URL, DATAHUB_TOKEN, TOPAZ_DIRECTORY_URL
"""
import os
import sys

from datahub_topaz_sync import fetch_datahub_assets, sync_assets, readback_assets
from topaz_sync import TopazClient


def main() -> int:
    datahub_url = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080/api/graphql")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    assets = fetch_datahub_assets(datahub_url)
    print(f"fetched {len(assets)} datasets from DataHub")
    if not assets:
        # Same guard as main(): an auth failure or a network blip returns [] and is
        # INDISTINGUISHABLE from "no datasets" -- a fetch failure must never drive a write.
        print("no assets - refusing to sync (a fetch failure must not seed or prune).")
        return 1

    with TopazClient(topaz_url) as client:
        plan, report = sync_assets(client, assets, prune=False)
        print(
            f"ADDED:   +{len(plan.add_objects)} objects, "
            f"+{len(plan.add_relations)} owner relations"
        )
        print(
            f"DELETED: -{len(plan.del_objects)} objects, "
            f"-{len(plan.del_relations)} relations  (expected 0 - prune is OFF)"
        )
        if report.snapshot_degraded:
            print(f"DEGRADED snapshot: {report.snapshot_degraded}")
        for item, reason in report.rejected:
            print(f"  [SKIP] {item}\n         topaz said: {reason}")

        print("===== Readback (positive control) =====")
        checked, failures = readback_assets(
            client, assets,
            skip_urns=report.rejected_dataset_urns,
            skip_owners=report.rejected_owner_ids,
        )
        print(f"  checked={checked}  failures={failures}")
        if failures:
            print("FAIL: seeded relations don't resolve - the apply lied.", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
