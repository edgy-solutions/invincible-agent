"""The `can_decide:<workflow_id>.<option>` rail (`policy/option_deciders.yaml`) -- ADR-0065 (provisional, not yet
written). Validator only.

WHAT EACH GROUP DEFENDS
  seed        the shipped rail parses clean, and the validate_policy CLI is green and prints its line.
  red arms    one per error class, each differing from the valid baseline in exactly one thing,
              each asserting a FRAGMENT of the message.
  when present  an absent file is valid; an error from the file reaches `validate()`, with the real
              groups and users.
  one home    a `can_decide:<x>` row in capability_grants.yaml is refused, naming this rail's file, and
              that refusal is distinct from the `cleared_for:` one.

Nothing reads the file yet (a workflow definition's decide step will carry the options, ruling 3), so
option membership and one-row-per-offered-option are not checked. The fixture workflows and options are
neutral ids, never a real one.

Run:  uv run pytest tests/security/test_option_deciders_rail.py -q
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
_RAIL = yaml.safe_load((_POLICY / "option_deciders.yaml").read_text(encoding="utf-8"))
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]
_GROUPS = yaml.safe_load((_POLICY / "groups.yaml").read_text(encoding="utf-8"))["groups"]

_B_USERS = [{"id": "svc:a", "groups": ["team-a"]}, {"id": "alice", "groups": ["team-a", "team-b"]}]
_B_GROUPS = {"team-a": {}, "team-b": {}, "team-empty": {}}


def _real_group() -> str:
    """A group of the real policy that has members, derived, never typed."""
    held = {g for u in _USERS for g in (u.get("groups") or [])}
    return sorted(g for g in _GROUPS if g in held)[0]


def _od(workflow="wf_a", option="opt_x", **over):
    row = {"workflow": workflow, "option": option, "grant_to_groups": ["team-a"], "granted_by": "seed",
           "reason": "because", "ratified_by": "owner"}
    row.update(over)
    return row


def _rail(*rows):
    return {"option_deciders": list(rows)}


def _ode(raw, groups=None, users=None):
    return vp.option_deciders_errors(raw, _B_GROUPS if groups is None else groups,
                                     _B_USERS if users is None else users)


def _drop(row, key):
    row = dict(row)
    del row[key]
    return row


# ---- the positive control and the seed ---------------------------------------------------------

def test_a_two_row_rail_is_clean():
    assert _ode(_rail(_od("wf_a", "opt_x"), _od("wf_a", "opt_y", grant_to_groups=["team-b"]))) == []


def test_the_same_option_under_two_workflows_is_clean():
    """Ruling 2's generic option: one row per workflow that offers it."""
    assert _ode(_rail(_od("wf_a", "opt_x"), _od("wf_b", "opt_x"))) == []


def test_the_same_workflow_and_option_twice_is_exactly_one_error():
    errs = _ode(_rail(_od(), _od()))
    assert len(errs) == 1 and "more than one row names this workflow and option" in errs[0], errs


def test_an_invalid_key_is_not_also_reported_as_a_duplicate():
    """A row whose workflow or option is invalid has its own error; it is skipped for the duplicate check."""
    errs = _ode(_rail(_od("wf.a"), _od("wf.a")))
    assert len(errs) == 2 and not any("more than one row" in e for e in errs), errs


def test_the_error_prefix_is_the_key():
    errs = _ode(_rail(_od(grant_to_groups="team-a")))
    assert errs and all(e.startswith("option_deciders.yaml: wf_a.opt_x:") for e in errs), errs


def test_an_empty_grant_to_groups_with_a_reason_is_valid():
    assert _ode(_rail(_od(grant_to_groups=[]))) == []


def test_the_shipped_rail_parses_clean():
    assert "option_deciders" in _RAIL                      # control: read
    assert vp.option_deciders_errors(_RAIL, _GROUPS, _USERS) == []


