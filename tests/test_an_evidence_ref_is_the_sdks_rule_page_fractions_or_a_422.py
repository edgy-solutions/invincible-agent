"""Architect ruling 2026-10-31 (fork 1): the SDK's `EvidenceRef` rule wins. A steward edit's
`evidence_ref` bbox is page FRACTIONS (0..1, x0<x1, y0<y1); a ref that is not is a 422
`evidence_ref_invalid` naming the check, and nothing is stored. The gateway has no EvidenceRef of
its own; `ingest_api.EvidenceRef` (the served model) agrees with the SDK verdict case by case
until it can import the SDK model (v0.9.13 schema, note omitted rather than null)."""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

pytest.importorskip("fastapi")

from iagent_mesh.provenance import EvidenceRef as SdkEvidenceRef  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.iagent import ingest_api  # noqa: E402
from tests.test_a_promotion_takes_row_edits_behind_its_flag import (  # noqa: E402,F401 -- fixture by name
    FLAG, _OPS, _nothing_written, _promote, _surfaces, _with, world)

ROOT = pathlib.Path(__file__).resolve().parents[1]

# cortex-ui src/lib/rowFractionSeal.test.ts. OLD_REF there also carries page_dims/units; the
# bbox-only form is the arm that names `bbox_not_fractions` (the extra keys name themselves first).
OLD_REF = {"page": 3, "bbox": [223, 917, 661, 953]}
OLD_REF_FULL = dict(OLD_REF, page_dims={"width": 1700, "height": 2200}, units="px")
NEW_REF = {"page": 3, "bbox": [0.131176, 0.416818, 0.388824, 0.433182]}
OPS = sorted(_OPS)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(FLAG, "true")


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("bad,check", [
    (OLD_REF, "bbox_not_fractions"),
    (OLD_REF_FULL, "extra_key:page_dims"),
    ({"page": 1, "bbox": [0.5, 0.1, 0.5, 0.9]}, "bbox_degenerate"),
    ({"page": 1, "bbox": [0.1, 0.9, 0.9, 0.1]}, "bbox_degenerate"),
    ({"page": 0, "bbox": [0.1, 0.1, 0.2, 0.2]}, "page"),
    ({"page": 1, "bbox": [0.1, 0.1, 0.2, 0.2], "note": "  "}, "note_blank"),
], ids=["pixels", "pixels_full", "x_degenerate", "y_degenerate", "page0", "blank_note"])
def test_a_non_fraction_ref_is_a_named_422_and_nothing_is_stored(world, on, op, bad, check):
    r = _promote(world, _with(op, evidence_ref=bad))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {"error": "evidence_ref_invalid", "check": check}
    _nothing_written(world)


@pytest.mark.parametrize("op", OPS)
def test_cortexs_new_ref_is_accepted_and_stored_as_sent(world, on, op):
    r = _promote(world, _with(op, evidence_ref=NEW_REF))
    assert r.status_code == 200, r.text
    got, log, rec = _surfaces(world)
    assert got[0]["evidence_ref"] == log[0]["evidence_ref"] == rec[0]["evidence_ref"] == NEW_REF


def test_the_legacy_string_form_is_still_accepted(world, on):
    r = _promote(world, _with("corrected", evidence_ref="  page 2, row 1 "))
    assert r.status_code == 200, r.text
    assert _surfaces(world)[0][0]["evidence_ref"] == {"note": "page 2, row 1"}


def test_a_ref_with_no_note_is_stored_without_a_note_key(world, on):
    r = _promote(world, _with("deleted", evidence_ref=NEW_REF))
    assert r.status_code == 200, r.text
    assert "note" not in _surfaces(world)[0][0]["evidence_ref"]


def test_a_served_row_with_no_note_has_no_note_key():
    # The extraction route serves 7f's dict as is; the documented model must not invent `note: null`.
    row = ingest_api.EvidenceRef.model_validate(NEW_REF)
    assert "note" not in row.model_dump(exclude_unset=True)
    schema = ingest_api.EvidenceRef.model_json_schema()["properties"]["note"]
    assert schema["type"] == "string" and "anyOf" not in schema


# -- the census: no EvidenceRef class of its own anywhere under src/iagent --------------------------

def _evidence_ref_classes(source: str) -> list[str]:
    return [n.name for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.ClassDef) and n.name == "EvidenceRef"]


def test_the_census_detector_finds_a_planted_class():
    assert _evidence_ref_classes("class A:\n    class EvidenceRef(object): ...\n") == ["EvidenceRef"]
    assert _evidence_ref_classes("class Other: ...\nEvidenceRef = 1\n") == []


def test_only_the_served_model_is_an_evidence_ref_class_under_src_iagent():
    found = {}
    for p in (ROOT / "src" / "iagent").rglob("*.py"):
        names = _evidence_ref_classes(p.read_text(encoding="utf-8"))
        if names:
            found[p.name] = names
    # ingest_api.EvidenceRef is the served model awaiting the v0.9.13 import (equivalence below).
    assert found == {"ingest_api.py": ["EvidenceRef"]}, found


# -- ingest_api.EvidenceRef agrees with the SDK verdict ---------------------------------------------

_CASES = {
    "new": NEW_REF, "old_pixels": OLD_REF, "old_full": OLD_REF_FULL,
    "x_eq": {"page": 1, "bbox": [0.5, 0.1, 0.5, 0.9]}, "x_rev": {"page": 1, "bbox": [0.9, 0.1, 0.1, 0.9]},
    "y_eq": {"page": 1, "bbox": [0.1, 0.5, 0.9, 0.5]}, "y_rev": {"page": 1, "bbox": [0.1, 0.9, 0.9, 0.1]},
    "null_bbox": {"page": 1, "bbox": None}, "omitted_bbox": {"page": 1},
    "blank_note": {"page": 1, "note": "  "}, "note": {"page": 1, "note": "the cell"},
    "null_note": {"page": 1, "note": None},
    "extra_key": {"page": 1, "extra": 1}, "page0": {"page": 0}, "page_bool": {"page": True},
    "bool_coord": {"page": 1, "bbox": [False, 0.1, 0.5, 0.9]},
    "short_bbox": {"page": 1, "bbox": [0.1, 0.1, 0.2]}, "nan": {"page": 1, "bbox": [float("nan"), 0, 1, 1]},
    "edge_full_page": {"page": 1, "bbox": [0, 0, 1, 1]},
}


def _verdict(model, d) -> bool:
    try:
        model.model_validate(d)
        return True
    except ValidationError:
        return False


#: Cases where the served model is deliberately STRICTER than the SDK's lax model: the served
#: `note` is never null, and a bool is not a page (the gateway's named checks refuse
#: it too). Everything else must agree; the served model is never LOOSER.
_STRICTER = {"null_note", "page_bool"}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_the_served_model_gives_the_sdk_verdict(name):
    d = _CASES[name]
    served, sdk = _verdict(ingest_api.EvidenceRef, d), _verdict(SdkEvidenceRef, d)
    if name in _STRICTER:
        assert sdk and not served, name
    else:
        assert served == sdk, name


@pytest.mark.parametrize("ref, ok", [
    ({"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4]}, True),
    ({"page": 1, "bbox": [0, 0, 1, 1]}, True),
    ({"page": 1, "bbox": ["0.1", 0.2, 0.3, 0.4]}, False),
    ({"page": "1", "bbox": None}, False),
    ({"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4], "note": None}, False),
])
def test_a_title_candidates_ref_is_strict_as_the_model_it_replaced(ref, ok):
    from src.iagent.gateway import TitleEvidenceRef
    assert _verdict(TitleEvidenceRef, ref) is ok, ref
