"""The BFF builds ONE directory HTTP client per process, never one per call.

Lane 1's packet (2026-11-14) measured the cost of building a client per call:
- about 2.6 s of CPU for each `GET /me/entitlements`;
- about 37 `httpx.Client` builds per request, at about 70 ms of CPU each;
- most of each build is the SSL context httpx makes, even for an `http://` URL.

Sealed here:
- Every directory reader in `human_tasks` builds no client after its first call (warm-up).
- A whole `GET /me/entitlements` builds none after warm-up.
- `_cells_of` (the label gate's read of another person's cells) builds none after warm-up.
- The counter is positive-controlled: a build it should see, it sees.
- An `http://` directory gets an SSL context that loads no trust store. That context still
  requires a certificate, so TLS fails closed. An `https://` directory keeps httpx's default
  verification.
- A shared client survives `close()` from any one user of it.

Every arm counts calls to `httpx.Client` as it stands when the code runs. The directory is an
`httpx.MockTransport` that answers with real `httpx.Response`s.

Run:  uv run python -m pytest tests/security/test_one_directory_client_serves_every_request.py -q
"""
from __future__ import annotations

import json
import ssl
import types

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from iagent.authz import topaz_client as tc  # noqa: E402 -- the module object human_tasks uses
from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402

AUTHZ = "E1001"
URL = "http://topaz.test"
_REAL_CLIENT = httpx.Client
LIST = "/api/v3/directory/objects"
CHECK = "/api/v3/directory/check"
CHECKS = "/api/v3/directory/checks"
RELATIONS = "/api/v3/directory/relations"
OBJECT = "/api/v3/directory/object/capability/"


def _handler(seen: list):
    def handler(request):
        seen.append(request.url.path)
        p = request.url.path
        if p == LIST:
            return httpx.Response(200, json={"results": [{"type": "capability", "id": k}
                                                         for k in ("zz:alpha", "zz:beta", "zz:gamma")]})
        if p == CHECK:
            return httpx.Response(200, json={"check": json.loads(request.content)["object_id"] != "zz:beta"})
        if p == CHECKS:
            return httpx.Response(200, json={"checks": [{"check": c["object_id"] != "zz:beta"}
                                                        for c in json.loads(request.content)["checks"]]})
        if p == RELATIONS:
            if request.url.params.get("object_type") == "group":
                return httpx.Response(200, json={"results": [{"subject_type": "user", "subject_id": "m@x.test"}]})
            return httpx.Response(200, json={"results": [
                {"subject_type": "user", "subject_id": AUTHZ},
                {"subject_type": "group", "subject_relation": "member", "subject_id": "g1"}]})
        if p.startswith(OBJECT):
            return httpx.Response(200, json={"result": {"type": "capability"}})
        return httpx.Response(404, json={})
    return handler


@pytest.fixture
def directory(monkeypatch):
    """A counting `httpx.Client` over a stub directory. `built` holds the kwargs of every build;
    `seen` holds the path of every request the directory answered."""
    rig = types.SimpleNamespace(built=[], seen=[])
    handler = _handler(rig.seen)

    def counting_client(**kw):
        rig.built.append(kw)
        return _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", URL)
    monkeypatch.setattr(httpx, "Client", counting_client)
    return rig


# One entry per directory reader in human_tasks: each opens the directory its own way.
READERS = {
    "_resolve_audience_actors": lambda: ht._resolve_audience_actors("aud-1"),
    "can_act_or_unavailable": lambda: ht.can_act_or_unavailable("aud-1", AUTHZ),
    "check_can_act": lambda: ht.check_can_act("aud-1", AUTHZ),
    "can_invoke_or_unavailable": lambda: ht.can_invoke_or_unavailable("zz:alpha", AUTHZ),
    "check_can_invoke": lambda: ht.check_can_invoke("zz:alpha", AUTHZ),
    "capability_object_exists": lambda: ht.capability_object_exists("zz:alpha"),
    "capability_keys": lambda: ht.capability_keys(),
    "can_invoke_each": lambda: ht.can_invoke_each(["zz:alpha", "zz:beta"], AUTHZ),
    "capabilities_and_held": lambda: ht.capabilities_and_held(AUTHZ),
}


@pytest.mark.parametrize("name", sorted(READERS))
def test_a_reader_builds_no_client_after_its_first_call(directory, name):
    call = READERS[name]
    first = call()
    warm = len(directory.built)
    asked = len(directory.seen)
    again = [call() for _ in range(3)]
    assert len(directory.seen) > asked, f"{name} asked the directory nothing: the count below proves nothing"
    assert len(directory.built) == warm, (
        f"{name} built {len(directory.built) - warm} httpx.Client(s) in 3 calls after warm-up; "
        f"the process's one directory client was not reused")
    assert all(a == first for a in again), f"{name} answered differently on a reused client"


