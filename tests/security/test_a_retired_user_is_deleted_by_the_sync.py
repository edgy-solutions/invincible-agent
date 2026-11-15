"""A user declared in users.yaml `retired_users` is deleted by topaz_sync, with its relations.

`user` is ensure-only in every sync (ENSURE_ONLY_TYPES), so an identity that nothing asserts any
more is never pruned. bob@company.com and alice@company.com, the old DataHub seed owners, were
still in the sandbox directory three months after 0.4.80 moved the seed to @example.com
(architect dispatch 2026-11-14, item 6: fix in policy, not by hand).

Seals:
- plan_diff deletes a retired user, and no other ensure-only user (the control is the same live
  set and the same desired state, with the retired id left out);
- load_policy refuses a retired id that another policy file still names, or that users.yaml
  also asserts, or lists twice; the unmodified copy of policy/ loads (positive control);
- main() passes the retired ids into the plan, finds a retired user the listing missed by exact
  key, and fails (rc 4) when a retired user is still there after the apply.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_REPO = Path(__file__).resolve().parents[2]
_SYNC = _REPO / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

import topaz_sync  # noqa: E402
from topaz_sync import (  # noqa: E402
    DesiredState,
    DirObject,
    PolicyBundle,
    load_policy,
    plan_diff,
)

_POLICY = _REPO / "policy"
RETIRED = "bob@company.com"


# --------------------------------------------------------------------------- plan_diff

def _live():
    return {
        DirObject("user", RETIRED),
        DirObject("user", "someone-a-grant-sync-ensured@example.com"),
    }


def test_plan_deletes_the_retired_user_and_no_other():
    plan = plan_diff(DesiredState(), _live(), set(), frozenset({RETIRED}))
    assert plan.del_objects == [DirObject("user", RETIRED)]


def test_control_without_the_retirement_no_user_is_deleted():
    plan = plan_diff(DesiredState(), _live(), set())
    assert plan.del_objects == []


def test_a_retired_id_that_is_desired_is_not_deleted():
    # The loader refuses this state; plan_diff must still not delete an object it is told to want.
    desired = DesiredState(objects={DirObject("user", RETIRED)})
    plan = plan_diff(desired, _live(), set(), frozenset({RETIRED}))
    assert plan.del_objects == []


# --------------------------------------------------------------------------- load_policy

def test_the_shipped_policy_retires_the_two_seed_twins():
    bundle = load_policy(_POLICY)
    ids = {r.id for r in bundle.retired_users}
    assert {"alice@company.com", "bob@company.com"} <= ids
    assert not ids & {u.id for u in bundle.users}


@pytest.fixture
def policy_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "policy"
    shutil.copytree(_POLICY, dst, ignore=shutil.ignore_patterns("__pycache__", "*.secret.yaml"))
    return dst


def test_positive_control_the_unmodified_copy_loads(policy_copy: Path):
    assert RETIRED in {r.id for r in load_policy(policy_copy).retired_users}


def test_a_retired_id_named_in_another_policy_file_is_refused(policy_copy: Path):
    target = policy_copy / "groups.yaml"
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n# {RETIRED}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"still named in groups\.yaml"):
        load_policy(policy_copy)


def test_a_retired_id_named_in_a_nested_users_yaml_is_refused(policy_copy: Path):
    # Only policy/users.yaml itself is exempt, not any file of that name.
    target = policy_copy / "grantors" / "users.yaml"
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n# {RETIRED}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"still named in grantors/users\.yaml"):
        load_policy(policy_copy)


def test_a_configmap_mounts_hidden_copy_does_not_refuse(policy_copy: Path):
    # A ConfigMap volume keeps every file twice: the visible link and `..data/<file>`.
    hidden = policy_copy / "..data"
    hidden.mkdir()
    shutil.copy2(policy_copy / "users.yaml", hidden / "users.yaml")
    assert RETIRED in {r.id for r in load_policy(policy_copy).retired_users}


def _bundle_with(retired: list[dict]) -> dict:
    data = load_policy(_POLICY).model_dump()
    data["retired_users"] = retired
    return data


def test_a_retired_id_also_asserted_in_users_is_refused():
    asserted = load_policy(_POLICY).users[0].id
    row = {"id": asserted, "reason": "r", "ruled": "r"}
    with pytest.raises(ValidationError, match="asserted or retired"):
        PolicyBundle.model_validate(_bundle_with([row]))


def test_a_retired_id_listed_twice_is_refused():
    row = {"id": RETIRED, "reason": "r", "ruled": "r"}
    with pytest.raises(ValidationError, match="more than once"):
        PolicyBundle.model_validate(_bundle_with([row, row]))


def test_a_retired_row_without_its_reason_is_refused():
    with pytest.raises(ValidationError):
        PolicyBundle.model_validate(_bundle_with([{"id": RETIRED, "reason": "", "ruled": "r"}]))


# --------------------------------------------------------------------------- main() wiring

class _FakeDirectory:
    """Stands in for TopazClient. `listed` is what the listing returns; `stored` is what an
    exact-key lookup finds; `delete_works` False models a delete that silently did nothing."""

    def __init__(self, listed: set, stored: set, delete_works: bool = True):
        self.listed, self.stored, self.delete_works = listed, stored, delete_works
        self.deleted: list[DirObject] = []

    def __call__(self, *_a, **_k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def object_exists(self, obj_type: str, obj_id: str) -> bool:
        return DirObject(obj_type, obj_id) in self.stored

    def delete_object(self, obj, with_relations: bool = True):
        self.deleted.append(obj)
        if self.delete_works:
            self.stored.discard(obj)

    def delete_relation(self, rel):
        pass

    def set_object(self, obj, display_name: str = ""):
        pass

    def set_relation(self, rel):
        pass


def _run_main(monkeypatch, fake: _FakeDirectory) -> int:
    monkeypatch.setattr(topaz_sync, "TopazClient", fake)
    monkeypatch.setattr(topaz_sync, "snapshot_live", lambda c: (set(c.listed), set()))
    monkeypatch.setattr(topaz_sync, "readback_verify", lambda c, b: (0, 0))
    monkeypatch.setattr(sys, "argv", ["topaz_sync", "--policy-dir", str(_POLICY)])
    return topaz_sync.main()


def test_main_deletes_a_retired_user_the_listing_returned(monkeypatch):
    bob = DirObject("user", RETIRED)
    fake = _FakeDirectory(listed={bob}, stored={bob})
    assert _run_main(monkeypatch, fake) == 0
    assert bob in fake.deleted


def test_main_deletes_a_retired_user_the_listing_missed(monkeypatch):
    bob = DirObject("user", RETIRED)
    fake = _FakeDirectory(listed=set(), stored={bob})
    assert _run_main(monkeypatch, fake) == 0
    assert bob in fake.deleted


def test_main_fails_when_a_retired_user_survives_the_apply(monkeypatch):
    bob = DirObject("user", RETIRED)
    fake = _FakeDirectory(listed={bob}, stored={bob}, delete_works=False)
    assert _run_main(monkeypatch, fake) == 4
