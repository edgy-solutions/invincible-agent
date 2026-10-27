"""Every `mesh:resolveInstance` provider is told WHO asked: `user_email` and `entitled_domains`.

WHY THIS EXISTS. Gov's origin-at-read report (2026-10-10, Q7): engine-o's SUSTAINMENT provider
returns drop-derived notices to any asker, because its request carried an identifier and a query
and nothing else. A provider cannot gate on a caller it was never told, so the origin gate
(gov's change) needs the caller on the wire first. This file seals that wire, in three hops:

  * supervisor -> engine-o `/fill_slots`: the person rides beside `acting_domains`;
  * engine-o `/resolve` and `/fill_slots` -> `_resolve_instance` -> `_call_resolver`: every call
    site forwards both, and the GRANT is never the ranking domain;
  * `_call_resolver` -> the provider: both fields on EVERY POST body, empty when nobody was named,
    so a gating provider reads "no caller" as a value it was sent, not a field it was not.

What a provider DOES with them is not sealed here; that is the gate, and the gate is gov's.

Run: uv run --frozen pytest tests/routing/test_resolve_instance_hears_the_caller.py -v
"""
from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_fleet.cost_agent.slots import slots_for

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_O = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_SUPERVISOR = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PERSON = "ann.analyst@example.test"
GRANT = ["PRODUCTION_COST", "SUSTAINMENT"]
PROVIDERS = [
    {"provider": "engine-cost", "endpoint_url": "http://cost/resolve_instance",
     "timeout_s": None, "domains": ["PRODUCTION_COST"]},
    {"provider": "engine-o", "endpoint_url": "http://eo/resolve_instance",
     "timeout_s": None, "domains": ["SUSTAINMENT"]},
]


def _eo():
    from agent_fleet.ontology_service import main as eo
    return eo


@pytest.fixture
def eo(monkeypatch):
    """Engine-o with a registry of two providers and an httpx that records every POST body."""
    mod = _eo()
    posts: list[tuple[str, dict]] = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kw):
            posts.append((url, dict(json or {})))
            return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                   json=lambda: {"candidates": []})

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(mod, "_discover_instance_resolvers",
                        lambda *a, **k: mod.MeshResult.answered(PROVIDERS))
    mod._test_posts = posts
    return mod


def _fill(eo, monkeypatch, **req):
    """`/fill_slots` as the supervisor calls it, for the shipped cost declaration: the model reads
    `lot 3`, which has a referent and no narrowing, so it goes to the resolveInstance fan-out."""
    filled = SimpleNamespace(slots_json=json.dumps({"lot": "lot 3"}), confidence=0.9,
                             reasoning="stub")

    async def _fake(**kw):
        return filled

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    body = {"query": "rates on lot 3", "verb_iri": "mesh:costRateComparison",
            "declarations": json.dumps(slots_for("cost_rate_comparison")),
            "acting_domains": list(GRANT), **req}
    return asyncio.run(eo.fill_slots(eo.FillSlotsRequest(**body)))


# --- hop 3: the provider's POST body, driven from /fill_slots ------------------------------

def test_EVERY_PROVIDER_IS_TOLD_THE_PERSON_AND_THE_GRANT(eo, monkeypatch):
    _fill(eo, monkeypatch, user_email=PERSON)
    posts = eo._test_posts
    assert {u for u, _ in posts} == {p["endpoint_url"] for p in PROVIDERS}, (
        "the fan-out did not reach every registered provider; this arm saw nothing to assert on")
    for url, body in posts:
        assert body.get("user_email") == PERSON, (url, body)
        assert body.get("entitled_domains") == GRANT, (url, body)
        assert body.get("identifier"), (url, body)


def test_CONTROL_NO_PERSON_IS_REFUSED_AND_NO_PROVIDER_IS_ASKED(eo, monkeypatch):
    """Differs from the arm above only in the person and the grant. `/fill_slots` now refuses a
    caller with no person (422 no_person; lane/74, 2026-10-16), so no provider is asked at all.
    The explicit-empty wire this arm used to seal moved to the next arm."""
    r = _fill(eo, monkeypatch, acting_domains=[])
    assert r.status_code == 422, r
    assert eo._test_posts == []


def test_CONTROL_THE_FAN_OUT_SENDS_NOBODY_AS_AN_EXPLICIT_EMPTY(eo):
    """MOVED from the arm above when `/fill_slots` began refusing (2026-10-16). `/resolve` still
    reaches the fan-out with no person (census rows 13/14, not yet refused), so both keys must
    still go: a gating provider must be able to tell "nobody" from an asker that predates this
    wire. Driven at the fan-out itself, the function every route shares."""
    asyncio.run(eo._resolve_instance("lot 3", "rates on lot 3"))
    assert eo._test_posts
    for url, body in eo._test_posts:
        assert body.get("user_email", None) == "", (url, body)
        assert body.get("entitled_domains", None) == [], (url, body)


