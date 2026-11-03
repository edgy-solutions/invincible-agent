"""The `can_configure:<subject>` rail: who may change a surface's configuration.

2026-11-02 ruling: "new capability `can_configure:deck_template` on the rail, group
`training-admins` (sandbox: alice), seed row with granted_by: seed". The check itself lives with the
surface that makes the change (the workbench asks Topaz `can_invoke` on `can_configure:<S>`); this
repo ships the row, the group and its sandbox member, and names no subject in code. Deny-by-default:
a subject with no row is configurable by nobody.

Rows, groups and members are read from policy/; the one case named here is the ruled first row.

Run:  uv run python -m pytest tests/security/test_can_configure_capability_rail.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "policy" / "sync"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import capability_grant_sync as cgs  # noqa: E402
import validate_policy as vp  # noqa: E402

PREFIX = "can_configure:"
FIRST_RULED = "can_configure:deck_template"  # the ruling's case: the workbench's deck template
RULED_GROUP = "training-admins"
RULED_SANDBOX_MEMBER = "alice@example.com"


def _load(name):
    return yaml.safe_load((ROOT / "policy" / name).read_text(encoding="utf-8"))


def _rows(caps=None) -> dict:
    caps = caps if caps is not None else _load("capability_grants.yaml")["capabilities"]
    return {k: v for k, v in caps.items() if str(k).startswith(PREFIX)}


def _cells() -> dict:
    return _load("groups.yaml")["groups"]


def _members() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for u in _load("users.yaml")["users"]:
        for g in u.get("groups") or []:
            out.setdefault(g, set()).add(u["id"])
    return out


def _defects(rows: dict, cells: dict, members: dict[str, set[str]]) -> list[str]:
    """Every way a `can_configure:` row can ship broken. Empty for a sound rail."""
    bad: list[str] = []
    for key, row in rows.items():
        row = row or {}
        if not key[len(PREFIX):].strip():
            bad.append(f"{key}: names no subject")
        if row.get("grant_to"):
            bad.append(f"{key}: grants a person directly (grant_to); grant through a group")
        groups = row.get("grant_to_groups") or []
        if not groups:
            bad.append(f"{key}: grants no group, so nobody configures")
        for g in groups:
            if g not in cells:
                bad.append(f"{key}: group {g} is not in groups.yaml")
            elif cells[g]:
                bad.append(f"{key}: group {g} carries a persona.domain cell; a configure group is capability-only")
            if not members.get(g):
                bad.append(f"{key}: group {g} has no member, so the row grants nobody")
    return bad


# -- (a) the shipped rail: the ruling's four facts ------------------------------------------

def test_a_the_ruled_row_is_a_seed_row_granting_the_ruled_group():
    row = _rows()[FIRST_RULED]
    assert row["granted_by"] == "seed"
    assert row["grant_to_groups"] == [RULED_GROUP]
    assert not row.get("grant_to")
    assert (row.get("reason") or "").strip()


def test_a_the_sandbox_member_is_the_ruled_one_and_nobody_else():
    assert _members()[RULED_GROUP] == {RULED_SANDBOX_MEMBER}


def test_a_every_shipped_configure_row_is_sound():
    rows = _rows()
    assert rows, "no can_configure row ships"
    assert _defects(rows, _cells(), _members()) == []


def test_a_the_shipped_rail_validates():
    pol = ROOT / "policy"
    assert vp.validate(pol, pol) == []


# -- (b) the detector reds on each defect form ----------------------------------------------

def _sound():
    return ({"can_configure:s": {"granted_by": "seed", "reason": "r", "grant_to_groups": ["g"]}},
            {"g": {}}, {"g": {"u@example.com"}})


def test_b_the_detector_passes_its_sound_control():
    assert _defects(*_sound()) == []


@pytest.mark.parametrize("form", ["person", "no_group", "unknown_group", "cell_group", "empty_group",
                                  "no_subject"])
def test_b_the_detector_reds_on_each_defect_form(form):
    rows, cells, members = _sound()
    row = rows["can_configure:s"]
    if form == "person":
        row["grant_to"] = ["u@example.com"]
    elif form == "no_group":
        row["grant_to_groups"] = []
    elif form == "unknown_group":
        cells = {}
    elif form == "cell_group":
        cells = {"g": {"personas": ["P"], "domains": ["D"]}}
    elif form == "empty_group":
        members = {}
    elif form == "no_subject":
        rows = {"can_configure:": row}
    assert _defects(rows, cells, members), form


# -- (c) what the sync writes ---------------------------------------------------------------

def test_c_the_sync_grants_each_configure_row_to_its_groups_members_and_nobody_else():
    caps, errors = cgs.load_capabilities(_load("capability_grants.yaml"))
    assert errors == []
    state = cgs.derive_desired(caps)
    rows = _rows()
    got = {(r.object_id, r.subject_type, r.subject_id, r.subject_relation)
           for r in state.relations if r.object_id.startswith(PREFIX)}
    want = {(k, "group", g, "member") for k, row in rows.items() for g in row["grant_to_groups"]}
    assert got == want and got
    assert all(r.relation == "invoker" for r in state.relations if r.object_id.startswith(PREFIX))


def test_c_a_subject_with_no_row_gets_no_capability_object():
    # Deny-by-default: the surface's can_invoke on an absent object is false. The control is the
    # ruled row, whose object the same derivation does write.
    caps, _ = cgs.load_capabilities(_load("capability_grants.yaml"))
    objs = {o.id for o in cgs.derive_desired(caps).objects if o.type == "capability"}
    assert FIRST_RULED in objs
    assert f"{PREFIX}a-subject-nobody-ruled" not in objs


# -- (d) no case in code (2026-10-30 rule) --------------------------------------------------

def test_d_no_configure_subject_or_group_is_quoted_in_code():
    rows = _rows()
    needles = set(rows) | {g for row in rows.values() for g in row["grant_to_groups"]}
    assert needles
    files = subprocess.run(["git", "ls-files", "*.py", "*.ts", "*.tsx", "*.baml"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    files = [f for f in files if not f.startswith("tests/")]
    assert "policy/sync/validate_policy.py" in files, "positive control: the scan sees the validator"
    hits = [(f, n) for f in files
            for n in needles if n in (ROOT / f).read_text(encoding="utf-8", errors="replace")]
    assert hits == [], hits
