"""The `can_review:<subject>` rail: who may record a review decision on a subject.

2026-10-31 directive: "`can_review` for the workbench's alignment reviewers". The check itself lives
with the surface that writes the decision (the workbench asks Topaz `can_invoke` on
`can_review:<S>`); this repo ships the rows, the groups and their sandbox members, and names no
subject in code. Deny-by-default: a subject with no row is reviewable by nobody.

Rows, groups and members are read from policy/; the one case named here is the ruled first row.

Run:  uv run python -m pytest tests/security/test_can_review_capability_rail.py -q
"""
from __future__ import annotations

import fnmatch
import re
import shutil
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

PREFIX = "can_review:"
FIRST_RULED = "can_review:alignment"  # the directive's case: the workbench's alignment proposals


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
    """Every way a `can_review:` row can ship broken. Empty for a sound rail."""
    bad: list[str] = []
    for key, row in rows.items():
        row = row or {}
        if not key[len(PREFIX):].strip():
            bad.append(f"{key}: names no subject")
        if row.get("grant_to"):
            bad.append(f"{key}: grants a person directly (grant_to); grant through a group")
        groups = row.get("grant_to_groups") or []
        if not groups:
            bad.append(f"{key}: grants no group, so nobody reviews")
        for g in groups:
            if g not in cells:
                bad.append(f"{key}: group {g} is not in groups.yaml")
            elif cells[g]:
                bad.append(f"{key}: group {g} carries a persona.domain cell; a review group is capability-only")
            if not members.get(g):
                bad.append(f"{key}: group {g} has no member, so the row grants nobody")
    return bad


# -- (a) the shipped rail -------------------------------------------------------------------

def test_a_the_first_ruled_row_ships():
    assert FIRST_RULED in _rows(), sorted(_rows())


def test_a_every_shipped_review_row_is_sound():
    rows = _rows()
    assert rows, "no can_review row ships"
    assert _defects(rows, _cells(), _members()) == []


def test_a_the_shipped_rail_validates():
    pol = ROOT / "policy"
    assert vp.validate(pol, pol) == []


# -- (b) the detector reds on each defect form ----------------------------------------------

def _sound():
    return ({"can_review:s": {"granted_by": "seed", "reason": "r", "grant_to_groups": ["g"]}},
            {"g": {}}, {"g": {"u@example.com"}})


def test_b_the_detector_passes_its_sound_control():
    assert _defects(*_sound()) == []


@pytest.mark.parametrize("form", ["person", "no_group", "unknown_group", "cell_group", "empty_group",
                                  "no_subject"])
def test_b_the_detector_reds_on_each_defect_form(form):
    rows, cells, members = _sound()
    row = rows["can_review:s"]
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
        rows = {"can_review:": row}
    assert _defects(rows, cells, members), form


# -- (c) what the sync writes ---------------------------------------------------------------

def test_c_the_sync_grants_each_review_row_to_its_groups_members_and_nobody_else():
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

def test_d_no_review_subject_or_group_is_quoted_in_code():
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


def test_d_the_validator_quotes_no_registered_subject():
    s = (ROOT / "policy" / "sync" / "validate_policy.py").read_text(encoding="utf-8")
    part = (s[s.index("def known_review_subjects"):s.index("#: No grantee is named in code")]
            + s[s.index("# `can_review:<S>` (2026-11-02"):
                s.index("# recipient_readers.yaml: validated WHEN PRESENT")])
    literals = {m[1] for m in re.findall(r"""(["'])([^"'\n]*)\1""", part)}
    assert "review_subjects.yaml" in literals, "positive control: the scan sees the reader"
    assert not (literals & _registered()), literals & _registered()


# -- (e) the registry (2026-11-02 ruling: a misspelt key fails) ------------------------------

def _registered() -> set[str]:
    return {r["name"] for r in _load("review_subjects.yaml")["review_subjects"]}


@pytest.fixture
def pol(tmp_path):
    """A deployment's policy dir: the policy with no registry in it."""
    d = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", d, ignore=shutil.ignore_patterns("__pycache__", "overlays", "review_subjects.yaml"))
    return d


