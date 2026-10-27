"""A review's subject lookups run as the ingest's DROPPER — ruling (a), 2026-10-10.

    "(a) service lookups (review composer) run on_behalf_of the task's requesting person — for a
     review that's the dropper/on_behalf_of of the ingest, who can already see it"

Before this, `review_composer.resolve_subject_via_engine_o` POSTed `{"identifier": mpn}` as
svc:engine-a with no person at all, so once engine-o's `/resolve_instance` gates on the caller
(gov's #39), a drop-derived notice resolves for nobody and every such review composes with its
subjects unresolved. The chain is three hops, and each is sealed here on what it SENDS:

  1. the BFF (`/reviews`) DERIVES the dropper from the artifact — review.json's sibling
     `manifest.json` names the `ingest_id`, the ingest's status row names its dropper of record
     (`on_behalf_of`) — and stamps it; a body cannot assert it;
  2. `ReviewStarter.start_review` binds that person into the composer's lookup seam;
  3. the adapter sends it to engine-o as `user_email`, with `entitled_domains` EMPTY — the dropper
     sees their own drop with no domain, and a domains list is never an entitlement.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst import review_composer as composer  # noqa: E402
from agent_fleet.restate_analyst import review_starter as starter  # noqa: E402
from tests.test_review_starter import _FakeContext, _START, _request, _wire  # noqa: E402

DROPPER = "dana@example.com"
DELEGATE = "svc:openddil"          # the authenticated submitter of a delegated drop — NOT the dropper
APPROVER = "qa"                    # _request()'s approver — must never stand in for the dropper
INGEST_ID = "ing-0123456789abcdef"
REVIEW_URI = "s3://processing-artifacts/sustainment/inbound/generated/IPCN25300X/v1/review.json"
MANIFEST_KEY = "sustainment/inbound/generated/IPCN25300X/v1/manifest.json"


# ── hop 3: the adapter's wire ───────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _capture_post(monkeypatch):
    sent: list = []

    def _post(url, json=None, **kw):
        sent.append({"url": url, "json": json})
        return _Resp({"candidates": [{"instance_id": "pcn:IPCN25300X#NSR01L30NXT5G"}]})

    monkeypatch.setattr(composer.requests, "post", _post)
    monkeypatch.setattr(composer, "outbound_auth_headers", lambda **kw: {})
    return sent


def test_the_adapter_sends_the_person_as_the_caller_with_no_domains(monkeypatch):
    sent = _capture_post(monkeypatch)
    assert composer.resolve_subject_via_engine_o("NSR01L30NXT5G", on_behalf_of=DROPPER) \
        == "pcn:IPCN25300X#NSR01L30NXT5G"
    assert sent[0]["url"].endswith("/resolve_instance")
    assert sent[0]["json"] == {"identifier": "NSR01L30NXT5G", "user_email": DROPPER,
                               "entitled_domains": []}


def test_no_person_is_sent_as_blank_never_omitted_and_never_a_domain(monkeypatch):
    sent = _capture_post(monkeypatch)
    composer.resolve_subject_via_engine_o("NSR01L30NXT5G")
    assert sent[0]["json"] == {"identifier": "NSR01L30NXT5G", "user_email": "",
                               "entitled_domains": []}


# ── hop 2: the starter binds the stamped person into the seam ───────────────────────────────


def _record_resolves(monkeypatch):
    _wire(monkeypatch)
    calls: list = []

    def _resolve(mpn, *, on_behalf_of=""):
        calls.append((mpn, on_behalf_of))
        return None

    monkeypatch.setattr(starter, "resolve_subject_via_engine_o", _resolve)
    return calls


@pytest.mark.asyncio
async def test_every_lookup_in_a_composition_runs_as_the_stamped_dropper(monkeypatch):
    calls = _record_resolves(monkeypatch)
    await _START(_FakeContext(), {**_request(), "on_behalf_of": DROPPER})
    assert calls, "the composition resolved no subject — the fixture no longer reaches the seam"
    assert {who for _, who in calls} == {DROPPER}, calls


@pytest.mark.asyncio
async def test_no_stamped_dropper_is_no_person_never_the_approver(monkeypatch):
    calls = _record_resolves(monkeypatch)
    req = _request()
    assert req["approver"] == APPROVER and "on_behalf_of" not in req
    await _START(_FakeContext(), req)
    assert calls
    assert {who for _, who in calls} == {""}, calls


# ── hop 1: the BFF derives the dropper from the artifact ────────────────────────────────────

gateway = pytest.importorskip("src.iagent.gateway")
from src.iagent import ingest_status  # noqa: E402


class _NoSuchKey(Exception):
    def __init__(self):
        super().__init__("An error occurred (NoSuchKey) when calling the GetObject operation")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3:
    def __init__(self, objects=None, boom=None):
        self.objects = objects or {}
        self.boom = boom
        self.asked: list = []

    def get_object(self, Bucket, Key):
        self.asked.append((Bucket, Key))
        if self.boom is not None:
            raise self.boom
        if (Bucket, Key) not in self.objects:
            raise _NoSuchKey()
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


def _manifest(**extra) -> bytes:
    return json.dumps({"doc_id": "IPCN25300X", "pages": [], **extra}).encode()


def _row(**kw):
    # A DELEGATED drop: the submitter and the dropper of record DIFFER, so the fixture
    # distinguishes the column the ruling names (on_behalf_of) from the one it does not.
    return {"id": INGEST_ID, "submitted_by": DELEGATE, "on_behalf_of": DROPPER, **kw}


def _wire_bff(monkeypatch, s3, row=None, row_boom=None):
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: s3)
    asked: list = []

    def _get_row(ingest_id):
        asked.append(ingest_id)
        if row_boom is not None:
            raise row_boom
        return row

    monkeypatch.setattr(ingest_status, "get_row", _get_row)
    return asked


def test_the_dropper_of_record_comes_from_the_sibling_manifests_ingest(monkeypatch):
    s3 = _FakeS3({("processing-artifacts", MANIFEST_KEY): _manifest(ingest_id=INGEST_ID)})
    asked = _wire_bff(monkeypatch, s3, row=_row())
    assert gateway._review_on_behalf_of(REVIEW_URI) == DROPPER
    assert s3.asked == [("processing-artifacts", MANIFEST_KEY)]
    assert asked == [INGEST_ID]


@pytest.mark.parametrize("uri", ["", "processing-artifacts/x/review.json", "s3://bucket-only",
                                 "https://processing-artifacts/x/review.json"])
def test_no_pointer_is_no_person_and_reads_nothing(monkeypatch, uri):
    s3 = _FakeS3()
    asked = _wire_bff(monkeypatch, s3, row=_row())
    assert gateway._review_on_behalf_of(uri) == ""
    assert s3.asked == [] and asked == []


@pytest.mark.parametrize("objects", [
    {},                                                                   # no manifest
    {("processing-artifacts", MANIFEST_KEY): _manifest()},               # manifest, no ingest_id
    {("processing-artifacts", MANIFEST_KEY): _manifest(ingest_id="")},
    {("processing-artifacts", MANIFEST_KEY): b"not json"},
])
def test_an_artifact_with_no_recorded_ingest_is_no_person(monkeypatch, objects):
    asked = _wire_bff(monkeypatch, _FakeS3(objects), row=_row())
    assert gateway._review_on_behalf_of(REVIEW_URI) == ""
    assert asked == []


def test_an_ingest_the_bff_never_recorded_is_no_person(monkeypatch):
    s3 = _FakeS3({("processing-artifacts", MANIFEST_KEY): _manifest(ingest_id=INGEST_ID)})
    asked = _wire_bff(monkeypatch, s3, row=None)
    assert gateway._review_on_behalf_of(REVIEW_URI) == ""
    assert asked == [INGEST_ID]


def test_an_object_store_outage_is_503_not_no_person(monkeypatch):
    _wire_bff(monkeypatch, _FakeS3(boom=ConnectionError("store down")), row=_row())
    with pytest.raises(gateway.HTTPException) as e:
        gateway._review_on_behalf_of(REVIEW_URI)
    assert e.value.status_code == 503
    assert e.value.detail["error"] == "artifact_store_unreachable"


def test_a_status_store_outage_is_503_not_no_person(monkeypatch):
    s3 = _FakeS3({("processing-artifacts", MANIFEST_KEY): _manifest(ingest_id=INGEST_ID)})
    _wire_bff(monkeypatch, s3, row_boom=ConnectionError("pg down"))
    with pytest.raises(gateway.HTTPException) as e:
        gateway._review_on_behalf_of(REVIEW_URI)
    assert e.value.status_code == 503
    assert e.value.detail["error"] == "ingest_status_unreachable"


def test_the_route_forwards_the_derived_dropper_and_drops_an_asserted_one(monkeypatch):
    """The route end to end: a caller that ASSERTS `on_behalf_of` in the body is ignored, and the
    body forwarded to start_review carries the dropper the artifact names."""
    from fastapi.testclient import TestClient

    s3 = _FakeS3({("processing-artifacts", MANIFEST_KEY): _manifest(ingest_id=INGEST_ID)})
    _wire_bff(monkeypatch, s3, row=_row())
    forwarded: dict = {}

    class _Resp200:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "STARTED", "workflow_id": "wf", "count": 1}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, **k):
            forwarded.update(json or {})
            return _Resp200()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    user = type("U", (), {"authz_id": "svc:review-starter", "id": "svc:review-starter",
                          "sub": "svc:review-starter", "email": None, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    try:
        r = TestClient(gateway.app).post("/reviews", json={
            "notice_id": "IPCN25300X", "impacted_parts": [], "artifact_uri": REVIEW_URI,
            "on_behalf_of": "mallory@example.com"})
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert forwarded["on_behalf_of"] == DROPPER
    assert forwarded["approver"] == "svc:review-starter"
