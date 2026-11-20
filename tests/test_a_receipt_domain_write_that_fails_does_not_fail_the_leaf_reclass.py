"""Gov's must-fix on #407, through the ROUTE: a leaf re-class at review files the g+1 task with the
REAL filer. The receipt-domain write after that filing is best effort, so when it fails (the write
AND its repair) the re-class still answers as done: the row moved, the old task superseded, the
answer names the g+1 task. The same request retried files nothing new: exactly one open g+1 task.

Control: nothing failing. The helper-level seals are in
tests/routing/test_the_receipt_carries_its_domain_so_the_scope_sits_in_the_query.py."""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: F401,E402
from tests.test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it import (  # noqa: E402,F401
    ALICE, ID, PREFIX, REF, _as, _leaf, db,
)

pytestmark = pytest.mark.usefixtures("can_drop_open")

# the REAL filer, taken before any fixture replaces it with a double
_REAL_FILER = gateway._file_or_find_document_promotion_task
G0 = f"document_promotion:{ID}"
G1 = f"document_promotion:{ID}:g1"


def _real_filer(db, monkeypatch):
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _REAL_FILER)
    monkeypatch.setattr(ht, "task_exists",
                        lambda task_id: any(k["task_id"] == task_id for k in db.registered))
    monkeypatch.setattr(ht, "get_open_task_payload", lambda task_id: None)
    monkeypatch.setattr(ht, "latest_task_for_subject", lambda subject_ref, kind: None)
    monkeypatch.setattr(ht, "check_can_view_program", lambda program, who: False)
    manifest = {"doc_id": "N-1", "filename": "doc.pdf", "source_key": PREFIX + "doc.pdf",
                "pipeline_version": "doc-tools@61f74dc", "ingest_id": ID,
                "provenance": {"standing": "supervised", "ingest_id": ID}}
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: manifest)
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {
        "review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}]})


def _review(db):
    return db.add(status="review", content_kind="pcn", leaf_source="title", extraction_ref=REF,
                  detail="d", extracted_count=3)


def _store_down(monkeypatch, *, times):
    calls = {"n": 0}

    def down(*a, **k):
        calls["n"] += 1
        if calls["n"] <= times:
            raise RuntimeError("db down")
        return True

    monkeypatch.setattr(ist, "set_domain", down)
    monkeypatch.setattr(ist, "clear_domain", down)
    return calls


_ALL_FAIL = gateway._RECEIPT_DOMAIN_ATTEMPTS + 1


def test_a_failed_post_filing_write_still_reclasses_and_the_retry_files_nothing_more(db, monkeypatch):
    _real_filer(db, monkeypatch)
    _review(db)
    calls = _store_down(monkeypatch, times=_ALL_FAIL)

    first = _leaf(_as(ALICE), "pdn")
    assert first.status_code == 200, first.text                    # not a 503 after a filed task
    b = first.json()
    assert b["task_id"] == G1 and b["superseded_task_id"] == G0
    assert calls["n"] == _ALL_FAIL                                  # the failure really happened
    assert [k["task_id"] for k in db.registered] == [G1]
    assert db.superseded == [G0]
    assert db.rows[ID]["content_kind"] == "pdn" and db.rows[ID]["review_generation"] == 1

    again = _leaf(_as(ALICE), "pdn")                                # the SAME request, retried
    assert again.status_code == 200, again.text                     # a no-op: the leaf is already pdn
    assert again.json()["stage"] == "review" and again.json()["leaf"] == "pdn"
    assert [k["task_id"] for k in db.registered] == [G1]            # exactly one open g1 task
    assert db.rows[ID]["review_generation"] == 1 and db.superseded == [G0]


def test_control_nothing_failing_files_the_same_single_g1_task(db, monkeypatch):
    _real_filer(db, monkeypatch)
    _review(db)
    calls = _store_down(monkeypatch, times=0)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == G1 and r.json()["superseded_task_id"] == G0
    assert calls["n"] == 1                                          # one clean write, no repair
    assert [k["task_id"] for k in db.registered] == [G1]
