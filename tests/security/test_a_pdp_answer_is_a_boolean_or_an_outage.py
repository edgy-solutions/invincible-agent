"""A PDP answer is a JSON boolean, or it is an outage: never a truthy guess.

Architect ruling 2026-10-31: "a non-boolean `check` is a malformed PDP answer, which is the outage
class: 503, never a 403 (a 403 asserts policy said no)". lane/saf found `bool(r.json().get("check"))`
admitting `"false"`, `"no"` and `"0"` in `recipient_readers`; the same form stood at every Topaz
reader. `agent_fleet/utils/pdp_answer.py` reads the answer strictly, and a malformed one raises an
`httpx.DecodingError`, which each site's existing outage handler already catches.

Three legs:
  1. the reader, over a matrix of bodies;
  2. the CLASS, found by form: every function that names a PDP endpoint reads the answer strictly
     and never takes `bool(...)` of the field. The population is found by parsing the source, with
     a control that the parse saw every textual mention, and a control that the detector sees each
     defect form;
  3. the consumers: a malformed answer is a 503 where an outage is a 503 (finance's door, the
     gateway's raising checks, the three engine rail checks) and a deny where every failure is a
     deny (a fail-closed site), each against a control that the same double can admit.

Run:  uv run python -m pytest tests/security/test_a_pdp_answer_is_a_boolean_or_an_outage.py -q
"""
from __future__ import annotations

import ast
import io
import json as _json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from agent_fleet.utils.pdp_answer import MalformedPdpAnswer, check_answer, decision_answer  # noqa: E402

ENDPOINTS = ("/api/v3/directory/check", "/api/v2/authz/is")
STRICT_READERS = {"check_answer", "decision_answer"}
FIELDS = {"check", "is"}
SCANNED = ("agent_fleet", "src", "policy", "scripts")
SKIP_PARTS = {"tests", ".venv", "__pycache__", "baml_client", "node_modules"}

URL = "http://topaz.test"


def _resp(status: int = 200, *, json=None, content: bytes | None = None) -> httpx.Response:
    # The body is serialised here, so `json=None` is the JSON `null`, not an empty body.
    req = httpx.Request("POST", URL + ENDPOINTS[0])
    if content is None:
        content = _json.dumps(json).encode()
    return httpx.Response(status, content=content, request=req, headers={"content-type": "application/json"})


# ---- 1. the reader ------------------------------------------------------------------------------

MALFORMED_CHECK = [{"check": None}, {"check": "false"}, {"check": "no"}, {"check": "0"}, {"check": "true"},
                   {"check": 0}, {"check": 1}, {"check": []}, {"check": {}}]
MALFORMED_BODY = [[], None, "true", 1]


@pytest.mark.parametrize("body,want", [({"check": True}, True), ({"check": False}, False),
                                       ({}, False), ({"allowed": True}, False)])
def test_a_boolean_or_an_absent_check_is_an_answer(body, want):
    assert check_answer(_resp(json=body)) is want


@pytest.mark.parametrize("body", MALFORMED_CHECK + MALFORMED_BODY, ids=repr)
def test_anything_else_is_malformed(body):
    with pytest.raises(MalformedPdpAnswer):
        check_answer(_resp(json=body))


@pytest.mark.parametrize("content", [b"", b"<html>bad gateway</html>", b"{\"check\": tru"])
def test_a_body_that_is_not_json_is_malformed(content):
    with pytest.raises(MalformedPdpAnswer):
        check_answer(_resp(content=content))


def test_malformed_is_the_transport_failure_class():
    # The property every site relies on: its outage handler catches an httpx.HTTPError. And a
    # body that is not JSON raised a ValueError before, so a caller that caught that still does.
    assert issubclass(MalformedPdpAnswer, httpx.HTTPError)
    assert issubclass(MalformedPdpAnswer, ValueError)


def _decisions(*ds):
    return _resp(json={"decisions": list(ds)})