def _add_row(d, key):
    p = d / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["capabilities"][key] = {"granted_by": "seed", "reason": "t",
                                 "grant_to_groups": _rows()[FIRST_RULED]["grant_to_groups"]}
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _drop_row(d, key):
    p = d / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    del data["capabilities"][key]
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_e_the_first_ruled_subject_is_registered():
    assert FIRST_RULED[len(PREFIX):] in _registered(), sorted(_registered())


def test_e_every_registered_subject_names_its_surface_and_reason():
    rows = _load("review_subjects.yaml")["review_subjects"]
    assert rows
    assert [r for r in rows if not (r.get("surface") and r.get("reason"))] == []
    assert len(rows) == len(_registered()), "a subject is registered twice"


def test_e_the_known_set_equals_an_independent_parse():
    subjects, notes = vp.known_review_subjects()
    assert subjects == _registered()
    assert "review_subjects.yaml" in notes[0] and f"({len(subjects)} subject(s))" in notes[0]


def test_e_a_registered_subject_validates_from_a_dir_with_no_registry_in_it(pol):
    assert not (pol / "review_subjects.yaml").exists()
    assert vp.validate(pol, pol) == []


def test_e_a_misspelt_key_is_refused_naming_the_key_and_the_registry(pol):
    _add_row(pol, f"{FIRST_RULED}nmet")
    errs = vp.validate(pol, pol)
    hit = [e for e in errs if f"{FIRST_RULED}nmet" in e]
    assert hit and "review_subjects.yaml" in hit[0] and "NOT a registered" in hit[0], errs
    assert len(errs) == 1, errs  # the correctly spelt row beside it stays clean


def test_e_an_empty_subject_is_refused(pol):
    _add_row(pol, PREFIX)
    errs = vp.validate(pol, pol)
    assert [e for e in errs if "NOT a registered" in e], errs


def test_e_a_registered_subject_with_no_row_still_validates(pol):
    # The choice, pinned: the row decides who reviews, and no row means nobody, as for `can_call:`.
    _drop_row(pol, FIRST_RULED)
    assert vp.validate(pol, pol) == []


@pytest.mark.parametrize("body", [None, "not: [yaml", "review_subjects: 7\n", "- a\n",
                                  "review_subjects:\n  - {surface: s}\n  - b\n  - {name: 7}\n"])
def test_e_an_absent_or_broken_registry_fails_closed_on_the_shipped_row(pol, tmp_path, monkeypatch, body):
    reg = tmp_path / "registry.yaml"
    if body is not None:
        reg.write_text(body, encoding="utf-8")
    subjects, notes = vp.known_review_subjects(reg)
    assert subjects == set()
    assert "registry.yaml" in notes[0]
    real = vp.known_review_subjects
    monkeypatch.setattr(vp, "known_review_subjects", lambda: real(reg))
    errs = vp.validate(pol, pol)
    assert [e for e in errs if FIRST_RULED in e and "NOT a registered" in e], errs


def test_e_the_registry_reaches_the_job_that_runs_the_validator():
    # Not a data file: adding one fails the seed of every deployment whose repo lacks it.
    assert "review_subjects.yaml" not in vp.DATA_FILES
    # The seed job runs the validator from the cortex-bff image, and that image is the whole repo.
    values = yaml.safe_load((ROOT / "helm" / "invincible-agent" / "values.yaml").read_text(encoding="utf-8"))
    assert values["topazSeed"]["image"]["name"] == "cortex-bff"
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "build-containers.yml").read_text(encoding="utf-8"))
    built = [row for job in ci["jobs"].values()
             for row in ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
             if isinstance(row, dict) and row.get("service") == "cortex-bff"]
    assert built and all(row["path"] == "." for row in built), built
    ignored = [ln.strip().rstrip("/") for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.startswith("#")]
    assert ignored, "positive control: the scan sees the ignore list"
    for path in ("policy", "policy/review_subjects.yaml"):
        assert [p for p in ignored if fnmatch.fnmatch(path, p)] == [], path
