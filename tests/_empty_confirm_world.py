"""A hand-built world for the `document_empty_confirm` tests (spec 208): an in-memory ingest row and
task store behind the same seams the other gateway tests patch. Not a test module."""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

HEX = "e" * 64
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
REF = f"{PREFIX}generated/doc_pdf/doc-tools@61f74dc/manifest.json"
DROPPER = "alice@example.com"
STEWARD = "bob@example.com"
OUTSIDER = "mallory@example.com"
SVC = "svc:doc-tools"


def review_doc(*, n_tables=0, no_col=0, emitted=0, reasons=("no_parts_found",), rows=0):
    """review.json as the extraction writes it: TOP-LEVEL `stats` and `review_reasons`."""
    items = [{"field_path": f"parts[{i}].affected_mpn", "value": "X"} for i in range(rows)]
    return {"review_items": items, "review_reasons": list(reasons),
            "stats": {"n_tables": n_tables, "grid_no_parts_col": no_col,
                      "grid_rows_emitted": emitted}}


class World:
    def __init__(self, kind="pcn"):
        self.row = {"id": ID, "status": "extracting", "kind": "pdf", "content_kind": kind,
                    "submitted_by": DROPPER, "on_behalf_of": None, "object_prefix": PREFIX,
                    "extraction_ref": None, "attempt": 1, "force_text_fallback": False,
                    "review_generation": 0}
        self.writes = []
        self.tasks = {}          # task_id -> {"kw": register kwargs, "open": bool, "decision": ...}
        self.review = review_doc()
        self.stewards = {STEWARD}

    # ingest_status seams
    def get_row(self, ingest_id):
        return self.row if ingest_id == ID else None

    def update_status(self, ingest_id, status, **kw):
        self.writes.append((status, kw))
        self.row["status"] = status
        if kw.get("detail") is not None:
            self.row["detail"] = kw["detail"]

    def relaunch(self, ingest_id, *, expect_attempt, now_ms=None):
        r = self.row
        if r["status"] != "review" or r["attempt"] != expect_attempt:
            return None
        r.update(status="received", force_text_fallback=True, attempt=r["attempt"] + 1)
        return r["attempt"]

    def pending_retries(self, *, limit):
        r = self.row
        if r["status"] == "received" and r["attempt"] > 1:
            return [{**r, "run_id": None, "updated_at": 1, "sha256": HEX, "retry_reason": "text_fallback"}]
        return []

    # human_tasks seams
    def task_exists(self, task_id):
        return task_id in self.tasks

    def register_task(self, **kw):
        self.tasks[kw["task_id"]] = {"kw": kw, "open": True, "decision": None}
        return {}

    def open_payload(self, task_id):
        t = self.tasks.get(task_id)
        return dict(t["kw"]["payload"]) if t and t["open"] else None

    def open_state(self, task_id):
        t = self.tasks.get(task_id)
        return {"audience": t["kw"]["audience"], "open": t["open"]} if t else None

    def resolve(self, task_id, *, caller_id, decision, comment=""):
        t = self.tasks[task_id]
        t["open"], t["decision"], t["by"] = False, decision, caller_id
        return 1

    def list_tasks_for(self, actor, status="pending"):
        if actor not in self.stewards:
            return []
        return [{"task_id": k, "audience": t["kw"]["audience"], "kind": t["kw"]["kind"],
                 "payload": t["kw"]["payload"], "case_id": None, "workflow_id": None}
                for k, t in self.tasks.items() if t["open"]]

    def can_act(self, audience, actor):
        return actor in self.stewards

    def empty_tasks(self):
        return {k: v for k, v in self.tasks.items() if v["kw"]["kind"] == "document_empty_confirm"}


def install(monkeypatch, kind="pcn"):
    w = World(kind)
    monkeypatch.setattr(ist, "get_row", w.get_row)
    monkeypatch.setattr(ist, "update_status", w.update_status)
    monkeypatch.setattr(ist, "relaunch_with_text_fallback", w.relaunch)
    monkeypatch.setattr(ist, "list_pending_retries", w.pending_retries)
    monkeypatch.setattr(ist, "get_status_unscoped", w.get_row)
    reg = type("Reg", (), {"domain": "SUSTAINMENT"})()
    monkeypatch.setattr(ck, "by_kind", lambda k: reg)
    monkeypatch.setattr(ht, "task_exists", w.task_exists)
    monkeypatch.setattr(ht, "register_task", w.register_task)
    monkeypatch.setattr(ht, "get_open_task_payload", w.open_payload)
    monkeypatch.setattr(ht, "get_task_open_state", w.open_state)
    monkeypatch.setattr(ht, "mark_task_resolved", w.resolve)
    monkeypatch.setattr(ht, "list_tasks_for", w.list_tasks_for)
    monkeypatch.setattr(ht, "check_can_act", w.can_act)
    monkeypatch.setattr(ht, "get_task_resolution", lambda *a, **k: None)
    monkeypatch.setattr(ht, "can_act_or_unavailable", w.can_act)
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: {})
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: w.review)
    monkeypatch.setattr(gateway, "_audit_ingest_access", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_DOC_TOOLS_SERVICE_AUTHZ_ID", SVC)
    return w


def as_user(authz):
    u = type("U", (), {"authz_id": authz, "id": authz, "sub": authz, "email": None,
                       "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: u


def client():
    return TestClient(gateway.app)


def stage_review(**extra):
    return client().post(f"/ingest/{ID}/stage",
                         json={"stage": "review", "extraction_ref": REF, **extra})
