"""The BFF leg of the three-repo row evidence_ref shape seal (architect 2026-10-21 and 2026-10-28).

WHAT THIS DEFENDS: GET /ingest/{id}/extraction serves each row's `evidence_ref` as 7f's
`wire_evidence_ref` `{page, bbox, note?}` (page fractions), byte for byte, and nothing else. No
`page_dims`, `bboxes`, `units` or `quality`, and no synthesis from a legacy item's
page_number/bboxes/page_dims. Every served ref validates against the `EvidenceRef` schema in the
published docs/api/cortex-bff.openapi.json. doc-tools and cortex-ui read the same fixture.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
import jsonschema  # noqa: E402  -- a hard import: the schema arms must read the published file
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_api  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "row_fraction_seal.json"
OPENAPI_PATH = ROOT / "docs" / "api" / "cortex-bff.openapi.json"

# doc-tools v0.2.2 tests/fixtures/sustainment/row_fraction_seal.json; cortex-ui
# src/lib/rowFractionSeal.test.ts reads the same file. A mismatch means one repo moved;
# re-vendor, never edit.
FIXTURE_SHA256 = "e3d063ecf76a110dc0d654410d26e77ac99ff4cf0250b61feff01606fcc4d872"

HEX = "5b15f205fc605c240c9ee37215d862bd977940eb26c74d73b739c538afa97091"
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
GEN = PREFIX + "generated/PCN26-119_pdf/doc-tools@61f74dc/"
REF = GEN + "manifest.json"
REVIEW_KEY = GEN + "review.json"
SRC_KEY = PREFIX + "PCN26-119.pdf"
DROPPER = "alice@example.com"
MANIFEST = {
    "doc_id": "PCN26-119", "filename": "PCN26-119.pdf", "source_key": SRC_KEY,
    "text_location": GEN + "text.json", "pipeline_version": "doc-tools@61f74dc",
    "provenance": {"standing": "supervised", "ingest_id": ID}, "ingest_id": ID,
}


@pytest.fixture(scope="module")
def fx():
    raw = FIXTURE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256, "fixture drifted: re-vendor from doc-tools"
    return json.loads(raw)


class _Body:
    def __init__(self, data):
        self._d = data

    def read(self, n=-1):
        d, self._d = self._d, b""
        return d

    def close(self):
        pass


class _FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        return {"Body": _Body(self.objects[Key])}


def _item(fp, value, **extra):
    d = {"field_path": fp, "value": value, "source_snippet": f"snip {value}", "region": "table",
         "match_method": "text_layer_cell", "match_confidence": 0.9, "needs_review": False,
         "review_reason": None, "approval_state": "pending"}
    d.update(extra)
    return d


def _serve(monkeypatch, items):
    review = {"doc_id": "PCN26-119", "doc_id_raw": "PCN #26-119", "notice_identity": {"mfr": "Acme"},
              "pages": [], "stats": {"text_layer_parts": 1}, "review_items": items}
    objs = {REF: json.dumps(MANIFEST).encode(),
            PREFIX + "manifest.json": json.dumps({"object_ref": SRC_KEY}).encode(),
            SRC_KEY: b"%PDF-1.7\n", REVIEW_KEY: json.dumps(review).encode()}
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _FakeS3(objs))
    row = {"id": ID, "status": "review", "kind": "pdf", "content_kind": "pcn", "attempt": 1,
           "object_prefix": PREFIX, "extraction_ref": REF, "submitted_by": DROPPER,
           "on_behalf_of": None, "notice_id": "PCN26-119"}
    monkeypatch.setattr(ist, "get_row", lambda i: row)
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: None)
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, who: False)
    user = type("U", (), {"authz_id": DROPPER, "id": DROPPER, "sub": DROPPER, "email": DROPPER,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    try:
        with TestClient(gateway.app) as c:
            r = c.get(f"/ingest/{ID}/extraction")
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _canon(x):
    return json.dumps(x, sort_keys=True)


def test_a_wire_ref_is_served_as_is(monkeypatch, fx):
    b = _serve(monkeypatch, [_item("parts[0].affected_mpn", "A", wire_evidence_ref=fx["new_shape"])])
    ev = b["rows"][0]["evidence_ref"]
    assert _canon(ev) == _canon(fx["new_shape"])
    assert "page_dims" not in ev
    assert b["rows_without_evidence"] == 0


def test_a_multi_box_union_is_served_as_is_with_its_note(monkeypatch, fx):
    want = fx["multi_box"]["new_shape"]
    assert want["note"] == "2 boxes"
    b = _serve(monkeypatch, [_item("parts[0].affected_mpn", "A", wire_evidence_ref=want)])
    ev = b["rows"][0]["evidence_ref"]
    assert _canon(ev) == _canon(want)
    assert "page_dims" not in ev


def test_every_served_ref_validates_against_the_published_schema(monkeypatch, fx):
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))["components"]["schemas"]["EvidenceRef"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"page", "bbox", "note"}
    b = _serve(monkeypatch, [
        _item("parts[0].affected_mpn", "A", wire_evidence_ref=fx["new_shape"]),
        _item("parts[0].replacement_mpn", "B", wire_evidence_ref=fx["multi_box"]["new_shape"]),
        _item("parts[1].affected_mpn", "C", wire_evidence_ref={"page": 1, "bbox": None})])
    served = [r["evidence_ref"] for r in b["rows"]]
    assert len(served) == 3 and all(s is not None for s in served)
    for s in served:
        jsonschema.validate(s, schema)


# cortex-ui src/lib/rowFractionSeal.test.ts, verbatim. Architect 2026-10-28: a schema that admits
# both shapes seals nothing, so the PUBLISHED schema must accept NEW_REF and refuse OLD_REF.
CORTEX_OLD_REF = {"page": 3, "bbox": [223, 917, 661, 953],
                  "page_dims": {"width": 1700, "height": 2200}, "units": "px"}
CORTEX_NEW_REF = {"page": 3, "bbox": [0.131176, 0.416818, 0.388824, 0.433182]}


def _published_evidence_ref_schema():
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))["components"]["schemas"]["EvidenceRef"]


def test_cortexs_refs_are_the_fixtures_shapes(fx):
    # By value: cortex writes the pixel numbers as ints, the fixture as floats.
    assert CORTEX_NEW_REF == fx["new_shape"]
    assert CORTEX_OLD_REF == fx["old_shape"]


def test_the_published_schema_accepts_cortexs_new_ref():
    jsonschema.validate(CORTEX_NEW_REF, _published_evidence_ref_schema())


@pytest.mark.parametrize("bad", [
    CORTEX_OLD_REF,
    {k: v for k, v in CORTEX_OLD_REF.items() if k != "page_dims"},  # pixels, no page_dims
    {k: v for k, v in CORTEX_OLD_REF.items() if k != "units"},      # page_dims alone
    dict(CORTEX_NEW_REF, page_dims=None),                           # today's wire: null page_dims
    dict(CORTEX_NEW_REF, note=None),                                # note?: string, never null
    dict(CORTEX_NEW_REF, note=" "),
], ids=["old_ref", "pixels_units", "pixels_page_dims", "new_plus_null_page_dims", "note_null", "note_blank"])
def test_the_published_schema_refuses_cortexs_old_ref_and_its_parts(bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _published_evidence_ref_schema())


def test_control_a_wire_ref_with_a_null_note_is_served_null(monkeypatch, fx):
    b = _serve(monkeypatch, [_item("parts[0].affected_mpn", "A",
                                   wire_evidence_ref=dict(fx["new_shape"], note=None))])
    assert b["rows"][0]["evidence_ref"] is None
    assert b["rows_without_evidence"] == 1


def test_control_the_old_shape_alone_is_served_null_and_counted(monkeypatch, fx):
    old = fx["old_shape"]
    legacy = _item("parts[0].affected_mpn", "A", page_number=old["page"], bboxes=[old["bbox"]],
                   page_dims=old["page_dims"])
    assert "wire_evidence_ref" not in legacy
    b = _serve(monkeypatch, [legacy])
    assert b["rows"][0]["evidence_ref"] is None
    assert b["rows_without_evidence"] == 1


def test_control_a_wire_ref_with_an_extra_key_is_served_null(monkeypatch, fx):
    bad = dict(fx["new_shape"], page_dims=fx["old_shape"]["page_dims"])
    b = _serve(monkeypatch, [_item("parts[0].affected_mpn", "A", wire_evidence_ref=bad)])
    assert b["rows"][0]["evidence_ref"] is None
    assert b["rows_without_evidence"] == 1
