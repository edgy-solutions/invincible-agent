"""The `can_drop:<content_kind>` capability rail (2026-10-28 ruling: pcn and pdn droppable by the
alert-processors group only).

A kind K is GATED iff the Topaz object `capability:can_drop:K` EXISTS. So the sync must make object
existence mirror the rows exactly (scoped prune), a group is granted as `group:<G>#member` without
the sync ever creating the group, and the validator refuses a key that names no known kind.
Doubles assert the REQUEST (what is written / deleted), not just the result.

Run:  uv run python -m pytest tests/security/test_can_drop_capability_rail.py -q
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_SYNC = ROOT / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

import capability_grant_sync as cgs  # noqa: E402
from topaz_sync import DirObject, DirRelation  # noqa: E402
from validate_policy import validate  # noqa: E402

GRANTS = ROOT / "policy" / "capability_grants.yaml"
GROUP = "alert-processors"
KINDS = ("pcn", "pdn")


def _rows() -> dict:
    return yaml.safe_load(GRANTS.read_text(encoding="utf-8"))["capabilities"]


def _row(group=(GROUP,), users=()):
    r = {"granted_by": "seed", "reason": "test"}
    if group:
        r["grant_to_groups"] = list(group)
    if users:
        r["grant_to"] = list(users)
    return r


class _Fake:
    """Records every write. Live state is `objects` / `relations`; groups must be in `objects`."""

    def __init__(self, objects=(), relations=()):
        self.objects = set(objects)
        self.relations = set(relations)
        self.writes: list = []

    def object_exists(self, t, i):
        return DirObject(t, i) in self.objects

    def set_object(self, obj, display_name=""):
        self.writes.append(("set_object", obj))
        self.objects.add(obj)

    def set_relation(self, rel):
        self.writes.append(("set_relation", rel))
        self.relations.add(rel)

    def delete_relation(self, rel):
        self.writes.append(("delete_relation", rel))
        self.relations.discard(rel)

    def delete_object(self, obj, with_relations=True):
        self.writes.append(("delete_object", obj))
        self.objects.discard(obj)

    def list_objects(self, t):
        return sorted((o for o in self.objects if o.type == t), key=lambda o: o.id)

    def list_relations(self, object_type="", relation=""):
        return [r for r in self.relations
                if (not object_type or r.object_type == object_type)
                and (not relation or r.relation == relation)]

    def check(self, *a, **k):
        return True


def _caps(raw):
    caps, errors = cgs.load_capabilities({"capabilities": raw})
    assert not errors, errors
    return caps


def _member(key, group=GROUP):
    return DirRelation("capability", key, "invoker", "group", group, "member")


# -- load ---------------------------------------------------------------------------------

def test_load_accepts_a_group_only_row_and_refuses_one_with_neither():
    caps, errors = cgs.load_capabilities({"capabilities": {"can_drop:pcn": _row()}})
    assert errors == [] and caps[0].grant_to == () and caps[0].grant_to_groups == (GROUP,)
    _, errors = cgs.load_capabilities({"capabilities": {"can_drop:pcn": _row(group=())}})
    assert errors and "grant_to_groups" in errors[0]


# -- derive -------------------------------------------------------------------------------

def test_derive_writes_group_member_invoker_for_both_rows_and_no_group_object():
    caps, errors = cgs.load_capabilities({"capabilities": {f"can_drop:{k}": _row() for k in KINDS}})
    assert not errors
    d = cgs.derive_desired(caps)
    assert {_member(f"can_drop:{k}") for k in KINDS} <= d.relations
    assert not [o for o in d.objects if o.type == "group"], "the sync must never create a group"
    assert {DirObject("capability", f"can_drop:{k}") for k in KINDS} <= d.objects


# -- refusal before any write -------------------------------------------------------------

def test_an_absent_group_is_refused_before_any_write():
    c = _Fake(objects=[DirObject("capability", "can_drop:stale")])
    with pytest.raises(cgs.GroupObjectMissing):
        cgs.sync_capabilities(c, _caps({"can_drop:pcn": _row()}), prune=True)
    assert c.writes == [], "a refused sync must write nothing, not even a prune"


def test_main_exits_5_when_the_group_is_absent(monkeypatch, tmp_path):
    f = tmp_path / "caps.yaml"
    f.write_text(yaml.safe_dump({"capabilities": {"can_drop:pcn": _row()}}), encoding="utf-8")
    c = _Fake()
    c.__enter__ = lambda self=c: c
    c.__exit__ = lambda *a: False

    class _Ctx:
        def __init__(self, url):
            pass

        def __enter__(self):
            return c

        def __exit__(self, *a):
            return False

    import topaz_sync
    monkeypatch.setattr(topaz_sync, "TopazClient", _Ctx)
    monkeypatch.setenv("CAPABILITY_GRANTS_FILE", str(f))
    assert cgs.main() == 5
    assert c.writes == []


# -- readback -----------------------------------------------------------------------------

def test_readback_fails_on_a_missing_group_relation_and_passes_when_present():
    caps = _caps({"can_drop:pcn": _row()})
    _, failures = cgs.readback(_Fake(), caps)
    assert failures == 1
    checked, failures = cgs.readback(_Fake(relations=[_member("can_drop:pcn")]), caps)
    assert (checked, failures) == (1, 0)


# -- scoped prune -------------------------------------------------------------------------

def _live():
    return _Fake(objects=[DirObject("group", GROUP),
                          DirObject("capability", "can_drop:x"),
                          DirObject("capability", "mesh:foo")])


def test_prune_deletes_an_orphan_can_drop_and_keeps_every_other_capability():
    c = _live()
    cgs.sync_capabilities(c, _caps({"can_drop:pcn": _row()}), prune=True)
    deleted = [o for k, o in c.writes if k == "delete_object"]
    assert deleted == [DirObject("capability", "can_drop:x")]
    assert DirObject("capability", "mesh:foo") in c.objects
    assert DirObject("capability", "can_drop:pcn") in c.objects, "a row's own object is kept"


def test_prune_false_deletes_nothing():
    c = _live()
    cgs.sync_capabilities(c, _caps({"can_drop:pcn": _row()}), prune=False)
    assert not [w for w in c.writes if w[0] == "delete_object"]
    assert DirObject("capability", "can_drop:x") in c.objects


# -- the repo's own rows ------------------------------------------------------------------

def test_the_repo_pins_exactly_two_can_drop_rows_pcn_and_pdn_group_only():
    drops = {k: v for k, v in _rows().items() if k.startswith("can_drop:")}
    assert sorted(drops) == ["can_drop:pcn", "can_drop:pdn"]
    for k, v in drops.items():
        assert v["grant_to_groups"] == [GROUP], k
        assert "grant_to" not in v, k
        assert v["granted_by"] == "seed", k


def test_alert_processors_grants_no_cell_and_alice_is_a_member():
    groups = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    assert GROUP in groups and not (groups[GROUP] or {}).get("grants")
    users = yaml.safe_load((ROOT / "policy" / "users.yaml").read_text(encoding="utf-8"))["users"]
    alice = [u for u in users if u.get("email") == "alice@example.com" or u.get("id") == "alice@example.com"]
    assert alice and GROUP in (alice[0].get("groups") or [])


def test_every_can_drop_key_names_a_kind_registered_in_the_overlay():
    reg = {yaml.safe_load(p.read_text(encoding="utf-8"))["kind"]
           for p in (ROOT / "policy" / "overlays" / "openddil-lab" / "content_kinds").glob("*.yaml")}
    for k in _rows():
        if k.startswith("can_drop:"):
            assert k[len("can_drop:"):] in reg, k


# -- validate_policy ----------------------------------------------------------------------

@pytest.fixture
def pol(tmp_path):
    d = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", d, ignore=shutil.ignore_patterns("__pycache__", "overlays"))
    return d


def _put(d, name, mutate):
    p = d / name
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    mutate(data)
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_validate_passes_on_the_repo():
    assert validate(ROOT / "policy", ROOT / "policy") == []


def test_validate_refuses_an_unknown_group(pol):
    _put(pol, "capability_grants.yaml",
         lambda d: d["capabilities"]["can_drop:pcn"].update(grant_to_groups=["no-such-group"]))
    errs = validate(pol, pol)
    assert any("no-such-group" in e and "capability_grants.yaml" in e for e in errs), errs


def test_validate_refuses_a_zero_member_group(pol):
    def drop_members(d):
        for u in d["users"]:
            u["groups"] = [g for g in (u.get("groups") or []) if g != GROUP]
    _put(pol, "users.yaml", drop_members)
    errs = validate(pol, pol)
    assert any(GROUP in e and "ZERO members" in e for e in errs), errs


def test_validate_refuses_can_drop_of_an_unknown_kind(pol):
    _put(pol, "capability_grants.yaml",
         lambda d: d["capabilities"].update({"can_drop:nosuch": _row()}))
    errs = validate(pol, pol)
    assert any("can_drop:nosuch" in e and "NOT a known content kind" in e for e in errs), errs


# -- the grantor ---------------------------------------------------------------------------

def test_a_capability_grants_refusal_resolves_a_grantable_by_and_is_not_object_scoped():
    from iagent.authz import refusal as r
    out = r.refusal("capability_grants:can_drop:pcn", "invoker on capability:can_drop:pcn")
    assert out["grantable_by"].strip() and "not declared" not in out["grantable_by"]
    assert r.grantors()["capability_grants"].object_scoped is False
