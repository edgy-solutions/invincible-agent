"""DataHub → Topaz sync — the pure transform core (ADR-0025 hop 1).

The deny-before-seed/permit-after proof is an integration probe against
live Topaz (a running directory is inherent to that assertion). THIS file
pins the deterministic core that decides WHAT gets seeded, hermetically:

  1. normalize_datahub_search — the DataHub GraphQL response → AssetRecord
     extraction (owners, tags), defensive against the deeply-optional
     shape.
  2. derive_asset_desired — AssetRecord → Topaz DesiredState (`dataset`
     objects + `owner` relations), with the honest-empty guarantee (no
     owners → no phantom owner relation) and the boundary discipline
     (owner `user` objects ensured, never a `cell`/persona type — that's
     the ADR-0026 sync's).

Run:  PYTHONPATH=policy/sync pytest tests/test_datahub_topaz_sync.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

# The sync module imports `topaz_sync` (its sibling) for the directory
# primitives, so policy/sync must be on the path.
_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from datahub_topaz_sync import (  # noqa: E402
    AssetRecord,
    derive_asset_desired,
    normalize_datahub_search,
    MANAGED_ASSET_OBJECT_TYPES,
    MANAGED_ASSET_RELATIONS,
)
from topaz_sync import DirObject, DirRelation  # noqa: E402


# ---------------------------------------------------------------------------
# normalize_datahub_search — the GraphQL → AssetRecord extraction
# ---------------------------------------------------------------------------
def _search_response(*entities: dict) -> dict:
    return {"data": {"searchAcrossEntities": {"searchResults": [
        {"entity": e} for e in entities
    ]}}}


def test_normalize_extracts_urn_owners_tags():
    resp = _search_response({
        "urn": "urn:li:dataset:(a,gold.sales.revenue,PROD)",
        "ownership": {"owners": [
            {"owner": {"username": "alice"}},
            {"owner": {"username": "bob"}},
        ]},
        "tags": {"tags": [
            {"tag": {"urn": "urn:li:tag:pii"}},
            {"tag": {"urn": "urn:li:tag:gold"}},
        ]},
    })
    [rec] = normalize_datahub_search(resp)
    assert rec.urn == "urn:li:dataset:(a,gold.sales.revenue,PROD)"
    assert rec.owners == ("alice", "bob")
    assert rec.tags == ("pii", "gold")


def test_normalize_is_defensive_against_missing_layers():
    """Every optional GraphQL layer missing must yield empty, never raise —
    a dataset with no ownership block is a record with no owners, not a
    crash."""
    resp = _search_response(
        {"urn": "urn:li:dataset:(a,x,PROD)"},               # no ownership/tags
        {"urn": "urn:li:dataset:(a,y,PROD)", "ownership": {}},
        {"ownership": {"owners": [{"owner": {"username": "z"}}]}},  # no urn → dropped
    )
    recs = normalize_datahub_search(resp)
    assert [r.urn for r in recs] == [
        "urn:li:dataset:(a,x,PROD)",
        "urn:li:dataset:(a,y,PROD)",
    ]
    assert all(r.owners == () for r in recs)


def test_normalize_empty_response():
    assert normalize_datahub_search({}) == []
    assert normalize_datahub_search({"data": {}}) == []


# ---------------------------------------------------------------------------
# derive_asset_desired — AssetRecord → DesiredState
# ---------------------------------------------------------------------------
def test_derive_produces_dataset_object_and_owner_relation():
    state = derive_asset_desired([
        AssetRecord(urn="urn:li:dataset:(a,x,PROD)", owners=("alice",)),
    ])
    assert DirObject("dataset", "urn:li:dataset:(a,x,PROD)") in state.objects
    # owner user ensured present (subject of the relation)
    assert DirObject("user", "alice") in state.objects
    assert DirRelation(
        object_type="dataset",
        object_id="urn:li:dataset:(a,x,PROD)",
        relation="owner",
        subject_type="user",
        subject_id="alice",
    ) in state.relations


def test_derive_no_owners_yields_no_phantom_relation():
    """The honest-empty guarantee: a dataset with no owners produces the
    object but ZERO owner relations — never a fabricated grant. (This is
    the data-layer sibling of [[optimistic-defaults-are-dishonest]].)"""
    state = derive_asset_desired([
        AssetRecord(urn="urn:li:dataset:(a,orphan,PROD)", owners=()),
    ])
    assert DirObject("dataset", "urn:li:dataset:(a,orphan,PROD)") in state.objects
    assert not any(r.relation == "owner" for r in state.relations), (
        "no owner → no owner relation; a dataset with no recorded owner "
        "must not manufacture one"
    )


def test_derive_multiple_owners_all_related():
    state = derive_asset_desired([
        AssetRecord(urn="urn:li:dataset:(a,x,PROD)", owners=("alice", "bob")),
    ])
    owner_subjects = {
        r.subject_id for r in state.relations if r.relation == "owner"
    }
    assert owner_subjects == {"alice", "bob"}


class _FakeTopaz:
    """In-memory Topaz directory — records object/relation writes so the
    driver's logic (ensure-users, diff, apply) is testable without a live
    directory. Implements the TopazClient surface the driver uses."""
    def __init__(self):
        self.objects: set = set()      # DirObject
        self.relations: set = set()    # DirRelation
        self.deleted_objects: list = []

    def set_object(self, obj, display_name=""):
        self.objects.add(obj)

    def set_relation(self, rel):
        self.relations.add(rel)

    def delete_object(self, obj, with_relations=True):
        self.deleted_objects.append(obj)
        self.objects.discard(obj)

    def delete_relation(self, rel):
        self.relations.discard(rel)

    def list_objects(self, obj_type):
        return [o for o in self.objects if o.type == obj_type]

    def list_relations(self, object_type, relation):
        return [
            r for r in self.relations
            if r.object_type == object_type and r.relation == relation
        ]


def test_sync_seeds_dataset_objects_and_owner_relations():
    from datahub_topaz_sync import sync_assets
    client = _FakeTopaz()
    sync_assets(client, [
        AssetRecord(urn="urn:li:dataset:(a,x,PROD)", owners=("alice",)),
    ])
    assert DirObject("dataset", "urn:li:dataset:(a,x,PROD)") in client.objects
    assert DirObject("user", "alice") in client.objects  # owner user ENSURED
    assert DirRelation(
        object_type="dataset", object_id="urn:li:dataset:(a,x,PROD)",
        relation="owner", subject_type="user", subject_id="alice",
    ) in client.relations


def test_sync_never_prunes_user_objects():
    """The boundary guarantee: this sync manages dataset+owner; a `user`
    object present in the directory (owned by the ADR-0026 sync) must NEVER
    be deleted here, even if no current asset references it."""
    from datahub_topaz_sync import sync_assets
    client = _FakeTopaz()
    client.objects.add(DirObject("user", "bob"))          # ADR-0026-owned user
    client.objects.add(DirObject("dataset", "urn:stale")) # a stale dataset
    sync_assets(client, [
        AssetRecord(urn="urn:li:dataset:(a,x,PROD)", owners=("alice",)),
    ])
    # bob (a user) is untouched; the stale dataset IS pruned (managed type).
    assert DirObject("user", "bob") in client.objects, (
        "the asset sync must never prune user objects — the ADR-0026 sync "
        "owns the user type; two syncs pruning one type would fight"
    )
    assert DirObject("dataset", "urn:stale") not in client.objects
    assert DirObject("user", "bob") not in client.deleted_objects


def test_fetch_returns_empty_on_datahub_failure():
    """A fetch failure returns [] (partial), and main() refuses to sync on
    empty — a DataHub outage must NEVER prune the directory to empty."""
    from datahub_topaz_sync import fetch_datahub_assets
    def _boom(url, json):
        raise RuntimeError("datahub down")
    assert fetch_datahub_assets("http://x", http_post=_boom) == []


def test_derive_never_touches_persona_types():
    """Boundary guard: this sync manages `dataset`/`owner` only. It must
    never emit persona/cell/group objects (the ADR-0026 sync owns those) —
    the two authority sources stay isolated so they don't fight over a
    shared managed type."""
    state = derive_asset_desired([
        AssetRecord(urn="urn:li:dataset:(a,x,PROD)", owners=("alice",)),
    ])
    emitted_types = {o.type for o in state.objects}
    assert emitted_types <= {"dataset", "user"}, (
        f"asset sync must emit only dataset+user objects; got {emitted_types}"
    )
    assert MANAGED_ASSET_OBJECT_TYPES == ["dataset"]
    assert MANAGED_ASSET_RELATIONS == [("dataset", "owner")]
    # user is NOT in the managed (prune) scope — ensured, never pruned.
    assert "user" not in MANAGED_ASSET_OBJECT_TYPES
