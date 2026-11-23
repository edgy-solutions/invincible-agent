"""The lifecycle status vocabulary (`policy/registry/lifecycle_status.yaml`, ADR-0065 §3) and the one
identity per term that it and `policy/classification/dimensions.yaml` carry (openddil ADR-0056 §1).
Validator only: iagent has no reader; the SDK's `load_lifecycle_status_vocabulary` (v0.9.16) reads it.

WHAT EACH GROUP DEFENDS
  seed        the shipped file parses clean, its statuses are ADR-0065 §3's seed, and validate_policy
              prints its line.
  sdk         the SDK loader's shape holds: `statuses` is a non-empty list of non-blank strings. The
              check is mirrored from v0.9.16 (`iagent_mesh/lifecycle_status.py:171-176`) because the
              pin is v0.9.15; the loader itself runs once the pin carries it.
  generator   the file's `generator` exists in this repo, writes nothing, and mints identities that
              pass the validator's own check, distinct from each other.
  red arms    one per error class, each differing from the shipped file in exactly one thing.
  collisions  no identity names two terms, within a file or across the two files; seeded both ways.
  validate    validate() reports a broken file WHEN PRESENT and is clean with it absent.

Fixture terms are neutral (`status-a`, `dim-s`, `v1`), never a real status beyond the shipped seed.

Run:  uv run pytest tests/security/test_lifecycle_status_registry.py -q
"""
from __future__ import annotations

import copy
import hashlib
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
_LS = "registry/lifecycle_status.yaml"
_CD = "classification/dimensions.yaml"
_RAW = yaml.safe_load((_POLICY / _LS).read_text(encoding="utf-8"))
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]

_B_USERS = [{"id": "svc:a", "groups": ["team-a"]}, {"id": "alice", "groups": ["team-a"]}]


def _urn(label):
    """A valid, distinct term identity per label (UUID v7 shape), derived, never typed."""
    h = hashlib.sha256(label.encode()).hexdigest()
    return f"urn:uuid:{h[:8]}-{h[8:12]}-7{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def _ls(**over):
    raw = copy.deepcopy(_RAW)
    raw.update(over)
    return raw


def _lse(raw):
    return vp.lifecycle_status_errors(raw, _B_USERS)


def _drop(raw, key):
    raw = dict(raw)
    del raw[key]
    return raw


# ---- seed -----------------------------------------------------------------------------------------

def test_the_shipped_file_parses_clean():
    assert _RAW["statuses"]                                # control: read
    assert vp.lifecycle_status_errors(_RAW, _USERS) == []


def test_the_shipped_statuses_are_adr_0065s_seed():
    """ADR-0065 §3, verbatim: "The seed takes IEC 62402 and EIA-724 wording (`active`,
    `not-recommended-for-new-design`, `last-time-buy`, `obsolete`, `unknown`)". Read from the ADR."""
    adr = " ".join(next((_REPO / "docs" / "adr").glob("ADR-0065-*.md")).read_text(encoding="utf-8").split())
    seed = adr.split("The seed takes IEC 62402 and EIA-724 wording (", 1)[1].split(")", 1)[0]
    words = [w.strip().strip("`") for w in seed.split(",")]
    assert len(words) == 5, words                          # control: the sentence was found
    assert _RAW["statuses"][:len(words)] == words


