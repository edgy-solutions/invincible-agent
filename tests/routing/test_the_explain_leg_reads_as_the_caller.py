"""THE EXPLAIN LEG READS AS THE CALLER — `/find_compatible_verbs` carries the person asking.

LEG 3 of the verb pool (`mesh:explain` reached through a universal referent) is confirmed by a
Jena read, and every `MeshOntology` READ calls `require_person`: a read is attributed to a
person or it is refused. Until this change the route had no person to attribute it to — its
request was exactly `{subject_uri, max_hops, entitled_domains}` — so the read ran as the
module's service identity and was refused on every call: LEG 3 contributed zero rows in
production while its own seal (`test_the_pool_reaches_the_universal_referent.py`) stayed
green on a monkeypatched person.

THE FORM IS THE PERSON FORM, NOT THE REGISTRAR'S DELEGATE FORM, and that is measured here, not
chosen. The dispatch named `on_behalf_of` "as the registrar does" — but the registrar WRITES,
and `require_person_or_delegate` is the write boundary only. `construct` and `ask` call
`require_person`, so a delegate is refused at a read before anything is sent
(`test_THE_REGISTRARS_DELEGATE_FORM_IS_REFUSED_AT_A_READ`). The caller is named the way
`/resolve` already names it: `user_email` in the body, the gateway's verified `authz_id`, read
as `Initiator(subject=user_email, kind="person")`.

NO CALLER STILL ANSWERS. A request that names nobody keeps the service identity, sends no
query, and the pool degrades to LEGs 1+2 with a 200 — never a 400, because this route is on the
routing path and a refusal here would take routing down for every non-person caller (the
workflow engine's structural checks, operator scripts).

THE CENSUS IS DERIVED. Every tracked non-test POST to `/find_compatible_verbs` is partitioned
into: THREADS (its function takes `user_email` and uses it), SERVICE (it authenticates as a
named service client, so there is no person to attribute to), or SCRIPT (an operator script
under `scripts/`). Anything else is UNDECIDED and fails. The THREADS functions are then
closed upward through every caller that passes `user_email=` on, and the closure must reach
the gateway — the place the caller's identity is verified — or the pass-through threads
nowhere.
"""
from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from iagent_mesh.interfaces import DelegateIdentityRefused, Initiator

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

THING = "http://invincible-agent/mesh#Thing"
CALLER = "alice@example.test"
_TEST_JENA_ENDPOINT = "http://ontology.invalid/ds/sparql"
_ROUTE = "/find_compatible_verbs"


# ── the module under test, loaded under its own name ─────────────────────────────────────────


