"""GET /me/entitlements asks the directory twice, and decides as the per-key path decides.

Step 2 of the BFF directory-client fix (Lane 1's packet of 2026-11-14). The response used to cost one
`can_drop:<kind>` object read per registered kind, one list, and one `can_invoke` check per key:
37 requests on sandbox. Now it costs one paginated list and ONE batched check
(`POST /api/v3/directory/checks`), however many keys and kinds there are.

Sealed:
- b1: a request is exactly LIST then CHECKS (one page), whatever the number of keys and kinds;
- b2: both fields equal what the per-key readers decide (`can_invoke_or_unavailable` per key,
  `can_drop_refusal` per kind) over one directory double, for callers granted all, some and none;
- b3: a key listed twice is asked once, and an empty list sends no check;
- b4: a caller with no authz_id is sent no check, and holds nothing.

The batched reader's answer rules, measured live on 2026-11-14, are sealed in
`test_a_pdp_answer_is_a_boolean_or_an_outage.py`, and their 503 at this route in
`test_me_entitlements_serves_held_capabilities.py`.

Run:  uv run python -m pytest tests/security/test_entitlements_asks_the_directory_twice.py -q
"""
from __future__ import annotations

import json
import types
from urllib.parse import unquote

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402

_REAL_CLIENT = httpx.Client
LIST = "/api/v3/directory/objects"
CHECK = "/api/v3/directory/check"
CHECKS = "/api/v3/directory/checks"
OBJECT = "/api/v3/directory/object/capability/"

# Made-up kinds and keys (config names the case): two gated kinds, one open, and plain keys.
KINDS = ("zk1", "zk2", "zk3")
KEYS = ["zz:alpha", "zz:beta", "zz:gamma", "can_drop:zk1", "can_drop:zk3"]
ALL, SOME, NONE = "E1001", "E1002", "E1003"
HELD = {ALL: set(KEYS), SOME: {"zz:beta", "can_drop:zk3"}, NONE: set()}


def _user(authz):
    return types.SimpleNamespace(
        authz_id=authz, id=authz, sub=authz, email="a@x.test", persona=None, entitled_domains=[],
        is_authenticated=True,
        entitlements=types.SimpleNamespace(cells=[], default=None, source="test"))


@pytest.fixture
def directory(monkeypatch):
    """One directory double that answers every form of the question from one state: `keys` are the
    capability objects, `held[who]` the keys `who` holds `can_invoke` on."""
    d = types.SimpleNamespace(keys=list(KEYS), held=HELD, paths=[], batches=[])

    def handler(request):
        p = request.url.path
        d.paths.append(p)
        if p == LIST:
            return httpx.Response(200, json={"results": [{"type": "capability", "id": k} for k in d.keys]})
        if p == CHECKS:
            body = json.loads(request.content)
            d.batches.append(body)
            who = body["default"]["subject_id"]
            return httpx.Response(200, json={"checks": [
                {"check": c["object_id"] in d.held.get(who, ()), "context": {}} for c in body["checks"]]})
        if p == CHECK:
            body = json.loads(request.content)
            return httpx.Response(200, json={"check": body["object_id"] in d.held.get(body["subject_id"], ())})
        if p.startswith(OBJECT):
            return httpx.Response(200 if unquote(p[len(OBJECT):]) in d.keys else 404, json={})
        return httpx.Response(404, json={})

    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz.test")
    monkeypatch.setattr(ht.httpx, "Client",
                        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    regs = tuple(types.SimpleNamespace(kind=k) for k in KINDS)
    monkeypatch.setattr(ck, "registrations", lambda: regs)
    return d


@pytest.fixture
def get():
    def _get(authz):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz)
        r = TestClient(gateway.app, raise_server_exceptions=False).get("/me/entitlements")
        assert r.status_code == 200, r.text
        return r.json()
    yield _get
    gateway.app.dependency_overrides.clear()


def _per_key(authz):
    """What the per-key readers decide: the reference the batched path must equal."""
    caps = [k for k in sorted(set(ht.capability_keys())) if ht.can_invoke_or_unavailable(k, authz)]
    kinds = [k for k in KINDS if ht.can_drop_refusal(k, authz) is None]
    return caps, kinds


@pytest.mark.parametrize("n_keys", [3, 40])
def test_b1_a_request_is_one_list_and_one_batched_check(directory, get, n_keys):
    directory.keys = [f"zz:k{i:02d}" for i in range(n_keys)] + ["can_drop:zk1"]
    get(SOME)
    assert directory.paths == [LIST, CHECKS], directory.paths
    (batch,) = directory.batches
    assert batch["default"] == {"object_type": "capability", "relation": "can_invoke",
                                "subject_type": "user", "subject_id": SOME}
    assert sorted(c["object_id"] for c in batch["checks"]) == sorted(directory.keys)


@pytest.mark.parametrize("authz", [ALL, SOME, NONE])
def test_b2_the_batched_answer_is_the_per_key_answer(directory, get, authz):
    caps, kinds = _per_key(authz)
    body = get(authz)
    assert body["capabilities"] == caps
    assert body["droppable_kinds"] == kinds


def test_b2_CONTROL_the_callers_differ(directory):
    """Without this, b2 could pass on three callers who all get the same answer."""
    answers = {a: _per_key(a) for a in (ALL, SOME, NONE)}
    assert len({repr(v) for v in answers.values()}) == 3, answers
    assert answers[NONE][1] == ["zk2"] and answers[ALL][1] == list(KINDS)


def test_b3_a_repeated_key_is_asked_once(directory, get):
    directory.keys = ["zz:alpha", "zz:alpha", "zz:beta"]
    get(ALL)
    (batch,) = directory.batches
    assert sorted(c["object_id"] for c in batch["checks"]) == ["zz:alpha", "zz:beta"]


def test_b3_an_empty_list_sends_no_check_and_every_kind_is_open(directory, get):
    directory.keys = []
    body = get(NONE)
    assert directory.paths == [LIST]
    assert body["capabilities"] == [] and body["droppable_kinds"] == list(KINDS)


def test_b4_no_authz_id_is_sent_no_check(directory):
    assert ht.can_invoke_each(["zz:alpha"], "") == [False]
    assert directory.paths == []
    assert ht.capabilities_and_held("")[1] == []
    assert directory.paths == [LIST]
