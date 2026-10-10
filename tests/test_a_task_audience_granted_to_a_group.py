"""A task audience may be granted to a GROUP (`group:<G>#member`), end to end (ruling 2026-10-10).

Pieces under test: the queue resolver (`human_tasks._resolve_audience_actors`), the sync
(`task_grant_sync`), the validator (`validate_policy`), and the REAL policy files.
Doubles assert the REQUEST (what is written / listed), not just the result.

Run:  uv run python -m pytest tests/test_a_task_audience_granted_to_a_group.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_SYNC = ROOT / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

import task_grant_sync as tgs  # noqa: E402
from topaz_sync import DirObject, DirRelation  # noqa: E402
from validate_policy import unusable_group_audiences, validate  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "iagent_human_tasks_grp", ROOT / "src" / "iagent" / "human_tasks.py")
ht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ht)  # type: ignore[union-attr]


# ── resolver ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, results, status=200):
        self._results, self.status_code = results, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"results": self._results}


def _directory(audience_rels, members_by_group, fail_groups=()):
    calls: list[dict] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, path, params=None):
            calls.append(dict(params))
            if params["object_type"] == "task_audience":
                return _Resp(audience_rels)
            g = params["object_id"]
            if g in fail_groups:
                return _Resp([], status=500)
            return _Resp([{"subject_type": "user", "subject_id": u}
                          for u in members_by_group.get(g, [])])

    return _Client, calls


def _resolve(client_cls):
    with mock.patch.object(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz"), \
            mock.patch.object(ht.httpx, "Client", client_cls):
        return ht._resolve_audience_actors("maint_fault_approval:ORG")


RELS = [
    {"subject_type": "user", "subject_id": "alice@example.com"},
    {"subject_type": "group", "subject_id": "maintenance-tier-org", "subject_relation": "member"},
    # a group subject WITHOUT the member relation is not a member userset: never expanded
    {"subject_type": "group", "subject_id": "other", "subject_relation": ""},
]


def test_resolver_expands_group_members_deduped_first_seen_order():
    cls, calls = _directory(RELS, {"maintenance-tier-org": ["bob@example.com", "alice@example.com",
                                                            "bob@example.com"],
                                   "other": ["mallory@example.com"]})
    assert _resolve(cls) == ["alice@example.com", "bob@example.com"]
    # the REQUEST: exactly one member listing, for the group#member subject
    member_calls = [c for c in calls if c["object_type"] == "group"]
    assert member_calls == [{"object_type": "group", "object_id": "maintenance-tier-org",
                             "relation": "member"}]


def test_resolver_group_member_listing_error_raises_not_partial():
    cls, _ = _directory(RELS, {}, fail_groups={"maintenance-tier-org"})
    with pytest.raises(RuntimeError):
        _resolve(cls)


# ── sync ────────────────────────────────────────────────────────────────────

def _group_audience(groups=("maintenance-tier-org",), users=()):
    return tgs.AudienceRecord(key="maint_tier_ack:ORG", grant_to=tuple(users),
                              granted_by="c", reason="r", grant_to_groups=tuple(groups))


class _Rec:
    def __init__(self, live_rels=(), existing_groups=("maintenance-tier-org",)):
        self.live_rels, self.groups = list(live_rels), set(existing_groups)
        self.set_objects, self.set_rels, self.del_rels = [], [], []

    def object_exists(self, t, i):
        return t == "group" and i in self.groups

    def set_object(self, o, display_name=""):
        self.set_objects.append(o)

    def list_relations(self, object_type="", relation=""):
        return [r for r in self.live_rels
                if r.object_type == object_type and r.relation == relation]

    def set_relation(self, r):
        self.set_rels.append(r)

    def delete_relation(self, r):
        self.del_rels.append(r)

    def delete_object(self, o):  # pragma: no cover - must never be reached
        raise AssertionError("sync must not delete objects")


def test_sync_writes_the_group_subject_with_the_member_relation():
    c = _Rec()
    tgs.sync_audiences(c, [_group_audience()])
    assert c.set_rels == [DirRelation(
        object_type="task_audience", object_id="maint_tier_ack:ORG", relation="actor",
        subject_type="group", subject_id="maintenance-tier-org", subject_relation="member")]
    # the group object is never created by this sync
    assert all(o.type != "group" for o in c.set_objects)


def test_prune_revokes_a_group_grant_removed_from_the_yaml():
    stale = DirRelation("task_audience", "maint_tier_ack:ORG", "actor", "group",
                        "maintenance-tier-org", "member")
    c = _Rec(live_rels=[stale])
    keep = tgs.AudienceRecord(key="maint_tier_ack:ORG", grant_to=("bob@example.com",),
                              granted_by="c", reason="r")
    tgs.sync_audiences(c, [keep])
    assert c.del_rels == [stale]


def test_missing_group_object_refuses_and_writes_nothing():
    c = _Rec(existing_groups=())
    with pytest.raises(tgs.GroupObjectMissing, match="group:maintenance-tier-org"):
        tgs.sync_audiences(c, [_group_audience()])
    assert c.set_objects == [] and c.set_rels == [] and c.del_rels == []


def test_main_exits_5_on_a_missing_group(tmp_path, monkeypatch):
    f = tmp_path / "tg.yaml"
    f.write_text(yaml.safe_dump({"audiences": {"a:B": {
        "granted_by": "c", "reason": "r", "grant_to_groups": ["ghost"]}}}))
    monkeypatch.setenv("TASK_GRANTS_FILE", str(f))
    rec = _Rec(existing_groups=())

    class _CM:
        def __init__(self, url):
            pass

        def __enter__(self):
            return rec

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sys.modules["topaz_sync"], "TopazClient", _CM)
    assert tgs.main() == 5
    assert rec.set_rels == []


def test_readback_fails_when_the_group_relation_is_absent_and_passes_when_present():
    a = _group_audience()
    absent = _Rec()
    assert tgs.readback(absent, [a]) == (1, 1)
    present = _Rec(live_rels=[next(iter(tgs.derive_desired([a]).relations))])
    assert tgs.readback(present, [a]) == (1, 0)


def test_audience_with_neither_list_is_refused():
    _, errors = tgs.load_audiences({"audiences": {"x:Y": {"granted_by": "g", "reason": "r"}}})
    assert errors and "grant_to_groups" in errors[0]


def test_group_with_no_grants_is_admitted_by_the_policy_bundle():
    from topaz_sync import GroupSpec
    assert GroupSpec().grants == [] and GroupSpec.model_validate({}).grants == []


# ── validate ────────────────────────────────────────────────────────────────

USERS = [{"id": "bob@example.com", "groups": ["maintenance-tier-org"]}]
GROUPS = {"maintenance-tier-org": {}, "empty-group": {}}


def test_validate_unknown_group_refused():
    errs = unusable_group_audiences([_group_audience(groups=("ghost",))], GROUPS, USERS)
    assert len(errs) == 1 and "maint_tier_ack:ORG" in errs[0] and "ghost" in errs[0]
    assert "NOT a group" in errs[0]


def test_validate_empty_group_refused():
    errs = unusable_group_audiences([_group_audience(groups=("empty-group",))], GROUPS, USERS)
    assert len(errs) == 1 and "ZERO members" in errs[0] and "empty-group" in errs[0]


def test_validate_populated_group_passes():
    assert unusable_group_audiences([_group_audience()], GROUPS, USERS) == []


def test_validate_the_real_policy_dir_passes():
    assert validate(ROOT / "policy", ROOT / "policy") == []


# ── the real files: every audience resolves to a user ──────────────────────

def _real():
    pol = ROOT / "policy"
    load = lambda n: yaml.safe_load((pol / n).read_text(encoding="utf-8"))  # noqa: E731
    audiences, errors = tgs.load_audiences(load("task_grants.yaml"))
    assert errors == []
    members: dict[str, set[str]] = {}
    for u in load("users.yaml")["users"]:
        for g in u.get("groups") or []:
            members.setdefault(g, set()).add(u["id"])
    return audiences, members


def test_every_real_audience_resolves_to_at_least_one_user():
    audiences, members = _real()
    for a in audiences:
        who = set(a.grant_to)
        for g in a.grant_to_groups:
            who |= members.get(g, set())
        assert who, f"audience {a.key} routes to NOBODY"


def test_the_two_maintenance_tier_audiences_resolve_to_bob():
    audiences, members = _real()
    by_key = {a.key: a for a in audiences}
    for key in ("maint_fault_approval:ORG", "maint_tier_ack:ORG"):
        a = by_key[key]
        assert a.grant_to == () and a.grant_to_groups == ("maintenance-tier-org",)
        assert members["maintenance-tier-org"] == {"bob@example.com"}


def test_the_actor_group_grants_no_cell():
    g = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    assert not (g["maintenance-tier-org"] or {}).get("grants")
