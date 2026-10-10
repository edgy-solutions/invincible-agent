"""The promotion task's payload is DERIVED from the extraction manifest, not asserted.

Found live (PCN26-119, roll #19): the stage route filed {ingest_id, domain, dropped_by} and the
promote was refused 422 promotion_payload_invalid. doc-tools now names its versioned manifest
(`extraction_ref`) on the review POST; `promotion.payload_from_extraction` turns that manifest
into the seven fields the act requires (ADR-0034: a caller may not assert pipeline_version or
format_fingerprint). Values below are the capture's own.
"""
from __future__ import annotations

import copy

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.utils.format_fingerprint import (  # noqa: E402
    format_fingerprint, format_fingerprint_from_manifest)
from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion  # noqa: E402

HEX = "5b15f205fc605c240c9ee37215d862bd977940eb26c74d73b739c538afa97091"
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
REF = PREFIX + "generated/PCN26-119_pdf/doc-tools@61f74dc/manifest.json"
ROW = {"id": ID, "status": "extracting", "kind": "pdf", "content_kind": "pcn",
       "object_prefix": PREFIX, "submitted_by": "alice@example.com"}
MANIFEST = {
    "doc_id": "PCN26-119", "filename": "PCN26-119.pdf", "source_key": PREFIX + "PCN26-119.pdf",
    "metadata": {}, "extraction_metadata": {}, "embedded_images": [], "pages": [],
    "text_location": "", "pipeline_version": "doc-tools@61f74dc",
    "provenance": {"standing": "supervised", "ingest_id": ID}, "ingest_id": ID,
}
OTHER = "sha256:" + "a" * 64


def _m(**over):
    m = copy.deepcopy(MANIFEST)
    m.update(over)
    return m


def test_the_captures_own_failure_reproduced():
    with pytest.raises(promotion.PromotionRefused) as ei:
        promotion.subject_from_payload({
            "domain": "SUSTAINMENT", "ingest_id": ID,
            "dropped_by": {"authz_id": "alice@example.com"}})
    assert ei.value.error == "promotion_payload_invalid"
    assert str(['object_ref', 'content_kind', 'pipeline_version', 'format_fingerprint',
                'standing', 'extraction_ref']) in str(ei.value)


def test_every_field_comes_from_its_stated_source_and_the_act_accepts_it():
    p = promotion.payload_from_extraction(ID, ROW, MANIFEST, "  " + REF + " ")
    assert p == {
        "ingest_id": ID,
        "object_ref": PREFIX + "PCN26-119.pdf",
        "content_kind": "pcn",
        "pipeline_version": "doc-tools@61f74dc",
        "format_fingerprint": "unknown/unknown/v1",
        "standing": "supervised",
        "extraction_ref": REF,
        "notice_id": "PCN26-119",
    }
    s = promotion.subject_from_payload(p)
    assert s.extraction_ref == REF and s.notice_id == "PCN26-119"


def _fi(doc_type, source, mfr="Acme"):
    block = {"manufacturer": mfr, "doc_type": doc_type, "doc_type_source": source}
    return format_fingerprint_from_manifest({"format_identity": block}, aliases={})


@pytest.mark.parametrize("source,expected", [
    ("title", "acme/pcn/v1"), ("extraction", "acme/pcn/v1"), ("TITLE ", "acme/pcn/v1"),
    ("title-ambiguous", "acme/unknown/v1"), ("no-title-evidence", "acme/unknown/v1"),
    ("defaulted", "acme/unknown/v1"), (None, "acme/unknown/v1"),
])
def test_manifest_fingerprint_attests_only_the_attesting_sources(source, expected):
    assert _fi("PCN", source) == expected


def test_manifest_fingerprint_vendor_absent_and_block_absent():
    assert _fi("PCN", "title", mfr=None) == "unknown/pcn/v1"
    for m in ({}, {"format_identity": None}, {"format_identity": "x"}, [], None):
        assert format_fingerprint_from_manifest(m, aliases={}) == "unknown/unknown/v1"


def test_review_json_reader_attests_title_too():
    review = {"review_items": [{"field_path": "header.mfr", "value": "Acme"}],
              "doc_type": "PCN", "doc_type_source": "title"}
    assert format_fingerprint(review, aliases={}) == "acme/pcn/v1"
    review["doc_type_source"] = "title-ambiguous"
    assert format_fingerprint(review, aliases={}) == "acme/unknown/v1"