def test_a_whole_entitlements_request_builds_no_client_after_warm_up(directory, monkeypatch):
    monkeypatch.setattr(ck, "registrations", lambda: ())
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: types.SimpleNamespace(
        authz_id=AUTHZ, id=AUTHZ, sub=AUTHZ, email="a@x.test", persona=None, entitled_domains=[],
        is_authenticated=True, entitlements=types.SimpleNamespace(cells=[], default=None, source="test"))
    try:
        c = TestClient(gateway.app, raise_server_exceptions=False)
        r = c.get("/me/entitlements")
        assert r.status_code == 200, r.text
        warm, asked = len(directory.built), len(directory.seen)
        for _ in range(3):
            r = c.get("/me/entitlements")
            assert r.status_code == 200, r.text
            assert r.json()["capabilities"] == ["zz:alpha", "zz:gamma"]
    finally:
        gateway.app.dependency_overrides.clear()
    # One list and one batched check each (the count itself is sealed in
    # test_entitlements_asks_the_directory_twice.py).
    assert len(directory.seen) - asked >= 3 * 2, "the requests asked the directory too little to count"
    assert len(directory.built) == warm, (
        f"3 entitlements requests built {len(directory.built) - warm} httpx.Client(s) after warm-up")


def test_the_cells_of_another_person_build_no_client_after_warm_up(directory, monkeypatch):
    """`_cells_of` (the label gate's read of a person who is not the caller) goes through
    `TopazDirectoryClient(url, shared=True)`, and so over the same one client."""
    import asyncio

    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", URL)
    first = asyncio.run(gateway._cells_of(AUTHZ))
    warm, asked = len(directory.built), len(directory.seen)
    again = [asyncio.run(gateway._cells_of(AUTHZ)) for _ in range(3)]
    assert len(directory.seen) > asked, "_cells_of asked the directory nothing"
    assert len(directory.built) == warm, (
        f"_cells_of built {len(directory.built) - warm} httpx.Client(s) in 3 calls after warm-up")
    assert all(a == first for a in again)


def test_CONTROL_the_counter_sees_a_build(directory):
    """Same counter, same directory. A build it must see: a second directory URL gets its own
    client, and so does a client built by hand. A counter that never counts would pass every arm
    above."""
    ht.capability_keys()
    warm = len(directory.built)
    tc.directory_http_client("http://other-topaz.test")
    httpx.Client(base_url=URL)
    assert len(directory.built) == warm + 2


def test_CONTROL_a_client_built_per_call_is_counted(directory, monkeypatch):
    """The defect this file seals, put back: `_directory` builds a client per call. Every call then
    counts one build, so the arms above go red against it."""
    import contextlib

    monkeypatch.setattr(ht, "_directory", lambda: contextlib.closing(
        httpx.Client(base_url=ht._TOPAZ_DIRECTORY_URL, timeout=5.0)))
    ht.can_act_or_unavailable("aud-1", AUTHZ)
    warm = len(directory.built)
    for _ in range(3):
        ht.can_act_or_unavailable("aud-1", AUTHZ)
    assert len(directory.built) == warm + 3


def test_an_http_directory_loads_no_trust_store_and_fails_tls_closed(directory):
    tc.directory_http_client("http://plain-topaz.test")
    ctx = directory.built[-1]["verify"]
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.cert_store_stats()["x509_ca"] == 0, "a trust store was loaded for an http:// URL"
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname, (
        "the http:// context would accept an unverified TLS peer")


def test_an_https_directory_keeps_the_default_verification(directory):
    tc.directory_http_client("https://tls-topaz.test")
    assert "verify" not in directory.built[-1], "an https:// directory was given a non-default context"


def test_a_shared_client_survives_any_users_close(directory):
    shared = tc.TopazDirectoryClient(URL, shared=True)
    shared.close()
    assert not tc.directory_http_client(URL).is_closed
    assert ht.can_act_or_unavailable("aud-1", AUTHZ) is True
    own = tc.TopazDirectoryClient(URL)
    own.close()
    assert own._client.is_closed and not tc.directory_http_client(URL).is_closed


def test_a_forked_child_builds_its_own_client(directory, monkeypatch):
    parent = tc.directory_http_client(URL)
    monkeypatch.setattr(tc.os, "getpid", lambda: -1)
    assert tc.directory_http_client(URL) is not parent
