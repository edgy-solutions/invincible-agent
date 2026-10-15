"""Every `mesh:enumerateInstances` provider is told WHO asked: `user_email` and `entitled_domains`.

WHY THIS EXISTS. Ruled 2026-10-10, (d): enumerateInstances gets the same origin gate as
resolveInstance (gov). `tests/routing/test_resolve_instance_hears_the_caller.py` seals the caller
onto the resolveInstance wire; this is the sibling verb, and it lists the very instances the
other one resolves. Without it, a provider gated on one verb would still hand everything out
through the other. The same names and the same shape go on both verbs, so one gate reads both.

The hops:

  * supervisor `_make_enumerator` -> engine-o `/enumerate_instances`: the config's person and
    grant are bound when the enumerator is made, at every call site;
  * engine-o `/fill_slots` -> `_bind_from_scope` -> the router: the fill request's caller;
  * the router -> every provider: both fields on EVERY POST, empty when nobody was named;
  * every in-repo provider ACCEPTS both keys. A request model with `extra="forbid"` that does not
    declare them would 422 every call, and the SDK's own `EnumerateInstancesRequest` is exactly
    such a model today — so a provider that adopts it before the SDK gains the fields goes red
    here, not in production.

What a provider DOES with them is not sealed here; that is the gate, and the gate is gov's.

Run: uv run --frozen pytest tests/routing/test_enumerate_instances_hears_the_caller.py -v
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[2]
_FLEET = _REPO / "agent_fleet"
_ENGINE_O = _FLEET / "ontology_service" / "main.py"
_SUPERVISOR = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PERSON = "ann.analyst@example.test"
GRANT = ["PRODUCTION_COST", "SUSTAINMENT"]
CLASS = "http://example.test/cost#RateTable"
PROVIDERS = [
    {"provider": "engine-cost", "endpoint_url": "http://cost/enumerate_instances",
     "timeout_s": None},
    {"provider": "engine-p", "endpoint_url": "http://p/enumerate_instances", "timeout_s": None},
]
CALLER_KEYS = {"user_email", "entitled_domains"}


def _eo():
    from agent_fleet.ontology_service import main as eo
    return eo


@pytest.fixture
def eo(monkeypatch):
    """Engine-o with two enumerate providers and an httpx that records every POST body. Every
    provider answers `empty`, so the router asks them all rather than stopping at the first."""
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
            return SimpleNamespace(status_code=200,
                                   json=lambda: {"outcome": "empty", "members": [], "count": 0})

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(mod, "_discover_enumerate_providers",
                        lambda *a, **k: mod.MeshResult.answered(PROVIDERS))
    mod._test_posts = posts
    return mod


def _calls(src: str, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == name]


def _kw(call: ast.Call) -> dict[str, ast.expr]:
    return {k.arg: k.value for k in call.keywords if k.arg}


def _attrs(node: ast.AST | None) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} if node else set()


# --- the router -> every provider -----------------------------------------------------------

def test_EVERY_ENUMERATE_PROVIDER_IS_TOLD_THE_PERSON_AND_THE_GRANT(eo):
    req = eo.EnumerateInstancesRequest(class_uri=CLASS, bound_slots={"lot": "3"},
                                       user_email=PERSON, entitled_domains=GRANT)
    asyncio.run(eo.enumerate_instances(req))
    posts = eo._test_posts
    assert {u for u, _ in posts} == {p["endpoint_url"] for p in PROVIDERS}, (
        "the fan-out did not reach every registered provider; this arm saw nothing to assert on")
    for url, body in posts:
        assert body.get("user_email") == PERSON, (url, body)
        assert body.get("entitled_domains") == GRANT, (url, body)
        assert (body.get("class_uri"), body.get("bound_slots")) == (CLASS, {"lot": "3"}), (
            "the caller displaced the request it rides with", url, body)


def test_CONTROL_NO_PERSON_IS_SENT_AS_AN_EXPLICIT_EMPTY(eo):
    """Differs from the arm above only in the caller. Both keys still go: a gating provider must
    be able to tell "nobody" from an asker that predates this wire."""
    asyncio.run(eo.enumerate_instances(eo.EnumerateInstancesRequest(class_uri=CLASS)))
    assert eo._test_posts
    for url, body in eo._test_posts:
        assert body.get("user_email", None) == "", (url, body)
        assert body.get("entitled_domains", None) == [], (url, body)


def test_THE_ROUTER_RECEIVES_BOTH_FIELDS_AND_AN_OLD_CALLER_STILL_PARSES():
    eo = _eo()
    req = eo.EnumerateInstancesRequest(class_uri=CLASS, user_email=PERSON, entitled_domains=GRANT)
    assert (req.user_email, req.entitled_domains) == (PERSON, GRANT)
    bare = eo.EnumerateInstancesRequest(class_uri=CLASS)
    assert (bare.user_email, bare.entitled_domains) == ("", [])


# --- /fill_slots -> _bind_from_scope -> the router ------------------------------------------

def test_THE_SCOPED_BIND_FORWARDS_ITS_CALLER(eo):
    asyncio.run(eo._bind_from_scope(CLASS, "2021-02-01", {"lot": "3"}, ["lot"],
                                    user_email=PERSON, entitled_domains=GRANT))
    assert eo._test_posts
    for url, body in eo._test_posts:
        assert (body.get("user_email"), body.get("entitled_domains")) == (PERSON, GRANT), (
            url, body)


def test_EVERY_ENUMERATE_REQUEST_IN_ENGINE_O_CARRIES_THE_CALLER():
    """Derived, not listed: every place engine-o builds a request to its own router, and every
    call into the scoped bind. A new one that forgets the caller defaults to "nobody", which a
    gate refuses, so the defect would read as a correct refusal."""
    src = _ENGINE_O.read_text(encoding="utf-8")
    for name in ("EnumerateInstancesRequest", "_bind_from_scope"):
        calls = _calls(src, name)
        assert calls, f"no call to {name} found; this census reads nothing"
        for c in calls:
            kw = _kw(c)
            assert CALLER_KEYS <= set(kw), (
                f"{name} at engine-o line {c.lineno} does not carry the caller: {sorted(kw)}")


def test_THE_FILL_SLOTS_CALLER_IS_THE_REQUESTS_OWN():
    """`/fill_slots` hands the scoped bind ITS request's person and grant — the same pair it
    hands the resolveInstance fan-out — and never a value it made up."""
    src = _ENGINE_O.read_text(encoding="utf-8")
    calls = _calls(src, "_bind_from_scope")
    assert calls, "no call to _bind_from_scope found; this census reads nothing"
    for c in calls:
        kw = _kw(c)
        assert "user_email" in _attrs(kw.get("user_email")), (
            f"line {c.lineno}: user_email is not the request's own")
        assert _attrs(kw.get("entitled_domains")) & {"acting_domains", "entitled_domains"}, (
            f"line {c.lineno}: entitled_domains is not the caller's grant")


# --- the supervisor -------------------------------------------------------------------------

class _Ctx:
    log = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)


def _enumerated(monkeypatch, **kw) -> dict:
    from iagent.defs import dynamic_supervisor as ds
    posted: dict = {}

    def _fake_post(url, json=None, timeout=None):
        posted.update(json or {})
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"outcome": "empty", "members": [], "count": 0})

    monkeypatch.setattr(ds, "_ENUMERATE_URL", "http://eo/enumerate_instances")
    monkeypatch.setattr(ds.requests, "post", _fake_post)
    ds._make_enumerator(_Ctx(), **kw)(CLASS, bound_slots={"lot": "3"})
    return posted


def test_THE_SUPERVISORS_ENUMERATOR_SENDS_THE_PERSON_AND_THE_GRANT(monkeypatch):
    posted = _enumerated(monkeypatch, user_email=PERSON, entitled_domains=GRANT)
    assert (posted.get("user_email"), posted.get("entitled_domains")) == (PERSON, GRANT), posted
    assert posted.get("bound_slots") == {"lot": "3"}, posted


def test_CONTROL_THE_SUPERVISORS_ENUMERATOR_SENDS_AN_EXPLICIT_EMPTY(monkeypatch):
    posted = _enumerated(monkeypatch)
    assert posted.get("user_email", None) == "", posted
    assert posted.get("entitled_domains", None) == [], posted


def test_EVERY_SUPERVISOR_ENUMERATOR_IS_MADE_WITH_THE_CONFIGS_CALLER():
    src = _SUPERVISOR.read_text(encoding="utf-8")
    calls = _calls(src, "_make_enumerator")
    assert calls, "no call to _make_enumerator found; this census reads nothing"
    for c in calls:
        kw = _kw(c)
        assert "user_email" in _attrs(kw.get("user_email")), (
            f"supervisor line {c.lineno}: the enumerator is not given the config's person")
        assert "entitled_domains" in _attrs(kw.get("entitled_domains")), (
            f"supervisor line {c.lineno}: the enumerator is not given the config's grant")


# --- every in-repo provider can receive them ------------------------------------------------

def _is_enumerate_route(fn: ast.AST) -> bool:
    for d in getattr(fn, "decorator_list", []):
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "post"
                and d.args and isinstance(d.args[0], ast.Constant)
                and d.args[0].value == "/enumerate_instances"):
            return True
    return False


def _provider_models() -> list[tuple[str, ast.ClassDef | None, str]]:
    """(engine file, the route's request model, its name) for every `/enumerate_instances` route
    in the fleet. The model is None when it is not a class defined in the same module, which is
    UNDECIDED and fails below rather than passing as "accepts"."""
    out = []
    for main in sorted(_FLEET.glob("*/main.py")):
        tree = ast.parse(main.read_text(encoding="utf-8"))
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_enumerate_route(fn):
                ann = fn.args.args[0].annotation if fn.args.args else None
                name = ann.id if isinstance(ann, ast.Name) else ast.unparse(ann) if ann else ""
                out.append((main.parent.name, classes.get(name), name))
    return out


def test_EVERY_IN_REPO_ENUMERATE_PROVIDER_ACCEPTS_THE_CALLER_KEYS():
    """The router now sends two keys no provider declared. A provider on a model that forbids
    extras and does not declare them would 422 EVERY enumerate call — the whole verb, not only
    the gated part. The SDK's `iagent_mesh.enumeration.EnumerateInstancesRequest` is such a model
    today (`extra="forbid"`, on purpose), so this is also the guard against adopting it before
    the SDK gains the fields."""
    providers = _provider_models()
    assert providers, "no /enumerate_instances route found in agent_fleet; this census reads nothing"
    for engine, cls, name in providers:
        assert cls is not None, (
            f"{engine}: the route's request model {name!r} is not a class in that module — "
            f"undecided, so not counted as accepting the caller")
        bases = {ast.unparse(b) for b in cls.bases}
        assert bases == {"BaseModel"}, (
            f"{engine}.{name} inherits from {sorted(bases)}; its extra policy is not visible here")
        forbids = any("forbid" in ast.unparse(n) for n in cls.body
                      if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", "") == "model_config" for t in n.targets))
        forbids |= any(k.arg == "extra" and "forbid" in ast.unparse(k.value) for k in cls.keywords)
        declared = {n.target.id for n in cls.body
                    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        assert not forbids or CALLER_KEYS <= declared, (
            f"{engine}.{name} forbids extra fields and does not declare {sorted(CALLER_KEYS)}: "
            f"every enumerate call carrying the caller would be a 422")


def test_THE_SDK_GAP_IS_REAL_AND_NAMED():
    """THE HALF THIS LANE CANNOT LAND, asserted rather than written in a comment. Survives the
    transition: whichever state the SDK is in, it says which, and goes red only on a third
    state (fields absent AND extras quietly allowed, which would let the keys travel unchecked)."""
    enumeration = pytest.importorskip(
        "iagent_mesh.enumeration",
        reason="iagent-mesh SDK not installed — this half is VOID, not green",
    )
    model = enumeration.EnumerateInstancesRequest
    fields = set(model.model_fields)
    if CALLER_KEYS <= fields:
        req = model(class_uri=CLASS, user_email=PERSON, entitled_domains=GRANT)
        assert (req.user_email, req.entitled_domains) == (PERSON, GRANT)
    else:
        assert model.model_config.get("extra") == "forbid", (
            "the SDK model neither declares the caller keys nor forbids extras — the keys would "
            "travel to an SDK-shaped provider with nothing checking their shape")
