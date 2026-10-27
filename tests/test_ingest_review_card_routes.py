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

import psycopg2
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


#: The notice's own id as the extraction PRINTED it. Deliberately NOT the manifest's `doc_id`
#: ("PCN26-119", the filename-derived key): a fixture where the two agree cannot tell the right
#: source from the rejected one (2026-10-18: TI and IDT were titled by their file stems).
PRINTED = "PCN #26-119"

REVIEW = {
    "doc_id": "PCN26-119", "doc_id_raw": PRINTED,
    "notice_identity": {"mfr": "FallbackCo"}, "pages": [],
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
    holders: authz ids can_act_or_unavailable says yes to."""
    monkeypatch.setattr(ist, "get_row", lambda i: row)
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: task)
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, who: who in holders)


OPEN = {"audience": "document_promotion:SUSTAINMENT", "open": True}
RESOLVED = {"audience": "document_promotion:SUSTAINMENT", "open": False}


def _get(path):
    with TestClient(gateway.app) as c:
        return c.get(path)


def _refused(r, code, error, *ctx):
    """The status is asserted FIRST: a wrong status fails here, not as a KeyError on `detail`."""
    assert r.status_code == code, (r.status_code, code, ctx, r.text[:200])
    assert r.json()["detail"]["error"] == error, (error, ctx, r.text[:200])


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
    assert reg["title"] == PRINTED and PRINTED != MANIFEST["doc_id"]
    assert reg["summary"] == f"PCN {PRINTED} — Acme Semi, 2 parts, attempt 2."
    assert p["notice_id"] == PRINTED and p["ingest_id"] == ID and p["content_kind"] == "pcn"
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
    # No review.json, so no printed id: the title falls back to the DROP id, never to the
    # manifest's filename-derived `doc_id`.
    assert p["notice_id"] == ""
    assert reg["title"] == f"Promote document {ID}"
    assert reg["summary"] == f"PCN {ID} — manufacturer unknown, ? parts, attempt 2."


@pytest.mark.parametrize("raw", [None, "", "   ", "MISSING", 7])
def test_an_unextracted_notice_id_titles_the_task_by_its_drop_id(monkeypatch, raw):
    review = dict(REVIEW)
    if raw == "MISSING":
        del review["doc_id_raw"]
    else:
        review["doc_id_raw"] = raw
    fake = FakeS3(_objects(review=review))
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    reg = _file(monkeypatch, fake)
    assert reg["payload"]["notice_id"] == ""
    assert reg["title"] == f"Promote document {ID}", reg["title"]


# ── Part B: extraction rows ──────────────────────────────────────────────────────────────────

def test_extraction_rows_are_mapped_and_evidence_less_rows_are_counted(monkeypatch, s3):
    _gate(monkeypatch, row=_row())
    _as(monkeypatch, DROPPER)
    r = _get(f"/ingest/{ID}/extraction")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["review_ref"] == REVIEW_KEY and b["part_count"] == 2
    assert b["notice"] == {"mfr": "Acme Semi", "mfr_source": "header", "mfr_parent": "Acme Holdings",
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


def test_extraction_notice_id_is_the_printed_id_not_the_key_nor_the_row(monkeypatch, s3):
    _gate(monkeypatch, row=_row(notice_id="STALE-ROW-VALUE"))
    _as(monkeypatch, DROPPER)
    b = _get(f"/ingest/{ID}/extraction").json()
    assert b["notice_id"] == PRINTED, b["notice_id"]


def test_extraction_notice_id_is_null_when_none_was_extracted(monkeypatch):
    review = {k: v for k, v in REVIEW.items() if k != "doc_id_raw"}
    fake = FakeS3(_objects(review=review))
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    _gate(monkeypatch, row=_row(notice_id="STALE-ROW-VALUE"))
    _as(monkeypatch, DROPPER)
    b = _get(f"/ingest/{ID}/extraction").json()
    assert "notice_id" in b and b["notice_id"] is None, b["notice_id"]


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
    _refused(r, 422, "no_extraction_ref")
    _gate(monkeypatch, row=_row(extraction_ref="ingress-user/pdf/other/generated/m.json"))
    r = _get(f"/ingest/{ID}/extraction")
    _refused(r, 422, "extraction_unbound")
    # text_location pointing outside the prefix is refused BEFORE the read
    s3.objects[REF] = json.dumps({**MANIFEST, "text_location": "elsewhere/text.json"}).encode()
    _gate(monkeypatch, row=_row())
    s3.calls.clear()
    r = _get(f"/ingest/{ID}/extraction")
    _refused(r, 422, "extraction_unbound")
    assert "elsewhere/review.json" not in s3.calls
    s3.objects[REF] = json.dumps(MANIFEST).encode()
    del s3.objects[REVIEW_KEY]
    r = _get(f"/ingest/{ID}/extraction")
    _refused(r, 422, "extraction_rows_absent")
    s3.objects[REVIEW_KEY] = b"[1]"
    r = _get(f"/ingest/{ID}/extraction")
    _refused(r, 422, "extraction_unreadable")


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
            _refused(r, 403, "not_entitled", path, who)
            assert s3.calls == [], f"{path}: the store was read before the gate said no"
        # unknown id and an event row: 404
        for row in (None, _row(kind=ist.EVENT)):
            _gate(monkeypatch, row=row)
            _as(monkeypatch, DROPPER)
            s3.calls.clear()
            r = _get(f"/ingest/{ID}/{path}")
            _refused(r, 404, "ingest_not_found")
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
    _refused(r, 422, "source_unbound")
    assert "ingress-user/pdf/" + "a" * 64 + "/x.pdf" not in s3.calls
    # the manifest names a seam key that is not in the store: 404
    s3.objects[PREFIX + "manifest.json"] = json.dumps({"object_ref": PREFIX + "gone.pdf"}).encode()
    r = _get(f"/ingest/{ID}/source")
    _refused(r, 404, "source_absent")


# ── Part D: the gating manifest ──────────────────────────────────────────────────────────────

def test_the_gating_manifest_declares_both_routes():
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1]
            / "docs/architecture/endpoint_gating_manifest.yaml").read_text(encoding="utf-8")
    for p in ("/ingest/{ingest_id}/extraction", "/ingest/{ingest_id}/source"):
        i = text.index(f"path: {p}\n")
        block = text[i:i + 900]
        assert "class: gated" in block and "method: GET" in text[i - 40:i], p


# ── the gate decides on WHICH task and WHICH audience, not merely on who the caller is ─────────
# The `_gate` stubs ignore their arguments, so they cannot tell a holder of THIS ingest's task from
# a holder of another's. These stubs are keyed: the task by its id, `can_act_or_unavailable` by (aud, who)
# (#73: the gate no longer calls `check_can_act`, so a stub of it would stub nothing).

TASK_ID = f"{promotion.KIND}:{ID}"
OTHER_TASK_ID = f"{promotion.KIND}:sha256:{'d' * 64}"


def _keyed_gate(monkeypatch, *, tasks, grants, row=None):
    """tasks: {task_id: open-state}; grants: {(audience, authz_id)} can_act_or_unavailable says yes to."""
    monkeypatch.setattr(ist, "get_row", lambda i: row or _row())
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: tasks.get(t))
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, who: (aud, who) in grants)


def _denied_untouched(s3, path, who, monkeypatch):
    _as(monkeypatch, who)
    s3.calls.clear()
    r = _get(f"/ingest/{ID}/{path}")
    _refused(r, 403, "not_entitled", path, who)
    assert s3.calls == [], f"{path}: the store was read before the gate said no"


def test_a_holder_of_ANOTHER_ingests_open_task_is_refused(monkeypatch, s3):
    for path in ("extraction", "source"):
        # control: the same grants, with the open task on THIS ingest, admit the holder
        _keyed_gate(monkeypatch, tasks={TASK_ID: OPEN}, grants={(OPEN["audience"], HOLDER)})
        _as(monkeypatch, HOLDER)
        assert _get(f"/ingest/{ID}/{path}").status_code == 200, path
        # the task that is open belongs to another document
        _keyed_gate(monkeypatch, tasks={OTHER_TASK_ID: OPEN}, grants={(OPEN["audience"], HOLDER)})
        _denied_untouched(s3, path, HOLDER, monkeypatch)


def test_a_holder_of_a_DIFFERENT_audience_than_the_tasks_is_refused(monkeypatch, s3):
    for path in ("extraction", "source"):
        # the task's audience is not the one a literal could be spelled as; HOLDER holds the
        # task's audience in the control and only ANOTHER audience in the refusal
        task = {"open": True, "audience": "document_promotion:MANUFACTURING"}
        _keyed_gate(monkeypatch, tasks={TASK_ID: task}, grants={(task["audience"], HOLDER)})
        _as(monkeypatch, HOLDER)
        assert _get(f"/ingest/{ID}/{path}").status_code == 200, path  # control
        _keyed_gate(monkeypatch, tasks={TASK_ID: task}, grants={(OPEN["audience"], HOLDER)})
        _denied_untouched(s3, path, HOLDER, monkeypatch)


def test_an_open_task_with_an_empty_audience_admits_nobody(monkeypatch, s3):
    for path in ("extraction", "source"):
        _keyed_gate(monkeypatch, tasks={TASK_ID: {"open": True, "audience": ""}}, grants=set())
        monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, who: True)  # only the guard can refuse
        _denied_untouched(s3, path, HOLDER, monkeypatch)


# S3 splits by class under the architect's Q12 (#73): a dependency that is down is 503, never
# not_entitled; only a failure of no known class still fails closed as 403. Each raise leaves the
# store untouched and writes exactly one deny audit line.
_FAILURES = [
    ("get_task_open_state", lambda: psycopg2.OperationalError("task store down"),
     503, "authorization_unavailable"),
    ("can_act_or_unavailable", lambda: ht.AuthorizationUnavailable("topaz down"),
     503, "authorization_unavailable"),
    ("get_task_open_state", lambda: ht.HumanTaskConfigError("no task store configured"),
     503, "hitl_unconfigured"),
    ("get_task_open_state", lambda: RuntimeError("unknown"), 403, "not_entitled"),
    ("can_act_or_unavailable", lambda: RuntimeError("unknown"), 403, "not_entitled"),
]


@pytest.mark.parametrize("failing,exc,code,error", _FAILURES,
                         ids=[f"{f}-{e().__class__.__name__}" for f, e, _, _ in _FAILURES])
def test_a_failing_task_check_answers_by_class_with_one_deny_audit_line(
        monkeypatch, s3, caplog, failing, exc, code, error):
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    for path in ("extraction", "source"):
        _keyed_gate(monkeypatch, tasks={TASK_ID: OPEN}, grants={(OPEN["audience"], HOLDER)})

        def _boom(*a, **kw):
            raise exc()

        monkeypatch.setattr(ht, failing, _boom)
        caplog.clear()
        _as(monkeypatch, HOLDER)
        s3.calls.clear()
        _refused(_get(f"/ingest/{ID}/{path}"), code, error, path, failing)
        assert s3.calls == [], f"{path}: the store was read before the gate said no"
        lines = [r for r in caplog.records if r.name == "iagent.audit.ingest_access"]
        assert len(lines) == 1, (path, [r.getMessage() for r in lines])
        assert "decision=deny" in lines[0].getMessage() and lines[0].levelno == logging.WARNING


# ── 205b: /source at awaiting_kind ───────────────────────────────────────────────────────────
# Ruling: "/source serves the PDF while a row is at awaiting_kind, to the dropper and to anyone who
# can pick the kind. No review task exists yet, so this is the same 'may vet' rule that applies once
# one does." /source and POST /leaf share one gate (`_ingest_review_access`); the join is asserted.
SVC = "svc:openddil"


def _kind_row(**over):
    base = dict(status="awaiting_kind", extraction_ref=None, content_kind=None, kind="pdf")
    base.update(over)
    return _row(**base)


def _post_leaf(path_id=ID):
    with TestClient(gateway.app, raise_server_exceptions=False) as c:
        return c.post(f"/ingest/{path_id}/leaf", json={"leaf": "pdn"})


# (label, caller, row overrides, expected /source status)
_KIND_CALLERS = [
    ("dropper", DROPPER, {}, 200),
    ("on_behalf_of", "carol@example.com", {"on_behalf_of": "carol@example.com"}, 200),
    ("seeding_delegate", SVC, {"submitted_by": SVC}, 200),
    ("stranger_no_task", STRANGER, {}, 403),
]


@pytest.mark.parametrize("label,who,over,code", _KIND_CALLERS, ids=[c[0] for c in _KIND_CALLERS])
def test_source_at_awaiting_kind_by_caller(monkeypatch, s3, label, who, over, code):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps({SVC: ["carol@example.com"]}))
    _gate(monkeypatch, row=_kind_row(**over), task=None, holders=())
    _as(monkeypatch, who)
    r = _get(f"/ingest/{ID}/source")
    assert r.status_code == code, (label, r.status_code, r.text[:200])
    if code == 200:
        assert r.content == PDF_BYTES, label
        assert r.headers["content-type"] == "application/pdf", label
    else:
        _refused(r, 403, "not_entitled", label)


@pytest.mark.parametrize("label,who,over,code", _KIND_CALLERS, ids=[c[0] for c in _KIND_CALLERS])
def test_source_and_leaf_agree_at_awaiting_kind(monkeypatch, s3, label, who, over, code):
    """THE JOIN: one gate, two routes. A refusal at /source is the same refusal at /leaf; an
    admission at /source is never a gate refusal (403/404) at /leaf."""
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps({SVC: ["carol@example.com"]}))
    _gate(monkeypatch, row=_kind_row(**over), task=None, holders=())
    _as(monkeypatch, who)
    src = _get(f"/ingest/{ID}/source")
    leaf = _post_leaf()
    assert src.status_code == code, (label, src.status_code)
    if code == 403:
        assert leaf.status_code == src.status_code, (label, leaf.status_code, leaf.text[:200])
        assert leaf.json()["detail"]["error"] == "not_entitled", label
    else:
        assert leaf.status_code not in (403, 404), (label, leaf.status_code, leaf.text[:200])


def test_source_refusal_at_awaiting_kind_is_for_lack_of_the_task_not_the_fixture(monkeypatch, s3):
    """Positive control for the stranger arm: the same caller, the same fixtures, at `review` with
    an OPEN task whose audience the caller passes, is served."""
    _gate(monkeypatch, row=_kind_row(), task=None, holders={STRANGER})
    _as(monkeypatch, STRANGER)
    _refused(_get(f"/ingest/{ID}/source"), 403, "not_entitled", "awaiting_kind, no task")
    _gate(monkeypatch, row=_row(status="review"), task=OPEN, holders={STRANGER})
    r = _get(f"/ingest/{ID}/source")
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.content == PDF_BYTES
