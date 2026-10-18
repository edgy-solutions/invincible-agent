"""The review card's gate (GET /ingest/{id}/extraction and /source): an outage, and a service.

The architect, 2026-10-17 (gov's Q12 and Q13):

  * Q12 -- "Topaz outage is 503, same as #54 -- a holder of the task is never told not_entitled
    because a dependency is down." A Topaz failure (no connection, a non-2xx, an unreadable body)
    and a task-store failure answer 503, never 403 `not_entitled`. A real Topaz "no" is still 403.
  * Q13 -- "a service reads the source of drops it delegated because the delegate rule already
    grants it (it seeded them), not because it is 'the submitter'; a service holding a review task
    counts for nothing." A service caller is decided by the seeding-delegate rule alone
    (`artifact_reads.is_entitled`: it seeded the row AND it is a declared delegate). It never
    matches as a dropper, and it is never a task holder.

Stubbed only at boundaries the gate does not choose: Topaz's HTTP transport, the task store's
connect, `ingest_status.get_row`, the delegate map (DELEGATE_ON_BEHALF_OF) and the S3 client. So
these arms decide behaviour, not which helper the gate calls.
"""
from __future__ import annotations

import json
import logging

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
psycopg2 = pytest.importorskip("psycopg2")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion  # noqa: E402

HEX = "9d0c0a4b3e8f1d2c6b5a49382716f5e4d3c2b1a09f8e7d6c5b4a392817160504"
ID = "sha256:" + HEX
OTHER_ID = "sha256:" + "0" * 64
PREFIX = f"ingress-user/pdf/{HEX}/"
SRC_KEY = PREFIX + "PCN26-140.pdf"
PDF_BYTES = b"%PDF-1.7\n" + bytes(range(256)) * 8
TOPAZ = "http://topaz.test:8282"
AUDIENCE = "document_promotion:SUSTAINMENT"

DROPPER = "alice@example.com"
HOLDER = "steward@example.com"
STRANGER = "mallory@example.com"
PRINCIPAL = "carol@example.com"
DELEGATE = "svc:openddil"           # a declared delegate (a key of DELEGATE_ON_BEHALF_OF)
OTHER_DELEGATE = "svc:other-seeder"  # also declared; it seeded nothing here
UNDECLARED_SVC = "svc:doc-tools"     # a service that is NOT a declared delegate
DELEGATE_MAP = json.dumps({DELEGATE: [PRINCIPAL], OTHER_DELEGATE: []})


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


class FakeTopaz:
    """Topaz's directory check, behind the real httpx transport. `mode` is "up" (answers
    `can_act` for `holders` on AUDIENCE only), "refused" (no connection), "5xx" or "garbage"."""

    def __init__(self, holders=(), mode="up"):
        self.holders, self.mode, self.calls = set(holders), mode, []

    def handle_request(self, transport, request):
        if not str(request.url).startswith(TOPAZ):  # nothing else is on the network here
            raise httpx.ConnectError("no network in this test", request=request)
        body = json.loads(request.content)
        self.calls.append(body)
        if self.mode == "refused":
            raise httpx.ConnectError("connection refused", request=request)
        if self.mode == "5xx":
            return httpx.Response(503, json={"error": "unavailable"}, request=request)
        if self.mode == "garbage":
            return httpx.Response(200, content=b"<html>proxy error</html>", request=request)
        yes = (body.get("relation") == "can_act" and body.get("object_id") == AUDIENCE
               and body.get("subject_id") in self.holders)
        return httpx.Response(200, json={"check": yes}, request=request)


def _row(**over):
    r = {"id": ID, "status": "review", "kind": "pdf", "content_kind": "pcn", "attempt": 1,
         "object_prefix": PREFIX, "extraction_ref": None, "submitted_by": DROPPER,
         "on_behalf_of": None, "notice_id": "PCN26-140"}
    r.update(over)
    return r


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3({PREFIX + "manifest.json": json.dumps({"object_ref": SRC_KEY}).encode(),
                   SRC_KEY: PDF_BYTES})
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", DELEGATE_MAP)
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", TOPAZ)
    yield
    gateway.app.dependency_overrides.clear()


