"""193.2 -- the document_promotion review card: payload, extraction rows, source bytes.

WHAT THESE DEFEND:
  * the task payload carries mfr / notice_date / part_count / attempt (always present, None when
    review.json is absent -- the task still files) and the title is the notice id.
  * GET /ingest/{id}/extraction maps review.json's `parts[i].*` items to rows with an
    `evidence_ref` (units pt for text_layer_cell, px otherwise) or null, counted.
  * the gate (dropper, or holder of the OPEN task) is decided BEFORE any S3 read; every decision
    is audited once on `iagent.audit.ingest_access`.
  * GET /ingest/{id}/source streams the dropped bytes; a key outside the prefix is 422.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion  # noqa: E402

HEX = "5b15f205fc605c240c9ee37215d862bd977940eb26c74d73b739c538afa97091"
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
GEN = PREFIX + "generated/PCN26-119_pdf/doc-tools@61f74dc/"
REF = GEN + "manifest.json"
REVIEW_KEY = GEN + "review.json"
SRC_KEY = PREFIX + "PCN26-119.pdf"
PDF_BYTES = b"%PDF-1.7\n" + bytes(range(256)) * 600
DROPPER = "alice@example.com"
HOLDER = "steward@example.com"
STRANGER = "mallory@example.com"

MANIFEST = {
    "doc_id": "PCN26-119", "filename": "PCN26-119.pdf", "source_key": SRC_KEY,
    "text_location": GEN + "text.json", "pipeline_version": "doc-tools@61f74dc",
    "provenance": {"standing": "supervised", "ingest_id": ID}, "ingest_id": ID,
}


def _item(fp, value, *, page=2, bboxes=((10.0, 20.0, 30.0, 40.0),), method="text_layer_cell"):
    return {"field_path": fp, "value": value, "source_snippet": f"snip {value}", "region": "table",
            "page_number": page, "bboxes": [list(b) for b in bboxes] if bboxes is not None else [],
            "page_dims": [612, 792], "match_method": method, "match_confidence": 0.9,
            "needs_review": False, "review_reason": None, "approval_state": "pending"}


REVIEW = {
    "doc_id": "PCN26-119", "notice_identity": {"mfr": "FallbackCo"}, "pages": [],
    "stats": {"text_layer_parts": 2},
    "review_items": [
        _item("header.mfr", "Acme Semi"),
        _item("header.pub_date", "2026-03-04"),
        _item("header.mfr_parent", "Acme Holdings"),
        _item("parts[0].affected_mpn", "ABC123"),
        _item("parts[0].replacement_mpn", "ABC123-R", method="layout_fuzzy", page=3),
        _item("parts[1].affected_mpn", "XYZ9", bboxes=None),
        _item("parts[1].ltb_date", "2026-09-01", page=None),
    ],
}


class _Body:
    def __init__(self, data):
        self._d, self._p = data, 0

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._d)
        out = self._d[self._p:self._p + n]
        self._p += n
        return out

    def close(self):
        pass


class FakeS3:
    def __init__(self, objects):
        self.objects, self.calls = dict(objects), []

    def get_object(self, Bucket, Key):
        self.calls.append(Key)
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        return {"Body": _Body(self.objects[Key])}


def _row(**over):
    r = {"id": ID, "status": "review", "kind": "pdf", "content_kind": "pcn", "attempt": 2,
         "object_prefix": PREFIX, "extraction_ref": REF, "submitted_by": DROPPER,
         "on_behalf_of": None, "notice_id": "PCN26-119"}
    r.update(over)
    return r


def _objects(review=REVIEW):
    objs = {REF: json.dumps(MANIFEST).encode(),
            PREFIX + "manifest.json": json.dumps({"object_ref": SRC_KEY}).encode(),
            SRC_KEY: PDF_BYTES}
    if review is not None:
        objs[REVIEW_KEY] = json.dumps(review).encode()
    return objs


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3(_objects())
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    return fake


def _as(monkeypatch, who):
    user = type("U", (), {"authz_id": who, "id": who, "sub": who, "email": who, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    gateway.app.dependency_overrides.clear()


def _gate(monkeypatch, *, row=None, task=None, holders=()):
    """row: what ingest_status.get_row answers; task: get_task_open_state's answer;
    holders: authz ids check_can_act says yes to."""
    monkeypatch.setattr(ist, "get_row", lambda i: row)
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: task)
    monkeypatch.setattr(ht, "check_can_act", lambda aud, who: who in holders)


OPEN = {"audience": "document_promotion:SUSTAINMENT", "open": True}
RESOLVED = {"audience": "document_promotion:SUSTAINMENT", "open": False}


def _get(path):
    with TestClient(gateway.app) as c:
        return c.get(path)


# ── Part A: payload and title ────────────────────────────────────────────────────────────────

def _file(monkeypatch, s3, row=None):
    reg = type("Reg", (), {"domain": "sustainment"})()
    monkeypatch.setattr(ck, "by_kind", lambda k: reg if k == "pcn" else None)
    monkeypatch.setattr(ht, "task_exists", lambda t: False)
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda k: dict(MANIFEST))
    seen = []
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: seen.append(kw) or {"task_id": kw["task_id"]})
    out = asyncio.run(gateway._file_or_find_document_promotion_task(
        ID, row or _row(), requested_by="svc:doc-tools", extraction_ref=REF))
    assert out == (f"{promotion.KIND}:{ID}", "FILED")
    assert len(seen) == 1
    return seen[0]


def test_payload_carries_the_card_facts_and_title_is_the_notice_id(monkeypatch, s3):
    reg = _file(monkeypatch, s3)
    p = reg["payload"]
    assert (p["mfr"], p["notice_date"], p["part_count"], p["attempt"]) == (
        "Acme Semi", "2026-03-04", 2, 2)
    assert reg["title"] == "PCN26-119"
    assert reg["summary"] == "PCN PCN26-119 — Acme Semi, 2 parts, attempt 2."
    assert p["notice_id"] == "PCN26-119" and p["ingest_id"] == ID and p["content_kind"] == "pcn"
    assert p["dropped_by"]["authz_id"] == DROPPER


def test_mfr_falls_back_to_notice_identity(monkeypatch, s3):
    review = {**REVIEW, "review_items": [i for i in REVIEW["review_items"]
                                         if i["field_path"] != "header.mfr"]}
    s3.objects[REVIEW_KEY] = json.dumps(review).encode()
    assert _file(monkeypatch, s3)["payload"]["mfr"] == "FallbackCo"


def test_review_json_absent_still_files_with_the_four_keys_none(monkeypatch):
    fake = FakeS3(_objects(review=None))
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    reg = _file(monkeypatch, fake)
    p = reg["payload"]
    for k in ("mfr", "notice_date", "part_count"):
        assert k in p and p[k] is None, k
    assert p["attempt"] == 2
    assert reg["summary"] == "PCN PCN26-119 — manufacturer unknown, ? parts, attempt 2."


# ── Part B: extraction rows ──────────────────────────────────────────────────────────────────

def test_extraction_rows_are_mapped_and_evidence_less_rows_are_counted(monkeypatch, s3):
    _gate(monkeypatch, row=_row())
    _as(monkeypatch, DROPPER)
    r = _get(f"/ingest/{ID}/extraction")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["review_ref"] == REVIEW_KEY and b["part_count"] == 2
    assert b["notice"] == {"mfr": "Acme Semi", "mfr_parent": "Acme Holdings",
                           "notice_date": "2026-03-04"}
    assert [(x["part_index"], x["field"], x["mpn"], x["extracted_value"]) for x in b["rows"]] == [
        (0, "affected_mpn", "ABC123", "ABC123"), (0, "replacement_mpn", "ABC123", "ABC123-R"),
        (1, "affected_mpn", "XYZ9", "XYZ9"), (1, "ltb_date", "XYZ9", "2026-09-01")]
    assert [x["row_index"] for x in b["rows"]] == [0, 1, 2, 3]
    assert b["rows"][0]["obtained_via"] == "text_layer_cell"
    # a row with no bbox, and a row with no page: null evidence, both counted
    assert b["rows"][2]["evidence_ref"] is None and b["rows"][3]["evidence_ref"] is None
    assert b["rows_without_evidence"] == 2
    ev = b["rows"][0]["evidence_ref"]
    assert ev == {"page": 2, "bbox": [10.0, 20.0, 30.0, 40.0],
                  "bboxes": [[10.0, 20.0, 30.0, 40.0]], "page_dims": [612, 792], "units": "pt",
                  "quality": "cell"}


def test_units_are_pt_for_a_text_layer_cell_and_px_for_anything_else(monkeypatch, s3):
    _gate(monkeypatch, row=_row())
    _as(monkeypatch, DROPPER)
    rows = _get(f"/ingest/{ID}/extraction").json()["rows"]
    assert rows[0]["evidence_ref"]["units"] == "pt"
    assert rows[1]["obtained_via"] == "layout_fuzzy"
    assert rows[1]["evidence_ref"]["units"] == "px"


def test_evidence_quality_is_cell_region_or_undecided():
    from src.iagent import gateway
    ev = lambda m: gateway._evidence_ref(_item("parts[0].mpn", "A", method=m))  # noqa: E731
    assert ev("text_layer_cell")["quality"] == "cell"
    assert ev("region_preferred")["quality"] == "region"
    assert ev("region_image")["quality"] == "region"
    # architect 2026-10-17: an unrecognised method is undecided, never guessed
    inherited = ev("inherited_doc_level")
    assert inherited is not None and inherited["quality"] is None
    assert gateway._evidence_ref(_item("parts[0].mpn", "A", bboxes=None)) is None


def test_extraction_refusals(monkeypatch, s3):
    _as(monkeypatch, DROPPER)
    _gate(monkeypatch, row=_row(extraction_ref=None))
    r = _get(f"/ingest/{ID}/extraction")
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "no_extraction_ref")
    _gate(monkeypatch, row=_row(extraction_ref="ingress-user/pdf/other/generated/m.json"))
    r = _get(f"/ingest/{ID}/extraction")
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "extraction_unbound")
    # text_location pointing outside the prefix is refused BEFORE the read
    s3.objects[REF] = json.dumps({**MANIFEST, "text_location": "elsewhere/text.json"}).encode()
    _gate(monkeypatch, row=_row())
    s3.calls.clear()
    r = _get(f"/ingest/{ID}/extraction")
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "extraction_unbound")
    assert "elsewhere/review.json" not in s3.calls
    s3.objects[REF] = json.dumps(MANIFEST).encode()
    del s3.objects[REVIEW_KEY]
    r = _get(f"/ingest/{ID}/extraction")
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "extraction_rows_absent")
    s3.objects[REVIEW_KEY] = b"[1]"
    r = _get(f"/ingest/{ID}/extraction")
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "extraction_unreadable")


# ── gate and audit ───────────────────────────────────────────────────────────────────────────

def test_gate_dropper_holder_stranger_resolved_and_unknown(monkeypatch, s3, caplog):
    for path in ("extraction", "source"):
        # dropper (and on_behalf_of, casefolded)
        _gate(monkeypatch, row=_row(on_behalf_of="Carol@Example.com"))
        for who in (DROPPER, "carol@example.com"):
            _as(monkeypatch, who)
            assert _get(f"/ingest/{ID}/{path}").status_code == 200, (path, who)
        # holder of the OPEN task
        _gate(monkeypatch, row=_row(), task=OPEN, holders={HOLDER})
        _as(monkeypatch, HOLDER)
        assert _get(f"/ingest/{ID}/{path}").status_code == 200, path
        # denied: a stranger, a stranger who is not a holder of an open task, a holder of a
        # RESOLVED task -- and the store is never touched
        for task, holders, who in ((OPEN, {HOLDER}, STRANGER), (None, {STRANGER}, STRANGER),
                                   (RESOLVED, {HOLDER}, HOLDER)):
            _gate(monkeypatch, row=_row(), task=task, holders=holders)
            _as(monkeypatch, who)
            s3.calls.clear()
            r = _get(f"/ingest/{ID}/{path}")
            assert (r.status_code, r.json()["detail"]["error"]) == (403, "not_entitled"), (path, who)
            assert s3.calls == [], f"{path}: the store was read before the gate said no"
        # unknown id and an event row: 404
        for row in (None, _row(kind=ist.EVENT)):
            _gate(monkeypatch, row=row)
            _as(monkeypatch, DROPPER)
            s3.calls.clear()
            r = _get(f"/ingest/{ID}/{path}")
            assert (r.status_code, r.json()["detail"]["error"]) == (404, "ingest_not_found")
            assert s3.calls == []


def test_every_decision_emits_one_audit_line(monkeypatch, s3, caplog):
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    cases = [("extraction", DROPPER, OPEN, set(), 200, "allow", logging.INFO),
             ("source", HOLDER, OPEN, {HOLDER}, 200, "allow", logging.INFO),
             ("extraction", STRANGER, OPEN, {HOLDER}, 403, "deny", logging.WARNING),
             ("source", STRANGER, None, set(), 403, "deny", logging.WARNING)]
    for route, who, task, holders, code, decision, level in cases:
        caplog.clear()
        _gate(monkeypatch, row=_row(), task=task, holders=holders)
        _as(monkeypatch, who)
        assert _get(f"/ingest/{ID}/{route}").status_code == code
        lines = [r for r in caplog.records if r.name == "iagent.audit.ingest_access"]
        assert len(lines) == 1, (route, who, [r.getMessage() for r in lines])
        msg = lines[0].getMessage()
        assert lines[0].levelno == level
        for frag in (f"route={route}", f"ingest_id={ID}", f"caller={who}", f"decision={decision}"):
            assert frag in msg, (frag, msg)
        assert "http" not in msg and REVIEW_KEY not in msg


# ── Part C: source bytes ─────────────────────────────────────────────────────────────────────

def test_source_streams_the_dropped_bytes(monkeypatch, s3):
    _gate(monkeypatch, row=_row(status="received", extraction_ref=None))  # no extraction yet
    _as(monkeypatch, DROPPER)
    r = _get(f"/ingest/{ID}/source")
    assert r.status_code == 200
    assert r.content == PDF_BYTES
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="PCN26-119.pdf"'
    assert "no-store" in r.headers["cache-control"]  # app-wide middleware forces plain no-store


def test_source_other_kinds_and_refusals(monkeypatch, s3):
    _as(monkeypatch, DROPPER)
    _gate(monkeypatch, row=_row(kind="cad"))
    assert _get(f"/ingest/{ID}/source").headers["content-type"] == "application/octet-stream"
    # the drop manifest names a key outside the row's prefix: 422, the object is never fetched
    s3.objects[PREFIX + "manifest.json"] = json.dumps(
        {"object_ref": "ingress-user/pdf/" + "a" * 64 + "/x.pdf"}).encode()
    _gate(monkeypatch, row=_row())
    s3.calls.clear()
    r = _get(f"/ingest/{ID}/source")
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "source_unbound")
    assert "ingress-user/pdf/" + "a" * 64 + "/x.pdf" not in s3.calls
    # the manifest names a seam key that is not in the store: 404
    s3.objects[PREFIX + "manifest.json"] = json.dumps({"object_ref": PREFIX + "gone.pdf"}).encode()
    r = _get(f"/ingest/{ID}/source")
    assert (r.status_code, r.json()["detail"]["error"]) == (404, "source_absent")


# ── Part D: the gating manifest ──────────────────────────────────────────────────────────────

def test_the_gating_manifest_declares_both_routes():
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1]
            / "docs/architecture/endpoint_gating_manifest.yaml").read_text(encoding="utf-8")
    for p in ("/ingest/{ingest_id}/extraction", "/ingest/{ingest_id}/source"):
        i = text.index(f"path: {p}\n")
        block = text[i:i + 900]
        assert "class: gated" in block and "method: GET" in text[i - 40:i], p
