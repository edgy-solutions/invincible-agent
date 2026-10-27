"""The ingest door reads doc-tools' published processable kinds, behind a flag that ships OFF.

Owner ruling: doc-tools PUTs its list to PUT /ingest/processable-kinds (svc:doc-tools only); the
BFF persists + caches; the door reads the cache. Flag INGEST_DOOR_READS_PROCESSABLE_KINDS default
OFF (store never touched). ON is deny-by-default: 503 processable_kinds_unknown before the first
publish, 400 kind_unprocessable after. No Postgres: the store functions are stubbed.
"""
from __future__ import annotations

import datetime
import types

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import processable_kinds as pk  # noqa: E402

FLAG = "INGEST_DOOR_READS_PROCESSABLE_KINDS"
_NOW = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)


def _reg(kind, branch="document", domain="maintenance"):
    return types.SimpleNamespace(kind=kind, branch=branch, domain=domain, seeds_workflow=None,
                                 identity_field=None)


_REGISTRY = (_reg("work-instruction"), _reg("pdf", domain=None), _reg("zeta-note"),
             _reg("maintenance-fault-event", branch="event"))


def _user(authz_id):
    return type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()


def _client_for(authz_id):
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz_id)
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def client():
    yield from _client_for("alice@example.com")


@pytest.fixture
def doc_tools():
    yield from _client_for("svc:doc-tools")


#: A stand-in for what a real psycopg2 error names: the database host. It must never reach a body.
_DRIVER_HOST = "pg-host.example.invalid"


@pytest.fixture
def rig(monkeypatch):
    """Fixed registry, write doubles, a stubbed store with spies, and a clean cache."""
    s3: list = []
    looked: list = []
    recorded: list = []
    loads: list = []
    publishes: list = []
    store = {"value": None, "boom": False, "publish_boom": False}

    class _S3:
        def put_object(self, **kw):
            s3.append(kw)

    def _load():
        loads.append(1)
        if store["boom"]:
            raise RuntimeError(f"pg down at {_DRIVER_HOST}")
        return store["value"]

    def _publish(kinds, source, published_by):
        if store["publish_boom"]:
            raise RuntimeError(f"pg down at {_DRIVER_HOST}")
        publishes.append((list(kinds), source, published_by))
        store["value"] = (tuple(kinds), _NOW)
        return _NOW

    monkeypatch.setattr(ck, "registrations", lambda: _REGISTRY)
    monkeypatch.setattr(ck, "by_kind",
                        lambda k: next((r for r in _REGISTRY if r.kind == k), None) if k else None)
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _S3())
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: looked.append(sha))
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: recorded.append(kw) or {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(pk, "load", _load)
    monkeypatch.setattr(pk, "publish", _publish)
    monkeypatch.setenv("PROCESSABLE_KINDS_CACHE_SECONDS", "30")
    monkeypatch.delenv(FLAG, raising=False)
    pk.reset_cache()
    yield types.SimpleNamespace(s3=s3, looked=looked, recorded=recorded, loads=loads,
                                publishes=publishes, store=store)
    pk.reset_cache()


def _drop(client, kind="work-instruction"):
    return client.post("/ingest", files={"file": ("f.pdf", b"%PDF-1.4 door bytes", "application/pdf")},
                       data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                             "content_kind": kind})


def _nothing_written(rig):
    assert rig.s3 == [] and rig.looked == [] and rig.recorded == []


def _passed_the_kind_gate(r):
    d = r.json().get("detail") if r.status_code >= 400 else None
    err = d.get("error") if isinstance(d, dict) else None
    return err not in ("processable_kinds_unknown", "kind_unprocessable", "kind_unregistered",
                       "content_kind_required")


# ---------------------------------------------------------------- flag OFF

@pytest.mark.parametrize("flag", [None, "false", "0", ""])
def test_flag_off_registered_kind_passes_and_the_store_is_never_read(client, rig, monkeypatch, flag):
    if flag is not None:
        monkeypatch.setenv(FLAG, flag)
    rig.store["value"] = (("pdf",), _NOW)  # a published set that lacks the kind
    def _spy_current():
        raise AssertionError("the cache/store must not be read with the flag off")
    monkeypatch.setattr(pk, "current", _spy_current)
    r = _drop(client, "work-instruction")
    assert _passed_the_kind_gate(r), r.text
    assert rig.loads == []


# ---------------------------------------------------------------- flag ON

