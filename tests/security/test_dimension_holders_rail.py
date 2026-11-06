"""The `holds:<dimension>:<value>` rail (`policy/dimension_holders.yaml`) -- gov ruling 2026-11-06.
Validator only; nothing reads it yet (dag-tools step 5).

WHAT EACH GROUP DEFENDS
  seed        the shipped rail parses clean, and the validate_policy CLI is green and prints both lines.
  red arms    one per error class, each differing from the valid baseline in exactly one thing,
              each asserting a FRAGMENT of the message.
  complete    every value of a SET dimension has a row, and a hierarchical value never needs one.
  unordered   rows out of vocabulary order are clean: a set has no order, so no ceiling check.
  refused     a refused registry (`dims=None`) gives the rail no membership or completeness error.
  when present  an absent rail is clean with no set dimension, and reports missing rows with one.
  one home    a `holds:` capability row is refused, naming this rail, distinct from `cleared_for:`.

Fixture ids are neutral (`dim-h`, `dim-s`, `v1`...), never a real dimension.

Run:  uv run pytest tests/security/test_dimension_holders_rail.py -q
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
_REGISTRY = yaml.safe_load((_POLICY / "classification" / "dimensions.yaml").read_text(encoding="utf-8"))
_RAIL = yaml.safe_load((_POLICY / "dimension_holders.yaml").read_text(encoding="utf-8"))
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]
_GROUPS = yaml.safe_load((_POLICY / "groups.yaml").read_text(encoding="utf-8"))["groups"]

_B_USERS = [{"id": "svc:a", "groups": ["team-a"]}, {"id": "alice", "groups": ["team-a", "team-b"]}]
_B_GROUPS = {"team-a": {}, "team-b": {}, "team-empty": {}}

_DIMS = {"dim-s": ("set", ["v1", "v2"]), "dim-h": ("hierarchical", ["level-a", "level-b"])}


def _real_group() -> str:
    """A group of the real policy that has members, derived, never typed."""
    held = {g for u in _USERS for g in (u.get("groups") or [])}
    return sorted(g for g in _GROUPS if g in held)[0]


def _dh(dimension="dim-s", value="v1", **over):
    row = {"dimension": dimension, "value": value, "grant_to_groups": ["team-a"],
           "granted_by": "seed", "reason": "because", "ratified_by": "owner"}
    row.update(over)
    return row


def _rail(*rows):
    return {"dimension_holders": list(rows)}


def _dhe(raw, dims=_DIMS, groups=None, users=None):
    return vp.dimension_holders_errors(raw, dims, _B_GROUPS if groups is None else groups,
                                       _B_USERS if users is None else users)


def _drop(row, key):
    row = dict(row)
    del row[key]
    return row


_FULL = _rail(_dh("dim-s", "v1"), _dh("dim-s", "v2", grant_to_groups=["team-b"]))


# ---- the positive control and the seed ---------------------------------------------------------

def test_the_shipped_rail_parses_clean():
    assert "dimension_holders" in _RAIL                   # control: read
    errs, dims = vp.classification_dimensions_errors(_REGISTRY, _USERS)
    assert errs == []
    assert vp.dimension_holders_errors(_RAIL, dims, _GROUPS, _USERS) == []


def test_the_validate_policy_cli_is_green_and_prints_both_lines():
    r = subprocess.run([sys.executable, str(_SYNC / "validate_policy.py")],
                       capture_output=True, text=True, cwd=_REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert f"dimension_holders.yaml: {len(_RAIL['dimension_holders'])} row(s)" in r.stdout
    assert "dimension_holders.yaml: 0 row(s)" in r.stdout
    assert f"classification/dimensions.yaml: {len(_REGISTRY['dimensions'])} dimension(s)" in r.stdout
    assert "classification/dimensions.yaml: 0 dimension(s)" in r.stdout


def test_the_rail_is_not_in_data_files():
    assert "dimension_holders.yaml" not in vp.DATA_FILES


def test_full_rows_for_a_set_dimension_are_clean():
    assert _dhe(_FULL) == []


def test_an_empty_grant_to_groups_with_a_reason_is_clean():
    assert _dhe(_rail(_dh("dim-s", "v1", grant_to_groups=[]), _dh("dim-s", "v2", grant_to_groups=[]))) == []


# ---- red arms ----------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,fragment", [
    ([], "top level must be a mapping"),
    ({"dimension_holders": [], "extra": 1}, "unknown key(s): extra"),
    ({"dimension_holders": {"dim-s": {}}}, "must be a list of rows"),
])
def test_a_malformed_rail_is_one_error(raw, fragment):
    errs = _dhe(raw)
    assert len(errs) == 1 and fragment in errs[0], errs


_V2 = _dh("dim-s", "v2", grant_to_groups=["team-b"])
_V1 = _dh("dim-s", "v1", grant_to_groups=["team-b"])


@pytest.mark.parametrize("rows,fragment", [
    ([_drop(_dh(), "dimension"), _V2], "`dimension` must be a non-empty string"),
    ([_drop(_dh(), "value"), _V2], "`value` must be a non-empty string"),
    ([_dh("dim-z", "v1"), _V1, _V2], "`dim-z` is not a dimension in classification/dimensions.yaml"),
    ([_dh("dim-h", "level-a"), _V1, _V2],
     "`dim-h` is hierarchical: its values are cleared through level_readers.yaml (`cleared_for:<level>`), not held"),
    ([_dh("dim-s", "v9"), _V1, _V2], "`v9` is not in the vocabulary of `dim-s`"),
    ([_dh(), _dh(), _V2], "more than one row names this dimension and value"),
    ([_drop(_dh(), "grant_to_groups"), _V2], "`grant_to_groups` must be a list"),
    ([_dh(grant_to_groups="team-a"), _V2], "`grant_to_groups` must be a list"),
    ([_dh(grant_to_groups=["team-a", "team-a"]), _V2], "group 'team-a' is listed more than once"),
    ([_dh(grant_to_groups=["no-such-group"]), _V2], "NOT a group in groups.yaml"),
    ([_dh(grant_to_groups=["team-empty"]), _V2], "ZERO members in users.yaml"),
    ([_dh(grant_to=["someone"]), _V2], "unknown key 'grant_to'"),
    ([_drop(_dh(), "granted_by"), _V2], "`granted_by` must be a non-empty string"),
    ([_drop(_dh(), "reason"), _V2], "`reason` must be a non-empty string"),
    ([_drop(_dh(), "ratified_by"), _V2], "`ratified_by` must be a non-empty string"),
    ([_dh(ratified_by="alice"), _V2], "names a seat"),
])
def test_a_bad_row_is_refused(rows, fragment):
    errs = _dhe(_rail(*rows))
    assert any(fragment in e for e in errs), errs
    assert all(e.startswith("dimension_holders.yaml: ") for e in errs), errs


# ---- completeness ------------------------------------------------------------------------------

def test_a_set_value_with_no_row_is_reported_naming_it():
    errs = _dhe(_rail(_dh("dim-s", "v1")))
    assert len(errs) == 1 and "value `dim-s:v2` has no row" in errs[0], errs


def test_a_hierarchical_value_never_needs_a_row():
    errs = _dhe(_FULL)
    assert not any("dim-h" in e for e in errs), errs


def test_a_registry_of_only_a_hierarchical_dimension_needs_no_row():
    assert _dhe(_rail(), dims={"dim-h": _DIMS["dim-h"]}) == []


def test_a_refused_registry_gives_the_rail_no_membership_or_completeness_errors():
    assert _dhe(_rail(_dh("dim-z", "v9"), _dh("dim-h", "level-a")), dims=None) == []
    assert _dhe(_rail(), dims=None) == []


def test_rows_out_of_vocabulary_order_are_clean():
    """A set is unordered: no ceiling, no row-order dependence."""
    assert _dhe(_rail(_dh("dim-s", "v2", grant_to_groups=["team-a"]),
                      _dh("dim-s", "v1", grant_to_groups=["team-a"]))) == []


# ---- through validate() ------------------------------------------------------------------------

def _policy_copy(tmp_path):
    pol = tmp_path / "policy"
    shutil.copytree(_POLICY, pol, ignore=shutil.ignore_patterns("__pycache__"))
    return pol


def _put(pol, name, raw):
    (pol / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _errs(pol, *files):
    return [e for e in vp.validate(pol, pol) if e.startswith(files)]


_FILES = ("classification/dimensions.yaml", "dimension_holders.yaml")


def _set_dim(*vocab):
    return {"dimensions": [{"name": "dim-s", "type": "set", "vocabulary": list(vocab), "owner": "owner"}]}


def test_validate_is_clean_as_copied(tmp_path):
    """The control for every arm below."""
    assert _errs(_policy_copy(tmp_path), *_FILES) == []


def test_the_rail_absent_with_no_dimensions_is_clean(tmp_path):
    pol = _policy_copy(tmp_path)
    (pol / "dimension_holders.yaml").unlink()
    assert _errs(pol, *_FILES) == []


def test_a_set_dimension_with_the_rail_absent_reports_its_missing_rows(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "classification/dimensions.yaml", _set_dim("v1", "v2"))
    (pol / "dimension_holders.yaml").unlink()
    errs = _errs(pol, *_FILES)
    assert len(errs) == 2 and all("has no row" in e for e in errs), errs


def test_validate_carries_a_rail_error(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "classification/dimensions.yaml", _set_dim("v1"))
    _put(pol, "dimension_holders.yaml", _rail(_dh("dim-s", "v1", grant_to_groups=[_real_group()],
                                                  colour="red")))
    errs = _errs(pol, *_FILES)
    assert any(e.startswith("dimension_holders.yaml") and "unknown key 'colour'" in e for e in errs), errs


def test_validate_passes_the_real_groups_and_users_to_the_rail(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "classification/dimensions.yaml", _set_dim("v1"))
    _put(pol, "dimension_holders.yaml", _rail(_dh("dim-s", "v1", grant_to_groups=[_real_group()])))
    assert _errs(pol, *_FILES) == []                      # the control: a real group is clean
    _put(pol, "dimension_holders.yaml", _rail(_dh("dim-s", "v1", grant_to_groups=["no-such-group"])))
    assert any("NOT a group in groups.yaml" in e for e in _errs(pol, *_FILES))


# ---- one home ----------------------------------------------------------------------------------

def _with_cap(pol, key):
    caps = yaml.safe_load((pol / "capability_grants.yaml").read_text(encoding="utf-8"))
    first = next(iter(caps["capabilities"].values()))
    caps = copy.deepcopy(caps)
    caps["capabilities"][key] = copy.deepcopy(first)
    _put(pol, "capability_grants.yaml", caps)


def test_a_holds_capability_row_is_refused_naming_this_rail(tmp_path):
    pol = _policy_copy(tmp_path)
    assert [e for e in vp.validate(pol, pol) if "holds:" in e] == []     # the control
    _with_cap(pol, "holds:dim-s:v1")
    errs = [e for e in vp.validate(pol, pol) if "holds:dim-s:v1" in e]
    assert any("a dimension value's holders are rows of policy/dimension_holders.yaml, "
               "not a capability row" in e for e in errs), errs


def test_the_cleared_for_and_holds_refusals_are_distinct(tmp_path):
    pol = _policy_copy(tmp_path)
    _with_cap(pol, "holds:dim-s:v1")
    _with_cap(pol, "cleared_for:level-a")
    errs = vp.validate(pol, pol)
    holds = [e for e in errs if "holds:dim-s:v1" in e]
    cleared = [e for e in errs if "cleared_for:level-a" in e]
    assert holds and cleared
    assert all("dimension_holders.yaml" in e and "level_readers.yaml" not in e for e in holds), holds
    assert all("level_readers.yaml" in e and "dimension_holders.yaml" not in e for e in cleared), cleared
