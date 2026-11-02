"""Spec 208 (architect ruling 2026-10-23): a zero-row extraction on a NOTICE (content_kind in
`ingest_status.LEAVES`) files a `document_empty_confirm` task and parks the row at `review`; it is no
longer `failed:extraction_empty`. Every other kind keeps today's 422 and failure dict.

Run: uv run --frozen pytest tests/test_a_zero_row_notice_is_asked_about_not_failed.py -v
"""
from __future__ import annotations

import pytest

from src.iagent import content_kinds as ck
from src.iagent import gateway
from src.iagent import ingest_status as ist
from tests._empty_confirm_world import ID, SVC, as_user, install, review_doc, stage_review


@pytest.fixture(autouse=True)
def _clear_overrides():
    as_user(SVC)
    yield
    gateway.app.dependency_overrides.clear()


@pytest.mark.parametrize("kind", ["pcn", "pdn"])
def test_a_leaf_with_zero_rows_files_the_empty_task_and_waits_at_review(monkeypatch, kind):
    w = install(monkeypatch, kind)
    w.review = review_doc(n_tables=0, reasons=("no_parts_found",))
    r = stage_review()
    assert r.status_code == 200, r.text
    task_id = f"document_empty_confirm:{ID}:a1"
    assert r.json() == {"ingest_id": ID, "stage": "review", "task_id": task_id,
                        "task_kind": "document_empty_confirm"}
    assert [s for s, _ in w.writes] == ["review"], "nothing may be written failed"
    assert w.writes[0][1]["detail"] == ("the extraction found no part rows; awaiting confirmation "
                                        "that the document has none")
    kw = w.tasks[task_id]["kw"]
    assert kw["kind"] == "document_empty_confirm" and kw["audience"] == "document_promotion:SUSTAINMENT"
    assert kw["payload"] == {
        "review_shape": "empty", "ingest_id": ID, "attempt": 1, "source": f"/ingest/{ID}/source",
        "account": {"n_tables": 0, "grid_no_parts_col": 0, "grid_rows_emitted": 0,
                    "review_reasons": ["no_parts_found"], "why": "no_table"},
        "forced_text_fallback": False, "add_missed_part": False, "content_kind": kind}


@pytest.mark.parametrize("kind", ["pdf"])
def test_CONTROL_a_non_notice_with_zero_rows_keeps_the_422_and_the_failure(monkeypatch, kind):
    w = install(monkeypatch, kind)
    r = stage_review()
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "extraction_empty" and d["stage"] == "failed" and d["retryable"] is True
    (status, kw), = w.writes
    assert status == "failed"
    assert kw["failure"]["reason_code"] == "extraction_empty"
    assert kw["failure"]["reason"] == "the extraction found no part rows" and kw["failure"]["step"] == "review"
    assert w.empty_tasks() == {}


@pytest.mark.parametrize("doc, why, n, col, em", [
    (review_doc(n_tables=0), "no_table", 0, 0, 0),
    (review_doc(n_tables=2, no_col=2), "no_parts_column", 2, 2, 0),
    (review_doc(n_tables=2, no_col=0), "zero_rows", 2, 0, 0),
    (review_doc(n_tables=1, no_col=0, emitted=4), "zero_rows", 1, 0, 4),
])
def test_why_is_derived_from_the_extractions_own_stats(doc, why, n, col, em):
    a = gateway._empty_account(doc)
    assert a["why"] == why
    assert (a["n_tables"], a["grid_no_parts_col"], a["grid_rows_emitted"]) == (n, col, em)


@pytest.mark.parametrize("doc", [None, {}, {"stats": "x"}, {"stats": None, "review_reasons": 3}, []])
def test_an_unreadable_review_json_gives_unknown_and_no_invented_figures(doc):
    a = gateway._empty_account(doc)
    assert a == {"n_tables": None, "grid_no_parts_col": None, "grid_rows_emitted": None,
                 "review_reasons": [], "why": "unknown"}


def test_stats_with_non_integer_figures_leave_those_figures_none():
    a = gateway._empty_account({"stats": {"n_tables": "2", "grid_no_parts_col": True,
                                          "grid_rows_emitted": 1.5}})
    assert (a["n_tables"], a["grid_no_parts_col"], a["grid_rows_emitted"]) == (None, None, None)
    assert a["why"] == "zero_rows"


def test_the_same_stage_posted_twice_files_one_task(monkeypatch):
    w = install(monkeypatch)
    assert stage_review().status_code == 200
    w.row["status"] = "extracting"        # a re-posted stage: the row is back where the post starts
    r = stage_review()
    assert r.status_code == 200, r.text
    assert list(w.empty_tasks()) == [f"document_empty_confirm:{ID}:a1"]


def test_a_new_attempt_files_a_new_task(monkeypatch):
    w = install(monkeypatch)
    assert stage_review().status_code == 200
    w.row.update(status="extracting", attempt=2)
    assert stage_review().status_code == 200
    assert sorted(w.empty_tasks()) == [f"document_empty_confirm:{ID}:a1", f"document_empty_confirm:{ID}:a2"]


def test_a_second_zero_after_the_forced_fallback_files_add_a_missed_part(monkeypatch):
    w = install(monkeypatch)
    w.row.update(attempt=2, force_text_fallback=True)
    assert stage_review().status_code == 200
    p = w.tasks[f"document_empty_confirm:{ID}:a2"]["kw"]["payload"]
    assert p["add_missed_part"] is True and p["forced_text_fallback"] is True


def test_a_notice_with_rows_still_does_not_take_the_empty_path(monkeypatch):
    w = install(monkeypatch)
    w.review = review_doc(rows=2)

    async def _file(ingest_id, row, **kw):
        return "T-1", "FILED"

    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _file)
    r = stage_review()
    assert r.status_code == 200, r.text
    assert w.empty_tasks() == {}


def test_a_refused_filing_fails_the_row_retryably_and_files_nothing(monkeypatch):
    w = install(monkeypatch)
    monkeypatch.setattr(ck, "by_kind", lambda k: type("Reg", (), {"domain": None})())
    r = stage_review()
    assert r.status_code == 422 and r.json()["detail"]["error"] == "no_declared_domain"
    (status, kw), = w.writes
    assert status == "failed" and kw["failure"]["reason_code"] == "no_declared_domain"
    assert w.empty_tasks() == {}


def test_CONTROL_an_s1000d_data_module_with_zero_rows_is_exempt_as_before(monkeypatch):
    """The spec expected a 422 here; today's code exempts the kind (it files no promotion), and the
    spec says non-notice behaviour is unchanged, so the exemption stands."""
    w = install(monkeypatch, "s1000d-data-module")
    r = stage_review()
    assert r.status_code == 200 and r.json()["task_status"] == "NO_TASK_KIND_SKIPS_PROMOTION"
    assert [s for s, _ in w.writes] == ["awaiting_origin"] and w.empty_tasks() == {}