def test_flag_on_never_published_is_503_and_writes_nothing(client, rig, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    r = _drop(client)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "processable_kinds_unknown"
    _nothing_written(rig)


def test_flag_on_kind_absent_from_published_set_is_400_and_writes_nothing(client, rig, monkeypatch):
    monkeypatch.setenv(FLAG, "ON")
    rig.store["value"] = (("pdf", "zeta-note"), _NOW)
    r = _drop(client, "work-instruction")
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["error"] == "kind_unprocessable"
    assert d["processable"] == ["pdf", "zeta-note"]
    _nothing_written(rig)


def test_flag_on_kind_in_published_set_passes(client, rig, monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    rig.store["value"] = (("work-instruction", "pdf"), _NOW)
    r = _drop(client, "work-instruction")
    assert _passed_the_kind_gate(r), r.text


def test_flag_on_unregistered_kind_is_still_kind_unregistered(client, rig, monkeypatch):
    monkeypatch.setenv(FLAG, "yes")
    rig.store["value"] = (("nope",), _NOW)
    r = _drop(client, "nope")
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "kind_unregistered"
    assert rig.loads == []  # the registry check stays first
    _nothing_written(rig)


# ---------------------------------------------------------------- PUT

def test_put_by_a_non_doc_tools_caller_is_403(client, rig):
    r = client.put("/ingest/processable-kinds", json={"kinds": ["pdf"]})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "not_doc_tools"
    assert rig.publishes == []


def test_put_with_an_empty_service_identity_denies_doc_tools_too(doc_tools, rig, monkeypatch):
    monkeypatch.setattr(gateway, "_DOC_TOOLS_SERVICE_AUTHZ_ID", "")
    r = doc_tools.put("/ingest/processable-kinds", json={"kinds": ["pdf"]})
    assert r.status_code == 403, r.text
    assert rig.publishes == []


def test_put_persists_sorted_deduped_kinds_and_the_door_then_reads_the_cache(
        doc_tools, rig, monkeypatch):
    r = doc_tools.put("/ingest/processable-kinds",
                      json={"kinds": [" zeta-note", "pdf", "pdf", "mystery"], "source": "dt-1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kinds"] == ["mystery", "pdf", "zeta-note"]
    assert body["unregistered"] == ["mystery"]
    assert body["published_at"] == _NOW.isoformat()
    assert rig.publishes == [(["mystery", "pdf", "zeta-note"], "dt-1", "svc:doc-tools")]
    # the next flagged door read is served from the cache: no store load
    monkeypatch.setenv(FLAG, "true")
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user("alice@example.com")
    r2 = _drop(doc_tools, "zeta-note")
    assert _passed_the_kind_gate(r2), r2.text
    r3 = _drop(doc_tools, "work-instruction")
    assert r3.status_code == 400 and r3.json()["detail"]["error"] == "kind_unprocessable"
    assert rig.loads == []


@pytest.mark.parametrize("payload", [
    {"kinds": []},
    {"kinds": [f"k{i}" for i in range(513)]},
    {"kinds": ["pdf", "   "]},
    {"kinds": ["x" * 129]},
    {"kinds": ["a/b"]},
    {"kinds": ["pdf"], "source": "s" * 201},
    {},
])
def test_put_422_cases(doc_tools, rig, payload):
    r = doc_tools.put("/ingest/processable-kinds", json=payload)
    assert r.status_code == 422, r.text
    assert rig.publishes == []


# ---------------------------------------------------------------- store unreachable

def test_put_store_unreachable_is_503(doc_tools, rig):
    rig.store["publish_boom"] = True
    r = doc_tools.put("/ingest/processable-kinds", json={"kinds": ["pdf"]})
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "processable_kinds_store_unreachable"
    assert _DRIVER_HOST not in r.text, "the driver's text (it can name the db host) reached the caller"


def test_door_store_unreachable_with_nothing_cached_is_503(client, rig, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    rig.store["boom"] = True
    r = _drop(client)
    assert r.status_code == 503, r.text
    d = r.json()["detail"]
    assert d["error"] == "processable_kinds_unknown"
    assert "unreachable" in d["message"]
    assert _DRIVER_HOST not in r.text, "the driver's text (it can name the db host) reached the dropper"
    _nothing_written(rig)


def test_door_store_unreachable_with_a_cached_value_serves_the_cache(client, rig, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setenv("PROCESSABLE_KINDS_CACHE_SECONDS", "0")  # every read is stale -> reload
    rig.store["value"] = (("work-instruction",), _NOW)
    assert _passed_the_kind_gate(_drop(client, "work-instruction"))
    rig.store["boom"] = True
    r = _drop(client, "work-instruction")
    assert _passed_the_kind_gate(r), r.text
    r2 = _drop(client, "zeta-note")
    assert r2.status_code == 400 and r2.json()["detail"]["error"] == "kind_unprocessable"