@pytest.mark.parametrize("response,want", [
    (_decisions({"decision": "allowed", "is": True}), True),
    (_decisions({"decision": "allowed", "is": False}), False),
    (_decisions({"decision": "allowed"}), False),
    (_decisions({"decision": "other", "is": True}), False),
    (_decisions(), False),
    (_resp(json={}), False),
], ids=["is-true", "is-false", "is-absent", "other-decision", "no-decisions", "no-decisions-key"])
def test_a_decision_is_its_boolean_is(response, want):
    assert decision_answer(response, "allowed") is want


@pytest.mark.parametrize("response", [
    _decisions({"decision": "allowed", "is": "false"}),
    _decisions({"decision": "allowed", "is": None}),
    _decisions({"decision": "allowed", "is": 1}),
    _decisions("allowed"),
    _resp(json={"decisions": {"allowed": True}}),
    _resp(json=[]),
    _resp(content=b"<html/>"),
], ids=["is-string", "is-null", "is-int", "decision-not-object", "decisions-not-list", "body-list", "not-json"])
def test_a_malformed_decision_is_malformed(response):
    with pytest.raises(MalformedPdpAnswer):
        decision_answer(response, "allowed")


# ---- 2. the class, by form ----------------------------------------------------------------------

def _files() -> list[Path]:
    out = []
    for top in SCANNED:
        for p in sorted((REPO / top).rglob("*.py")):
            if not SKIP_PARTS & set(p.relative_to(REPO).parts):
                out.append(p)
    return out


def _name(func: ast.AST) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _endpoint_constants(tree: ast.AST) -> list[ast.Constant]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and any(e in n.value for e in ENDPOINTS)]


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _sites(source: str) -> dict[str, ast.AST]:
    """Each function whose CODE (not its docstring) names a PDP endpoint, keyed by qualified name."""
    tree = ast.parse(source)
    parents: dict[int, tuple[ast.AST, str]] = {}

    def index(node, qual):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{qual}.{child.name}" if qual else child.name
                parents[id(child)] = (child, q)
                index(child, q)
            elif isinstance(child, ast.ClassDef):
                index(child, f"{qual}.{child.name}" if qual else child.name)
            else:
                index(child, qual)
    index(tree, "")
    docs = _docstrings(tree)
    owner: dict[int, tuple[ast.AST, str]] = {}

    def assign(node, current):
        for child in ast.iter_child_nodes(node):
            nxt = parents.get(id(child), current)
            owner[id(child)] = nxt
            assign(child, nxt)
    assign(tree, None)
    found = {}
    for c in _endpoint_constants(tree):
        if id(c) in docs:
            continue
        fn = owner.get(id(c))
        key = fn[1] if fn else "<module>"
        found[key] = fn[0] if fn else tree
    return found


def _problems(fn: ast.AST) -> list[str]:
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    strict = any(_name(c.func) in STRICT_READERS for c in calls) or any(
        _name(c.func) == "isinstance" and len(c.args) == 2 and _name(c.args[1]) == "bool" for c in calls)
    truthy = [c for c in calls if _name(c.func) == "bool" and any(
        isinstance(n, ast.Constant) and n.value in FIELDS for n in ast.walk(c))]
    out = []
    if not strict:
        out.append("reads the answer without check_answer/decision_answer or an isinstance(_, bool) guard")
    if truthy:
        out.append(f"takes bool(...) of an answer field at line(s) {[c.lineno for c in truthy]}")
    return out


def _census() -> dict[str, ast.AST]:
    out = {}
    for p in _files():
        for qual, fn in _sites(p.read_text(encoding="utf-8")).items():
            out[f"{p.relative_to(REPO).as_posix()}::{qual}"] = fn
    return out


CENSUS = _census()


def test_the_parse_saw_every_mention_of_an_endpoint():
    # Control: per file, the endpoint strings the AST holds plus those in comments equal the raw
    # text's count, so the census below cannot be quietly short of a reader.
    pat = re.compile("|".join(re.escape(e) for e in ENDPOINTS))
    for p in _files():
        text = p.read_text(encoding="utf-8")
        raw = len(pat.findall(text))
        if not raw:
            continue
        in_ast = sum(len(pat.findall(c.value)) for c in _endpoint_constants(ast.parse(text)))
        in_comments = sum(len(pat.findall(t.string)) for t in tokenize.generate_tokens(io.StringIO(text).readline)
                          if t.type == tokenize.COMMENT)
        assert in_ast + in_comments == raw, (p.relative_to(REPO).as_posix(), raw, in_ast, in_comments)


