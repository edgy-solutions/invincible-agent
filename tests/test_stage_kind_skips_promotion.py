"""The stage route files NO document_promotion task for an `s1000d-data-module` (architect ruling
2026-10-17, on 7f's ruling 1): an s1000d data module has no PCN/PDN card to vet.

A user's drop goes to `awaiting_origin`; a delegate's drop goes to `promoted`. The CONTROL is the
same fixture differing only in `content_kind` (`pcn`): it files a task and moves to `review`, so
arms 1-2 test the branch and not a fixture that never files.

Run: uv run --frozen pytest tests/test_stage_kind_skips_promotion.py -v
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_HEX = "c" * 64
_ID = "sha256:" + _HEX
_PREFIX = f"ingress-user/xml/{_HEX}/"
_REF = f"{_PREFIX}generated/doc_xml/doc-tools@61f74dc/manifest.json"
ALICE = "alice@example.com"
DELEGATE = "svc:seeder"
_REAL_FILE_PROMOTION_IF_READY = gateway._file_promotion_if_ready  # before _world() stubs it


class World:
    def __init__(self, kind, dropper):
        self.row = {"id": _ID, "status": "extracting", "kind": "xml", "content_kind": kind,
                    "submitted_by": dropper, "on_behalf_of": None, "object_prefix": _PREFIX,
                    "extraction_ref": None}
        self.moves = []
        self.filed = []

    def get_row(self, ingest_id):
        return self.row if ingest_id == _ID else None

    def update_status(self, ingest_id, status, **kw):
        self.moves.append(status)
        self.row["status"] = status

    async def file_task(self, ingest_id, row, **kw):
        self.filed.append(row.get("content_kind"))
        return "T-1", "FILED"


def _world(monkeypatch, kind, dropper=ALICE):
    w = World(kind, dropper)
    monkeypatch.setattr(ist, "get_row", w.get_row)
    monkeypatch.setattr(ist, "update_status", w.update_status)
    reg = type("Reg", (), {"domain": "SUSTAINMENT"})()
    monkeypatch.setattr(ck, "by_kind", lambda k: reg)
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", w.file_task)
    # the zero-row gate reads the extraction at REVIEW entry (architect ruling 2026-10-17); one part row
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: {})
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {
        "review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}]})

    async def _no_file(*a, **kw):
        raise AssertionError("_file_promotion_if_ready must not run on the skipped-kind branch")

    monkeypatch.setattr(gateway, "_file_promotion_if_ready", _no_file)
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps({DELEGATE: [ALICE]}))
    user = type("U", (), {"authz_id": "svc:doc-tools", "id": "svc:doc-tools",
                          "sub": "svc:doc-tools", "email": None, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return w


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    gateway.app.dependency_overrides.clear()


def _stage_review():
    return TestClient(gateway.app).post(f"/ingest/{_ID}/stage",
                                        json={"stage": "review", "extraction_ref": _REF})


def test_a_user_drop_of_an_s1000d_data_module_awaits_origin_and_files_no_task(monkeypatch):
    w = _world(monkeypatch, "s1000d-data-module")
    r = _stage_review()
    assert r.status_code == 200, r.text
    assert r.json() == {"ingest_id": _ID, "stage": "awaiting_origin", "task_id": None,
                        "task_status": "NO_TASK_KIND_SKIPS_PROMOTION"}
    assert w.moves == ["awaiting_origin"] and w.filed == []


def test_a_delegate_drop_of_an_s1000d_data_module_is_promoted_and_files_no_task(monkeypatch):
    w = _world(monkeypatch, "s1000d-data-module", dropper=DELEGATE)
    r = _stage_review()
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "promoted" and r.json()["task_id"] is None
    assert r.json()["task_status"] == "NO_TASK_KIND_SKIPS_PROMOTION"
    assert w.moves == ["promoted"] and w.filed == []


def test_CONTROL_the_same_fixture_with_a_pcn_files_a_task_and_moves_to_review(monkeypatch):
    w = _world(monkeypatch, "pcn")
    r = _stage_review()
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == "T-1" and r.json()["task_status"] == "FILED"
    assert w.filed == ["pcn"] and w.moves == ["review"]


# -- the later exit: a steward's accepted origin on a row at `awaiting_origin` -------------------
# Same ruling, one step later: an s1000d row records the origin and goes `promoted` with no task.
# (a) and (b) differ ONLY in `content_kind`.

def _exit_from_awaiting_origin(monkeypatch, kind):
    w = _world(monkeypatch, kind)
    w.row["status"] = "awaiting_origin"
    monkeypatch.setattr(gateway, "_read_accepted_origin",
                        lambda i: {"owner_domain": "SUSTAINMENT", "program": None,
                                   "resolved_by": "steward"})
    out = asyncio.run(_REAL_FILE_PROMOTION_IF_READY(_ID, requested_by="svc:case-runner"))
    return w, out


def test_a_steward_origin_on_an_awaiting_s1000d_row_promotes_it_and_files_no_task(monkeypatch):
    w, out = _exit_from_awaiting_origin(monkeypatch, "s1000d-data-module")
    assert w.moves == ["promoted"], w.moves
    assert w.filed == [], w.filed
    assert out["task_id"] is None and out["task_status"] == "NO_TASK_KIND_SKIPS_PROMOTION"
    assert not out["filed"]


def test_CONTROL_a_steward_origin_on_an_awaiting_pcn_row_files_the_task_as_before(monkeypatch):
    w, out = _exit_from_awaiting_origin(monkeypatch, "pcn")
    assert w.filed == ["pcn"], w.filed
    assert w.moves == ["review"], w.moves
    assert out["filed"] is True and out["task_id"] == "T-1"


# -- the retry route's view of the same exit ------------------------------------------------------
# POST /ingest/{id}/retry on a row at `awaiting_origin` re-files through `_file_promotion_if_ready`;
# an s1000d row is promoted by it, so the route answers 200 `promoted`, not a 503.

def _retry_awaiting_origin(monkeypatch, kind):
    w = _world(monkeypatch, kind)
    w.row["status"] = "awaiting_origin"
    monkeypatch.setattr(gateway, "_file_promotion_if_ready", _REAL_FILE_PROMOTION_IF_READY)
    monkeypatch.setattr(gateway, "_read_accepted_origin",
                        lambda i: {"owner_domain": "SUSTAINMENT", "program": None,
                                   "resolved_by": "steward"})
    monkeypatch.setattr(ist, "get_status_for", lambda i, caller_id=None: dict(w.row))
    person = type("U", (), {"authz_id": ALICE, "id": ALICE, "sub": ALICE, "email": ALICE,
                            "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: person
    return w, TestClient(gateway.app).post(f"/ingest/{_ID}/retry")


def test_a_retry_on_an_awaiting_s1000d_row_answers_promoted_and_files_no_task(monkeypatch):
    w, r = _retry_awaiting_origin(monkeypatch, "s1000d-data-module")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["stage"] == "promoted", b
    assert b["task_id"] is None and b["task_status"] == "NO_TASK_KIND_SKIPS_PROMOTION", b
    assert w.filed == [] and w.moves == ["promoted"]


def test_CONTROL_a_retry_on_an_awaiting_pcn_row_returns_the_filed_task_shape(monkeypatch):
    w, r = _retry_awaiting_origin(monkeypatch, "pcn")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["stage"] == "review" and b["task_id"] == "T-1" and b["task_status"] == "FILED", b
    assert w.filed == ["pcn"]
