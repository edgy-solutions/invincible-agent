"""The classification dimensions registry (`policy/classification/dimensions.yaml`) -- gov ruling
2026-11-06 (levels.yaml becomes dimensions.yaml: name, type, vocabulary, owner;
ratified_by kept on every row per the architect's ruling on #282). Validator only.

WHAT EACH GROUP DEFENDS
  seed        the shipped registry parses clean.
  order       `dims` comes back in file order with types; a hierarchical vocabulary keeps list position.
  red arms    one per error class, each differing from the valid baseline in exactly one thing,
              each asserting a FRAGMENT of the message.
  one hier    a second hierarchical dimension is refused and the first one's vocabulary is the answer.
  identity    `generator`, `identity` and `identities` (openddil ADR-0056 §1): a UUID v7 urn per term.
  empty       `required` and `empty_means` per row and per boundary (openddil ADR-0055 §1, amended):
              each refused where it could never apply; a boundary that declares nothing is refused.

Fixture ids are neutral (`dim-h`, `dim-s`, `dim-t`, `v1`, `level-a`...), never a real dimension.

Run:  uv run pytest tests/security/test_classification_dimensions.py -q
"""
from __future__ import annotations

import hashlib
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


def _urn(label):
    """A valid, distinct term identity per label (UUID v7 shape), derived, never typed."""
    h = hashlib.sha256(label.encode()).hexdigest()
    return f"urn:uuid:{h[:8]}-{h[8:12]}-7{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def _dim(name="dim-s", typ="set", vocab=("v1", "v2"), **over):
    row = {"name": name, "identity": _urn(name), "type": typ, "vocabulary": list(vocab),
           "identities": {v: _urn(f"{name}.{v}") for v in vocab}, "owner": "owner", "ratified_by": "owner"}
    row.update(over)
    return row


def _hier(name="dim-h", vocab=("level-a", "level-b", "level-c"), **over):
    return _dim(name, "hierarchical", vocab, **over)


def _reg(*rows, **over):
    raw = {"generator": "scripts/mint_term_identity.py", "dimensions": list(rows)}
    raw.update(over)
    return raw


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
    ([_dim(owner="alice")], "`owner` names a seat"),
    ([_drop(_dim(), "ratified_by")], "`ratified_by` must be a non-empty string"),
    ([_dim(ratified_by="alice")], "`ratified_by` names a seat"),
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


# ---- identity, required, empty_means (openddil ADR-0056 §1; ADR-0055 §1's boundary amendment) ----

@pytest.mark.parametrize("raw,fragment", [
    ({"dimensions": []}, "`generator` must name"),
    ({"generator": " ", "dimensions": []}, "`generator` must name"),
    (_reg(_drop(_dim(), "identity")), "`identity` must be a UUID v7"),
    (_reg(_dim(identity="urn:uuid:3f2c8e1a-4b6d-4c1e-9a7f-2b3c4d5e6f70")), "`identity` must be a UUID v7"),
    (_reg(_dim(identity=_urn("dim-s").upper())), "`identity` must be a UUID v7"),
    (_reg(_dim(identity=_urn("dim-s")[len("urn:uuid:"):])), "`identity` must be a UUID v7"),
    (_reg(_drop(_dim(), "identities")), "`identities` must map each value"),
    (_reg(_dim(identities={"v1": _urn("dim-s.v1")})), "value 'v2' has no identity"),
    (_reg(_dim(identities={"v1": _urn("a"), "v2": _urn("b"), "v3": _urn("c")})), "names 'v3', which is not a value"),
    (_reg(_dim(identities={"v1": "v1", "v2": _urn("b")})), "the identity of 'v1' must be a UUID v7"),
    (_reg(_dim(required="yes")), "`required` must be true or false"),
    (_reg(_dim(empty_means="maybe")), "`empty_means` must be one of"),
    (_reg(_hier(empty_means="admits_everyone")), "`empty_means` on a hierarchical dimension"),
    (_reg(_dim(required=True, empty_means="admits_no_one")), "`empty_means` beside `required: true`"),
])
def test_a_bad_identity_or_empty_value_declaration_is_one_error(raw, fragment):
    errs, dims = _cd(raw)
    assert len(errs) == 1 and fragment in errs[0], errs
    assert errs[0].startswith("classification/dimensions.yaml: "), errs