def test_the_census_finds_readers():
    assert len(CENSUS) >= 2, sorted(CENSUS)
    assert all("::" in k and not k.endswith("::<module>") for k in CENSUS), sorted(CENSUS)


def _tracked_sources() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if not SKIP_PARTS & set(Path(f).parts)]


def test_every_tracked_file_that_names_an_endpoint_is_scanned():
    # Control on the scope: drop a directory from SCANNED and its readers would leave the census
    # with nothing red. Every tracked non-test source that names an endpoint must be a scanned file.
    pat = re.compile("|".join(re.escape(e) for e in ENDPOINTS))
    scanned = {p.relative_to(REPO).as_posix() for p in _files()}
    naming = [f for f in _tracked_sources() if pat.search((REPO / f).read_text(encoding="utf-8", errors="replace"))]
    assert naming, "git ls-files found no reader at all: the control cannot see"
    assert not [f for f in naming if f not in scanned], [f for f in naming if f not in scanned]


def test_every_read_of_an_answer_field_is_in_the_census():
    # The census finds a reader by the endpoint it names. A reader whose URL arrives some other way
    # would still read the field by name: every `.get("check")` / `["check"]` (and `"is"`) in a
    # tracked source must sit inside a census function, or in the strict reader itself.
    census_fns = {}
    for key, fn in CENSUS.items():
        census_fns.setdefault(key.split("::")[0], []).append((fn.lineno, fn.end_lineno))
    stray = []
    for f in _tracked_sources():
        if f == "agent_fleet/utils/pdp_answer.py":
            continue
        tree = ast.parse((REPO / f).read_text(encoding="utf-8", errors="replace"))
        for n in ast.walk(tree):
            key = None
            if isinstance(n, ast.Call) and _name(n.func) == "get" and n.args:
                key = n.args[0]
            elif isinstance(n, ast.Subscript):
                key = n.slice
            if isinstance(key, ast.Constant) and key.value in FIELDS and not any(
                    a <= n.lineno <= b for a, b in census_fns.get(f, [])):
                stray.append(f"{f}:{n.lineno}")
    assert not stray, stray


@pytest.mark.parametrize("site", sorted(CENSUS))
def test_every_pdp_reader_reads_strictly(site):
    assert not _problems(CENSUS[site]), (site, _problems(CENSUS[site]))


_BAD = {
    "bool-of-check": 'def f(r):\n    httpx.post("http://t/api/v3/directory/check")\n'
                     '    return bool(r.json().get("check"))\n',
    "bool-of-is": 'async def f(c):\n    r = await c.post(f"{U}/api/v2/authz/is")\n'
                  '    for d in r.json().get("decisions", []):\n        return bool(d.get("is", False))\n',
    "bare-subscript": 'def f(r):\n    r = c.post("/api/v3/directory/check")\n    return r.json()["check"]\n',
    "strict-then-bool": 'def f(r):\n    r = c.post("/api/v3/directory/check")\n    check_answer(r)\n'
                        '    return bool(r.json().get("check"))\n',
    "method": 'class C:\n    def f(self):\n        r = self.c.post("/api/v3/directory/check")\n'
              '        return bool(r.json().get("check", False))\n',
}
_GOOD = {
    "helper": 'def f(r):\n    r = c.post("/api/v3/directory/check")\n    return check_answer(r)\n',
    "decision": 'def f(r):\n    r = c.post(f"{U}/api/v2/authz/is")\n    return decision_answer(r, "allowed")\n',
    "inline": 'def f(r):\n    r = c.post("/api/v3/directory/check")\n    v = r.json().get("check", False)\n'
              '    if not isinstance(v, bool):\n        raise ValueError(v)\n    return v\n',
    "docstring-only": 'def f():\n    """Calls `/api/v3/directory/check`."""\n    return bool(x.get("check"))\n',
}


