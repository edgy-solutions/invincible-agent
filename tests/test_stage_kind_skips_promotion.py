"""The stage route files NO document_promotion task for an `s1000d-data-module` (architect ruling
2026-10-17, on 7f's ruling 1): an s1000d data module has no PCN/PDN card to vet.

A user's drop goes to `awaiting_origin`; a delegate's drop goes to `promoted`. The CONTROL is the
same fixture differing only in `content_kind` (`pcn`): it files a task and moves to `review`, so
arms 1-2 test the branch and not a fixture that never files.

Run: uv run --frozen pytest tests/test_stage_kind_skips_promotion.py -v
"""
from __future__ import annotations

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
