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
