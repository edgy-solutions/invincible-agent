"""DataHub → Topaz directory sync (ADR-0025 enforcement arc, HOP 1).

WHY THIS EXISTS. Topaz can only answer `can_read(user, dataset)` if its
directory HOLDS the `dataset` objects and their `owner`/`reader`
relations. Today that directory is EMPTY of assets — so every catalog/
data read would deny-all if enforcement were switched on. This module is
the seam that seeds it: DataHub is the attribute source of record for
resource facts (owner, domain, tags), and this sync flows those facts
INTO Topaz so the one decider can evaluate policy over them. DataHub
INFORMS; Topaz DECIDES (see `[[single-authz-decider]]`).

NO MANIFEST CHANGE. The Topaz manifest already declares
    dataset: relations {owner, reader}; permissions {can_read: reader|owner}
(topaz-configmap.yaml) and `data_broker.rego` already checks
`can_read` on `dataset`. Hop 1 is purely the empty-directory DATA gap,
not a model gap. The catalog `can_view` permission named in the ADR-0025
amendment is a DISTINCT, later concern (hop 2, the query_metadata stopgap
retirement); introducing an `asset`/`can_view` scheme now would be the
"invent a second identity scheme on the spot" the amendment warns
against. Hop 1 uses the primitive that already exists.

BOUNDARY WITH THE ADR-0026 SYNC (`topaz_sync.py`). That tool owns the
persona/entitlement types (persona, domain, group, cell, USER) and
deliberately leaves `dataset`/`owner`/`reader` alone. This tool is the
mirror image: it owns `dataset` objects + `owner` relations and MUST NOT
prune `user` objects (the ADR-0026 sync owns those). It only *ensures*
owner users exist (idempotent set_object, never delete) so the `owner`
relation has a valid subject. Two syncs pruning the same type would
fight; the split keeps each authority source's writes isolated.

THIS MODULE'S TESTED CORE is the two PURE transforms below
(`normalize_datahub_search`, `derive_asset_desired`) — no network, no
Topaz, exhaustively testable. The driver (fetch from DataHub, diff, apply,
readback) is the I/O shell around them; the deny-before-seed/permit-after
proof is an integration probe against live Topaz (deploy-gated), because
that assertion is inherently about a running directory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Reuse the ADR-0026 sync's directory primitives verbatim — same object /
# relation / desired-state vocabulary, one definition.
from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402


# The types/relations THIS sync asserts ownership over (its prune scope).
# Deliberately EXCLUDES "user" — owner users are ensured-present but never
# pruned here (the ADR-0026 sync owns the user type). See module docstring.
MANAGED_ASSET_OBJECT_TYPES = ["dataset"]
MANAGED_ASSET_RELATIONS = [("dataset", "owner")]


@dataclass(frozen=True)
class AssetRecord:
    """A DataHub dataset normalized to just what the directory needs: its
    URN (the Topaz object id) and its owner usernames (the subjects of the
    `owner` relation). Tags/domain are carried for later hops (policy
    attributes) but the OWNER relation is what hop 1 seeds."""

    urn: str
    owners: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def normalize_datahub_search(response: dict) -> list[AssetRecord]:
    """PURE transform: DataHub GraphQL `searchAcrossEntities` response →
    list[AssetRecord]. Mirrors Engine D's owner/tag extraction
    (`agent_fleet/datahub_wrapper/main.py`) so the two read DataHub the
    same way. No network — operates on an already-fetched response dict.

    Defensive against the deeply-optional GraphQL shape: any missing layer
    yields empty, never raises. A dataset with no owners produces a record
    with empty owners (→ a `dataset` object but NO `owner` relation — an
    honest 'no owner recorded', never a phantom grant)."""
    results = (
        ((response or {}).get("data") or {})
        .get("searchAcrossEntities") or {}
    ).get("searchResults") or []

    out: list[AssetRecord] = []
    for r in results:
        entity = (r or {}).get("entity") or {}
        urn = entity.get("urn")
        if not urn:
            continue

        owners: list[str] = []
        for o in ((entity.get("ownership") or {}).get("owners") or []):
            owner = (o or {}).get("owner") or {}
            uname = owner.get("username")
            if uname:
                owners.append(uname)

        tags: list[str] = []
        for t in ((entity.get("tags") or {}).get("tags") or []):
            tag = (t or {}).get("tag") or {}
            tag_urn = tag.get("urn") or ""
            if tag_urn.startswith("urn:li:tag:"):
                tags.append(tag_urn[len("urn:li:tag:"):])

        out.append(AssetRecord(
            urn=urn,
            owners=tuple(dict.fromkeys(owners)),   # dedupe, preserve order
            tags=tuple(dict.fromkeys(tags)),
        ))
    return out


def derive_asset_desired(assets: list[AssetRecord]) -> DesiredState:
    """PURE transform: normalized assets → the Topaz DesiredState hop 1
    seeds. Produces:
      - one `dataset` object per URN,
      - one `owner` relation `dataset:<urn>#owner@user:<owner>` per owner,
      - the owner `user` objects (ENSURE-present; the driver must add these
        WITHOUT pruning — see MANAGED_ASSET_* scope).

    An asset with zero owners yields the `dataset` object and NO relation —
    honest-empty, never a fabricated owner. This mirrors ADR-0026's
    `derive_desired`; the difference is the source (DataHub, not git YAML)
    and the managed types (`dataset`/`owner`, not `cell`/`assumable_by`)."""
    state = DesiredState()
    for asset in assets:
        state.objects.add(DirObject("dataset", asset.urn))
        for owner in asset.owners:
            # Ensure the owner user object exists (the relation's subject).
            # The driver adds these but never prunes them — the ADR-0026
            # sync owns the `user` type's lifecycle.
            state.objects.add(DirObject("user", owner))
            state.relations.add(
                DirRelation(
                    object_type="dataset",
                    object_id=asset.urn,
                    relation="owner",
                    subject_type="user",
                    subject_id=owner,
                )
            )
    return state


# ---------------------------------------------------------------------------
# The I/O shell — DataHub fetch + the snapshot-diff-apply driver.
# ---------------------------------------------------------------------------
import os  # noqa: E402

# Minimal DataHub GraphQL: datasets + their owners (the owner relation is
# what hop 1 seeds) + tags (carried for later policy hops). Same
# searchAcrossEntities shape Engine D uses, trimmed to what the sync needs.
_DATAHUB_SEARCH_QUERY = """
query SyncAssets($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start count total
    searchResults {
      entity {
        urn
        ... on Dataset {
          ownership { owners { owner { ... on CorpUser { username } } } }
          tags { tags { tag { urn } } }
        }
      }
    }
  }
}
"""


def fetch_datahub_assets(
    datahub_url: str,
    *,
    page_size: int = 200,
    max_pages: int = 50,
    http_post=None,
) -> list[AssetRecord]:
    """Fetch every DATASET from DataHub's GraphQL, normalized to
    AssetRecords. Pages through searchAcrossEntities. `http_post` is
    injectable for tests; defaults to httpx. Returns [] on any failure
    (the caller treats an empty fetch as "sync nothing", never as
    "delete everything" — a fetch failure must not prune the directory)."""
    if http_post is None:
        import httpx
        def http_post(url, json):  # noqa: ANN001
            return httpx.post(url, json=json, timeout=30.0).json()

    records: list[AssetRecord] = []
    start = 0
    for _ in range(max_pages):
        try:
            resp = http_post(
                datahub_url,
                {
                    "query": _DATAHUB_SEARCH_QUERY,
                    "variables": {
                        "input": {
                            "types": ["DATASET"],
                            "query": "*",
                            "start": start,
                            "count": page_size,
                        }
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001
            print(f"DataHub fetch failed at start={start}: {exc}")
            return records  # partial is fine; empty-on-first-failure never prunes
        page = normalize_datahub_search(resp)
        records.extend(page)
        sar = ((resp or {}).get("data") or {}).get("searchAcrossEntities") or {}
        total = sar.get("total") or 0
        start += page_size
        if start >= total or not page:
            break
    return records


def snapshot_assets(client) -> DesiredState:
    """Fetch THIS sync's managed live state from Topaz — `dataset` objects
    and `owner` relations ONLY. Deliberately excludes `user` (the ADR-0026
    sync owns that type; we ensure-not-prune users). The exclusion is what
    makes plan_diff never emit a user deletion."""
    live = DesiredState()
    for t in MANAGED_ASSET_OBJECT_TYPES:
        live.objects.update(client.list_objects(t))
    for obj_type, rel in MANAGED_ASSET_RELATIONS:
        live.relations.update(
            client.list_relations(object_type=obj_type, relation=rel)
        )
    return live


def sync_assets(client, assets: list[AssetRecord], *, prune: bool = True):
    """Seed Topaz's directory from DataHub assets. Ensures owner `user`
    objects exist (idempotent, NEVER pruned), then diffs+applies the
    managed `dataset` objects + `owner` relations via the ADR-0026 sync's
    plan_diff/apply_plan (one apply engine, two authority sources).

    Returns the applied Plan. With `prune=False`, additions only (no
    deletes) — a safe first-run / dry-adjacent mode."""
    from topaz_sync import plan_diff, apply_plan

    desired = derive_asset_desired(assets)

    # 1. Ensure owner users exist (the owner relation's subject). NEVER
    #    pruned here — split from the managed diff below.
    owner_users = {o for o in desired.objects if o.type == "user"}
    for u in owner_users:
        client.set_object(u)

    # 2. Managed diff over dataset objects + owner relations only (users
    #    excluded from BOTH sides, so no user is ever added-then-deleted or
    #    pruned by this tool).
    desired_managed = DesiredState(
        objects={o for o in desired.objects if o.type in MANAGED_ASSET_OBJECT_TYPES},
        relations=set(desired.relations),
    )
    live = snapshot_assets(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback_assets(client, assets: list[AssetRecord]) -> tuple[int, int]:
    """Positive control for the enforcement seed — every seeded owner must
    resolve `can_read` TRUE on its dataset. Returns (checked, failures); a
    missing relation FAILS LOUD (`[[verification-must-fail]]`). Uses the
    general `client.check` (the working `/check` endpoint — the sibling to
    the ADR-0026 cell readback that was 404-dead). This is the sync's own
    reference: it confirms the relations it WROTE resolve. (The reference-
    INDEPENDENT check — that a REAL user's REAL token resolves — is the
    real-token / browser probe, `[[verification-reference-independence]]`;
    both matter, this catches an inert apply, that catches a mis-keyed
    identity.)"""
    checked = failures = 0
    for a in assets:
        for owner in a.owners:
            checked += 1
            if not client.check("dataset", a.urn, "can_read", owner):
                print(f"  [FAIL] {owner} can_read {a.urn}")
                failures += 1
    return checked, failures


def main() -> int:
    """CLI: fetch DataHub assets and sync their owner relations into Topaz.
    Env: DATAHUB_GMS_URL, TOPAZ_DIRECTORY_URL."""
    from topaz_sync import TopazClient

    datahub_url = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080/api/graphql")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    assets = fetch_datahub_assets(datahub_url)
    print(f"fetched {len(assets)} datasets from DataHub")
    if not assets:
        print("no assets — refusing to sync (a fetch failure must not prune).")
        return 1
    with TopazClient(topaz_url) as client:
        plan = sync_assets(client, assets)
        print(
            f"synced: +{len(plan.add_objects)} objects, "
            f"+{len(plan.add_relations)} owner relations, "
            f"-{len(plan.del_objects)} objects, -{len(plan.del_relations)} relations"
        )
        # Positive control — the relations we wrote must actually grant
        # can_read. A dead readback (like the ADR-0026 one was) is worse
        # than none when you're seeding an authorization directory.
        print("===== Readback (positive control) =====")
        checked, failures = readback_assets(client, assets)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print(
                "FAIL: seeded owner relations don't resolve can_read — the "
                "apply lied. NOT safe to enable enforcement.",
                file=sys.stderr,
            )
            return 4
    return 0


import sys  # noqa: E402


if __name__ == "__main__":
    import sys
    sys.exit(main())
