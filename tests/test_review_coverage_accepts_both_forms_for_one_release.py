"""review_coverage in both forms for 0.4.73: the SDK's item form is stored as sent, the 1.4.0
`parts` form is read as items (parts -> items, item_kind=part, ids as decimal strings) under the
content kind's declared review_shape, and a kind that declares no shape keeps today's behaviour.
Architect ruling 2026-10-30: no migration; both forms for one release.

The REAL `promotion.act` runs against fake stores (the `world` of the sibling test); the
extraction's part set is doubled. No network, no Postgres.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from iagent_mesh import review_coverage as sdk  # noqa: E402

from src.iagent import content_kinds, gateway, review_coverage, review_shapes  # noqa: E402
from tests.test_a_promotion_records_what_was_looked_at import (  # noqa: E402,F401
    INGEST_ID, PARTS, PAYLOAD, PREFIX, _act, _cov, _inputs, _invalid, _nothing_written, world)

_LAB_KINDS = Path(__file__).resolve().parents[1] / "policy" / "overlays" / "openddil-lab" / "content_kinds"


def _new(**over):
    """The item form of `_cov()`: the notice shape's row, string ids."""
    base = {"review_shape": "notice", "item_kind": "part", "rules_version": "notice.v1",
            "looked_at": ["0", "1", "5"], "sampled": ["1", "3"], "flagged": ["2"],
            "groups": [{"rule": "same_shape_run", "key": "FK25->FK25", "items": ["2", "3", "4"]}],
            "shared": [{"rule": "same_inherited_crop", "page": 1, "bbox": [0.1, 0.2, 0.9, 0.8],
                        "items": ["2", "3"], "confirmed": True}],
            "sample": {"seed": "abc", "per_run": 2, "min_run": 3, "all": False}}
    base.update(over)
    return base


def _kinds(monkeypatch, tmp_path, *, shape):
    """A tmp content-kind dir holding `pcn`, declaring `shape` (None = declares none)."""
    d = tmp_path / "content_kinds"
    d.mkdir()
    lines = [ln for ln in (_LAB_KINDS / "pcn.yaml").read_text(encoding="utf-8").splitlines()
             if not ln.startswith("review_shape:")]
    if shape:
        lines.insert(2, f"review_shape: {shape}")
    (d / "pcn.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_KIND_OVERLAY_DIRS", str(d))
    monkeypatch.setattr(content_kinds, "_REGISTRATIONS_CACHE", None)


# 1 ------------------------------------------------------------------------------------------
def test_a_new_form_body_is_stored_as_sent_and_its_replay_is_not_a_409(world):
    r = _act(world, _new())
    assert r.status_code == 200, r.text
    assert _inputs(world)["review_coverage"] == _new()
    again = _act(world, _new())
    assert again.status_code == 200, again.text
    assert len(world.ledger.records) == 1


# 2 ------------------------------------------------------------------------------------------
def test_a_legacy_body_becomes_the_converted_form(world):
    assert _act(world, _cov()).status_code == 200
    cov = _inputs(world)["review_coverage"]
    assert (cov["review_shape"], cov["item_kind"]) == ("notice", "part")
    assert cov["looked_at"] == ["0", "1", "5"] and cov["flagged"] == ["2"]
    assert cov["groups"][0]["items"] == ["2", "3", "4"] and "parts" not in cov["groups"][0]
    assert cov["shared"][0]["items"] == ["2", "3"] and "parts" not in cov["shared"][0]
    assert cov["rules_version"] == "cortex.reviewRuns.v1"       # copied as sent, not validated


# 3 ------------------------------------------------------------------------------------------
def test_a_record_stored_legacy_is_read_back_converted(world):
    assert _act(world, _cov(rules_version="notice.v1")).status_code == 200
    (stored,) = world.ledger.records.values()
    (check,) = [c for c in stored["record"]["checks"] if c["name"] == "human_review"]
    check["inputs"]["review_coverage"] = _cov(rules_version="notice.v1")   # the 1.4.0 record, as written
    assert "parts" in check["inputs"]["review_coverage"]["groups"][0]
    ok = _act(world, _new())
    assert ok.status_code == 200, ok.text
    other = _act(world, _new(flagged=["1"]))
    assert other.status_code == 409, other.text
    assert other.json()["detail"]["error"] == "review_coverage_differs_from_the_record"


# 4 ------------------------------------------------------------------------------------------
def test_a_kind_with_no_shape_keeps_the_legacy_body_exactly(world, monkeypatch, tmp_path):
    _kinds(monkeypatch, tmp_path, shape=None)
    assert _act(world, _cov()).status_code == 200
    assert _inputs(world)["review_coverage"] == gateway.ReviewCoverage(**_cov()).model_dump()
    assert "parts" in _inputs(world)["review_coverage"]["groups"][0]


@pytest.mark.parametrize("bad,check", [
    (_cov(looked_at=[0, 1, 5, 99]), "unknown_part"),
    (_cov(looked_at=[0, 0, 1, 5]), "duplicate_part"),
    (_cov(groups=[{"rule": "r", "key": "k", "parts": [1, 2, 3, 4]}]), "overlap"),
    (_cov(groups=[]), "uncovered")])
def test_a_kind_with_no_shape_still_answers_the_1_4_0_checks(world, monkeypatch, tmp_path, bad, check):
    _kinds(monkeypatch, tmp_path, shape=None)
    _invalid(_act(world, bad), check)
    _nothing_written(world)


