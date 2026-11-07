"""The classification dimensions registry (`policy/classification/dimensions.yaml`) -- gov ruling
2026-11-06 (levels.yaml becomes dimensions.yaml: name, type, vocabulary, owner). Validator only.

WHAT EACH GROUP DEFENDS
  seed        the shipped registry parses clean.
  order       `dims` comes back in file order with types; a hierarchical vocabulary keeps list position.
  red arms    one per error class, each differing from the valid baseline in exactly one thing,
              each asserting a FRAGMENT of the message.
  one hier    a second hierarchical dimension is refused and the first one's vocabulary is the answer.

Fixture ids are neutral (`dim-h`, `dim-s`, `dim-t`, `v1`, `level-a`...), never a real dimension.

Run:  uv run pytest tests/security/test_classification_dimensions.py -q
"""
from __future__ import annotations

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
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]

_B_USERS = [{"id": "svc:a", "groups": ["team-a"]}, {"id": "alice", "groups": ["team-a"]}]


def _dim(name="dim-s", typ="set", vocab=("v1", "v2"), **over):
    row = {"name": name, "type": typ, "vocabulary": list(vocab), "owner": "owner"}
    row.update(over)
    return row


def _hier(name="dim-h", vocab=("level-a", "level-b", "level-c"), **over):
    return _dim(name, "hierarchical", vocab, **over)


def _reg(*rows):
    return {"dimensions": list(rows)}


def _cd(raw):
    return vp.classification_dimensions_errors(raw, _B_USERS)


def _drop(row, key):
    row = dict(row)
    del row[key]
    return row


def test_the_shipped_registry_parses_clean():
    assert "dimensions" in _REGISTRY                      # control: read
    errs, dims = vp.classification_dimensions_errors(_REGISTRY, _USERS)
    assert errs == [] and list(dims) == [r["name"] for r in _REGISTRY["dimensions"]]


def test_one_hierarchical_and_two_set_dimensions_are_clean_and_come_back_in_order():
    errs, dims = _cd(_reg(_dim("dim-s"), _hier("dim-h"), _dim("dim-t", vocab=("v1",))))
    assert errs == []
    assert list(dims) == ["dim-s", "dim-h", "dim-t"]
    assert [t for t, _ in dims.values()] == ["set", "hierarchical", "set"]
    assert dims["dim-h"][1] == ["level-a", "level-b", "level-c"]


@pytest.mark.parametrize("raw,fragment", [
    ([], "top level must be a mapping"),
    ({"dimensions": [], "extra": 1}, "unknown key(s): extra"),
    ({"dimensions": {"dim-s": {}}}, "must be a list of rows"),
])
def test_a_malformed_registry_is_one_error_and_no_dims(raw, fragment):
    errs, dims = _cd(raw)
    assert len(errs) == 1 and fragment in errs[0], errs
    assert dims is None


@pytest.mark.parametrize("rows,fragment", [
    ([_drop(_dim(), "name")], "`name` must be a non-empty string"),
    ([_dim("dim:s")], "`name` must have no whitespace and no `:`"),
    ([_dim("dim s")], "`name` must have no whitespace and no `:`"),
    ([_dim(), _dim()], "more than one row has this name"),
    ([_dim(typ="ordered")], "`hierarchical` or `set`"),
    ([_drop(_dim(), "type")], "`hierarchical` or `set`"),
    ([_dim(vocabulary="v1")],"`vocabulary` must be a non-empty list"),
    ([_dim(vocab=())], "`vocabulary` must be a non-empty list"),
    ([_dim(vocab=("v:1",))], "must have no whitespace and no `:`"),
    ([_dim(vocab=("v 1",))], "must have no whitespace and no `:`"),
    ([_dim(vocab=("v1", "v1"))], "'v1' is listed more than once"),
    ([_drop(_dim(), "owner")], "`owner` must be a non-empty string"),
    ([_dim(owner="alice")], "names a seat"),
    ([_dim(colour="red")], "unknown key 'colour'"),
])
def test_a_bad_row_is_one_error(rows, fragment):
    errs, dims = _cd(_reg(*rows))
    assert len(errs) == 1 and fragment in errs[0], errs
    assert errs[0].startswith("classification/dimensions.yaml: "), errs


def test_a_bad_row_contributes_no_dimension():
    errs, dims = _cd(_reg(_dim("dim-s", vocab=("v1", "v1")), _dim("dim:t"), _dim(typ="x", name="dim-u"),
                          _dim("dim-ok")))
    assert list(dims) == ["dim-ok"], (errs, dims)


def test_a_duplicate_name_is_not_added_twice():
    errs, dims = _cd(_reg(_dim(), _dim()))
    assert list(dims) == ["dim-s"]


def test_a_second_hierarchical_dimension_is_refused_and_the_first_wins():
    errs, dims = _cd(_reg(_hier("dim-h", ("level-a", "level-b")), _hier("dim-i", ("x1", "x2"))))
    assert len(errs) == 1 and "a second hierarchical dimension" in errs[0], errs
    assert errs[0].startswith("classification/dimensions.yaml: dim-i: "), errs
    assert list(dims) == ["dim-h"]
    assert vp.hierarchical_levels(dims) == ["level-a", "level-b"]


def test_hierarchical_levels_none_in_none_out():
    assert vp.hierarchical_levels(None) is None


def test_hierarchical_levels_is_empty_without_a_hierarchical_dimension():
    assert vp.hierarchical_levels({}) == []
    _, dims = _cd(_reg(_dim("dim-s"), _dim("dim-t")))
    assert vp.hierarchical_levels(dims) == []


def test_hierarchical_levels_preserves_order():
    _, dims = _cd(_reg(_hier(vocab=("level-c", "level-a", "level-b"))))
    assert vp.hierarchical_levels(dims) == ["level-c", "level-a", "level-b"]
