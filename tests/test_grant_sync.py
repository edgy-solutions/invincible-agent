"""git-asserted reader-grant sync — the pure core + prove-the-negative.

The grant mechanism CREATES access, so a bug that grants too broadly is a
spill-generator (classification: TS/SCI/proprietary/PII). This file pins the
deterministic core AND the refusals — the negative path is the point:

  * load_grants        — parse + REJECT malformed (missing subject/asset/
                         granted_by); the accountable-human field is required.
  * derive_grant_desired — grants → `reader` relations + grantee user objects.
  * find_dangling      — REFUSE a grant whose asset isn't in the directory
                         (deny-on-dangling).
  * sync_grants        — apply reader relations; PRUNE revoked (git = truth);
                         never touch owner/user (boundary with the other syncs).

Run:  PYTHONPATH=policy/sync pytest tests/test_grant_sync.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from grant_sync import (  # noqa: E402
    GrantRecord,
    load_grants,
    derive_grant_desired,
    find_dangling,
    sync_grants,
    readback_grants,
    MANAGED_GRANT_RELATIONS,
)
from topaz_sync import DirObject, DirRelation  # noqa: E402


_GOLD = "urn:li:dataset:(a,gold.sales.customers_gold,PROD)"


# ---------------------------------------------------------------------------
# load_grants — parse + PROVE-THE-NEGATIVE (malformed refused)
# ---------------------------------------------------------------------------
def test_load_wellformed_grant():
    grants, errors = load_grants({"grants": [
        {"subject": "alice@example.com", "asset": _GOLD, "granted_by": "cnogradi", "reason": "demo"},
    ]})
    assert errors == []
    assert grants == [GrantRecord("alice@example.com", _GOLD, "cnogradi", "demo")]


def test_load_rejects_missing_granted_by():
    """The accountable-human field is REQUIRED — an anonymous grant is refused,
    not silently applied. This is the audit-trail guarantee at the load."""
    grants, errors = load_grants({"grants": [
        {"subject": "alice@example.com", "asset": _GOLD},  # no granted_by
    ]})
    assert grants == []
    assert len(errors) == 1 and "granted_by" in errors[0]


def test_load_rejects_missing_subject_or_asset():
    grants, errors = load_grants({"grants": [
        {"asset": _GOLD, "granted_by": "x"},                       # no subject
        {"subject": "bob@example.com", "granted_by": "x"},         # no asset
    ]})
    assert grants == []
    assert len(errors) == 2
    assert "subject" in errors[0] and "asset" in errors[1]


def test_load_empty_is_clean():
    assert load_grants({}) == ([], [])
    assert load_grants({"grants": []}) == ([], [])


# ---------------------------------------------------------------------------
# derive_grant_desired — grants → reader relations
# ---------------------------------------------------------------------------
def test_derive_makes_reader_relation_and_user():
    state = derive_grant_desired([GrantRecord("alice@example.com", _GOLD, "cnogradi")])
    assert DirObject("user", "alice@example.com") in state.objects   # grantee ensured
    assert DirRelation("dataset", _GOLD, "reader", "user", "alice@example.com") in state.relations
    # It asserts READER, never OWNER (that's the DataHub sync's).
    assert all(r.relation == "reader" for r in state.relations)


# ---------------------------------------------------------------------------
# Fake directory (adds .check + dataset listing to the shared fake shape)
# ---------------------------------------------------------------------------
class _FakeTopaz:
    def __init__(self):
        self.objects: set = set()
        self.relations: set = set()
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

    def object_exists(self, obj_type, obj_id):
        return DirObject(obj_type, obj_id) in self.objects

    def list_relations(self, object_type, relation):
        return [r for r in self.relations
                if r.object_type == object_type and r.relation == relation]

    def check(self, object_type, object_id, relation, subject_id, subject_type="user"):
        # can_read = reader | owner — mirror the manifest permission so the
        # readback test exercises the real allow shape.
        return any(
            r.object_type == object_type and r.object_id == object_id
            and r.relation in ("reader", "owner") and r.subject_id == subject_id
            for r in self.relations
        )


# ---------------------------------------------------------------------------
# find_dangling — PROVE-THE-NEGATIVE (deny-on-dangling)
# ---------------------------------------------------------------------------
def test_dangling_refused_when_asset_absent():
    client = _FakeTopaz()  # directory has NO datasets
    dangling = find_dangling(client, [GrantRecord("alice@example.com", _GOLD, "cnogradi")])
    assert len(dangling) == 1 and _GOLD in dangling[0]


def test_not_dangling_when_asset_present():
    client = _FakeTopaz()
    client.objects.add(DirObject("dataset", _GOLD))  # seeded by the DataHub sync
    assert find_dangling(client, [GrantRecord("alice@example.com", _GOLD, "cnogradi")]) == []


def test_dangling_check_never_lists_datasets():
    """Regression pin (work seed, 2026-07-16): find_dangling sat on
    list_objects('dataset'), so topaz's store-iterator 500 at 9k+
    datasets killed the grant sync — the domino AFTER the asset sync
    had already survived the same 500 via degraded mode. The check
    must use POINT lookups (object_exists) only: O(granted assets),
    iterator-free."""
    class _ListingBroken(_FakeTopaz):
        def list_objects(self, obj_type):
            raise AssertionError(
                "find_dangling must not LIST datasets — point lookups only"
            )

    client = _ListingBroken()
    client.objects.add(DirObject("dataset", _GOLD))
    grants = [
        GrantRecord("alice@example.com", _GOLD, "cnogradi"),
        GrantRecord("bob@example.com", "urn:li:dataset:absent", "cnogradi"),
    ]
    dangling = find_dangling(client, grants)
    assert len(dangling) == 1 and "urn:li:dataset:absent" in dangling[0]


# ---------------------------------------------------------------------------
# sync_grants — apply, revoke-by-prune, boundary
# ---------------------------------------------------------------------------
def test_sync_applies_reader_and_ensures_user():
    client = _FakeTopaz()
    client.objects.add(DirObject("dataset", _GOLD))
    sync_grants(client, [GrantRecord("alice@example.com", _GOLD, "cnogradi")])
    assert DirRelation("dataset", _GOLD, "reader", "user", "alice@example.com") in client.relations
    assert DirObject("user", "alice@example.com") in client.objects  # ensured
    # readback resolves through the sealed gate's permission
    assert readback_grants(client, [GrantRecord("alice@example.com", _GOLD, "cnogradi")]) == (1, 0)


def test_sync_prunes_revoked_grant():
    """Removing a grant from git REVOKES it (git = source of truth for grants,
    the deny-by-default direction). A reader relation not asserted is pruned."""
    client = _FakeTopaz()
    client.objects.add(DirObject("dataset", _GOLD))
    stale = DirRelation("dataset", _GOLD, "reader", "user", "carol@example.com")
    client.relations.add(stale)  # a grant no longer in the git file
    sync_grants(client, [GrantRecord("alice@example.com", _GOLD, "cnogradi")])
    assert stale not in client.relations, "a grant removed from git must be REVOKED"
    assert DirRelation("dataset", _GOLD, "reader", "user", "alice@example.com") in client.relations


def test_sync_never_prunes_owner_or_user():
    """Boundary: this sync manages `reader` only. An `owner` relation (DataHub
    sync's) and a `user` object (ADR-0026 sync's) must be untouched — three
    syncs, disjoint scope, no fighting."""
    client = _FakeTopaz()
    client.objects.add(DirObject("dataset", _GOLD))
    client.objects.add(DirObject("user", "dave@company.com"))
    owner_rel = DirRelation("dataset", _GOLD, "owner", "user", "dave@company.com")
    client.relations.add(owner_rel)
    sync_grants(client, [GrantRecord("alice@example.com", _GOLD, "cnogradi")])
    assert owner_rel in client.relations, "must not prune owner relations (DataHub sync owns them)"
    assert DirObject("user", "dave@company.com") in client.objects
    assert DirObject("user", "dave@company.com") not in client.deleted_objects
    assert MANAGED_GRANT_RELATIONS == [("dataset", "reader")]