# 5 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad,check", [
    (_new(review_shape="finding"), "review_shape"),
    (_new(review_shape="nonesuch"), "review_shape"),
    (_new(item_kind="page"), "item_kind"),
    (_new(rules_version="notice.v0"), "unknown_rules_version"),
    (_new(groups=[{"rule": "made_up", "key": "k", "items": ["2", "3", "4"]}]), "unknown_rule"),
    (_new(shared=[{"rule": "made_up", "page": 1, "bbox": [0.1, 0.2, 0.9, 0.8], "items": ["2"],
                   "confirmed": False}]), "unknown_rule"),
    (_new(looked_at=["0", "1", "5", "99"]), "unknown_part"),
    (_new(looked_at=["0", "0", "1", "5"]), "duplicate_part")])
def test_the_new_form_checks(world, bad, check):
    _invalid(_act(world, bad), check)
    _nothing_written(world)


def test_a_new_form_body_to_a_kind_that_declares_no_shape_is_a_review_shape_refusal(
        world, monkeypatch, tmp_path):
    _kinds(monkeypatch, tmp_path, shape=None)
    _invalid(_act(world, _new()), "review_shape")
    _nothing_written(world)


# 6 ------------------------------------------------------------------------------------------
def test_control_a_converted_legacy_body_with_an_unknown_rules_version_is_accepted(world):
    """The one-release tolerance, and the control for `unknown_rules_version` above: the same
    unknown version, sent in the legacy form, is not refused."""
    assert _cov()["rules_version"] != "notice.v1"
    assert _act(world, _cov()).status_code == 200
    _invalid(_act(world, _new(rules_version=_cov()["rules_version"])), "unknown_rules_version")


# 7 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("body", [
    _new(groups=[{"rule": "same_shape_run", "key": "k", "items": ["2", "3"]},
                 {"rule": "same_shape_run", "key": "j", "parts": [4]}]),
    {**_cov(), "review_shape": "notice"},
    {**_cov(), "item_kind": "part"},
    {**_new(), "parts": [1]}])
def test_a_body_mixing_the_forms_is_a_422(world, body):
    r = _act(world, body)
    assert r.status_code == 422, r.text
    _nothing_written(world)


# 8 ------------------------------------------------------------------------------------------
def test_an_item_kind_with_no_reader_is_a_503(world, monkeypatch, tmp_path):
    shapes = tmp_path / "shapes"
    shapes.mkdir()
    (shapes / "page.yaml").write_text(
        "review_shape: page\nitem_kind: page\nrules_version: page.v1\nrules: []\n", encoding="utf-8")
    monkeypatch.setenv("REVIEW_SHAPE_OVERLAY_DIRS", str(shapes))
    review_shapes.clear_cache()
    _kinds(monkeypatch, tmp_path, shape="page")
    page = _new(review_shape="page", item_kind="page", rules_version="page.v1", groups=[], shared=[])
    for body in (page, _cov()):
        r = _act(world, body)
        assert r.status_code == 503, r.text
        assert r.json()["detail"]["error"] == "review_coverage_unverifiable"
    _nothing_written(world)
    review_shapes.clear_cache()


def test_universe_for_has_exactly_the_part_reader():
    assert set(review_coverage._UNIVERSES) == {"part"}
    with pytest.raises(LookupError):
        review_coverage.universe_for("page")


# 9 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("strict,base", [
    (review_coverage.ItemReviewCoverage, sdk.ReviewCoverage),
    (review_coverage.ItemCoverageGroup, sdk.ReviewCoverageGroup),
    (review_coverage.ItemCoverageShared, sdk.ReviewCoverageSharedFact)])
def test_the_strict_models_restate_exactly_the_sdk_fields(strict, base):
    assert set(strict.model_fields) == set(base.model_fields)
    assert strict.model_config.get("extra") == "forbid"


# 10 -----------------------------------------------------------------------------------------
def test_coverage_on_another_kind_is_refused_with_the_same_body(world):
    world.kind = "grouped_review"
    r = _act(world, _cov())
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {
        "error": "review_coverage_not_for_kind", "kind": "grouped_review",
        "message": "review coverage is read only on a document promotion; sent here it "
                   "would be lost"}


# 11 -----------------------------------------------------------------------------------------
def _extraction(monkeypatch, content_kind):
    monkeypatch.setattr(gateway, "_rejected_relocation", lambda i, row: None)
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda ref: {})
    monkeypatch.setattr(gateway, "_review_json_key", lambda m, ref: PREFIX + "review.json")
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {"review_items": []})
    row = {"extraction_ref": PREFIX + "m.json", "object_prefix": PREFIX, "content_kind": content_kind,
           "attempt": 1}
    return asyncio.run(gateway._extraction_body(INGEST_ID, copy.deepcopy(row)))


def test_the_extraction_serves_the_shape_and_item_kind(world, monkeypatch):
    out = _extraction(monkeypatch, "pcn")
    assert (out["review_shape"], out["item_kind"]) == ("notice", "part")


def test_the_extraction_serves_none_for_an_undeclared_kind(world, monkeypatch, tmp_path):
    _kinds(monkeypatch, tmp_path, shape=None)
    out = _extraction(monkeypatch, "pcn")
    assert (out["review_shape"], out["item_kind"]) == (None, None)
    out = _extraction(monkeypatch, "not-registered")
    assert (out["review_shape"], out["item_kind"]) == (None, None)
