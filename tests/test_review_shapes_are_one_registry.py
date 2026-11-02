"""review_shape is ONE vocabulary and ONE registry (Chris, 2026-10-30): the task's `review_shape` and
a content kind's `review_shape` both name a row of `policy/review_shapes/<shape>.yaml`, a platform
seed overlaid per deployment (architect, 2026-10-30). Rows are the SDK's `ReviewShapeRow`; a bad
row is reported, never raised; `GET /review-shapes` serves the valid ones; `validate_policy`
refuses a bad row and a content kind that names no row.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_SYNC = ROOT / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from validate_policy import validate  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import review_shapes as rs  # noqa: E402

SEED = ROOT / "policy" / "review_shapes"
OVERLAY_KINDS = ROOT / "policy" / "overlays" / "openddil-lab" / "content_kinds"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("REVIEW_SHAPE_POLICY_DIR", raising=False)
    monkeypatch.delenv("REVIEW_SHAPE_OVERLAY_DIRS", raising=False)
    rs.clear_cache()
    yield
    gateway.app.dependency_overrides.clear()
    rs.clear_cache()


def _row(shape="notice", **over):
    row = {"review_shape": shape, "item_kind": "part", "rules_version": f"{shape}.v1", "rules": []}
    row.update(over)
    return yaml.safe_dump(row, sort_keys=False)


def _dir(tmp_path, name, **files):
    d = tmp_path / name
    d.mkdir()
    for stem, text in files.items():
        (d / f"{stem}.yaml").write_text(text, encoding="utf-8")
    return d


def test_the_shipped_seed_is_four_valid_shapes_and_notice_is_read_from_its_file():
    rows = rs.load_review_shapes()
    assert set(rows) == {"notice", "document", "course", "finding"}
    assert set(rows) == set(rs.valid_review_shapes())
    declared = yaml.safe_load((SEED / "notice.yaml").read_text(encoding="utf-8"))
    notice = rows["notice"]
    assert [r.model_dump() for r in notice.rules] == declared["rules"]
    assert notice.rules_version == "notice.v1" == declared["rules_version"]


def test_an_overlay_row_with_the_same_shape_replaces_the_seed_row(monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", notice=_row("notice"), extra=_row("extra"))
    overlay = _dir(tmp_path, "ovl", notice=_row("notice", item_kind="page", rules_version="notice.v9"))
    monkeypatch.setenv("REVIEW_SHAPE_POLICY_DIR", str(seed))
    monkeypatch.setenv("REVIEW_SHAPE_OVERLAY_DIRS", str(overlay))
    rows = rs.valid_review_shapes()
    assert set(rows) == {"notice", "extra"}
    assert (rows["notice"].item_kind, rows["notice"].rules_version) == ("page", "notice.v9")


@pytest.mark.parametrize("name,text", [
    ("malformed", "review_shape: [unclosed\n"),
    ("failsmodel", "review_shape: failsmodel\nitem_kind: part\n"),
    ("stem", _row("other")),
])
def test_a_bad_row_is_a_shape_invalid_and_absent_from_the_valid_set(monkeypatch, tmp_path, name, text):
    seed = _dir(tmp_path, "seed", good=_row("good"), **{name: text})
    monkeypatch.setenv("REVIEW_SHAPE_POLICY_DIR", str(seed))
    rows = rs.load_review_shapes()
    assert isinstance(rows[name], rs.ShapeInvalid)
    assert name not in rs.valid_review_shapes() and not rs.is_review_shape(name)
    assert rs.is_review_shape("good")


def test_the_stem_mismatch_reason_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEW_SHAPE_POLICY_DIR", str(_dir(tmp_path, "seed", stem=_row("other"))))
    assert "must equal review_shape" in rs.load_review_shapes()["stem"].reason


def _as_caller():
    user = SimpleNamespace(authz_id="u", id="u", sub="u", email="u", persona=None,
                           entitled_domains=[], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


def test_the_route_serves_the_valid_rows_sorted_and_leaves_out_an_invalid_one(monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", zeta=_row("zeta"), alpha=_row("alpha"), broken="review_shape: [\n")
    monkeypatch.setenv("REVIEW_SHAPE_POLICY_DIR", str(seed))
    _as_caller()
    with TestClient(gateway.app) as c:
        r = c.get("/review-shapes")
    assert r.status_code == 200
    assert [row["review_shape"] for row in r.json()] == ["alpha", "zeta"]
    assert r.json()[0] == rs.valid_review_shapes()["alpha"].model_dump(mode="json")


@pytest.fixture
def pol(tmp_path):
    d = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", d, ignore=shutil.ignore_patterns("__pycache__", "overlays"))
    return d


def test_validate_refuses_a_content_kind_that_names_an_unregistered_shape(pol):
    (pol / "content_kinds" / "zz.yaml").write_text(
        "kind: zz\ndomain: sustainment\nreview_shape: nosuch\n", encoding="utf-8")
    errs = validate(pol, pol)
    assert any("zz.yaml" in e and "'nosuch'" in e for e in errs), errs


def test_the_gates_restated_required_fields_are_the_sdk_models():
    """validate_policy runs without the SDK, so it restates ReviewShapeRow's required fields: a
    fork. When the SDK makes one optional (card-only rows), this goes red until the gate follows."""
    from iagent_mesh.review_coverage import ReviewShapeRow
    import validate_policy as vp
    required = {n for n, f in ReviewShapeRow.model_fields.items() if f.is_required()}
    assert set(vp.REVIEW_SHAPE_REQUIRED) == required


def test_validate_names_the_file_of_a_row_that_does_not_validate(pol):
    (pol / "review_shapes" / "bad.yaml").write_text("review_shape: bad\n", encoding="utf-8")
    assert any("bad.yaml" in e for e in validate(pol, pol))


def test_an_overlay_content_kind_is_checked_against_the_seed_plus_its_own_shapes(pol):
    ovl = pol / "overlays" / "x"
    (ovl / "content_kinds").mkdir(parents=True)
    (ovl / "content_kinds" / "k.yaml").write_text(
        "kind: k\ndomain: sustainment\nreview_shape: mine\n", encoding="utf-8")
    assert any("k.yaml" in e and "'mine'" in e for e in validate(pol, pol))
    (ovl / "review_shapes").mkdir()
    (ovl / "review_shapes" / "mine.yaml").write_text(_row("mine"), encoding="utf-8")
    assert not [e for e in validate(pol, pol) if "mine" in e]


@pytest.mark.parametrize("kind,shape", [("pcn", "notice"), ("pdn", "notice"), ("course", "course")])
def test_the_overlay_rows_name_a_registered_shape(kind, shape):
    declared = yaml.safe_load((OVERLAY_KINDS / f"{kind}.yaml").read_text(encoding="utf-8"))["review_shape"]
    assert declared == shape
    assert rs.is_review_shape(declared)