def test_the_validate_policy_cli_is_green_and_prints_its_line():
    r = subprocess.run([sys.executable, str(_SYNC / "validate_policy.py")],
                       capture_output=True, text=True, cwd=_REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert f"option_deciders.yaml: {len(_RAIL['option_deciders'])} row(s)" in r.stdout
    assert "option_deciders.yaml: 0 row(s)" in r.stdout


def test_the_rail_is_not_in_data_files():
    assert "option_deciders.yaml" not in vp.DATA_FILES


# ---- the rail: malformed top level, bad rows ---------------------------------------------------

@pytest.mark.parametrize("raw,fragment", [
    ([], "top level must be a mapping"),
    ({"option_deciders": [], "extra": 1}, "unknown key(s): extra"),
    ({"option_deciders": {"option-a": {}}}, "must be a list of rows"),
])
def test_a_malformed_rail_is_one_error(raw, fragment):
    errs = _ode(raw)
    assert len(errs) == 1 and fragment in errs[0], errs


@pytest.mark.parametrize("rows,fragment", [
    ([_drop(_od(), "workflow")], "`workflow` must be a non-empty string"),
    ([_drop(_od(), "option")], "`option` must be a non-empty string"),
    ([_od("wf.a")], "`workflow` must have no whitespace, no `:` and no `.`"),
    ([_od("wf:a")], "`workflow` must have no whitespace, no `:` and no `.`"),
    ([_od("wf a")], "`workflow` must have no whitespace, no `:` and no `.`"),
    ([_od(option="opt.x")], "`option` must have no whitespace, no `:` and no `.`"),
    ([_od(option="opt:x")], "`option` must have no whitespace, no `:` and no `.`"),
    ([_od(option="opt x")], "`option` must have no whitespace, no `:` and no `.`"),
    ([_drop(_od(), "grant_to_groups")], "`grant_to_groups` must be a list"),
    ([_od(grant_to_groups="team-a")], "`grant_to_groups` must be a list"),
    ([_od(grant_to_groups=["team-a", "team-a"])], "group 'team-a' is listed more than once"),
    ([_od(grant_to_groups=["no-such-group"])], "NOT a group in groups.yaml"),
    ([_od(grant_to_groups=["team-empty"])], "ZERO members in users.yaml"),
    ([_od(grant_to=["someone"])], "unknown key 'grant_to'"),
    ([_drop(_od(), "granted_by")], "`granted_by` must be a non-empty string"),
    ([_drop(_od(), "reason")], "`reason` must be a non-empty string"),
    ([_drop(_od(), "ratified_by")], "`ratified_by` must be a non-empty string"),
    ([_od(ratified_by="alice")], "names a seat"),
])
def test_a_bad_rail_row_is_refused(rows, fragment):
    errs = _ode(_rail(*rows))
    assert any(fragment in e for e in errs), errs
    assert all(e.startswith("option_deciders.yaml: ") for e in errs), errs


# ---- through validate() ------------------------------------------------------------------------

def _policy_copy(tmp_path):
    pol = tmp_path / "policy"
    shutil.copytree(_POLICY, pol, ignore=shutil.ignore_patterns("__pycache__"))
    return pol


def _put(pol, name, raw):
    (pol / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _errs(pol, *files):
    return [e for e in vp.validate(pol, pol) if e.startswith(files)]


_FILES = ("option_deciders.yaml",)


def test_validate_is_clean_as_copied(tmp_path):
    """The control for every arm below."""
    assert _errs(_policy_copy(tmp_path), *_FILES) == []


def test_the_rail_absent_is_clean(tmp_path):
    pol = _policy_copy(tmp_path)
    (pol / "option_deciders.yaml").unlink()
    assert _errs(pol, *_FILES) == []


def test_validate_carries_a_rail_error(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "option_deciders.yaml", _rail(_od("wf_a", "opt_x", grant_to_groups=[_real_group()], colour="red")))
    errs = _errs(pol, *_FILES)
    assert any("unknown key 'colour'" in e for e in errs), errs


def test_validate_passes_the_real_groups_and_users_to_the_rail(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, "option_deciders.yaml", _rail(_od("wf_a", "opt_x", grant_to_groups=[_real_group()])))
    assert _errs(pol, *_FILES) == []                       # the control: a real group is clean
    _put(pol, "option_deciders.yaml", _rail(_od("wf_a", "opt_x", grant_to_groups=["no-such-group"])))
    assert any("NOT a group in groups.yaml" in e for e in _errs(pol, *_FILES))


# ---- one home ----------------------------------------------------------------------------------

def _caps_with(pol, key):
    caps = yaml.safe_load((pol / "capability_grants.yaml").read_text(encoding="utf-8"))
    first = next(iter(caps["capabilities"].values()))
    caps = copy.deepcopy(caps)
    caps["capabilities"][key] = copy.deepcopy(first)
    _put(pol, "capability_grants.yaml", caps)
    return [e for e in vp.validate(pol, pol) if key in e]


def test_a_can_decide_capability_row_is_refused(tmp_path):
    pol = _policy_copy(tmp_path)
    assert [e for e in vp.validate(pol, pol) if "can_decide:" in e] == []   # the control
    errs = _caps_with(pol, "can_decide:wf_a.opt_x")
    assert any("an option's deciders are rows of policy/option_deciders.yaml, not a capability row" in e
               for e in errs), errs


def test_a_cleared_for_refusal_and_a_can_decide_refusal_are_distinct(tmp_path):
    pol = _policy_copy(tmp_path)
    cleared = _caps_with(pol, "cleared_for:level-a")
    decide = _caps_with(pol, "can_decide:wf_a.opt_x")
    assert any("policy/level_readers.yaml" in e for e in cleared), cleared
    assert not any("option_deciders.yaml" in e for e in cleared), cleared
    assert any("policy/option_deciders.yaml" in e for e in decide), decide
    assert not any("level_readers.yaml" in e for e in decide), decide
