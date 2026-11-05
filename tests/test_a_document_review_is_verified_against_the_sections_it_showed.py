"""A course is reviewed as a document: its promotion task serves `sections[]`, and a promote's
section coverage is verified against exactly that stored list (never a second read of the document).

The REAL filing path (`_file_or_find_document_promotion_task`) runs against a fake artifact store
holding the manifest and `extraction.json`; the REAL `/human_tasks/{id}/act` route runs against the
act world of `test_a_promotion_records_what_was_looked_at.py` (fake stores, no network).

Part coverage on a `notice` task is sealed by that file (`test_c1`..`test_c12`) and by
`test_review_coverage_accepts_both_forms_for_one_release.py`; here only the notice PAYLOAD is pinned.

Cortex's reader is `src/lib/documentReview.ts` `parse()` and its fixture is
`src/lib/documentReviewFixture.ts` (cortex-ui master); the rules and key names below restate what
`parse()` accepts, so a change on either side is a red here.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")
from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway, review_coverage as rcov, review_shapes  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from tests.test_a_promotion_records_what_was_looked_at import (  # noqa: E402,F401
    _LAB, _act, _nothing_written, world,
)

HEX = "c0" * 32
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
GEN = PREFIX + "generated/Course_pdf/doc-tools@61f74dc/"
REF = GEN + "manifest.json"
EXT_KEY = GEN + "extraction.json"
SRC_KEY = PREFIX + "Course.pdf"
ROOT = Path(__file__).resolve().parents[1]

MANIFEST = {"doc_id": "Course", "filename": "Course.pdf", "source_key": SRC_KEY,
            "text_location": GEN + "text.json", "pipeline_version": "doc-tools@61f74dc",
            "provenance": {"standing": "supervised", "ingest_id": ID}, "ingest_id": ID}

#: doc-tools #172's outline augmentation: nested, one section with no end_page.
OUTLINE = {"sections": [
    {"title": "Safety", "level": 1, "start_page": 1, "end_page": 2, "subsections": [
        {"title": "Hazards", "level": 2, "start_page": 1, "end_page": 1, "subsections": []},
        {"title": "PPE", "level": 2, "start_page": 2, "subsections": []}]},
    {"title": "Operation", "level": 1, "start_page": 3, "end_page": 6, "subsections": [
        {"title": "Start-up", "level": 2, "start_page": 3, "end_page": 4}]}],
    "metadata": {}, "outline_source": "toc"}
EXPECTED = [
    {"section_id": f"{ID}_s0", "title": "Safety", "page": 1, "page_end": 2},
    {"section_id": f"{ID}_s0_s0", "title": "Hazards", "page": 1, "page_end": 1},
    {"section_id": f"{ID}_s0_s1", "title": "PPE", "page": 2},
    {"section_id": f"{ID}_s1", "title": "Operation", "page": 3, "page_end": 6},
    {"section_id": f"{ID}_s1_s0", "title": "Start-up", "page": 3, "page_end": 4},
]
IDS = [s["section_id"] for s in EXPECTED]


class _Body:
    def __init__(self, data):
        self._d = data

    def read(self, n=-1):
        return self._d

    def close(self):
        pass


class FakeS3:
    def __init__(self, objects):
        self.objects = dict(objects)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        return {"Body": _Body(self.objects[Key])}


def _extraction(*augs):
    return json.dumps({"doc_id": "Course", "domain_type": "training",
                       "augmentations": list(augs)}).encode()


def _filed(monkeypatch, *, content_kind="course", extraction=None, manifest=None, objects=None):
    """File through the real helper; return the registered task (kwargs of `register_task`)."""
    monkeypatch.setenv("CONTENT_KIND_OVERLAY_DIRS", str(_LAB))
    monkeypatch.setattr(ck, "_REGISTRATIONS_CACHE", None)
    objs = {EXT_KEY: _extraction({"x": 1}, OUTLINE) if extraction is None else extraction}
    objs.update(objects or {})
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: FakeS3(objs))
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda k: dict(manifest or MANIFEST))
    monkeypatch.setattr(ht, "task_exists", lambda t: False)
    seen = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: seen.append(kw) or {"task_id": kw["task_id"]})
    row = {"id": ID, "status": "review", "kind": "pdf", "content_kind": content_kind, "attempt": 1,
           "object_prefix": PREFIX, "extraction_ref": REF, "submitted_by": "alice", "on_behalf_of": None}
    asyncio.run(gateway._file_or_find_document_promotion_task(
        ID, row, requested_by="svc:doc-tools", extraction_ref=REF))
    assert len(seen) == 1
    return seen[0]


def _course_shape():
    return yaml.safe_load((_LAB / "course.yaml").read_text(encoding="utf-8"))["review_shape"]


def _body(ids, **over):
    """A section coverage whose shape, item_kind and rules_version are READ from the shape row."""
    shape = review_shapes.valid_review_shapes()[_course_shape()]
    b = {"review_shape": shape.review_shape, "item_kind": shape.item_kind,
         "rules_version": shape.rules_version, "looked_at": list(ids), "sampled": [], "flagged": [],
         "groups": [], "shared": []}
    b.update(over)
    return b


def _serve(w, monkeypatch, payload):
    """Make `payload` the task the act route finds, as the queue serves it."""
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, status="pending": [
        {"task_id": "t-1", "kind": w.kind, "audience": "document_promotion:TRAINING",
         "payload": copy.deepcopy(payload)}])


# ---- the served payload ------------------------------------------------------------------------

def test_a_course_task_serves_the_shape_and_the_derived_section_ids_in_order(monkeypatch):
    p = _filed(monkeypatch)["payload"]
    assert p["review_shape"] == _course_shape()                       # the overlay row's own word
    assert p["sections"] == EXPECTED                                  # depth-first, nested included
    assert p["ingest_id"] == ID and p["content_kind"] == "course"


def test_the_served_payload_satisfies_cortexs_reader(monkeypatch):
    p = _filed(monkeypatch)["payload"]
    # documentReview.ts parse(): the keys and rules it reads (restated; the fixture's key names).
    assert p["review_shape"] == "document"
    assert isinstance(p["ingest_id"], str) and p["ingest_id"].strip()
    secs = p["sections"]
    assert isinstance(secs, list) and secs
    seen = set()
    for s in secs:
        assert set(s) <= {"section_id", "title", "page", "page_end"}   # documentReviewFixture.ts
        assert {"section_id", "title", "page"} <= set(s)
        assert isinstance(s["section_id"], str) and s["section_id"].strip()
        assert isinstance(s["title"], str) and s["title"].strip()
        assert type(s["page"]) is int and s["page"] >= 1
        if "page_end" in s:
            assert type(s["page_end"]) is int and s["page_end"] >= s["page"]   # never null
        assert s["section_id"] not in seen
        seen.add(s["section_id"])


def test_ids_follow_contract_v3_parent_id_s_i_with_the_ingest_id_as_the_course_id():
    # docs/contracts/training-workbench.md (lane/tr-g): `{parent.id}_s{i}`, nested `{Course.id}_s1_s0`.
    out = rcov.sections_from_extraction(json.loads(_extraction(OUTLINE)), "C")
    assert [s["section_id"] for s in out] == ["C_s0", "C_s0_s0", "C_s0_s1", "C_s1", "C_s1_s0"]


# ---- the refusals: absent, never partial, never empty ---------------------------------------------

def _bad(mut):
    o = copy.deepcopy(OUTLINE)
    mut(o)
    return _extraction(o)


@pytest.mark.parametrize("name,ext", [
    ("no_title", _bad(lambda o: o["sections"][0]["subsections"][1].update(title=" "))),
    ("page_zero", _bad(lambda o: o["sections"][1].update(start_page=0))),
    ("page_str", _bad(lambda o: o["sections"][1].update(start_page="3"))),
    ("page_bool", _bad(lambda o: o["sections"][1].update(start_page=True))),
    ("end_before_start", _bad(lambda o: o["sections"][1].update(end_page=2))),
    ("end_zero", _bad(lambda o: o["sections"][1].update(end_page=0))),
    ("deep_row_bad", _bad(lambda o: o["sections"][1]["subsections"][0].update(start_page=None))),
    ("empty", _extraction({**OUTLINE, "sections": []})),
    ("no_outline", _extraction({"x": 1})),
    ("two_outlines", _extraction(OUTLINE, OUTLINE)),
    ("not_json_object", b"[]"),
    ("not_json", b"\xff"),
])
def test_one_bad_row_or_no_single_outline_leaves_sections_absent_not_shorter(monkeypatch, caplog, name, ext):
    with caplog.at_level(logging.WARNING, logger="cortex"):
        p = _filed(monkeypatch, extraction=ext)["payload"]
    assert "sections" not in p, name                      # never null, never [], never partial
    assert p["review_shape"] == "document"                # the card still shows its reason line
    assert any(ID in r.getMessage() and "no sections served" in r.getMessage()
               for r in caplog.records), name


def test_an_absent_extraction_json_files_the_task_without_sections(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="cortex"):
        p = _filed(monkeypatch, extraction=None, objects={})["payload"]
    assert "sections" in p                                # control: present when the file is there
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: FakeS3({}))
    seen = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: seen.append(kw) or {})
    row = {"id": ID, "content_kind": "course", "attempt": 1, "object_prefix": PREFIX,
           "submitted_by": "alice", "on_behalf_of": None}
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="cortex"):
        asyncio.run(gateway._file_or_find_document_promotion_task(
            ID, row, requested_by="svc", extraction_ref=REF))
    assert "sections" not in seen[0]["payload"] and seen[0]["payload"]["review_shape"] == "document"
    assert any(ID in r.getMessage() for r in caplog.records)


def test_an_extraction_json_outside_the_documents_directory_is_not_read(monkeypatch):
    other = "ingress-user/pdf/" + "d1" * 32 + "/generated/x/"
    reads = []
    elsewhere = {other + "extraction.json": _extraction(OUTLINE)}
    m = {**MANIFEST, "text_location": other + "text.json"}
    real = gateway._read_extraction_json
    monkeypatch.setattr(gateway, "_read_extraction_json", lambda k: reads.append(k) or real(k))
    p = _filed(monkeypatch, manifest=m, objects=elsewhere)["payload"]
    assert "sections" not in p and reads == []            # refused before any read
    m2 = {**MANIFEST, "text_location": "s3://another-bucket/" + EXT_KEY}
    p2 = _filed(monkeypatch, manifest=m2)["payload"]
    assert "sections" not in p2 and reads == []
    # control: the bound key IS read (the spy sees it), so the empty reads above mean the refusal
    p3 = _filed(monkeypatch)["payload"]
    assert reads == [EXT_KEY] and "sections" in p3


# ---- a notice is untouched ---------------------------------------------------------------------

def test_a_notice_payload_carries_neither_the_shape_nor_sections_even_with_an_outline(monkeypatch):
    p = _filed(monkeypatch, content_kind="pcn")["payload"]
    assert "sections" not in p and "review_shape" not in p
    assert p["content_kind"] == "pcn"


# ---- the coverage -------------------------------------------------------------------------------

def _course_payload(monkeypatch):
    return _filed(monkeypatch)["payload"]


def test_a_coverage_over_every_section_passes_and_reads_no_extraction_parts(world, monkeypatch):
    _serve(world, monkeypatch, _course_payload(monkeypatch))
    r = _act(world, _body(IDS))
    assert r.status_code == 200, r.text
    assert world.part_reads == []                          # the universe was the stored list
    assert len(world.ledger.records) == 1


def test_one_missing_section_is_422_uncovered_and_nothing_is_written(world, monkeypatch):
    _serve(world, monkeypatch, _course_payload(monkeypatch))
    r = _act(world, _body(IDS[:-1]))
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "review_coverage_invalid" and d["check"] == "uncovered"
    assert IDS[-1] in d["message"]
    _nothing_written(world)


def test_an_unknown_section_id_is_422(world, monkeypatch):
    _serve(world, monkeypatch, _course_payload(monkeypatch))
    r = _act(world, _body(IDS + [f"{ID}_s9"]))
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "review_coverage_invalid" and d["check"] == "unknown_section"
    _nothing_written(world)


@pytest.mark.parametrize("drop", ["absent", "unreadable_outline"])
def test_a_task_with_no_sections_is_503_unverifiable_and_nothing_is_written(world, monkeypatch, drop):
    if drop == "absent":                                   # a task filed before this change
        p = _course_payload(monkeypatch)
        p.pop("sections")
        p.pop("review_shape")
    else:                                                  # filed now, outline unreadable
        p = _filed(monkeypatch, extraction=b"[]")["payload"]
        assert "sections" not in p
    _serve(world, monkeypatch, p)
    r = _act(world, _body(IDS))
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "review_coverage_unverifiable"
    _nothing_written(world)


def test_an_empty_sections_list_never_becomes_an_empty_universe_that_passes_anything(world, monkeypatch):
    p = _course_payload(monkeypatch)
    p["sections"] = []
    _serve(world, monkeypatch, p)
    r = _act(world, _body([]))
    assert r.status_code == 503 and r.json()["detail"]["error"] == "review_coverage_unverifiable"
    _nothing_written(world)


# ---- the rows are read from the files -----------------------------------------------------------

def test_the_overlay_row_and_the_shape_row_are_read_from_their_files_not_restated(monkeypatch):
    declared = _course_shape()
    row = yaml.safe_load((ROOT / "policy" / "review_shapes" / f"{declared}.yaml").read_text(encoding="utf-8"))
    assert row["item_kind"] in rcov.PAYLOAD_SERVED          # the card's item_kind is served from the payload
    assert row["item_kind"] in rcov._UNIVERSES
    # the filing path puts the DECLARED shape on the payload, whatever it is named
    assert _filed(monkeypatch)["payload"]["review_shape"] == declared
    # and a notice's declared shape is not one that is served from the payload
    notice = yaml.safe_load((_LAB / "pcn.yaml").read_text(encoding="utf-8"))["review_shape"]
    nrow = yaml.safe_load((ROOT / "policy" / "review_shapes" / f"{notice}.yaml").read_text(encoding="utf-8"))
    assert nrow["item_kind"] not in rcov.PAYLOAD_SERVED


def test_the_course_row_in_the_shape_registry_still_exists():
    assert (ROOT / "policy" / "review_shapes" / "course.yaml").is_file()      # retiring it is another PR