@pytest.fixture(scope="module")
def engine_o_module():
    """Engine O's `main.py` under a name no other test uses — the same stubs, and the same
    reason `rdflib` is NOT stubbed, as `test_the_pool_reaches_the_universal_referent.py`:
    the Jena double hands back real Turtle and the SDK parses it."""
    svc_dir = _REPO / "agent_fleet" / "ontology_service"
    for _p in (str(svc_dir), str(_REPO)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    for name in [
        "weaviate", "weaviate.classes", "weaviate.classes.query",
        "neo4j", "baml_client", "baml_client.types", "baml_client.type_builder",
        "llm_utils", "utils", "utils.weaviate_utils",
    ]:
        sys.modules.setdefault(name, MagicMock())
    import importlib.util
    mod_name = "engine_o_main__explain_leg_identity_test"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(mod_name, svc_dir / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


@pytest.fixture
def client(engine_o_module):
    """Server errors come back as RESPONSES, as a caller sees them: a crash in the route is a
    500 an arm asserts against, not an exception that kills the arm before it can."""
    return TestClient(engine_o_module.app, raise_server_exceptions=False)


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text


class _Post:
    """The Jena transport: records every query actually SENT."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    def __call__(self, url, *, data, headers):
        self.calls.append({"url": url, "data": data, "headers": headers})
        return _Resp(200, self._text)


def _confirming_turtle() -> str:
    return (
        "@prefix mesh: <http://invincible-agent/mesh#> .\n"
        "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
        "mesh:Thing a owl:Class .\n"
        'mesh:Thing mesh:universalReferent "true" .\n'
    )


class _FakeSession:
    def __init__(self) -> None:
        self.executed: tuple[str, dict] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, cypher: str, **params):
        self.executed = (cypher, params)
        return []


class _FakeDriver:
    def __init__(self) -> None:
        self.session_obj = _FakeSession()

    def session(self):
        return self.session_obj


@pytest.fixture
def wired(engine_o_module, monkeypatch):
    """A Jena double primed to CONFIRM `mesh:Thing`, wrapped so every initiator the route hands
    to `construct` is recorded before the REAL SDK boundary judges it. The confirming Turtle is
    the point: an arm that sees zero posts here saw a refusal, not an empty store."""
    mod = engine_o_module
    post = _Post(_confirming_turtle())
    real_cls = type(mod._JENA_ONTOLOGY)
    seen: list = []

    class _Recording(real_cls):
        def construct(self, initiator, **kw):
            seen.append(initiator)
            return super().construct(initiator, **kw)

    monkeypatch.setattr(mod, "_JENA_ONTOLOGY", _Recording(endpoint=_TEST_JENA_ENDPOINT, post=post))
    driver = _FakeDriver()
    monkeypatch.setattr(mod, "_NEO4J_DRIVER", driver)
    return post, seen, driver


# ── the route ─────────────────────────────────────────────────────────────────────────────────


def test_A_NAMED_CALLER_IS_THE_PERSON_THE_JENA_READ_IS_ATTRIBUTED_TO(client, wired):
    post, seen, driver = wired
    r = client.post(_ROUTE, json={"subject_uri": THING, "user_email": CALLER})
    assert r.status_code == 200, r.text
    assert seen, "the route never asked Jena at all"
    assert all(i.subject == CALLER and i.kind == "person" for i in seen), (
        f"the read was not attributed to the caller: {seen!r}"
    )
    assert len(post.calls) == 1, "the person's read was refused before it was sent"
    assert driver.session_obj.executed[1]["universal_referents"] == [THING], (
        "Jena confirmed mesh:Thing for this caller, and the confirmed set never reached LEG 3"
    )


@pytest.mark.parametrize("named", [None, "", "   "], ids=["absent", "empty", "blank"])
def test_NO_CALLER_SENDS_NO_QUERY_AND_THE_POOL_STILL_ANSWERS(client, wired, named):
    """Nobody to attribute the read to → no read is SENT (the SDK refuses the service identity
    before the transport), LEG 3 gets `[]`, and the route still answers 200 — a blank is not a
    person, so whitespace must not become `Initiator(subject="   ", kind="person")`. Measured:
    the SDK's `Initiator` refuses a blank subject with a ValidationError, so a route that let a
    blank through would answer 500, not read as nobody — the 200 is what the strip defends."""
    post, seen, driver = wired
    body = {"subject_uri": THING}
    if named is not None:
        body["user_email"] = named
    r = client.post(_ROUTE, json=body)
    assert r.status_code == 200, r.text
    assert post.calls == [], "a query was sent with no person to attribute it to"
    assert all(i.kind != "person" for i in seen), f"a blank became a person: {seen!r}"
    assert driver.session_obj.executed[1]["universal_referents"] == []


def test_THE_FIELD_IS_NAMED_AS_RESOLVE_NAMES_IT(engine_o_module):
    """One name for the caller across Engine O's routing requests, so a client that already
    threads it to `/resolve` threads it here by the same key."""
    mod = engine_o_module
    assert "user_email" in mod.ResolveRequest.model_fields
    assert "user_email" in mod.FindCompatibleVerbsRequest.model_fields, (
        "/find_compatible_verbs has no caller field; the explain leg reads as nobody"
    )


def test_THE_REGISTRARS_DELEGATE_FORM_IS_REFUSED_AT_A_READ(engine_o_module):
    """WHY THIS IS NOT `on_behalf_of`. The registrar's delegate form passes the WRITE boundary;
    a read calls `require_person`, which refuses a delegate before anything is sent. If this arm
    ever reds, the SDK admits delegates on reads and the form chosen here is worth revisiting."""
    post = _Post(_confirming_turtle())
    jena = type(engine_o_module._JENA_ONTOLOGY)(endpoint=_TEST_JENA_ENDPOINT, post=post)
    delegate = Initiator(subject="engine-o", kind="delegate", on_behalf_of=CALLER)
    with pytest.raises(DelegateIdentityRefused):
        jena.construct(delegate, subject=THING)
    assert post.calls == []


# ── the client and the direct path ────────────────────────────────────────────────────────────


def test_THE_CLIENT_SENDS_THE_CALLER_AND_OMITS_A_BLANK(monkeypatch):
    import iagent.verb_lookup as vl

    assert "user_email" in inspect.signature(vl.find_compatible_verbs).parameters, (
        "the shared client cannot carry the caller"
    )
    bodies: list[dict] = []

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"verbs": []}

    def _post(url, json=None, timeout=None, **k):
        bodies.append(json)
        return _R()

    monkeypatch.setattr(vl.requests, "post", _post)
    vl.find_compatible_verbs(THING, ["MESH"], ontology_url="http://engine-o", user_email=CALLER)
    vl.find_compatible_verbs(THING, ["MESH"], ontology_url="http://engine-o", user_email="  ")
    vl.find_compatible_verbs(THING, ["MESH"], ontology_url="http://engine-o")
    assert bodies[0].get("user_email") == CALLER
    assert "user_email" not in bodies[1], "a blank caller was sent as if it named someone"
    assert "user_email" not in bodies[2]


def test_THE_DIRECT_PATH_VERIFIES_AS_THE_CALLER(monkeypatch):
    dd = pytest.importorskip("iagent.direct_dispatch")
    assert "user_email" in inspect.signature(dd.dispatch_pre_resolved).parameters, (
        "the direct path cannot carry the caller to its verifier"
    )
    got: dict = {}

    def _verifier(subject, domains, *, ontology_url, **k):
        got.update(k)
        return None, "stubbed: the verifier is all this arm drives"

    monkeypatch.setattr(dd, "find_compatible_verbs", _verifier)
    out = dd.dispatch_pre_resolved(
        pre_resolved={"subject_uri": THING, "verb_iri": "mesh:explain"},
        bound_slots={}, spoken_answer="", user_query="how do I add an engine",
        run_id="run-test-explain-identity", entitled_domains=["MESH"],
        acting_persona="DOCS_READER", ontology_url="http://engine-o",
        accept_slots=lambda *a, **k: None, user_email=CALLER,
    )
    assert out.kind == dd.FALL_BACK
    assert got.get("user_email") == CALLER, f"the verifier was called without the caller: {got!r}"


# ── the census: derived from the tree, partitioned, undecided fails ───────────────────────────


def _tracked_sources() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=_REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [
        p for p in out
        if not p.startswith("tests/") and "baml_client" not in p and "/." not in p
    ]


def _module_file(importer: str, node: ast.ImportFrom) -> str | None:
    parts = node.module.split(".") if node.module else []
    if node.level:
        base = Path(importer).parent
        for _ in range(node.level - 1):
            base = base.parent
        cands = [base.joinpath(*parts).with_suffix(".py"), base.joinpath(*parts, "__init__.py")]
    else:
        cands = []
        for root in (Path("src"), Path(".")):
            cands += [
                root.joinpath(*parts).with_suffix(".py"), root.joinpath(*parts, "__init__.py"),
            ]
    for c in cands:
        if (_REPO / c).is_file():
            return c.as_posix()
    return None


class _Parsed:
    def __init__(self, path: str) -> None:
        self.path = path
        self.tree = ast.parse((_REPO / path).read_text(encoding="utf-8"), filename=path)
        self.defs = {
            n.name for n in self.tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.aliases: dict[str, tuple[str, str]] = {}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.ImportFrom):
                target = _module_file(path, n)
                if target:
                    for a in n.names:
                        self.aliases[a.asname or a.name] = (target, a.name)

    def resolve(self, name: str) -> tuple[str, str] | None:
        if name in self.defs:
            return (self.path, name)
        return self.aliases.get(name)


def _functions(tree):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n


def _calls(fn):
    return (n for n in ast.walk(fn) if isinstance(n, ast.Call))


def _takes_and_uses_user_email(fn) -> bool:
    args = fn.args
    names = {a.arg for a in args.args + args.kwonlyargs + args.posonlyargs}
    if "user_email" not in names:
        return False
    return any(
        isinstance(n, ast.Name) and n.id == "user_email" and isinstance(n.ctx, ast.Load)
        for n in ast.walk(fn)
    )


def _posts_to_route(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], ast.JoinedStr):
        return False
    tail = call.args[0].values[-1]
    return isinstance(tail, ast.Constant) and str(tail.value).endswith(_ROUTE)


def _service_client(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "headers" and isinstance(kw.value, ast.Call):
            f = kw.value.func
            if isinstance(f, ast.Name) and f.id == "outbound_auth_headers":
                for k in kw.value.keywords:
                    if k.arg == "client_id" and isinstance(k.value, ast.Constant):
                        return str(k.value.value)
    return None


def _forwards_the_caller(expr) -> bool:
    """A hop forwards what it was handed (`user_email`), the run config's field of the same
    name (`config.user_email` — the supervisor op's copy, filled by the gateway at launch), or —
    at the entry — the VERIFIED identity (`<principal>.authz_id`). A literal, or any other name,
    is a hop that names someone else or nobody, and it fails exactly as dropping the keyword
    does."""
    if isinstance(expr, ast.Name):
        return expr.id == "user_email"
    return isinstance(expr, ast.Attribute) and expr.attr in ("user_email", "authz_id")


def _callee_name(call: ast.Call) -> str | None:
    """The function a call reaches: its own name, or the first argument of a `partial(...)`."""
    f = call.func
    is_partial = (isinstance(f, ast.Name) and f.id == "partial") or (
        isinstance(f, ast.Attribute) and f.attr == "partial"
    )
    if is_partial:
        f = call.args[0] if call.args else None
    return f.id if isinstance(f, ast.Name) else None


def _census():
    parsed = [_Parsed(p) for p in _tracked_sources()]
    sites: dict[str, list[str]] = {"THREADS": [], "SERVICE": [], "SCRIPT": [], "UNDECIDED": []}
    chain: set[tuple[str, str]] = set()
    for pf in parsed:
        for fn in _functions(pf.tree):
            for call in _calls(fn):
                if not _posts_to_route(call):
                    continue
                where = f"{pf.path}:{call.lineno} ({fn.name})"
                service = _service_client(call)
                if _takes_and_uses_user_email(fn):
                    sites["THREADS"].append(where)
                    chain.add((pf.path, fn.name))
                elif service:
                    sites["SERVICE"].append(f"{where} as {service}")
                elif pf.path.startswith("scripts/"):
                    sites["SCRIPT"].append(where)
                else:
                    sites["UNDECIDED"].append(where)

    # Close upward: a call to a function on the chain is a hop. It must pass `user_email=` on,
    # and when its own function takes and uses `user_email` that function joins the chain.
    dropped: list[str] = []
    changed = True
    while changed:
        changed = False
        for pf in parsed:
            for fn in _functions(pf.tree):
                for call in _calls(fn):
                    name = _callee_name(call)
                    if name is None or pf.resolve(name) not in chain:
                        continue
                    passed = [k.value for k in call.keywords if k.arg == "user_email"]
                    if not (passed and _forwards_the_caller(passed[0])):
                        where = f"{pf.path}:{call.lineno} ({fn.name} -> {name})"
                        if where not in dropped:
                            dropped.append(where)
                        continue
                    me = (pf.path, fn.name)
                    if me not in chain and _takes_and_uses_user_email(fn):
                        chain.add(me)
                        changed = True
    return sites, chain, dropped


def test_EVERY_POST_TO_THE_ROUTE_IS_DECIDED():
    sites, _, _ = _census()
    population = sum(len(v) for v in sites.values())
    assert population >= 1, "the census found no POST to the route; its matcher points at nothing"
    assert sites["UNDECIDED"] == [], (
        "a POST to /find_compatible_verbs that neither threads the caller, authenticates as a "
        f"named service, nor is an operator script: {sites['UNDECIDED']}"
    )
    assert sites["THREADS"], f"no POST carries the caller at all: {sites}"


def test_THE_CALLER_THREADS_FROM_THE_GATEWAY_TO_THE_POST_AND_NO_HOP_DROPS_IT():
    """The chain must reach `src/iagent/gateway.py`, where the caller's identity is verified;
    a pass-through that stops short of it threads a parameter nobody fills. And every call to a
    function on the chain passes `user_email=` the caller it was handed — a hop that drops it,
    or passes a literal, reads as nobody."""
    _, chain, dropped = _census()
    assert dropped == [], f"a call on the chain drops the caller: {dropped}"
    files = {f for f, _ in chain}
    assert "src/iagent/gateway.py" in files, (
        f"the caller never threads back to the gateway; the chain stops at {sorted(chain)}"
    )
    assert "src/iagent/defs/dynamic_supervisor.py" in files, (
        f"the supervisor's routing path does not carry the caller: {sorted(chain)}"
    )
