"""user objects are ENSURE-ONLY family-wide — the sync-fight fix.

THE BUG THIS PINS (work cluster, 2026-07-16): topaz_sync pruned every
`user` object not in users.yaml. In sandbox that was invisible — every
DataHub owner (alice@example.com…) also existed in users.yaml. At work
the populations don't coincide (E-number entitlements vs email-style
DataHub owner usernames), so every tick the persona sync DELETED the
asset sync's ~107 owner users (cascading their `owner` relations — a
fail-closed ownership gap) and the asset sync re-created them minutes
later. The fix lives in plan_diff's ENSURE_ONLY_TYPES so no individual
sync can reintroduce the fight: user objects are never emitted as
deletions, by the one diff engine every sync shares.

Revocation is NOT weakened: removing a user from users.yaml still
prunes their `member` relations, and cells/grants all derive from
those — the bare user object is inert under deny-by-default.

Run:  PYTHONPATH=policy/sync pytest tests/test_topaz_sync_user_ensure_only.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from topaz_sync import (  # noqa: E402
    ENSURE_ONLY_TYPES,
    DirObject,
    DirRelation,
    DesiredState,
    plan_diff,
)


def _member(group: str, user: str) -> DirRelation:
    return DirRelation(
        object_type="group", object_id=group, relation="member",
        subject_type="user", subject_id=user,
    )


def test_foreign_user_survives_the_entitlement_diff():
    """The fight scenario: a DataHub-owner user (NOT in users.yaml) is
    live; the entitlement sync's desired state doesn't contain it. It
    must NOT be planned for deletion."""
    desired = DesiredState(
        objects={DirObject("user", "E12345"), DirObject("group", "data-engineers")},
        relations={_member("data-engineers", "E12345")},
    )
    live_objects = {
        DirObject("user", "E12345"),
        DirObject("group", "data-engineers"),
        DirObject("user", "owner.from.datahub@example.com"),  # asset-sync-ensured
    }
    plan = plan_diff(desired, live_objects, {_member("data-engineers", "E12345")})
    assert plan.del_objects == [], (
        "a user object ensured by another sync must survive this sync's tick"
    )


def test_owned_types_still_prune():
    """The exemption is user-objects ONLY — stale groups/cells/personas
    keep the full diff-prune discipline."""
    desired = DesiredState(objects={DirObject("group", "keep")}, relations=set())
    live_objects = {
        DirObject("group", "keep"),
        DirObject("group", "stale-group"),
        DirObject("cell", "ARCHITECT:RETIRED_DOMAIN"),
        DirObject("user", "stale-user@example.com"),
    }
    plan = plan_diff(desired, live_objects, set())
    deleted = {(o.type, o.id) for o in plan.del_objects}
    assert ("group", "stale-group") in deleted
    assert ("cell", "ARCHITECT:RETIRED_DOMAIN") in deleted
    assert not any(t == "user" for t, _ in deleted)


def test_user_removal_still_revokes_via_relations():
    """Removing a user from users.yaml must still REVOKE: their member
    relations are pruned (cells and everything derived go with them)
    even though the bare user object stays."""
    desired = DesiredState(
        objects={DirObject("group", "data-engineers")},
        relations=set(),  # user removed from the group in YAML
    )
    live_objects = {
        DirObject("group", "data-engineers"),
        DirObject("user", "E99999"),
    }
    live_relations = {_member("data-engineers", "E99999")}
    plan = plan_diff(desired, live_objects, live_relations)
    assert _member("data-engineers", "E99999") in plan.del_relations, (
        "revocation must still flow through relation pruning"
    )
    assert plan.del_objects == []


def test_user_adds_still_diff_cleanly():
    """Ensure-only must not degrade adds into every-tick upsert noise:
    a user already live is NOT re-added."""
    desired = DesiredState(objects={DirObject("user", "E12345")}, relations=set())
    live_objects = {DirObject("user", "E12345")}
    plan = plan_diff(desired, live_objects, set())
    assert plan.add_objects == []


def test_ensure_only_scope_is_exactly_user():
    """Pin the scope: widening it would silently disable pruning for an
    owned type; narrowing it reintroduces the fight."""
    assert ENSURE_ONLY_TYPES == frozenset({"user"})
