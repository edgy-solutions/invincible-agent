"""engine-o `/enumerate_instances` refuses a caller who is not a person: 422 `no_person`.

THE RULINGS. Chris, 2026-10-10 (b): "scripts and restate_analyst send a real test persona or get
refused -- a domains list is never an entitlement". Architect, 2026-10-14: "a svc: literal counts
as absent in every arm, same as blank; a service identity is never a person."

WHY NOW. The route used to ANSWER a caller with no person (the gate showed it seeded content only,
gov #39). The refusal waited for its callers to carry a person; both wire callers now do -- census
rows 3 (supervisor, TOKEN) and 7 (in-process `_bind_from_scope`, FORWARD) in
`tests/security/test_every_engine_o_caller_is_classified.py`. A `/fill_slots` caller with no person
is rows 15/16 (NO_PERSON), refused at `/fill_slots`, not here.

WHAT IS SEALED. The refusal body (the shape of safety's `no_person`), that neither the registry
nor any provider is asked, the CONTROL that differs only in the caller, `_bind_from_scope`
treating a refusal as "no bind", and the supervisor's `NoPersonRefused` reaching the ask's
`detail` rather than the generic `HTTPError`.

Run: uv run --frozen pytest tests/security/test_enumerate_instances_refuses_a_caller_who_is_not_a_person.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

CLASS = "http://example.test/cost#RateTable"
PERSON = "alice@example.com"
EXPECTED = {"error": "no_person",
            "message": "this verb answers for a person; the caller carries none",
            "fn": "enumerate_instances"}
PROVIDERS = [{"provider": "engine-cost", "endpoint_url": "http://cost/enumerate_instances",
              "timeout_s": None}]
MEMBERS = {"outcome": "members", "count": 1,
           "members": [{"instance_id": "2021-02-01", "label": "2021-02-01"}]}


@pytest.fixture
def eo(monkeypatch):
    from agent_fleet.ontology_service import main as mod
    posts: list = []
    discovered: list = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kw):
            posts.append((url, dict(json or {})))
            return SimpleNamespace(status_code=200, json=lambda: dict(MEMBERS))

    def _discover(*a, **k):
        discovered.append(1)
        return mod.MeshResult.answered(PROVIDERS)

    async def _passthrough(request, body):
        return body["members"], int(body.get("count") or len(body["members"]))

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(mod, "_discover_enumerate_providers", _discover)
    monkeypatch.setattr(mod, "_gate_enumerated_members", _passthrough)
    mod._test_posts, mod._test_discovered = posts, discovered
    return mod


def _post(eo, **body):
    from fastapi.testclient import TestClient
    return TestClient(eo.app).post("/enumerate_instances", json={"class_uri": CLASS, **body})


_NOT_PERSONS = [pytest.param({"user_email": ""}, id="blank"),
                pytest.param({"user_email": "  "}, id="whitespace"),
                pytest.param({}, id="absent"),
                pytest.param({"user_email": "svc:supervisor"}, id="svc"),
                pytest.param({"user_email": " svc:engine-o"}, id="padded-svc")]


@pytest.mark.parametrize("caller", _NOT_PERSONS)
def test_a_caller_who_is_not_a_person_is_refused_and_nothing_is_asked(eo, caller):
    r = _post(eo, entitled_domains=["SUSTAINMENT"], **caller)
    assert r.status_code == 422, r.text
    assert r.json() == EXPECTED
    assert eo._test_discovered == [], "the registry was asked on behalf of a non-person"
    assert eo._test_posts == [], "a provider was asked on behalf of a non-person"


def test_CONTROL_a_person_with_the_same_stubs_is_answered(eo):
    r = _post(eo, user_email=PERSON)
    assert r.status_code == 200, r.text
    assert r.json().get("outcome") == "members"
    assert eo._test_discovered == [1]
    assert eo._test_posts, "the provider was not asked; the control proves nothing"


# --- the in-process caller -------------------------------------------------------------------

def test_the_scoped_bind_with_no_person_returns_none_and_sends_nothing(eo):
    got = asyncio.run(eo._bind_from_scope(CLASS, "2021-02-01", {}, [], user_email=""))
    assert got is None
    assert eo._test_posts == [] and eo._test_discovered == []


def test_CONTROL_the_scoped_bind_with_a_person_binds(eo):
    got = asyncio.run(eo._bind_from_scope(CLASS, "2021-02-01", {}, [], user_email=PERSON))
    assert got is not None and got["instance_id"] == "2021-02-01"
    assert eo._test_posts


# --- the supervisor --------------------------------------------------------------------------

class _Ctx:
    log = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)


def _response(status, body):
    import json as _json
    r = requests.Response()
    r.status_code = status
    r._content = _json.dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    r.url = "http://eo/enumerate_instances"
    return r


def _enumerator(monkeypatch, response):
    from iagent.defs import dynamic_supervisor as ds
    monkeypatch.setattr(ds, "_ENUMERATE_URL", "http://eo/enumerate_instances")
    monkeypatch.setattr(ds.requests, "post", lambda *a, **k: response)
    return ds, ds._make_enumerator(_Ctx(), user_email=PERSON)


def test_the_supervisor_names_a_no_person_refusal(monkeypatch):
    ds, enum = _enumerator(monkeypatch, _response(422, EXPECTED))
    with pytest.raises(ds.NoPersonRefused, match="answers for a person"):
        enum(CLASS)


def test_CONTROL_another_422_stays_an_http_error(monkeypatch):
    ds, enum = _enumerator(monkeypatch, _response(422, {"detail": "bad"}))
    with pytest.raises(requests.HTTPError):
        enum(CLASS)


def test_the_ask_detail_reads_no_person_refused_not_http_error(monkeypatch):
    """Lands on `free_text_reason=FT_NO_PROVIDER` (slot_disposition's blanket except), with the
    detail now naming the cause."""
    from agent_fleet.planning_agent.slots import slots_for
    from iagent_pure.slot_disposition import ASK, FT_NO_PROVIDER, decide_disposition
    ds, enum = _enumerator(monkeypatch, _response(422, EXPECTED))
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {
            "outcome": "wrong_class", "spoken": "ERP Modernization project",
            "instance_id": None, "candidates": []}},
        enumerate_class=enum)
    assert d.action == ASK
    assert d.detail == "NoPersonRefused", d
    assert d.free_text_reason == FT_NO_PROVIDER


# --- reported, not decided -------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="gov: is_person is case-sensitive on svc:; the census is not -- 2026-10-16")
def test_a_capitalised_service_head_is_still_a_service():
    from agent_fleet.utils import origin_entitlement
    assert not origin_entitlement.is_person("SVC:x")
