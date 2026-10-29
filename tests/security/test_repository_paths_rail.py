"""The `policy/repository_paths.yaml` rail (ADR-0062 section 5) and its validator.

WHAT EACH GROUP DEFENDS
  seed        the shipped rail validates clean against the shipped audiences, groups and users, the
              validate_policy CLI is green and prints the rail's line, and engine-r's own parser and
              `Policy` accept the very same file.
  join        `validate_policy.GOVERNED_ROOTS` equals `repo_core.GOVERNED_ROOTS` (the validator
              restates it because pygit2 is not in every image).
  ratchets    the floor on `policy/` rows, and the deliberate absence of an asset_grants row.
  red arms    one per error class (4a-4g), each differing from the valid baseline in exactly one
              thing, each asserting a FRAGMENT of the message.

Run:  uv run pytest tests/security/test_repository_paths_rail.py -q
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SYNC = _REPO / "policy" / "sync"
for _p in (str(_SYNC), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import validate_policy as vp  # noqa: E402
from task_grant_sync import load_audiences  # noqa: E402

_POLICY = _REPO / "policy"
_RAIL = _POLICY / "repository_paths.yaml"
REPO = "invincible-agent"


def _load(name: str) -> dict:
    return yaml.safe_load((_POLICY / name).read_text(encoding="utf-8")) or {}


_SEED = _load("repository_paths.yaml")
_AUDIENCES, _AUD_ERRORS = load_audiences(_load("task_grants.yaml"))
_GROUPS = _load("groups.yaml").get("groups") or {}
_USERS = _load("users.yaml").get("users") or []


def _errs(raw, audiences=None, groups=None, users=None):
    return vp.repository_paths_errors(
        raw, _AUDIENCES if audiences is None else audiences,
        _GROUPS if groups is None else groups, _USERS if users is None else users)


# ---- the valid baseline: small, in memory, differs from every red arm in one thing ----------

class _Aud:
    def __init__(self, key, grant_to=(), grant_to_groups=()):
        self.key, self.grant_to, self.grant_to_groups = key, tuple(grant_to), tuple(grant_to_groups)


_B_AUDS = [_Aud("rv:A", ["u1", "u2"]), _Aud("rv:B", ["u1", "u2"]), _Aud("rv:S", ["u1", "u2"])]
_B_USERS = [{"id": "u1"}, {"id": "u2"}]


def _row(**over):
    row = {"review": "rv:A", "approvers": 2, "granted_by": "cnogradi", "reason": "because"}
    row.update(over)
    return row


def _base():
    return {"repository_paths": {REPO: {
        "paths": {
            "policy/": _row(),
            "sessions/": _row(review="owning_lane", unowned_review="rv:S", approvers=1),
        },
        "tags": {"rel-*": _row(review="rv:B")},
    }}}


def _b(raw, **kw):
    kw.setdefault("audiences", _B_AUDS)
    kw.setdefault("groups", {})
    kw.setdefault("users", _B_USERS)
    return vp.repository_paths_errors(raw, kw["audiences"], kw["groups"], kw["users"])


def _mut(fn):
    raw = _base()
    fn(raw["repository_paths"][REPO], raw)
    return raw


# ---- 8. the positive control -------------------------------------------------------------------

def test_the_valid_baseline_is_clean():
    assert _b(_base()) == []


# ---- 1-3. the seed -----------------------------------------------------------------------------

def test_the_seed_parses_clean():
    assert not _AUD_ERRORS
    assert _errs(_SEED) == []


def test_the_validate_policy_cli_is_green_and_prints_the_rail():
    r = subprocess.run([sys.executable, str(_SYNC / "validate_policy.py")],
                       capture_output=True, text=True, cwd=_REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert "repository_paths.yaml:" in r.stdout


def test_the_consumer_reads_the_seed():
    """Built the real `repo_core.Policy` (a signer from `sshsig.Signer.generate()`, as the
    engine-r tests do); `Policy.__post_init__` raises on any prefix outside the governed roots."""
    pytest.importorskip("pygit2")
    from agent_fleet.repository_agent import repo_core, sshsig

    text = _RAIL.read_text(encoding="utf-8")
    keys = repo_core.parse_repository_paths(text, REPO)
    assert set(keys) == set(_SEED["repository_paths"][REPO]["paths"])
    assert keys
    repo_core.Policy(governed=keys, customer_terms=[], signer=sshsig.Signer.generate(),
                     committer_name="x", committer_email="x@x")


# ---- 4. the join -------------------------------------------------------------------------------

def test_the_governed_roots_join():
    pytest.importorskip("pygit2")
    from agent_fleet.repository_agent import repo_core

    assert vp.GOVERNED_ROOTS == repo_core.GOVERNED_ROOTS


# ---- 5-6. ratchets on the seed -----------------------------------------------------------------

def test_only_program_members_sits_below_the_policy_floor():
    """The `policy/` rows with fewer than two approvers are exactly `policy/program_members.yaml`
    (one Grant, ruled 2026-10-28). A NEW member of this set needs a ruling, not an edit."""
    paths = _SEED["repository_paths"][REPO]["paths"]
    below = {k for k, v in paths.items() if k.startswith("policy/") and v["approvers"] < 2}
    assert below == {"policy/program_members.yaml"}


def test_asset_grants_has_no_row_of_its_own_pending_the_ruling():
    """DELIBERATE: section 5 gives `policy/asset_grants.yaml` the audience `access_grant:<DOMAIN>`
    at 2, but `access_grant:DATA_ENGINEERING` has one user, so rule 8 would refuse the row. The
    architect's ruling (a second member, or a different count) is OPEN. When the row is added this
    arm flips, which is the prompt to re-read that ruling and this docstring."""
    assert "policy/asset_grants.yaml" not in _SEED["repository_paths"][REPO]["paths"]


# ---- 7. one red arm per error class ------------------------------------------------------------

def _del_paths(r, raw):
    del r["paths"]


def _red(raw, fragment, **kw):
    errs = _b(raw, **kw)
    assert any(fragment in e for e in errs), errs
    assert all(e.startswith("repository_paths.yaml:") for e in errs), errs


def test_a_clean_row_mutation_stays_clean():
    """Control for the arms below: a mutation that changes nothing the rules decide on is green."""
    assert _b(_mut(lambda r, raw: r["paths"]["policy/"].update(reason="other"))) == []


def test_unknown_top_level_key():
    raw = _base()
    raw["extra"] = {}
    _red(raw, "unknown key(s): extra")


def test_top_level_not_a_mapping():
    _red([], "exactly one key")


def test_unknown_repository_key():
    _red(_mut(lambda r, raw: r.update(rules={})), "unknown key 'rules'")


def test_unknown_row_key_approver():
    def f(r, raw):
        r["paths"]["policy/"]["approver"] = 2
    _red(_mut(f), "paths: policy/: unknown key 'approver'")


def test_unknown_row_key_on_a_tag():
    def f(r, raw):
        r["tags"]["rel-*"]["approver"] = 2
    _red(_mut(f), "tags: rel-*: unknown key 'approver'")


def test_missing_paths():
    _red(_mut(_del_paths), "`paths` is required")


def test_prefix_outside_the_governed_roots():
    def f(r, raw):
        r["paths"]["src/"] = _row()
    _red(_mut(f), "paths: src/: outside the governed roots")


def test_prefix_with_a_dotdot_segment():
    def f(r, raw):
        r["paths"]["policy/../src/"] = _row()
    _red(_mut(f), "paths: policy/../src/: a `..` segment")


def test_prefix_with_a_leading_slash():
    def f(r, raw):
        r["paths"]["/policy/"] = _row()
    _red(_mut(f), "paths: /policy/: a leading `/`")


def test_star_in_a_path_key():
    def f(r, raw):
        r["paths"]["policy/*.yaml"] = _row()
    _red(_mut(f), "paths: policy/*.yaml: `*` is not allowed")


def test_approvers_missing():
    def f(r, raw):
        del r["paths"]["policy/"]["approvers"]
    _red(_mut(f), "paths: policy/: `approvers` is required")


@pytest.mark.parametrize("bad", [True, 0, "2", 1.5])
def test_approvers_must_be_an_int_of_at_least_one(bad):
    def f(r, raw):
        r["paths"]["policy/"]["approvers"] = bad
    _red(_mut(f), "`approvers` must be an int >= 1")


def test_review_missing():
    def f(r, raw):
        del r["paths"]["policy/"]["review"]
    _red(_mut(f), "paths: policy/: `review` is required")


def test_review_not_an_audience():
    _red(_mut(lambda r, raw: r["paths"]["policy/"].update(review="nope:X")),
         "`review` 'nope:X' is not an audience")


def test_owning_lane_on_policy():
    def f(r, raw):
        r["paths"]["policy/"].update(review="owning_lane", unowned_review="rv:S")
    _red(_mut(f), "paths: policy/: `review: owning_lane` is legal only on a `sessions/` path row")


def test_owning_lane_on_a_tag():
    def f(r, raw):
        r["tags"]["rel-*"].update(review="owning_lane", unowned_review="rv:S")
    _red(_mut(f), "tags: rel-*: `review: owning_lane` is legal only")


def test_owning_lane_on_a_tag_named_under_sessions():
    """The tag clause on its own: a tag pattern that starts `sessions/` passes the path test, so
    only `is_tag` refuses it. (The `rel-*` arm above is refused by the path test as well, so it
    cannot see the tag clause go missing; mutant R2, 2026-10-29.)"""
    def f(r, raw):
        r["tags"]["sessions/*"] = _row(review="owning_lane", unowned_review="rv:S", approvers=1)
    _red(_mut(f), "tags: sessions/*: `review: owning_lane` is legal only")




def test_owning_lane_without_unowned_review():
    def f(r, raw):
        del r["paths"]["sessions/"]["unowned_review"]
    _red(_mut(f), "requires `unowned_review`")


def test_unowned_review_not_an_audience():
    def f(r, raw):
        r["paths"]["sessions/"]["unowned_review"] = "nope:X"
    _red(_mut(f), "`unowned_review` 'nope:X' is not an audience")


def test_unowned_review_on_a_non_owning_lane_row():
    def f(r, raw):
        r["paths"]["policy/"]["unowned_review"] = "rv:S"
    _red(_mut(f), "`unowned_review` is allowed only on an `owning_lane` row")


def test_granted_by_missing():
    def f(r, raw):
        del r["paths"]["policy/"]["granted_by"]
    _red(_mut(f), "paths: policy/: `granted_by` is required")


def test_reason_missing():
    def f(r, raw):
        del r["paths"]["policy/"]["reason"]
    _red(_mut(f), "paths: policy/: `reason` is required")


def test_tag_row_is_held_to_the_same_fields():
    def f(r, raw):
        del r["tags"]["rel-*"]["reason"]
    _red(_mut(f), "tags: rel-*: `reason` is required")


def test_empty_tag_key():
    def f(r, raw):
        r["tags"][""] = _row()
    _red(_mut(f), "tag pattern must be a non-empty str")


# ---- rule 8 ------------------------------------------------------------------------------------

def test_rule_8_an_audience_with_one_user_cannot_carry_two_approvers():
    auds = [_Aud("rv:A", ["u1"]), _Aud("rv:B", ["u1", "u2"]), _Aud("rv:S", ["u1", "u2"])]
    _red(_base(), "audience 'rv:A' (review) has 1 distinct user(s) but the row requires 2", audiences=auds)


def test_rule_8_checks_unowned_review_too():
    auds = [_Aud("rv:A", ["u1", "u2"]), _Aud("rv:B", ["u1", "u2"]), _Aud("rv:S", ["u1"])]
    raw = _mut(lambda r, raw: r["paths"]["sessions/"].update(approvers=2))
    _red(raw, "audience 'rv:S' (unowned_review) has 1 distinct user(s) but the row requires 2",
         audiences=auds)


def test_rule_8_counts_group_members():
    auds = [_Aud("rv:A", [], ["g"]), _Aud("rv:B", ["u1", "u2"]), _Aud("rv:S", ["u1", "u2"])]
    users = [{"id": "u1", "groups": ["g"]}, {"id": "u2", "groups": ["g"]}]
    assert _b(_base(), audiences=auds, groups={"g": {}}, users=users) == []


def test_rule_8_counts_distinct_users():
    """alice in `grant_to` AND in the group is ONE user, so two approvers is refused."""
    auds = [_Aud("rv:A", ["u1"], ["g"]), _Aud("rv:B", ["u1", "u2"]), _Aud("rv:S", ["u1", "u2"])]
    users = [{"id": "u1", "groups": ["g"]}]
    _red(_base(), "audience 'rv:A' (review) has 1 distinct user(s)", audiences=auds,
         groups={"g": {}}, users=users)


def test_rule_8_does_not_expand_groups_of_groups():
    """One level: a member listed under a group counts; nothing deeper is read."""
    auds = [_Aud("rv:A", [], ["g"]), _Aud("rv:B", ["u1", "u2"]), _Aud("rv:S", ["u1", "u2"])]
    users = [{"id": "u1", "groups": ["g"]}, {"id": "u2", "groups": ["other"]}]
    _red(_base(), "audience 'rv:A' (review) has 1 distinct user(s)", audiences=auds,
         groups={"g": {}}, users=users)


def test_the_seed_survives_a_deep_copy_mutation_control():
    """Positive control on the seed arms: change one seed row's approvers beyond its audience and
    the same call goes red, so a green seed is a measurement and not a vacuous pass."""
    raw = copy.deepcopy(_SEED)
    raw["repository_paths"][REPO]["paths"]["docs/adr/"]["approvers"] = 99
    assert any("docs/adr/" in e and "requires 99" in e for e in _errs(raw))


# ---- the wiring: validate() carries the rail's errors ------------------------------------------

def test_validate_carries_a_rail_error_and_is_clean_without_it(tmp_path):
    """`validate()` on a copy of the policy dir: clean as copied (the control), and refused once one
    row's `approvers` is 0. Without this arm the CLI test stays green with the rail's errors
    dropped on the floor (mutant R13, 2026-10-29)."""
    import shutil

    pol = tmp_path / "policy"
    shutil.copytree(_POLICY, pol, ignore=shutil.ignore_patterns("__pycache__"))
    assert [e for e in vp.validate(pol, pol) if e.startswith("repository_paths.yaml")] == []
    raw = copy.deepcopy(_SEED)
    raw["repository_paths"][REPO]["paths"]["docs/adr/"]["approvers"] = 0
    (pol / "repository_paths.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    errs = vp.validate(pol, pol)
    assert any(e.startswith("repository_paths.yaml") and "docs/adr/" in e and ">= 1" in e
               for e in errs), errs