def test_validate_prints_the_status_count():
    r = subprocess.run([sys.executable, str(_SYNC / "validate_policy.py")], cwd=_REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert f"{_LS}: {len(_RAW['statuses'])} status(es)" in r.stdout


# ---- the SDK loader's shape -------------------------------------------------------------------------

def _sdk_shape_ok(raw) -> bool:
    """Mirrored from iagent-mesh-sdk v0.9.16 `iagent_mesh/lifecycle_status.py:171-176`."""
    statuses = raw.get("statuses") if isinstance(raw, dict) else None
    return isinstance(statuses, list) and bool(statuses) and all(
        isinstance(s, str) and s.strip() for s in statuses)


def test_the_shipped_file_has_the_sdk_loaders_shape():
    assert _sdk_shape_ok(_RAW)
    assert not _sdk_shape_ok(_ls(statuses=[]))             # the control: the mirror can refuse


@pytest.mark.parametrize("raw", [_ls(statuses=[]), _ls(statuses=["status-a", " "]), _drop(_RAW, "statuses"),
                                 _ls(statuses="active")])
def test_what_the_sdk_loader_refuses_the_validator_refuses(raw):
    assert not _sdk_shape_ok(raw)
    assert _lse(raw) != []


def test_the_sdk_loader_reads_the_shipped_file():
    mod = pytest.importorskip("iagent_mesh.lifecycle_status",
                              reason="the pinned SDK predates v0.9.16's lifecycle_status module")
    assert mod.load_lifecycle_status_vocabulary(_POLICY / _LS) == tuple(_RAW["statuses"])


# ---- the generator ----------------------------------------------------------------------------------

def test_the_named_generator_exists_and_mints_valid_distinct_identities():
    gen = _REPO / _RAW["generator"]
    assert gen.is_file(), gen
    cd = yaml.safe_load((_POLICY / _CD).read_text(encoding="utf-8"))
    assert cd["generator"] == _RAW["generator"]            # one generator for both files
    r = subprocess.run([sys.executable, str(gen), "-n", "5"], cwd=_REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    minted = r.stdout.split()
    assert len(minted) == 5 and len(set(minted)) == 5, minted
    for m in minted:
        assert vp._term_identity_errors("x", m, "it") == [], m


def test_the_generator_writes_nothing(tmp_path):
    r = subprocess.run([sys.executable, str(_REPO / _RAW["generator"])], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 0 and list(tmp_path.iterdir()) == []


# ---- red arms -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,fragment", [
    (_ls(colour="red"), "unknown key 'colour'"),
    (_drop(_RAW, "generator"), "`generator` must name"),
    (_drop(_RAW, "identity"), "`identity` must be a UUID v7"),
    (_ls(identity="urn:uuid:3f2c8e1a-4b6d-4c1e-9a7f-2b3c4d5e6f70"), "`identity` must be a UUID v7"),
    (_drop(_RAW, "identities"), "`identities` must map each value"),
    (_ls(statuses=_RAW["statuses"] + ["status-a"]), "value 'status-a' has no identity"),
    (_ls(identities={**_RAW["identities"], "status-a": _urn("status-a")}), "names 'status-a', which is not a value"),
    (_ls(identities={**_RAW["identities"], "active": "active"}), "the identity of 'active' must be a UUID v7"),
    (_ls(statuses=_RAW["statuses"] + ["active"]), "status 'active' is listed more than once"),
    (_ls(statuses=[], identities={}), "`statuses` must be a non-empty list"),
    (_ls(owner="alice"), "`owner` names a seat"),
    (_drop(_RAW, "ratified_by"), "`ratified_by` must be a non-empty string"),
])
def test_a_bad_file_is_one_error(raw, fragment):
    errs = _lse(raw)
    assert len(errs) == 1 and fragment in errs[0], errs
    assert errs[0].startswith(f"{_LS}: "), errs


def test_a_non_mapping_is_one_error():
    assert _lse(["active"]) == [f"{_LS}: top level must be a mapping"]


# ---- one identity per thing ----------------------------------------------------------------------------

def _cd_raw(*rows):
    return {"generator": _RAW["generator"], "dimensions": list(rows)}


def _dim(name="dim-s", vocab=("v1", "v2"), **over):
    row = {"name": name, "identity": _urn(name), "type": "set", "vocabulary": list(vocab),
           "identities": {v: _urn(f"{name}.{v}") for v in vocab}, "owner": "owner", "ratified_by": "owner"}
    row.update(over)
    return row


def test_the_shipped_files_share_no_identity():
    cd = yaml.safe_load((_POLICY / _CD).read_text(encoding="utf-8"))
    files = {_LS: _RAW, _CD: cd}
    assert len(vp.term_identities(files)) == 1 + len(_RAW["statuses"]) + sum(
        1 + len(r["vocabulary"]) for r in cd["dimensions"])          # control: every term is seen
    assert vp.term_identity_collisions(files) == []


def test_distinct_identities_across_both_files_are_clean():
    assert vp.term_identity_collisions({_LS: _RAW, _CD: _cd_raw(_dim("dim-s"), _dim("dim-t"))}) == []


@pytest.mark.parametrize("files,first,again", [
    ({_LS: _ls(identities={**_RAW["identities"], "obsolete": _RAW["identities"]["active"]})},
     f"{_LS}: statuses.active", f"{_LS}: statuses.obsolete"),
    ({_LS: _ls(identities={**_RAW["identities"], "active": _RAW["identity"]})},
     f"{_LS}: statuses", f"{_LS}: statuses.active"),
    ({_CD: _cd_raw(_dim("dim-s"), _dim("dim-t", identity=_urn("dim-s")))},
     f"{_CD}: dim-s", f"{_CD}: dim-t"),
    ({_CD: _cd_raw(_dim("dim-s", identities={"v1": _urn("dim-s.v1"), "v2": _urn("dim-s.v1")}))},
     f"{_CD}: dim-s.v1", f"{_CD}: dim-s.v2"),
    ({_LS: _RAW, _CD: _cd_raw(_dim("dim-s", identity=_RAW["identities"]["unknown"]))},
     f"{_LS}: statuses.unknown", f"{_CD}: dim-s"),
])
def test_an_identity_for_two_terms_is_one_error_naming_both(files, first, again):
    errs = vp.term_identity_collisions(files)
    assert len(errs) == 1, errs
    assert errs[0].startswith(f"{again}: identity ") and errs[0].endswith(
        f"is already {first}'s (one identity per thing, openddil ADR-0056 §1)"), errs


# ---- through validate() ---------------------------------------------------------------------------------

def _policy_copy(tmp_path):
    pol = tmp_path / "policy"
    shutil.copytree(_POLICY, pol, ignore=shutil.ignore_patterns("__pycache__"))
    return pol


def _put(pol, name, raw):
    (pol / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _errs(pol):
    return [e for e in vp.validate(pol, pol) if e.startswith((_LS, _CD))]


def test_validate_is_clean_as_copied(tmp_path):
    """The control for every arm below."""
    assert _errs(_policy_copy(tmp_path)) == []


def test_validate_reports_a_broken_file(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, _LS, _ls(colour="red"))
    assert any("unknown key 'colour'" in e for e in _errs(pol))


def test_validate_with_the_file_absent_is_clean(tmp_path):
    pol = _policy_copy(tmp_path)
    (pol / _LS).unlink()
    assert _errs(pol) == []


def test_validate_reports_a_collision_across_the_files(tmp_path):
    pol = _policy_copy(tmp_path)
    _put(pol, _CD, _cd_raw(_dim("dim-s")))
    assert _errs(pol) == []                                # the control: distinct identities
    _put(pol, _CD, _cd_raw(_dim("dim-s", identity=_RAW["identity"])))
    errs = _errs(pol)
    assert len(errs) == 1 and "registry/lifecycle_status.yaml: statuses" in errs[0], errs
    assert f"{_CD}: dim-s" in errs[0] and "one identity per thing" in errs[0], errs