@pytest.mark.parametrize("label,manifest,row,ref,error", [
    ("other hex in source_key", _m(source_key="ingress-user/pdf/" + "a" * 64 + "/x.pdf"),
     ROW, REF, "extraction_unbound"),
    ("source_key not a str", _m(source_key=None), ROW, REF, "extraction_unbound"),
    ("manifest ingest_id differs", _m(ingest_id=OTHER), ROW, REF, "extraction_unbound"),
    ("provenance ingest_id differs",
     _m(provenance={"standing": "supervised", "ingest_id": OTHER}), ROW, REF,
     "extraction_unbound"),
    ("ref outside prefix", MANIFEST, ROW, "ingress-user/pdf/" + "a" * 64 + "/m.json",
     "extraction_unbound"),
    ("ref blank", MANIFEST, ROW, "  ", "extraction_unbound"),
    ("version empty", _m(pipeline_version=""), ROW, REF, "extraction_unversioned"),
    ("version unknown", _m(pipeline_version="unknown"), ROW, REF, "extraction_unversioned"),
    ("version doc-tools@unknown", _m(pipeline_version="doc-tools@unknown"), ROW, REF,
     "extraction_unversioned"),
    ("standing absent", _m(provenance={"ingest_id": ID}), ROW, REF, "extraction_unbound"),
    ("content_kind None", MANIFEST, {**ROW, "content_kind": None}, REF, "extraction_unbound"),
    ("manifest a list", [MANIFEST], ROW, REF, "extraction_unreadable"),
])
def test_each_refusal_names_its_error(label, manifest, row, ref, error):
    with pytest.raises(promotion.PromotionRefused) as ei:
        promotion.payload_from_extraction(ID, row, manifest, ref)
    assert ei.value.error == error, (label, str(ei.value))
    assert ei.value.status == 422


# -- the route ---------------------------------------------------------------------------------
@pytest.fixture
def doc_tools_client():
    user = type("U", (), {"authz_id": "svc:doc-tools", "id": "svc:doc-tools",
                          "sub": "svc:doc-tools", "email": None, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def wired(monkeypatch):
    rec = {"reads": [], "status": [], "registered": []}
    row = dict(ROW)
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    monkeypatch.setattr(ist, "update_status",
                        lambda ingest_id, stage, **kw: rec["status"].append((stage, kw)))
    reg = type("Reg", (), {"domain": "sustainment"})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg if kind == "pcn" else None)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: rec["registered"].append(kw) or {"task_id": kw["task_id"],
                                                                      "recipients": ["x"]})
    monkeypatch.setattr(gateway, "_read_extraction_manifest",
                        lambda key: rec["reads"].append(key) or copy.deepcopy(MANIFEST))
    return rec


def test_route_without_an_extraction_ref_files_nothing(doc_tools_client, wired):
    r = doc_tools_client.post(f"/ingest/{ID}/stage", json={"stage": "review"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_extraction_ref"
    assert wired["status"] == [] and wired["registered"] == [] and wired["reads"] == []


def test_route_refuses_a_ref_outside_the_documents_directory_before_reading(
        doc_tools_client, wired):
    r = doc_tools_client.post(f"/ingest/{ID}/stage", json={
        "stage": "review", "extraction_ref": "ingress-user/pdf/" + "a" * 64 + "/m.json"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "extraction_unbound"
    assert wired["reads"] == []
    assert wired["status"] == [] and wired["registered"] == []


def test_route_with_the_good_ref_files_a_payload_the_act_accepts(doc_tools_client, wired):
    r = doc_tools_client.post(f"/ingest/{ID}/stage",
                              json={"stage": "review", "extraction_ref": REF})
    assert r.status_code == 200, r.text
    assert wired["reads"] == [REF]
    (reg,) = wired["registered"]
    p = reg["payload"]
    for f in promotion.PAYLOAD_FIELDS:
        assert p[f], f
    assert p["review_pool"] == "SUSTAINMENT"
    assert p["dropped_by"] == {"authz_id": "alice@example.com"}
    assert p["extraction_ref"] == REF and p["pipeline_version"] == "doc-tools@61f74dc"
    promotion.subject_from_payload(p)
    assert wired["status"] == [("review", {"extracted_count": None, "extracted_total": None,
                                           "detail": None, "extraction_ref": REF})]
