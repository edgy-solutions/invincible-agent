"""A zero-row extraction never files `document_promotion` (architect ruling 2026-10-17): the stage
POST for `review` with rows=0 is refused, and the row goes `failed:extraction_empty`, retryable.

"Rows" is the SERVER's count from review.json -- the distinct `i` of the `parts[i].*` items, the
same items `GET /ingest/{id}/extraction` serves as `rows`. A claimed `extracted_count` does not
outvote it. Every kind that files a promotion is covered (find-or-file now, or `awaiting_origin`
-> `_file_promotion_if_ready` later); a kind in `_PROMOTION_SKIPPED_KINDS` files none and is exempt.
The CONTROL is the same fixture with one part row: it files as before.

Run: uv run --frozen pytest tests/test_a_zero_row_extraction_never_files_a_promotion.py -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_HEX = "d" * 64
_ID = "sha256:" + _HEX
_PREFIX = f"ingress-user/pdf/{_HEX}/"
_REF = f"{_PREFIX}generated/doc_pdf/doc-tools@61f74dc/manifest.json"
ALICE = "alice@example.com"

_PART = {"field_path": "parts[0].affected_mpn", "value": "X-1"}
_PART_SAME_ROW = {"field_path": "parts[0].disposition", "value": "replace"}
_HEADER = {"field_path": "header.mfr", "value": "ACME"}


class World:
    def __init__(self, kind):
        self.row = {"id": _ID, "status": "extracting", "kind": "pdf", "content_kind": kind,
                    "submitted_by": ALICE, "on_behalf_of": None, "object_prefix": _PREFIX,
                    "extraction_ref": None}
        self.writes = []            # (status, kwargs) in order
        self.filed = []
        self.review = {"review_items": []}
        self.review_raises = None

    def get_row(self, ingest_id):
        return self.row if ingest_id == _ID else None

    def update_status(self, ingest_id, status, **kw):
        self.writes.append((status, kw))
        self.row["status"] = status

    async def file_task(self, ingest_id, row, **kw):
        self.filed.append(row.get("content_kind"))
        return "T-1", "FILED"

    def read_review(self, key):
        if self.review_raises is not None:
            raise self.review_raises
        return self.review


def _world(monkeypatch, kind="pcn", *, domainless=False):
    w = World(kind)
    monkeypatch.setattr(ist, "get_row", w.get_row)
    monkeypatch.setattr(ist, "update_status", w.update_status)
    if domainless:
        reg = type("Reg", (), {"domain": None, "model_fields_set": frozenset({"domain"})})()
    else:
        reg = type("Reg", (), {"domain": "SUSTAINMENT"})()
    monkeypatch.setattr(ck, "by_kind", lambda k: reg)
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", w.file_task)
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: {})
    monkeypatch.setattr(gateway, "_read_review_json", w.read_review)

    async def _not_ready(*a, **kw):
        return None

    monkeypatch.setattr(gateway, "_file_promotion_if_ready", _not_ready)
    user = type("U", (), {"authz_id": "svc:doc-tools", "id": "svc:doc-tools",
                          "sub": "svc:doc-tools", "email": None, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return w


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    gateway.app.dependency_overrides.clear()


def _stage_review(**extra):
    return TestClient(gateway.app).post(
        f"/ingest/{_ID}/stage", json={"stage": "review", "extraction_ref": _REF, **extra})


def _assert_refused_empty(w, r):
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "extraction_empty" and d["reason_code"] == "extraction_empty"
    assert d["stage"] == "failed" and d["retryable"] is True
    (status, kw), = w.writes
    assert status == "failed"
    assert kw["failure"]["reason_code"] == "extraction_empty"
    assert kw["failure"]["step"] == "review"
    assert kw["failure"]["reason"] == "the extraction found no part rows"
    assert w.filed == [], "a promotion task was filed for an empty extraction"
    # `ingest_status.retry_failed` re-opens `status = 'failed' AND kind <> 'event'`
    assert w.row["status"] == "failed" and w.row["kind"] != "event"


def test_a_pdf_review_with_zero_part_rows_is_refused_and_the_row_fails_retryably(monkeypatch):
    w = _world(monkeypatch, "pdf")  # spec 208: a LEAF (pcn/pdn) is asked, not failed
    _assert_refused_empty(w, _stage_review())


def test_the_run_the_request_carried_rides_on_the_failure(monkeypatch):
    w = _world(monkeypatch, "pdf")  # spec 208: a LEAF (pcn/pdn) is asked, not failed
    r = _stage_review(run_id="run-9")
    assert r.status_code == 422, r.text
    (_, kw), = w.writes
    assert kw["failure"]["run_id"] == "run-9"
    assert kw["run_id"] == "run-9"


def test_a_claimed_zero_is_refused_even_though_review_json_holds_parts(monkeypatch):
    w = _world(monkeypatch, "pdf")  # spec 208: a LEAF (pcn/pdn) is asked, not failed
    w.review = {"review_items": [_PART]}
    _assert_refused_empty(w, _stage_review(extracted_count=0))


def test_a_claimed_five_does_not_outvote_a_server_count_of_zero(monkeypatch):
    w = _world(monkeypatch, "pdf")  # spec 208: a LEAF (pcn/pdn) is asked, not failed
    _assert_refused_empty(w, _stage_review(extracted_count=5))


def test_header_items_alone_are_not_rows(monkeypatch):
    w = _world(monkeypatch, "pdf")  # spec 208: a LEAF (pcn/pdn) is asked, not failed
    w.review = {"review_items": [_HEADER, {"field_path": "header.pub_date", "value": "2026-01-01"}]}
    _assert_refused_empty(w, _stage_review())


def test_CONTROL_the_same_pcn_review_with_one_part_row_files_as_before(monkeypatch):
    w = _world(monkeypatch)
    w.review = {"review_items": [_HEADER, _PART, _PART_SAME_ROW]}
    r = _stage_review()
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == "T-1" and r.json()["task_status"] == "FILED"
    assert w.filed == ["pcn"] and [s for s, _ in w.writes] == ["review"]


def test_an_s1000d_data_module_with_zero_parts_is_unaffected(monkeypatch):
    """Exempt: the kind files no promotion, so it is not the gate's population."""
    w = _world(monkeypatch, "s1000d-data-module")
    r = _stage_review()
    assert r.status_code == 200, r.text
    assert r.json()["task_status"] == "NO_TASK_KIND_SKIPS_PROMOTION"
    assert [s for s, _ in w.writes] == ["awaiting_origin"] and w.filed == []


