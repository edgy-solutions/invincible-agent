"""The `can_read:<level>` rail (`policy/level_readers.yaml`) and the levels registry
(`policy/classification_levels.yaml`) -- ADR-0064 item B (Proposed, #266). Validator only.

WHAT EACH GROUP DEFENDS
  seed        the shipped registry and rail parse clean, and the validate_policy CLI is green and
              prints both lines.
  order       list position IS the level order: reversing the rows reverses `levels`.
  red arms    one per error class, each differing from the valid baseline in exactly one thing,
              each asserting a FRAGMENT of the message.
  refused     a refused registry gives the rail no "unknown level" error of its own.
  when present  an absent file is valid; an absent registry registers no level; a registered level
              with the rail absent reports its missing row; errors from each file reach `validate()`.
  one home    a `can_read:<x>` row in capability_grants.yaml is refused.

Nothing reads either file yet (dag-tools step 5 serves a dataset's level). The fixture levels are
neutral names, never a real level.

Run:  uv run pytest tests/security/test_level_readers_rail.py -q
"""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SYNC = _REPO / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

import validate_policy as vp  # noqa: E402

_POLICY = _REPO / "policy"
_REGISTRY = yaml.safe_load((_POLICY / "classification_levels.yaml").read_text(encoding="utf-8"))
_RAIL = yaml.safe_load((_POLICY / "level_readers.yaml").read_text(encoding="utf-8"))
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]
_GROUPS = yaml.safe_load((_POLICY / "groups.yaml").read_text(encoding="utf-8"))["groups"]

_B_USERS = [{"id": "svc:a", "groups": ["team-a"]}, {"id": "alice", "groups": ["team-a", "team-b"]}]
_B_GROUPS = {"team-a": {}, "team-b": {}, "team-empty": {}}


def _real_group() -> str:
    """A group of the real policy that has members, derived, never typed."""
    held = {g for u in _USERS for g in (u.get("groups") or [])}
    return sorted(g for g in _GROUPS if g in held)[0]


def _lvl(lid="level-a", **over):
    row = {"id": lid, "reason": "because", "ratified_by": "owner"}
    row.update(over)
    return row


def _reg(*rows):
    return {"classification_levels": list(rows)}


def _lr(level="level-a", **over):
    row = {"level": level, "grant_to_groups": ["team-a"], "granted_by": "seed",
           "reason": "because", "ratified_by": "owner"}
    row.update(over)
    return row


def _rail(*rows):
    return {"level_readers": list(rows)}


def _cl(raw, users=None):
    return vp.classification_levels_errors(raw, _B_USERS if users is None else users)


def _lre(raw, levels, groups=None, users=None):
    return vp.level_readers_errors(raw, levels, _B_GROUPS if groups is None else groups,
                                   _B_USERS if users is None else users)


def _drop(row, key):
    row = dict(row)
    del row[key]
    return row


_AB = _reg(_lvl("level-a"), _lvl("level-b"))


# ---- the positive control and the seed ---------------------------------------------------------

def test_a_two_level_registry_and_two_rows_are_clean():
    errs, levels = _cl(_AB)
    assert errs == [] and levels == ["level-a", "level-b"]
    assert _lre(_rail(_lr("level-a"), _lr("level-b")), levels) == []


def test_levels_come_back_in_file_order():
    """Position is the order: reversing the rows reverses the answer."""
    errs, levels = _cl(_reg(_lvl("level-b"), _lvl("level-a")))
    assert errs == [] and levels == ["level-b", "level-a"]


def test_the_shipped_files_parse_clean():
    assert "classification_levels" in _REGISTRY and "level_readers" in _RAIL   # control: read
    errs, levels = vp.classification_levels_errors(_REGISTRY, _USERS)
    assert errs == [] and levels == [r["id"] for r in _REGISTRY["classification_levels"]]
    assert vp.level_readers_errors(_RAIL, levels, _GROUPS, _USERS) == []


