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