def _as(who):
    user = type("U", (), {"authz_id": who, "id": who, "sub": who, "email": who, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


def _topaz(monkeypatch, **kw):
    fake = FakeTopaz(**kw)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda self, request: fake.handle_request(self, request))
    return fake


def _task(monkeypatch, state):
    """The task store answers `state` for THIS ingest's promotion task only."""
    monkeypatch.setattr(ht, "get_task_open_state",
                        lambda t: state if t == f"{promotion.KIND}:{ID}" else None)


def _get(path):
    with TestClient(gateway.app) as c:
        return c.get(path)


def _audit(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "iagent.audit.ingest_access"]


OPEN = {"audience": AUDIENCE, "open": True}


# ── Q12: an outage is 503, never not_entitled ────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["extraction", "source"])
def test_topaz_up_decides_and_topaz_down_is_503_never_not_entitled(monkeypatch, s3, caplog, path):
    """Matched: the same holder, the same open task, the same route. Only Topaz's state differs.
    Up and yes -> the holder is in (200 on /source); up and no -> 403; down three ways -> 503."""
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    _task(monkeypatch, OPEN)
    _as(HOLDER)

    topaz = _topaz(monkeypatch, holders={HOLDER})
    r = _get(f"/ingest/{ID}/{path}")
    assert topaz.calls, "the control never reached Topaz, so the outage arms below decide nothing"
    if path == "source":
        assert r.status_code == 200 and r.content == PDF_BYTES
    else:  # no extraction_ref: past the gate, refused by the route itself
        assert (r.status_code, r.json()["detail"]["error"]) == (422, "no_extraction_ref")

    _topaz(monkeypatch, holders=set())
    s3.calls.clear()
    r = _get(f"/ingest/{ID}/{path}")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_entitled"
    assert s3.calls == []

    for mode in ("refused", "5xx", "garbage"):
        topaz = _topaz(monkeypatch, holders={HOLDER}, mode=mode)
        s3.calls.clear()
        caplog.clear()
        r = _get(f"/ingest/{ID}/{path}")
        assert r.status_code == 503, (mode, r.status_code, r.text)
        assert r.json()["detail"]["error"] == "authorization_unavailable", mode
        assert topaz.calls, mode
        assert s3.calls == [], f"{mode}: the store was read on an outage"
        lines = _audit(caplog)
        assert len(lines) == 1 and "decision=deny" in lines[0], (mode, lines)
        assert "reason=authorization_unavailable" in lines[0], (mode, lines)


@pytest.mark.parametrize("path", ["extraction", "source"])
def test_a_task_store_outage_is_503_never_not_entitled(monkeypatch, s3, caplog, path):
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    topaz = _topaz(monkeypatch, holders={HOLDER})
    _as(HOLDER)

    def _down():
        raise psycopg2.OperationalError("could not connect to server")

    monkeypatch.setattr(ht, "_pg_connect", _down)
    r = _get(f"/ingest/{ID}/{path}")
    assert r.status_code == 503, (r.status_code, r.text)
    assert r.json()["detail"]["error"] == "authorization_unavailable"
    assert s3.calls == [] and topaz.calls == []
    lines = _audit(caplog)
    assert len(lines) == 1 and "reason=authorization_unavailable" in lines[0], lines


@pytest.mark.parametrize("path", ["extraction", "source"])
def test_an_unconfigured_task_store_is_the_fleets_existing_503(monkeypatch, s3, path):
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    monkeypatch.setattr(ht, "_PG_DSN", "")
    topaz = _topaz(monkeypatch, holders={HOLDER})
    _as(HOLDER)
    r = _get(f"/ingest/{ID}/{path}")
    assert (r.status_code, r.json()["detail"]["error"]) == (503, "hitl_unconfigured")
    assert s3.calls == [] and topaz.calls == []


def test_no_task_and_a_resolved_task_are_still_not_entitled_and_ask_nobody(monkeypatch, s3):
    """The 503 is for "could not tell". No task, or a resolved one, is a real no: 403, and
    Topaz is not asked (so a Topaz outage cannot turn a real no into a 503)."""
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    _as(HOLDER)
    for state in (None, {"audience": AUDIENCE, "open": False}, {"audience": "", "open": True}):
        _task(monkeypatch, state)
        topaz = _topaz(monkeypatch, holders={HOLDER}, mode="refused")
        r = _get(f"/ingest/{ID}/source")
        assert (r.status_code, r.json()["detail"]["error"]) == (403, "not_entitled"), state
        assert topaz.calls == [], state
        assert s3.calls == []


# ── Q13: a service is decided by the seeding-delegate rule alone ─────────────────────────────

def test_the_seeding_delegate_reads_by_the_delegate_rule_not_as_the_submitter(
        monkeypatch, s3, caplog):
    """A delegated drop records the delegate as `submitted_by` and the person as `on_behalf_of`.
    The delegate reads it -- and the audit says WHY: `seeding_delegate`, never `dropped_by`."""
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    monkeypatch.setattr(ist, "get_row",
                        lambda i: _row(submitted_by=DELEGATE, on_behalf_of=PRINCIPAL))
    topaz = _topaz(monkeypatch)
    for who, reason in ((DELEGATE, "seeding_delegate"), (PRINCIPAL, "dropped_by")):
        _as(who)
        caplog.clear()
        r = _get(f"/ingest/{ID}/source")
        assert r.status_code == 200 and r.content == PDF_BYTES, who
        lines = _audit(caplog)
        assert len(lines) == 1, (who, lines)
        assert f"reason={reason}" in lines[0], (who, lines)
    assert topaz.calls == []


def test_a_service_the_delegate_rule_does_not_grant_reads_nothing(monkeypatch, s3, caplog):
    """Matched against the arm above: a service caller, each time equal to one of the row's two
    dropper fields, and the delegate rule does not grant it. Each is 403 before the store."""
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    topaz = _topaz(monkeypatch)
    cases = [
        # a service that seeded the row but is not a declared delegate
        (UNDECLARED_SVC, _row(submitted_by=UNDECLARED_SVC, on_behalf_of=None)),
        # a declared delegate named as the PERSON on a row another delegate seeded
        (OTHER_DELEGATE, _row(submitted_by=DELEGATE, on_behalf_of=OTHER_DELEGATE)),
        # a declared delegate, on a row a person dropped, named as on_behalf_of
        (DELEGATE, _row(submitted_by=DROPPER, on_behalf_of=DELEGATE)),
        # a declared delegate on a row a different delegate seeded
        (OTHER_DELEGATE, _row(submitted_by=DELEGATE, on_behalf_of=PRINCIPAL)),
    ]
    for path in ("extraction", "source"):
        for who, row in cases:
            monkeypatch.setattr(ist, "get_row", lambda i, row=row: row)
            _as(who)
            s3.calls.clear()
            caplog.clear()
            r = _get(f"/ingest/{ID}/{path}")
            assert (r.status_code, r.json()["detail"]["error"]) == (403, "not_entitled"), \
                (path, who, row["submitted_by"], row["on_behalf_of"])
            assert s3.calls == []
            lines = _audit(caplog)
            assert len(lines) == 1 and "decision=deny" in lines[0], lines
    assert topaz.calls == []


@pytest.mark.parametrize("who", [DELEGATE, UNDECLARED_SVC])
def test_a_service_holding_the_review_task_counts_for_nothing(monkeypatch, s3, who):
    """Matched: the same open task, and Topaz would say yes for both the person and the service.
    The person holder reads; the service gets 403, and Topaz is never asked about it."""
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    _task(monkeypatch, OPEN)
    topaz = _topaz(monkeypatch, holders={HOLDER, who})
    _as(HOLDER)
    assert _get(f"/ingest/{ID}/source").status_code == 200
    assert [c["subject_id"] for c in topaz.calls] == [HOLDER]
    topaz.calls.clear()
    for path in ("extraction", "source"):
        _as(who)
        s3.calls.clear()
        r = _get(f"/ingest/{ID}/{path}")
        assert (r.status_code, r.json()["detail"]["error"]) == (403, "not_entitled"), (path, who)
        assert s3.calls == []
    assert topaz.calls == [], "a service was asked about as a task holder"


def test_a_service_is_not_503_on_an_outage(monkeypatch, s3):
    """A service counts for nothing as a holder, so a Topaz outage cannot change its answer."""
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    _task(monkeypatch, OPEN)
    topaz = _topaz(monkeypatch, holders={DELEGATE}, mode="refused")
    _as(DELEGATE)
    r = _get(f"/ingest/{ID}/source")
    assert (r.status_code, r.json()["detail"]["error"]) == (403, "not_entitled")
    assert topaz.calls == []