def test_the_validate_policy_cli_is_green_and_prints_both_lines():
    r = subprocess.run([sys.executable, str(_SYNC / "validate_policy.py")],
                       capture_output=True, text=True, cwd=_REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert f"classification_levels.yaml: {len(_REGISTRY['classification_levels'])} level(s)" in r.stdout
    assert f"level_readers.yaml: {len(_RAIL['level_readers'])} row(s)" in r.stdout


def test_neither_file_is_in_data_files():
    assert "classification_levels.yaml" not in vp.DATA_FILES
    assert "level_readers.yaml" not in vp.DATA_FILES


# ---- the registry: malformed top level, bad rows -----------------------------------------------

@pytest.mark.parametrize("raw,fragment", [
    ([], "top level must be a mapping"),
    ({"classification_levels": [], "extra": 1}, "unknown key(s): extra"),
    ({"classification_levels": {"level-a": {}}}, "must be a list of rows"),
])
def test_a_malformed_registry_is_one_error_and_no_levels(raw, fragment):
    errs, levels = _cl(raw)
    assert len(errs) == 1 and fragment in errs[0], errs
    assert levels is None


@pytest.mark.parametrize("row,fragment", [
    (_drop(_lvl(), "id"), "`id` must be a non-empty string"),
    (_lvl("level:a"), "no whitespace and no `:`"),
    (_lvl("level a"), "no whitespace and no `:`"),
    (_drop(_lvl(), "reason"), "`reason` must be a non-empty string"),
    (_drop(_lvl(), "ratified_by"), "`ratified_by` must be a non-empty string"),
    (_lvl(ratified_by="alice"), "names a seat"),
    (_lvl(colour="red"), "unknown key 'colour'"),
])
def test_a_bad_registry_row_is_refused(row, fragment):
    errs, levels = _cl(_reg(row))
    assert any(fragment in e for e in errs), errs
    assert all(e.startswith("classification_levels.yaml: ") for e in errs), errs


def test_a_duplicate_id_is_an_error_and_is_not_added_twice():
    errs, levels = _cl(_reg(_lvl("level-a"), _lvl("level-a")))
    assert any("more than one row has this id" in e for e in errs), errs
    assert levels == ["level-a"]


# ---- the rail ----------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,fragment", [
    ([], "top level must be a mapping"),
    ({"level_readers": [], "extra": 1}, "unknown key(s): extra"),
    ({"level_readers": {"level-a": {}}}, "must be a list of rows"),
])
def test_a_malformed_rail_is_one_error(raw, fragment):
    errs = _lre(raw, ["level-a"])
    assert len(errs) == 1 and fragment in errs[0], errs


@pytest.mark.parametrize("rows,fragment", [
    ([_lr("level-z")], "'level-z' is not a level in classification_levels.yaml"),
    ([_lr(), _lr()], "more than one row names this level"),
    ([_drop(_lr(), "grant_to_groups")], "`grant_to_groups` must be a list"),
    ([_lr(grant_to_groups="team-a")], "`grant_to_groups` must be a list"),
    ([_lr(grant_to_groups=["team-a", "team-a"])], "group 'team-a' is listed more than once"),
    ([_lr(grant_to_groups=["no-such-group"])], "NOT a group in groups.yaml"),
    ([_lr(grant_to_groups=["team-empty"])], "ZERO members in users.yaml"),
    ([_lr(grant_to=["someone"])], "unknown key 'grant_to'"),
    ([_drop(_lr(), "granted_by")], "`granted_by` must be a non-empty string"),
    ([_drop(_lr(), "reason")], "`reason` must be a non-empty string"),
    ([_drop(_lr(), "ratified_by")], "`ratified_by` must be a non-empty string"),
    ([_lr(ratified_by="alice")], "names a seat"),
])
def test_a_bad_rail_row_is_refused(rows, fragment):
    errs = _lre(_rail(*rows), ["level-a"])
    assert any(fragment in e for e in errs), errs
    assert all(e.startswith("level_readers.yaml: ") for e in errs), errs


def test_an_empty_grant_to_groups_with_a_reason_is_valid():
    assert _lre(_rail(_lr(grant_to_groups=[])), ["level-a"]) == []


def test_a_registered_level_with_no_row_is_refused_naming_the_level():
    errs = _lre(_rail(_lr("level-a")), ["level-a", "level-b"])
    assert len(errs) == 1 and "level 'level-b' has no row" in errs[0], errs


def test_a_refused_registry_gives_the_rail_no_level_errors():
    """`levels=None`: rows naming unregistered levels, and a registered level with no row, are
    silent; the registry's own error already stands."""
    assert _lre(_rail(_lr("level-x"), _lr("level-y")), None) == []
    assert _lre(_rail(), None) == []