@pytest.mark.parametrize("name", sorted(_BAD))
def test_the_detector_sees_each_defect_form(name):
    sites = _sites(_BAD[name])
    assert len(sites) == 1, sites
    assert _problems(next(iter(sites.values()))), name


@pytest.mark.parametrize("name", sorted(_GOOD))
def test_the_detector_passes_a_strict_reader(name):
    assert not any(_problems(fn) for fn in _sites(_GOOD[name]).values()), name


# ---- 3. the consumers ---------------------------------------------------------------------------

CONSUMER_BODIES = [{"check": "false"}, {"check": "0"}, {"check": None}, {"check": 1}, []]


@pytest.fixture
def topaz(monkeypatch):
    """Every `httpx.Client` answers the body in `topaz['body']`."""
    state = {"body": {"check": True}}
    real = httpx.Client

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: httpx.Response(200, json=state["body"], request=req))
        return real(*a, **k)

    monkeypatch.setattr(httpx, "Client", factory)
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", URL)
    return state


def _rail_checks():
    from agent_fleet.utils.export_capability import can_export
    from agent_fleet.utils.program_membership import can_view_program
    from agent_fleet.utils.recipient_readers import can_read_recipient
    return {"can_view_program": lambda: can_view_program("P1", "alice@example.com"),
            "can_export": lambda: can_export("profile", "alice@example.com"),
            "can_read_recipient": lambda: can_read_recipient("owner", "scope", "alice@example.com")}


@pytest.mark.parametrize("check", ["can_view_program", "can_export", "can_read_recipient"])
@pytest.mark.parametrize("body", CONSUMER_BODIES, ids=repr)
def test_a_rail_check_raises_on_a_malformed_answer(topaz, check, body):
    call = _rail_checks()[check]
    assert call() is True  # control: the same double admits on a true
    topaz["body"] = body
    with pytest.raises(httpx.HTTPError):
        call()


@pytest.mark.parametrize("body", CONSUMER_BODIES, ids=repr)
def test_finance_answers_503_not_403_on_a_malformed_answer(topaz, body):
    from fastapi import HTTPException

    from agent_fleet.finance_agent import main as engine
    assert engine._require_visible("P1", "alice@example.com") is None  # control: admitted
    topaz["body"] = {"check": False}
    with pytest.raises(HTTPException) as no:
        engine._require_visible("P1", "alice@example.com")
    assert no.value.status_code == 403  # control: a real "no" is a 403
    topaz["body"] = body
    with pytest.raises(HTTPException) as got:
        engine._require_visible("P1", "alice@example.com")
    assert got.value.status_code == 503, got.value.detail


@pytest.mark.parametrize("fn", ["can_act_or_unavailable", "can_invoke_or_unavailable"])
@pytest.mark.parametrize("body", CONSUMER_BODIES, ids=repr)
def test_the_gateway_check_is_unavailable_on_a_malformed_answer(topaz, monkeypatch, fn, body):
    from iagent import human_tasks
    from iagent.authz import AuthorizationUnavailable
    monkeypatch.setattr(human_tasks, "_TOPAZ_DIRECTORY_URL", URL)
    call = getattr(human_tasks, fn)
    assert call("subject", "alice@example.com") is True  # control
    topaz["body"] = body
    with pytest.raises(AuthorizationUnavailable):
        call("subject", "alice@example.com")


@pytest.mark.parametrize("body", CONSUMER_BODIES, ids=repr)
def test_a_fail_closed_site_denies_a_malformed_answer(monkeypatch, body):
    from agent_fleet.docs_agent import entitlement
    state = {"body": {"check": True}}
    monkeypatch.setattr(entitlement, "TOPAZ_DIRECTORY_URL", URL)
    monkeypatch.setattr(entitlement.httpx, "post",
                        lambda url, **k: httpx.Response(200, json=state["body"], request=httpx.Request("POST", url)))
    assert entitlement.can_invoke("alice@example.com", "cap") is True  # control
    state["body"] = body
    assert entitlement.can_invoke("alice@example.com", "cap") is False
