"""Kind at drop (architect directive 2026-10-23, overriding the 10-21 "no picker before the drop").

The composer's [PCN] [PDN] [Not sure] row sends `leaf` on POST /ingest for the first two and nothing
for "Not sure". The door writes the leaf into the sidecar as `metadata.content_kind` and onto the
row, where `record_received`'s `_declared_leaf` makes it `leaf_source=declared`. "Not sure" is
today's drop, unchanged. Refusals come before any write: an unknown leaf, a leaf on a non-PDF
file, and a leaf that contradicts a declared content_kind.
"""
from __future__ import annotations

import json
import types

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("can_drop_open")

PDF_BYTES = b"%PDF-1.4 door bytes"
XML_BYTES = b'<?xml version="1.0"?><a/>'


def _reg(kind, branch="document", domain="sustainment"):
    return types.SimpleNamespace(kind=kind, branch=branch, domain=domain, seeds_workflow=None,
                                 identity_field=None)


_REGISTRY = (_reg("pcn"), _reg("pdn"), _reg("pdf", domain=None), _reg("s1000d", domain="maintenance"),
             _reg("xml", domain=None))


@pytest.fixture
def client():
    user = type("U", (), {"authz_id": "alice@example.com", "id": "alice@example.com",
                          "sub": "alice@example.com", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


def _rig(monkeypatch, registry=_REGISTRY):
    s3: list[dict] = []
    looked: list = []
    recorded: list = []

    class _S3:
        def put_object(self, **kw):
            s3.append(kw)

    monkeypatch.setattr(ck, "registrations", lambda: registry)
    monkeypatch.setattr(ck, "by_kind", lambda k: next((r for r in registry if r.kind == k), None) if k else None)
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _S3())
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: looked.append(sha))
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: recorded.append(kw) or {"id": kw["ingest_id"], "status": "received"})
    return types.SimpleNamespace(s3=s3, looked=looked, recorded=recorded)


@pytest.fixture
def rig(monkeypatch):
    return _rig(monkeypatch)


def _drop(client, kind="pdf", body=PDF_BYTES, name="f.pdf", **extra):
    return client.post("/ingest", files={"file": (name, body, "application/octet-stream")},
                       data={"kind": kind, "on_behalf_of": "alice@example.com", **extra})


def _sidecar(rig) -> dict:
    (put,) = [p for p in rig.s3 if p["Key"].endswith("manifest.json")]
    return json.loads(put["Body"])


def _nothing_written(rig):
    assert rig.s3 == [] and rig.looked == [] and rig.recorded == []


def _row_source(rig):
    """The leaf columns the REAL record_received would write for what the door handed it."""
    (kw,) = rig.recorded
    return ist._declared_leaf(kw["content_kind"], kw["submitted_by"], 0)["leaf_source"]


@pytest.mark.parametrize("extra, leaf", [
    ({"leaf": "pcn", "content_kind": "pdf"}, "pcn"),
    ({"leaf": "pdn", "content_kind": "pdf"}, "pdn"),
    ({"leaf": "pcn"}, "pcn"),                        # the leaf alone is a declared kind
    ({"leaf": " PDN ", "content_kind": "pdf"}, "pdn"),  # normalised, as the row stores it
    ({"leaf": "pcn", "content_kind": "pcn"}, "pcn"),  # agreeing with itself is not a conflict
])
def test_a_leaf_is_the_sidecars_content_kind_and_the_rows_declared_leaf(client, rig, extra, leaf):
    r = _drop(client, **extra)
    assert r.status_code == 200, r.text
    side = _sidecar(rig)
    assert side["metadata"] == {"content_kind": leaf}
    assert side["content_kind"] == leaf and side["domain_type"] == "sustainment"
    assert rig.recorded[0]["content_kind"] == leaf
    assert _row_source(rig) == "declared"


def test_not_sure_sends_no_leaf_and_the_drop_is_todays(client, rig):
    """The control: the same drop without `leaf` stays `pdf`, with no declared leaf, so the title
    read -> awaiting_kind -> pick -> relaunch path is the one it takes."""
    r = _drop(client, content_kind="pdf")
    assert r.status_code == 200, r.text
    assert _sidecar(rig)["metadata"] == {"content_kind": "pdf"}
    assert rig.recorded[0]["content_kind"] == "pdf"
    assert _row_source(rig) is None


@pytest.mark.parametrize("bad", ["bogus", "   ", "pdf", "s1000d"])
def test_an_unknown_leaf_is_422_leaf_unknown_and_writes_nothing(client, rig, bad):
    r = _drop(client, leaf=bad, content_kind="pdf")
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "leaf_unknown" and d["leaves"] == list(ist.LEAVES)
    _nothing_written(rig)


def test_a_leaf_on_an_xml_drop_is_422_leaf_requires_pdf_and_writes_nothing(client, rig):
    r = _drop(client, kind="xml", body=XML_BYTES, name="dm.xml", leaf="pcn", content_kind="s1000d")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "leaf_requires_pdf"
    _nothing_written(rig)


@pytest.mark.parametrize("ck_value", ["pdn", "s1000d"])
def test_a_leaf_against_another_content_kind_is_422_and_writes_nothing(client, rig, ck_value):
    r = _drop(client, leaf="pcn", content_kind=ck_value)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "leaf_conflicts_with_content_kind"
    _nothing_written(rig)


def test_the_registry_check_runs_on_the_leaf(client, monkeypatch):
    """A deployment that has not registered `pcn` refuses a PCN drop with the door's own 400,
    as it refuses `content_kind=pcn` today. The leaf does not bypass the registry."""
    rig = _rig(monkeypatch, registry=(_reg("pdn"), _reg("pdf", domain=None)))
    r = _drop(client, leaf="pcn", content_kind="pdf")
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "kind_unregistered"
    _nothing_written(rig)