# ---- through validate() ------------------------------------------------------------------------

def _policy_copy(tmp_path):
    pol = tmp_path / "policy"
    shutil.copytree(_POLICY, pol, ignore=shutil.ignore_patterns("__pycache__"))
    return pol


def _put(pol, name, raw):
    (pol / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _errs(pol, *files):
    return [e for e in vp.validate(pol, pol) if e.startswith(files)]


_FILES = ("classification_levels.yaml", "level_readers.yaml")


def test_validate_is_clean_as_copied(tmp_path):
    """The control for every arm below."""
    assert _errs(_policy_copy(tmp_path), *_FILES) == []


def test_validate_carries_an_error_from_each_file(tmp_path):
    pol = _policy_copy(tmp_path)
    grp = _real_group()
    _put(pol, "classification_levels.yaml", _reg(_lvl("level-a"), _lvl("level:b")))
    _put(pol, "level_readers.yaml", _rail(_lr("level-a", grant_to_groups=[grp], colour="red")))
    errs = _errs(pol, *_FILES)
    assert any(e.startswith("classification_levels.yaml") and "no whitespace" in e for e in errs), errs
    assert any(e.startswith("level_readers.yaml") and "unknown key 'colour'" in e for e in errs), errs


def test_validate_passes_the_real_groups_and_users_to_the_rail(tmp_path):
    pol = _policy_copy(tmp_path)
    grp = _real_group()
    _put(pol, "classification_levels.yaml", _reg(_lvl("level-a")))
    _put(pol, "level_readers.yaml", _rail(_lr("level-a", grant_to_groups=[grp])))
    assert _errs(pol, *_FILES) == []                       # the control: a real group is clean
    _put(pol, "level_readers.yaml", _rail(_lr("level-a", grant_to_groups=["no-such-group"])))
    assert any("NOT a group in groups.yaml" in e for e in _errs(pol, *_FILES))


def test_validate_with_a_broken_registry_reports_it_and_no_unknown_level(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "classification_levels.yaml", {"classification_levels": "nope"})
    _put(pol, "level_readers.yaml", _rail(_lr("level-x", grant_to_groups=[_real_group()])))
    errs = _errs(pol, *_FILES)
    assert any("must be a list of rows" in e for e in errs), errs
    assert not any("is not a level" in e for e in errs), errs


def test_both_files_absent_is_clean(tmp_path):
    pol = _policy_copy(tmp_path)
    for f in _FILES:
        (pol / f).unlink()
    assert _errs(pol, *_FILES) == []


def test_an_absent_registry_with_a_rail_row_is_an_unknown_level(tmp_path):
    pol = _policy_copy(tmp_path)
    (pol / "classification_levels.yaml").unlink()
    _put(pol, "level_readers.yaml", _rail(_lr("level-a", grant_to_groups=[_real_group()])))
    errs = _errs(pol, *_FILES)
    assert any("'level-a' is not a level in classification_levels.yaml" in e for e in errs), errs


def test_a_registered_level_with_an_absent_rail_reports_its_missing_row(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "classification_levels.yaml", _reg(_lvl("level-a")))
    (pol / "level_readers.yaml").unlink()
    errs = _errs(pol, *_FILES)
    assert len(errs) == 1 and "level 'level-a' has no row" in errs[0], errs


# ---- one home ----------------------------------------------------------------------------------

def test_a_can_read_capability_row_is_refused(tmp_path):
    pol = _policy_copy(tmp_path)
    caps = yaml.safe_load((pol / "capability_grants.yaml").read_text(encoding="utf-8"))
    first = next(iter(caps["capabilities"].values()))
    base = [e for e in vp.validate(pol, pol) if "can_read:" in e]
    assert base == []                                      # the control
    caps = copy.deepcopy(caps)
    caps["capabilities"]["can_read:level-a"] = copy.deepcopy(first)
    _put(pol, "capability_grants.yaml", caps)
    errs = [e for e in vp.validate(pol, pol) if "can_read:level-a" in e]
    assert any("a level's readers are rows of policy/level_readers.yaml, not a capability row" in e
               for e in errs), errs


@pytest.mark.parametrize("bad", ["", "level:a", "level a"])
def test_a_row_with_a_bad_id_contributes_no_level(bad):
    errs, levels = _cl(_reg(_lvl(bad)))
    assert errs and levels == []