def test_a_domainless_kind_that_awaits_origin_is_refused_on_zero_parts_too(monkeypatch):
    w = _world(monkeypatch, "pdf", domainless=True)
    _assert_refused_empty(w, _stage_review())


def test_CONTROL_a_domainless_kind_with_a_part_row_still_awaits_origin(monkeypatch):
    w = _world(monkeypatch, "pdf", domainless=True)
    w.review = {"review_items": [_PART]}
    r = _stage_review()
    assert r.status_code == 200, r.text
    assert r.json()["task_status"] == "NO_TASK_AWAITING_ORIGIN"
    assert [s for s, _ in w.writes] == ["awaiting_origin"]


@pytest.mark.parametrize("exc", [
    HTTPException(status_code=422, detail={"error": "extraction_unreadable"}),
    HTTPException(status_code=503, detail={"error": "artifact_store_unreachable"}),
    RuntimeError("boom")])
def test_an_unreadable_review_json_is_not_empty_and_keeps_todays_behaviour(monkeypatch, exc):
    """Today the find-or-file helper owns the refusal. Here it is stubbed to refuse as it does."""
    w = _world(monkeypatch)
    w.review_raises = exc

    async def _refuse(*a, **kw):
        raise HTTPException(status_code=422, detail={"error": "extraction_unreadable"})

    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _refuse)
    r = _stage_review()
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "extraction_unreadable"
    (status, kw), = w.writes
    assert status == "failed" and kw["failure"]["reason_code"] == "extraction_unreadable"
    assert kw["failure"]["reason_code"] != "extraction_empty"


def test_the_row_count_is_the_distinct_part_index_not_the_item_count():
    count = gateway._extraction_row_count
    assert count({"review_items": []}) == 0
    assert count({"review_items": [_HEADER]}) == 0
    assert count({"review_items": [_PART, _PART_SAME_ROW]}) == 1
    assert count({"review_items": [_PART, {"field_path": "parts[3].affected_mpn"}]}) == 2
