"""A shipped row's grantor is the seed, never a person (ruled 2026-10-31, on #176).

Every `granted_by` in a rail file this repository ships says `seed`. A deployment's own rows (its
policy repository, an overlay, the reader grant an approval writes at runtime) name their approver,
so the rule is a repo seal, not a `validate_policy` row: the validator runs on the deployed policy.

The rail files are derived from `policy/grantors/*.yaml` (`rail_file`), never listed. That map is
complete by its own seal (`test_every_policy_refusal_names_policy_binding_grantor.py`).

Run:  uv run python -m pytest tests/security/test_a_shipped_grantor_is_the_seed.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SEED = "seed"


def _rail_files() -> list[str]:
    rows = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "policy" / "grantors").glob("*.yaml"))]
    return sorted({r["rail_file"] for r in rows if r.get("rail_file")})


def _grantors(node, path=()) -> list[tuple[tuple, object]]:
    """Every `granted_by` value in a parsed document, at any depth, with its path."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            found += [(path + (k,), v)] if k == "granted_by" else _grantors(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _grantors(v, path + (i,))
    return found


def test_the_rail_files_are_derived_and_carry_grants():
    files = _rail_files()
    assert "policy/capability_grants.yaml" in files                   # positive control: the map is read
    bearing = [f for f in files if _grantors(yaml.safe_load((ROOT / f).read_text(encoding="utf-8")))]
    assert len(bearing) >= 2, bearing                                 # positive control: the population is non-trivial



def test_every_grant_bearing_policy_file_is_a_rail_file():
    # The derivation must not shrink the population: a top-level policy file with a grantor key is
    # in the map. Overlays are a deployment's own rows and are out of scope.
    bearing = {f"policy/{p.name}" for p in sorted((ROOT / "policy").glob("*.yaml"))
               if re.search(r"^\s+granted_by:", p.read_text(encoding="utf-8"), flags=re.M)}
    assert bearing, "positive control: some shipped policy file carries a grantor"
    assert bearing <= set(_rail_files()), sorted(bearing - set(_rail_files()))


@pytest.mark.parametrize("rail_file", _rail_files())
def test_every_shipped_grantor_is_the_seed(rail_file):
    text = (ROOT / rail_file).read_text(encoding="utf-8")
    found = _grantors(yaml.safe_load(text))
    # Control: the walk reaches every row the text declares (a key line, not a comment).
    assert len(found) == len(re.findall(r"^\s+granted_by:", text, flags=re.M)), rail_file
    people = [(p, v) for p, v in found if v != SEED]
    assert not people, f"{rail_file}: a shipped row's grantor is `{SEED}`, never a person: {people}"


def test_the_detector_sees_a_person_at_any_depth():
    doc = {"a": {"granted_by": SEED, "b": [{"granted_by": "someone"}]}}  # positive control on the detector
    assert [v for _, v in _grantors(doc) if v != SEED] == ["someone"]
