"""A review finds its evidence by its OWN source reference (finding 13, point 2; lane 74, item 4).

The ruling, in its words: "the evidence lookup resolves from the review's own source reference,
never a fixed prefix."

THE CAUSE. The review card's evidence came from `GET /notices/{id}/provenance`, which turns a notice
id into an artifact prefix by scanning ONE fixed root (`REVIEW_WATCH_PREFIX`). A review started from
a user drop keeps its review.json under another root, so its evidence was always empty. Yet every
STARTED review already held its exact source: `artifact_uri` (`s3://<bucket>/<prefix>/review.json`),
which `start_review` refuses to start without. It was never persisted. Now the starter carries it,
the grouped step keeps it, `get_batch` serves it, and `GET /reviews/{wf}/provenance` resolves the
evidence from it.

Arms:
  A1  the starter carries `artifact_uri` on its workflow_send arg
  A2  the grouped step persists it and get_batch serves it; legacy state serves ""
  A3  `_review_source_prefix` table
  A4  the route reads the review's own bucket and prefix and never touches the scan
  A5  an unreadable reference does not fall back to the scan
  A6  a review with no reference falls back to the scan, labelled
  A7  the gate: a caller without the task gets 404 and get_batch is not called
  A8  the bucket parameter reaches every read in the store reader
  A9  no uri, bucket or prefix in the log

NO workflow, kind, domain or person name is in the code under test; the strings here are fixtures.

Run: uv run pytest tests/test_a_review_finds_its_evidence_by_its_own_source.py -v
"""
from __future__ import annotations

import json
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("restate")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from tests.test_review_starter import (  # noqa: E402
    _START, _ARTIFACT_URI, _FakeContext, _request as _starter_request, _wire as _starter_wire,
)
from tests.test_steward_correction import _Ctx, _request as _step_request, _step  # noqa: E402

import dispatch_driver  # noqa: E402
import grouped_review_workflow as grw  # noqa: E402
import main as ra_main  # noqa: E402

_GET_BATCH = grw.get_batch.__wrapped__

# A root that is NOT the fixed scan root, and a bucket that is NOT the default one.
OWN_BUCKET = "bucket-own"
OWN_PREFIX = "drops/elsewhere/generated/DOC-1"
OWN_URI = f"s3://{OWN_BUCKET}/{OWN_PREFIX}/review.json"
WF = "wf-own-source"


# ── A1 ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_starter_carries_the_artifact_uri(monkeypatch):
    _starter_wire(monkeypatch)
    ctx = _FakeContext()
    out = await _START(ctx, _starter_request())
    assert out["status"] == "STARTED"
    assert len(ctx.sends) == 1
    assert ctx.sends[0]["arg"]["artifact_uri"] == _ARTIFACT_URI


# ── A2 ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_grouped_step_persists_it_and_get_batch_serves_it(monkeypatch):
    monkeypatch.setattr(dispatch_driver, "_mint_dispatch_task", lambda task: {"ok": True})
    ctx = _Ctx({"verdict": "rejected", "reason_code": "not_a_notice", "acted_by": "x@example.com",
                "overrides": {}})
    await ra_main._run_grouped_human_await(
        ctx, "wf-1", _step(), "decision", _step_request(artifact_uri=OWN_URI), {}, "")
    assert ctx.state["artifact_uri"] == OWN_URI
    out = await _GET_BATCH(ctx)
    assert out["artifact_uri"] == OWN_URI


@pytest.mark.asyncio
async def test_legacy_state_without_the_reference_serves_blank():
    state = {"batch_items": [], "approver": "a@example.com", "notice_fingerprint": "N1",
             "notice_id": "N1", "doc_type": "PCN"}
    out = await _GET_BATCH(_Ctx(None, state=state))
    assert out["artifact_uri"] == ""


# ── A3 ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("uri,expected", [
    (OWN_URI, (OWN_BUCKET, OWN_PREFIX)),
    ("s3://b/one/review.json", ("b", "one")),
    ("", None),
    (None, None),
    ("http://host/bucket/a/review.json", None),
    ("s3://bucket", None),
    ("s3://bucket/", None),
    ("s3://bucket/a/manifest.json", None),
    ("s3://bucket/a/review.json.bak", None),
    ("s3://bucket/review.json", None),
    ("s3:///a/review.json", None),
])
def test_review_source_prefix_table(uri, expected):
    assert gateway._review_source_prefix(uri) == expected


# ── the route harness ───────────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, body):
        self._b = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._b


