"""Rev 208 (cortex packet 2026-10-24 §1, ruled Q1 yes): at `review` the status row names the task a
steward actually acts on. A zero-row notice is held on a `document_empty_confirm` task, so its
`review_task_id` is THAT task, `review_shape` is "empty" and `account` is the extraction's own account;
every other review row names its current promotion task. Before 208 the row named a promotion task
that was never filed. Also `extraction_defect`: the newest defect filed about the drop, as
{task_id, edits}, null when none, ABSENT when the route cannot tell.

Run: uv run --frozen pytest tests/test_the_status_row_names_the_task_a_steward_acts_on.py -v
"""
from __future__ import annotations

import pytest

from src.iagent import gateway
from src.iagent import human_tasks as ht
from tests._empty_confirm_world import (
    DROPPER, ID, STEWARD, SVC, as_user, client, install, review_doc, stage_review)

EMPTY = f"document_empty_confirm:{ID}:a1"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    gateway.app.dependency_overrides.clear()


def _status():
    as_user(DROPPER)
    r = client().get(f"/ingest/{ID}/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_zero_row_notice_at_review_names_the_empty_task_the_hold_filed(monkeypatch):
    w = install(monkeypatch)
    w.review = review_doc(n_tables=2, no_col=2, reasons=("no_parts_found",))
    as_user(SVC)
    held = stage_review()
    assert held.status_code == 200, held.text
    filed = held.json()["task_id"]
    assert w.tasks[filed]["open"] is True, "the hold must have filed the task it names"
    b = _status()
    assert b["stage"] == "review"
    assert b["review_task_id"] == filed == EMPTY
    assert b["review_shape"] == "empty"
    assert b["account"] == w.tasks[filed]["kw"]["payload"]["account"]
    assert b["account"]["why"] == "no_parts_column"


def test_a_review_row_with_no_empty_task_names_its_current_promotion_task(monkeypatch):
    w = install(monkeypatch)
    w.row.update(status="review", review_generation=1)
    b = _status()
    assert b["review_task_id"] == gateway._promotion_task_id(ID, 1)
    assert b["review_task_id"] != gateway._promotion_task_id(ID, 0), "the generation must count"
    assert b["review_shape"] == "promotion" and b["account"] is None


def test_CONTROL_an_empty_task_of_ANOTHER_attempt_does_not_make_the_row_empty(monkeypatch):
    w = install(monkeypatch)
    as_user(SVC)
    assert stage_review().status_code == 200
    w.row.update(attempt=2)          # the a1 task is still open; the row's current attempt is a2
    b = _status()
    assert b["review_shape"] == "promotion"
    assert b["review_task_id"] == gateway._promotion_task_id(ID, 0)


@pytest.mark.parametrize("stage", ["received", "extracting", "promoted", "no_parts", "failed"])
def test_off_review_all_three_are_null(monkeypatch, stage):
    w = install(monkeypatch)
    w.row.update(status=stage)
    b = _status()
    assert (b["review_task_id"], b["review_shape"], b["account"]) == (None, None, None)


def test_an_unreadable_task_store_at_review_leaves_the_three_null_not_guessed(monkeypatch):
    w = install(monkeypatch)
    w.row.update(status="review")

    def _down(task_id):
        raise RuntimeError("pg down")
    monkeypatch.setattr(ht, "get_open_task_payload", _down)
    b = _status()
    assert (b["review_task_id"], b["review_shape"], b["account"]) == (None, None, None)


def test_no_defect_on_record_is_null(monkeypatch):
    install(monkeypatch)
    b = _status()
    assert "extraction_defect" in b and b["extraction_defect"] is None


def test_an_unreadable_defect_store_leaves_the_key_absent(monkeypatch):
    install(monkeypatch)

    def _down(subject_ref, kind):
        raise RuntimeError("pg down")
    monkeypatch.setattr(ht, "latest_task_for_subject", _down)
    assert "extraction_defect" not in _status()


def test_has_parts_on_an_empty_extraction_reads_back_as_a_defect_with_no_row_edits(monkeypatch):
    w = install(monkeypatch)
    as_user(SVC)
    assert stage_review().status_code == 200
    as_user(STEWARD)
    r = client().post(f"/human_tasks/{EMPTY}/act", json={"decision": "has_parts", "page": 3})
    assert r.status_code == 200, r.text
    b = _status()
    assert b["extraction_defect"] == {"task_id": f"extraction-defect:{ID}:empty-a1", "edits": 0}
    assert b["review_task_id"] is None, "the row went back to received"


def _correction(w, task_id, edits):
    w.register_task(kind="extraction_defect", task_id=task_id, audience="dispatch_failure:X",
                    title="t", summary="s", requested_by=STEWARD, subject_ref=ID,
                    payload={"edits": edits})


def test_edits_counts_rows_corrected_added_and_deleted_never_a_header(monkeypatch):
    w = install(monkeypatch)
    _correction(w, "extraction-defect:N-1:d1", [
        {"op": "corrected"}, {"op": "added"}, {"op": "deleted"}, {"op": "deleted"},
        {"op": "header_corrected", "field": "notice_id"}])
    assert _status()["extraction_defect"] == {"task_id": "extraction-defect:N-1:d1", "edits": 4}


def test_the_newest_defect_is_the_one_reported(monkeypatch):
    w = install(monkeypatch)
    _correction(w, "extraction-defect:N-1:d1", [{"op": "added"}])
    _correction(w, "extraction-defect:N-1:d2", [{"op": "added"}, {"op": "corrected"}])
    assert _status()["extraction_defect"] == {"task_id": "extraction-defect:N-1:d2", "edits": 2}


def test_CONTROL_a_defect_about_another_drop_is_not_this_drops(monkeypatch):
    w = install(monkeypatch)
    w.register_task(kind="extraction_defect", task_id="extraction-defect:other:d1",
                    audience="a", title="t", summary="s", requested_by=STEWARD,
                    subject_ref="sha256:" + "f" * 64, payload={"edits": [{"op": "added"}]})
    assert _status()["extraction_defect"] is None


class _Cur:
    def __init__(self, rec):
        self.rec = rec

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.rec.append((" ".join(sql.split()), params))

    def fetchone(self):
        return {"task_id": "T-2", "payload": '{"edits": []}'}


class _Conn:
    def __init__(self, rec):
        self.rec = rec

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, **kw):
        return _Cur(self.rec)


def test_the_lookup_filters_on_subject_AND_kind_and_takes_the_newest(monkeypatch):
    rec = []
    monkeypatch.setattr(ht, "_pg_connect", lambda: _Conn(rec))
    assert ht.latest_task_for_subject(ID, "extraction_defect") == {"task_id": "T-2",
                                                                   "payload": {"edits": []}}
    (sql, params), = rec
    assert "WHERE subject_ref = %s AND kind = %s" in sql
    assert "ORDER BY created_at DESC, task_id DESC LIMIT 1" in sql
    assert params == (ID, "extraction_defect")


def test_the_lookup_asks_nothing_for_a_blank_subject(monkeypatch):
    rec = []
    monkeypatch.setattr(ht, "_pg_connect", lambda: _Conn(rec))
    assert ht.latest_task_for_subject("", "extraction_defect") is None and rec == []