@pytest.mark.parametrize("row", [
    _dim(required=True), _dim(required=False), _dim(empty_means="admits_everyone"),
    _dim(empty_means="admits_no_one"), _dim(required=False, empty_means="admits_no_one"), _hier(required=True),
])
def test_required_and_empty_means_are_clean_where_they_can_apply(row):
    errs, dims = _cd(_reg(row))
    assert errs == [] and list(dims) == [row["name"]], errs


def _bnd(name="dest-a", *decls, **over):
    row = {"name": name, "dimensions": list(decls) or [{"dimension": "dim-s", "empty_means": "admits_no_one"}],
           "owner": "owner", "ratified_by": "owner"}
    row.update(over)
    return row


def _breg(*boundaries):
    return _reg(_dim("dim-s"), _hier("dim-h"), boundaries=list(boundaries))


def test_a_boundary_declaring_each_dimension_is_clean():
    errs, dims = _cd(_breg(_bnd("dest-a", {"dimension": "dim-s", "required": True},
                                {"dimension": "dim-h", "required": True}),
                           _bnd("dest-b", {"dimension": "dim-s", "empty_means": "admits_everyone"})))
    assert errs == [] and list(dims) == ["dim-s", "dim-h"], errs


def test_a_boundary_may_relax_what_the_row_requires():
    """The declaration is per boundary: a row's `required: true` does not bind a destination's meaning."""
    raw = _reg(_dim("dim-s", required=True), boundaries=[_bnd()])
    assert _cd(raw)[0] == []


def test_boundaries_left_out_or_empty_is_clean():
    assert _cd(_reg(_dim()))[0] == []
    assert _cd(_reg(_dim(), boundaries=[]))[0] == []


@pytest.mark.parametrize("boundaries,fragment", [
    ("dest-a", "boundaries: must be a list of rows"),
    (["dest-a"], "boundaries: row 0: must be a mapping"),
    ([_bnd(colour="red")], "unknown key 'colour'"),
    ([_drop(_bnd(), "name")], "`name` must be a non-empty string"),
    ([_bnd("dest:a")], "`name` must have no whitespace and no `:`"),
    ([_bnd(), _bnd()], "more than one boundary has this name"),
    ([_bnd(owner="alice")], "`owner` names a seat"),
    ([_drop(_bnd(), "ratified_by")], "`ratified_by` must be a non-empty string"),
    ([_bnd(dimensions=[])], "`dimensions` must be a non-empty list of declarations"),
    ([_bnd("dest-a", "dim-s")], "declaration 0: must be a mapping"),
    ([_bnd("dest-a", {"dimension": "dim-s", "required": True, "colour": "red"})], "unknown key 'colour'"),
    ([_bnd("dest-a", {"dimension": "dim-z", "required": True})], "must name a dimension this file registers"),
    ([_bnd("dest-a", {"dimension": "dim-s", "required": True}, {"dimension": "dim-s", "required": False})],
     "declared more than once at this boundary"),
    ([_bnd("dest-a", {"dimension": "dim-s"})], "declares neither `required` nor `empty_means`"),
    ([_bnd("dest-a", {"dimension": "dim-s", "required": "yes"})], "`required` must be true or false"),
    ([_bnd("dest-a", {"dimension": "dim-s", "empty_means": "maybe"})], "`empty_means` must be one of"),
    ([_bnd("dest-a", {"dimension": "dim-h", "empty_means": "admits_no_one"})], "on a hierarchical dimension"),
    ([_bnd("dest-a", {"dimension": "dim-s", "required": True, "empty_means": "admits_no_one"})],
     "beside `required: true`"),
])
def test_a_bad_boundary_is_one_error(boundaries, fragment):
    errs, dims = _cd(_breg(*boundaries) if isinstance(boundaries, list) else _reg(_dim(), boundaries=boundaries))
    assert len(errs) == 1 and fragment in errs[0], errs
    assert errs[0].startswith("classification/dimensions.yaml: boundaries: "), errs
    assert "dim-s" in dims                                 # a bad boundary costs no dimension