@pytest.fixture
def route(monkeypatch):
    """The route with a pending queue, a fake get_batch, and a scan that explodes if touched."""
    st = {"rows": [{"workflow_id": WF, "kind": "grouped_review", "task_id": "t1"}],
          "batch": {"notice_id": "N-1", "artifact_uri": OWN_URI, "items": []},
          "batch_calls": 0, "scan_calls": [], "reads": []}

    async def _pending(user, authz_id, route_name):
        return st["rows"]

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, **k):
            st["batch_calls"] += 1
            return _Resp(st["batch"])

    def _scan(*a, **k):
        st["scan_calls"].append(a)
        raise AssertionError("the fixed-root scan was used")

    def _read(prefix, **kw):
        st["reads"].append((prefix, kw))
        return [{"mpn": "X"}]

    monkeypatch.setattr(gateway, "_pending_for_actor", _pending)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(gateway, "_build_notice_prefix_index", _scan)
    monkeypatch.setattr(gateway, "_resolve_notice_prefix", _scan)
    monkeypatch.setattr(gateway, "_read_notice_provenance_from_store", _read)
    user = type("U", (), {"authz_id": "a@example.com", "id": "a@example.com", "sub": "a@example.com",
                          "email": None, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    yield st
    gateway.app.dependency_overrides.clear()


def _get():
    return TestClient(gateway.app).get(f"/reviews/{WF}/provenance")


# ── A4 ──────────────────────────────────────────────────────────────────────────────────────────
def test_the_route_resolves_from_the_review_source_never_the_scan(route):
    assert not OWN_PREFIX.startswith(gateway._NOTICE_SCAN_ROOT), "fixture must sit off the scan root"
    r = _get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resolved_by"] == "review_source"
    assert body["source"] == "doc-tools"
    assert body["notice_id"] == "N-1"
    assert body["items"] == [{"mpn": "X"}]
    assert route["reads"] == [(OWN_PREFIX, {"bucket": OWN_BUCKET})]
    assert route["scan_calls"] == []


# ── A5 ──────────────────────────────────────────────────────────────────────────────────────────
def test_an_unreadable_reference_does_not_fall_back_to_the_scan(route):
    route["batch"] = {"notice_id": "N-1", "artifact_uri": "not-a-uri", "items": []}
    r = _get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resolved_by"] == "review_source_unreadable"
    assert body["items"] == [] and body["source"] == "none"
    assert route["scan_calls"] == [] and route["reads"] == []


# ── A6 ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_review_with_no_reference_falls_back_and_says_so(route, monkeypatch):
    route["batch"] = {"notice_id": "N-LEGACY", "items": []}
    seen = []

    def _resolve(notice_id):
        seen.append(notice_id)
        return "legacy/prefix"

    monkeypatch.setattr(gateway, "_resolve_notice_prefix", _resolve)
    r = _get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen == ["N-LEGACY"]
    assert body["resolved_by"] == "notice_id_index"
    assert route["reads"] == [("legacy/prefix", {})]

    monkeypatch.setattr(gateway, "_resolve_notice_prefix", lambda n: None)   # a miss
    body = _get().json()
    assert body["items"] == [] and body["source"] == "none"
    assert body["resolved_by"] == "notice_id_index"


def test_a_store_error_is_an_honest_empty(route, monkeypatch):
    def _boom(prefix, **kw):
        raise ConnectionError("store down")
    monkeypatch.setattr(gateway, "_read_notice_provenance_from_store", _boom)
    body = _get().json()
    assert body["items"] == [] and body["source"] == "error"


# ── A7 ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rows", [
    [],
    [{"workflow_id": "someone-else", "kind": "grouped_review", "task_id": "t9"}],
    [{"workflow_id": WF, "kind": "another_kind", "task_id": "t9"}],
])
def test_the_gate_a_caller_without_the_task_gets_404_and_nothing_is_read(route, rows):
    route["rows"] = rows
    r = _get()
    assert r.status_code == 404
    assert r.json()["detail"] == {"error": "review_not_found"}
    assert route["batch_calls"] == 0
    assert route["reads"] == [] and route["scan_calls"] == []


# ── A8 ──────────────────────────────────────────────────────────────────────────────────────────
def test_the_bucket_parameter_reaches_every_read(monkeypatch):
    import boto3

    calls = []

    class _Body:
        def __init__(self, v): self._v = v
        def read(self): return json.dumps(self._v).encode()

    class _S3:
        def get_object(self, Bucket, Key):
            calls.append((Bucket, Key))
            name = Key.rsplit("/", 1)[-1]
            return {"Body": _Body({"review.json": {"review_items": []},
                                   "manifest.json": {}, "text.json": []}[name])}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _S3())
    assert gateway._read_notice_provenance_from_store("p/q", bucket="b2") == []
    assert len(calls) == 3
    assert {b for b, _ in calls} == {"b2"}
    calls.clear()
    gateway._read_notice_provenance_from_store("p/q")      # existing callers unchanged
    assert {b for b, _ in calls} == {gateway._ARTIFACT_BUCKET}


# ── A9 ──────────────────────────────────────────────────────────────────────────────────────────
def test_no_uri_bucket_or_prefix_in_the_log(route, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    _get()
    def _boom(prefix, **kw):
        raise ConnectionError(f"s3://{OWN_BUCKET}/{OWN_PREFIX}")
    monkeypatch.setattr(gateway, "_read_notice_provenance_from_store", _boom)
    _get()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert WF in text and "review_source" in text, "the route must log the workflow id and how it resolved"
    for secret in (OWN_URI, OWN_BUCKET, OWN_PREFIX):
        assert secret not in text