def test_THE_GRANT_IS_NOT_THE_RANKING_DOMAIN(eo):
    """`asked_domains` ranks and `entitled_domains` grants. Forwarding the first as the second
    would let a routing hint stand in for an entitlement."""
    asyncio.run(eo._resolve_instance("lot 3", "q", asked_domains=["MAINTENANCE"],
                                     user_email=PERSON, entitled_domains=GRANT))
    assert eo._test_posts
    for url, body in eo._test_posts:
        assert body["entitled_domains"] == GRANT, (url, body)


# --- hop 2: every engine-o call site, by census --------------------------------------------

def _calls(src: str, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == name]


def _kw(call: ast.Call) -> dict[str, ast.expr]:
    return {k.arg: k.value for k in call.keywords if k.arg}


def test_EVERY_CALL_INTO_THE_FAN_OUT_FORWARDS_THE_CALLER():
    """Derived, not listed: every `_resolve_instance(` and `_call_resolver(` call in engine-o. A
    new call site that forgets the caller defaults to "nobody", which a gate would refuse, so the
    defect would read as a correct refusal."""
    src = _ENGINE_O.read_text(encoding="utf-8")
    for name in ("_resolve_instance", "_call_resolver"):
        calls = _calls(src, name)
        assert calls, f"no call to {name} found; this census reads nothing"
        for c in calls:
            kw = _kw(c)
            assert {"user_email", "entitled_domains"} <= set(kw), (
                f"{name} at engine-o line {c.lineno} does not forward the caller: {sorted(kw)}")


def test_THE_LEGACY_ROUTING_DOMAIN_IS_NEVER_A_GRANT():
    """`/resolve`'s legacy `domain` defaults to MAINTENANCE. It may rank; it may not grant."""
    src = _ENGINE_O.read_text(encoding="utf-8")
    for c in _calls(src, "_resolve_instance"):
        grant = _kw(c)["entitled_domains"]
        attrs = {n.attr for n in ast.walk(grant) if isinstance(n, ast.Attribute)}
        assert "domain" not in attrs, (
            f"line {c.lineno}: entitled_domains is built from the legacy routing `domain`")
        assert attrs & {"domains", "acting_domains", "entitled_domains"}, (
            f"line {c.lineno}: entitled_domains is not the caller's grant: {ast.unparse(grant)}")
        assert "user_email" in {n.attr for n in ast.walk(_kw(c)["user_email"])
                                if isinstance(n, ast.Attribute)}, (
            f"line {c.lineno}: user_email is not the request's own")


def test_THE_PROVIDER_ROUTE_RECEIVES_BOTH_FIELDS():
    eo = _eo()
    req = eo.ResolveInstanceRequest(identifier="X", user_email=PERSON, entitled_domains=GRANT)
    assert (req.user_email, req.entitled_domains) == (PERSON, tuple(GRANT))
    bare = eo.ResolveInstanceRequest(identifier="X")
    assert (bare.user_email, bare.entitled_domains) == ("", ())


# --- hop 1: the supervisor ------------------------------------------------------------------

class _Ctx:
    log = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)


def _posted(monkeypatch, **kw) -> dict:
    from iagent.defs import dynamic_supervisor as ds
    posted: dict = {}

    def _fake_post(url, json=None, timeout=None):
        posted.update(json or {})
        return SimpleNamespace(status_code=200, json=lambda: {"slots": {}, "resolution": {}})

    monkeypatch.setattr(ds.requests, "post", _fake_post)
    ds._fill_slots_from_query(_Ctx(), query="q", verb_iri="mesh:v", declarations=[],
                              acting_domains=list(GRANT), **kw)
    return posted


def test_THE_SUPERVISOR_SENDS_THE_PERSON_TO_FILL_SLOTS(monkeypatch):
    assert _posted(monkeypatch, user_email=PERSON).get("user_email") == PERSON


def test_CONTROL_THE_SUPERVISOR_SENDS_AN_EXPLICIT_EMPTY(monkeypatch):
    assert _posted(monkeypatch).get("user_email", None) == ""


def test_EVERY_SUPERVISOR_CALL_SITE_PASSES_THE_CONFIGS_PERSON():
    src = _SUPERVISOR.read_text(encoding="utf-8")
    calls = _calls(src, "_fill_slots_from_query")
    assert calls, "no call to _fill_slots_from_query found; this census reads nothing"
    for c in calls:
        v = _kw(c).get("user_email")
        assert isinstance(v, ast.Attribute) and v.attr == "user_email", (
            f"supervisor line {c.lineno}: /fill_slots is not told the config's person "
            f"({ast.unparse(v) if v is not None else 'absent'})")
