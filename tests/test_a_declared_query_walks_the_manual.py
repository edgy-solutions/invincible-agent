"""The fault walk is declared data: one verb, read by name, walked over the fixture graph.

Dispatch item 2: the openddil-lab YAML's walk verb is now a DECLARED QUERY
(`agent_fleet/utils/declared_query.py`). The runner renders its params, the executor posts only the
verb's NAME and VALUES to engine-o's `/declared_query`, and engine-o runs the selects it loads from
its OWN policy tree.

What this file seals, and what each expectation is derived from:

* A. The walk for MRAD-ARR-0417 equals GROUND-TRUTH.json's citations, with GT's `DMC-` prefix
  stripped. GT is a DRAFT (ADR-0046 v2 §9). Its `bit_text` differs from the graph's literal in case
  and full stop only; the arm asserts exactly that difference, so a third spelling reds.
* B. Every DMC the walk or an option cites is the `rdfs:label` of exactly one module in the graph,
  of the kind its citation slot names. A DMC is never invented.
* C. Four options, the spares row, and the part read off the IPD. The option set is the
  template's; its divergence from GT's options is a finding, not asserted here.
* D. The wire carries a name and values, never a query.
* E. The verb's declared capability is asked; a refusal posts nothing and offers nothing.
* F. A fault the manual does not know is refused at the walk, never rendered into options.
* G. Engine-o serves by name from its own tree. A body's extra `sparql` is not read; an unknown
  verb is 404, bad params are 422, and a stub is never served as a query.
* H. No Python on the path names the domain it reads.
* I. A numeric path segment indexes a list. A position the list does not have is refused, never
  rendered blank, so a walk with one remove/install module cannot fill a second citation.
* J-K. Only a registry definition may name a declared query. From the registry, the read is one
  journaled `ctx.run`.
* L-N. A refused capability is terminal 403. A user caller is asked as itself and sends its own
  token. A 4xx is terminal; a 5xx is left to retry.
* G (shape). An answer that does not fit its declared cardinality is 422, never the store's
  first row.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import rdflib
from rdflib.namespace import RDF, RDFS

from tests.test_a_case_runs_from_trigger_to_terminal import wd
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- fixtures by name
    ACK, DECIDE, _MRAD_TTL, _NEAREST, _Resp, _event, _options, _real_policy, _run, _shaped_walk,
    registered,
)
import spo_step_executor as ex  # noqa: E402 -- the SAME module object main imports the call from
from agent_fleet.utils.declared_query import build_selects

REPO = Path(__file__).resolve().parents[1]
GT = json.loads((_MRAD_TTL.parent / "GROUND-TRUTH.json").read_text(encoding="utf-8"))
MIL = rdflib.Namespace("http://edgy-solutions.com/ontology/mil#")
WALK_VERB = "s1000d_fault_walk"
KNOWN = GT["bit_code"]
UNKNOWN = "MRAD-NOT-0000"


def _graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(str(_MRAD_TTL), format="turtle")
    return g


def _strip(v):
    """GT's citations as the walk serves them: canonical labels, no `DMC-`, no `*_note` keys."""
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items() if not k.endswith("_note")}
    if isinstance(v, list):
        return [_strip(x) for x in v]
    if isinstance(v, str) and v.startswith("DMC-"):
        return v[len("DMC-"):]
    return v


@pytest.fixture(autouse=True)
def wire(monkeypatch):
    """The executor's two outbound seams, RECORDED: the capability check and the POST. The POST
    runs the real declaration's selects over the committed fixture (`_shaped_walk`)."""
    rec = {"asked": [], "posts": [], "allow": True}

    def _can(cap, who, **kw):
        rec["asked"].append((cap, who))
        return rec["allow"]

    def _post(url, json, headers, timeout):
        if "/internal/cases/" in url:
            # the runner's writes at `released`, not the walk's wire: accepted, not recorded here
            return _Resp({})
        rec["posts"].append({"url": url, "json": json, "headers": dict(headers)})
        decl, shaped = _shaped_walk(json["verb"], json["params"])
        return _Resp({"verb": decl.verb, "domain": decl.domain, "selects": shaped})

    monkeypatch.setattr(ex, "check_can_invoke", _can)
    monkeypatch.setattr(ex, "mint_case_runner_token", lambda **kw: "case-runner-token")
    monkeypatch.setattr(ex.requests, "post", _post)
    return rec


def _walk(c, key="EV-1"):
    return c.ctx(key).state["instance:2"]["outputs"]["maint_fault_propose"]["walk"]


def _offered(rows):
    """The approval tasks the proposal opened: anything registered is something offered."""
    return list(rows)


# ── A. GROUND TRUTH ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_THE_WALK_CITES_WHAT_GROUND_TRUTH_CITES(registered):
    _, c = await _run(_event(), [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    walk = _walk(c)
    assert walk["citations"] == _strip(GT["citations"]), walk
    assert walk["bit_code"] == KNOWN, walk
    # bit_text is the GRAPH's literal, read off the fault code node, not GT's spelling.
    g = _graph()
    [fc] = list(g.subjects(MIL.hasFaultCodeValue, rdflib.Literal(KNOWN)))
    assert walk["bit_text"] == str(g.value(fc, MIL.hasFaultCodeText)), walk
    # GT's spelling differs by case and the full stop ONLY.
    assert walk["bit_text"] != GT["bit_text"]
    assert walk["bit_text"].casefold().rstrip(".") == GT["bit_text"].casefold().rstrip("."), walk


# ── B. NO DMC IS INVENTED ───────────────────────────────────────────────────────────────────

_SLOT_KIND = {
    "fault_isolation": MIL.FaultIsolationDataModule,
    "remove_install": MIL.ProcedureDataModule,
    "ipd": MIL.IllustratedPartsDataModule,
}


@pytest.mark.asyncio
async def test_B_EVERY_CITED_DMC_IS_ONE_MODULE_OF_ITS_SLOTS_KIND_IN_THE_GRAPH(registered):
    _, c = await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    walk, opts, g = _walk(c), _options(c), _graph()

    def _one(label):
        subs = list(g.subjects(RDFS.label, rdflib.Literal(label)))
        assert len(subs) == 1, (label, subs)
        return subs[0]

    cited = {}
    for slot, cit in walk["citations"].items():
        dmcs = cit["dmc"] if isinstance(cit["dmc"], list) else [cit["dmc"]]
        assert dmcs and all(dmcs), (slot, cit)
        for d in dmcs:
            node = _one(d)
            if slot in _SLOT_KIND:
                assert (node, RDF.type, _SLOT_KIND[slot]) in g, (slot, d)
            else:
                assert slot == "planning_interval", slot
                assert g.value(node, MIL.hasPlanningInterval) is not None, d
            cited[d] = slot
    assert set(cited.values()) == set(_SLOT_KIND) | {"planning_interval"}, cited
    # The options cite ONLY what the walk cited, and every task_ref carries a code.
    refs = [r["data_module_code"] for o in opts for r in o["task_refs"]]
    assert refs and set(refs) <= set(cited), (refs, cited)


# ── C. FOUR OPTIONS, THE SPARES ROW, THE PART ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_C_FOUR_OPTIONS_CARRY_THE_IPD_PART_AND_THE_RESUPPLY_CARRIES_THE_SPARES_ROW(registered):
    ev = _event()
    _, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    opts, ipd = _options(c), _strip(GT["citations"]["ipd"])
    assert len(opts) == 4, opts
    parts = [p for o in opts for p in o["parts"]]
    assert parts, opts
    for p in parts:
        assert (p["part_ref"], p["quantity"], p["icn"], p["hotspot_id"]) == (
            ipd["part_number"], ipd["quantity"], ipd["icn"], ipd["hotspot_id"]), p
        assert type(p["quantity"]) is int, p
    [resupply] = [o for o in opts if "nearest_spare" in o]
    assert resupply["nearest_spare"] == _NEAREST == ev["picture"]["nearest_spare"], resupply


# ── D. THE WIRE ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_D_THE_WIRE_CARRIES_THE_VERBS_NAME_AND_VALUES_NEVER_A_QUERY(registered, wire):
    await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    [post] = wire["posts"]
    assert post["url"].endswith("/declared_query"), post["url"]
    assert post["json"] == {"verb": WALK_VERB, "params": {"fault_code": KNOWN}}, post["json"]
    assert "select" not in json.dumps(post["json"]).casefold()
    assert post["headers"].get("Authorization", "").startswith("Bearer "), post["headers"]


# ── E. THE CAPABILITY ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_E_THE_DECLARED_CAPABILITY_IS_ASKED_AND_A_REFUSAL_POSTS_AND_OFFERS_NOTHING(
        registered, wire):
    declared = wd.load_query_verbs()[WALK_VERB].capability
    assert declared == "mesh:s1000dFaultWalk"
    await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    assert [cap for cap, _ in wire["asked"]] == [declared], wire["asked"]

    wire.update(asked=[], posts=[], allow=False)
    registered.clear()
    with pytest.raises(AssertionError, match="not authorized"):
        await _run(_event(), [(DECIDE, "replace_now")])
    assert [cap for cap, _ in wire["asked"]] == [declared], wire["asked"]
    assert wire["posts"] == [] and _offered(registered) == [], (wire, registered)


# ── F. AN UNKNOWN FAULT ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_F_A_FAULT_THE_MANUAL_DOES_NOT_KNOW_IS_REFUSED_AT_THE_WALK_NOT_RENDERED(
        registered, wire):
    ev = _event()
    ev["fault"]["fault_code"] = UNKNOWN
    with pytest.raises(AssertionError, match=r"declared query s1000d_fault_walk\.returns"):
        await _run(ev, [(DECIDE, "replace_now")])
    # The walk DID run (the refusal is the manual's silence, not a skipped read) ...
    assert [p["json"]["params"] for p in wire["posts"]] == [{"fault_code": UNKNOWN}], wire["posts"]
    # ... and nothing was offered for approval.
    assert _offered(registered) == [], registered


# ── G. ENGINE-O SERVES BY NAME ──────────────────────────────────────────────────────────────

@pytest.fixture
def engine_o(monkeypatch):
    from fastapi.testclient import TestClient
    from agent_fleet.ontology_service import main as eo

    ran: list = []
    ds = rdflib.Dataset(default_union=True)
    ds.parse(str(_MRAD_TTL), format="turtle")

    async def _sparql(q, domain="UNSET", **kw):
        ran.append((q, domain))
        res = ds.query(q)
        cols = [str(v) for v in res.vars]
        return [{v: (str(r[v]) if r[v] is not None else None) for v in cols} for r in res]

    monkeypatch.setattr(eo, "execute_sparql", _sparql)
    # A server exception is a 500 the CALLER sees, never a test-side raise: an arm that expects
    # a 404 must be red when the route crashes instead of refusing.
    return TestClient(eo.app, raise_server_exceptions=False), ran, eo


def test_G_ENGINE_O_RUNS_ITS_OWN_DECLARATION_AND_IGNORES_A_BODYS_QUERY(engine_o):
    client, ran, _ = engine_o
    decl = wd.load_query_verbs()[WALK_VERB]
    expected = build_selects(decl, {"fault_code": KNOWN})
    r = client.post("/declared_query", json={
        "verb": WALK_VERB, "params": {"fault_code": KNOWN},
        "sparql": "SELECT ?s ?p ?o WHERE { ?s ?p ?o }"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["verb"], body["domain"]) == (WALK_VERB, decl.domain), body
    assert body["selects"] == _shaped_walk(WALK_VERB, {"fault_code": KNOWN})[1], body
    assert sorted(ran) == sorted((q, decl.domain) for q in expected.values()), ran


@pytest.mark.parametrize("body,status", [
    ({"verb": "no_such_verb", "params": {}}, 404),
    ({"verb": WALK_VERB, "params": {}}, 422),
    ({"verb": WALK_VERB, "params": {"fault_code": KNOWN, "extra": "x"}}, 422),
    ({"verb": WALK_VERB, "params": {"fault_code": "x } GRAPH <urn:a> { ?s ?p ?o"}}, 422),
], ids=["unknown-verb", "missing-param", "extra-param", "graph-clause-param"])
def test_G_A_REQUEST_THE_REGISTRY_CANNOT_SERVE_RUNS_NOTHING(engine_o, body, status):
    client, ran, _ = engine_o
    r = client.post("/declared_query", json=body)
    assert r.status_code == status, r.text
    assert ran == [], ran


def test_G_A_STUB_IS_NEVER_SERVED_AS_A_QUERY(engine_o, monkeypatch, tmp_path):
    client, ran, eo = engine_o
    (tmp_path / "canned.yaml").write_bytes(
        b"verb: canned_read\nstub: true\nretired_by: test\nreturns: {x: 1}\n")
    monkeypatch.setattr(eo, "verb_dirs", lambda root: [tmp_path])
    r = client.post("/declared_query", json={"verb": "canned_read", "params": {}})
    assert r.status_code == 404, r.text
    assert ran == [], ran


# ── H. NO PYTHON NAMES THE DOMAIN ───────────────────────────────────────────────────────────

# `default` contains `fault`; the lookbehind keeps the commonest English word out of the class.
_DOMAIN_NAMES = re.compile(r"maint|s1000d|mrad|(?<!de)fault|\bdmc\b|\bipd\b|remove_install",
                           re.IGNORECASE)


def _tree(rel):
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _function(rel, name):
    [fn] = [n for n in ast.walk(_tree(rel))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    return fn


def _runner_branch():
    """The `elif` that dispatches a declared query, located by its TEST (`... in queries` and no
    `stubs`), never by a line number. Exactly one. Its BODY is the subject."""
    hits = [n for n in ast.walk(_tree("agent_fleet/restate_analyst/main.py"))
            if isinstance(n, ast.If)
            and any(isinstance(c, ast.Compare) and any(isinstance(o, ast.In) for o in c.ops)
                    and isinstance(c.comparators[0], ast.Name) and c.comparators[0].id == "queries"
                    for c in ast.walk(n.test))
            and not any(isinstance(c, ast.Name) and c.id == "stubs" for c in ast.walk(n.test))]
    assert len(hits) == 1, [ast.unparse(h.test) for h in hits]
    return ast.Module(body=hits[0].body, type_ignores=[])


def _code_words(node) -> list[str]:
    """What the CODE spells under `node`: every identifier, attribute, argument, keyword, import
    and string constant, minus docstrings. Comments never reach the AST. A docstring that SAYS the
    mechanism is domain-agnostic is prose about the code, not the code naming its domain."""
    docs = {id(n.body[0].value) for n in ast.walk(node)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
        elif isinstance(n, ast.arg):
            out.append(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            out.append(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, ast.alias):
            out.extend(x for x in (n.name, n.asname) if x)
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.append(n.module)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            out.append(n.value)
    return out


def _hits(node) -> list[str]:
    return sorted({m.group(0) for w in _code_words(node) for m in _DOMAIN_NAMES.finditer(w)})


def test_H_THE_DETECTOR_SEES_EACH_NAME_AND_NOT_THE_WORD_DEFAULT():
    for word in ("maint_fault", "S1000D", "MRAD", "fault_code", "Fault", "dmc", "IPD",
                 "remove_install"):
        assert _DOMAIN_NAMES.search(word), word
    for word in ("default", "default_factory", "DEFAULT", "Deny-by-default"):
        assert not _DOMAIN_NAMES.search(word), word
    # Through the AST reader: every place code can spell a name is seen ...
    for snippet in ("fault_code = 1", "x.ipd", "def f(dmc): pass", "f(maint=1)",
                    "def maint_walk(): pass", "class Mrad: pass", "import s1000d",
                    "from s1000d import x", "x = 'remove_install'",
                    "def f():\n    'doc'\n    return 'MAINTENANCE'"):
        assert _hits(ast.parse(snippet)), snippet
    # ... and prose is not.
    assert _hits(ast.parse("def f():\n    'a maintenance walk'\n    return 1  # fault\n")) == []


_PATH = {
    "declared_query.py": lambda: _tree("agent_fleet/utils/declared_query.py"),
    "execute_declared_query": lambda: _function(
        "agent_fleet/restate_analyst/spo_step_executor.py", "execute_declared_query"),
    "runner-branch": _runner_branch,
    "engine-o-route": lambda: _function(
        "agent_fleet/ontology_service/main.py", "declared_query_route"),
}


@pytest.mark.parametrize("where", list(_PATH))
def test_H_NO_PYTHON_ON_THE_PATH_NAMES_THE_DOMAIN_IT_READS(where):
    node = _PATH[where]()
    assert len(_code_words(node)) > 10, where
    assert _hits(node) == [], (where, _hits(node))


# ── I. A LIST IS CITED BY POSITION, AND A SHORT ONE IS REFUSED ──────────────────────────────

from tests.test_a_case_runs_from_trigger_to_terminal import _refused, main  # noqa: E402

_LIST_CTX = {"walk": {"dmc": ["A-520A", "A-720A"], "one": ["A-520A"], "keyed": {"0": "zero"},
                      "nested": [{"x": "deep"}], "counts": [3]}}


def test_I_A_NUMERIC_SEGMENT_INDEXES_A_LIST_AND_NOTHING_ELSE():
    assert main._render("{walk.dmc.0}", _LIST_CTX, where="t") == "A-520A"
    assert main._render("{walk.dmc.1}", _LIST_CTX, where="t") == "A-720A"
    assert main._render("{walk.nested.0.x}", _LIST_CTX, where="t") == "deep"
    # A dict whose key IS that string is an ordinary key lookup.
    assert main._render("{walk.keyed.0}", _LIST_CTX, where="t") == "zero"
    # A WHOLE placeholder with a numeric segment yields the RAW element, as any whole one does:
    # an int stays an int (a quantity cited by position is still a number).
    whole = main._render("{walk.counts.0}", _LIST_CTX, where="t")
    assert whole == 3 and isinstance(whole, int), repr(whole)


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [
    "{walk.one.1}",        # the walk found fewer modules than the template cites
    "{walk.dmc.2}",        # past the end
    "{walk.keyed.1}",      # a numeric key a dict does not have
    "{walk.dmc.x}",        # a name segment on a list
    "{walk.0}",            # a numeric segment on a dict without that key
    "see {walk.one.1}",    # interpolated: never a blank in a sentence
])
async def test_I_A_POSITION_THE_LIST_DOES_NOT_HAVE_IS_REFUSED_NOT_BLANK(template):
    async def _go():
        return main._render(template, _LIST_CTX, where="t")
    await _refused(_go(), 400)


# ── J-N. THE RUNNER, THE EXECUTOR AND ENGINE-O AT THEIR EDGES ───────────────────────────────

import requests  # noqa: E402
import restate  # noqa: E402
from tests.test_a_case_record_is_written_by_the_executor import (  # noqa: E402
    _Ctx, _TRIGGER, _answer, _await, _drive,
)

_WALK_STEP = {"kind": "spo_operation", "id": "walk", "subject": "urn:s", "verb": WALK_VERB}
_WALK_TRIGGER = {**_TRIGGER, "fault": {**_TRIGGER["fault"], "fault_code": KNOWN}}


@pytest.mark.asyncio
async def test_J_A_CALLER_SUPPLIED_DEFINITION_MAY_NOT_NAME_A_DECLARED_QUERY(registered, wire):
    """The verb's capability, domain and selects are the registry's; a caller who could name it
    from its own definition would choose when engine-o reads. Refused before the first step."""
    ctx = _Ctx({"approval_first": _answer("ok")})
    with pytest.raises(restate.TerminalError) as exc:
        await _drive([_await("first"), _WALK_STEP], ctx=ctx, trigger=_WALK_TRIGGER)
    assert "only a registry definition may" in str(exc.value), str(exc.value)
    assert registered == [] and wire["posts"] == [] and ctx.runs == [], (registered, ctx.runs)


@pytest.mark.asyncio
async def test_K_FROM_THE_REGISTRY_THE_READ_IS_ONE_JOURNALED_RUN(registered, wire):
    """The control for J (same steps, registry-sourced, so it runs) and the journal: the read is
    an effect, so a replay must return the recorded answer, never re-ask engine-o."""
    ctx, env = await _drive([_WALK_STEP], from_registry=True, trigger=_WALK_TRIGGER)
    assert ctx.runs.count("exec_walk") == 1, ctx.runs
    assert len(wire["posts"]) == 1, wire["posts"]
    assert env["outputs"]["seal_def"]["walk"]["citations"] == _strip(GT["citations"]), env["outputs"]


@pytest.mark.asyncio
async def test_L_A_REFUSED_CAPABILITY_IS_TERMINAL_403_NOT_A_RETRY(registered, wire):
    from tests.test_a_case_runs_from_trigger_to_terminal import _refused
    wire["allow"] = False
    msg = await _refused(_drive([_WALK_STEP], from_registry=True, trigger=_WALK_TRIGGER), 403)
    assert "not authorized" in msg and wire["posts"] == [], (msg, wire["posts"])


def test_M_A_USER_CALLER_IS_ASKED_AS_ITSELF_AND_SENDS_ITS_OWN_TOKEN(wire, monkeypatch):
    def _no_mint(**kw):
        raise AssertionError("a user-JWT call minted the case-runner credential")
    monkeypatch.setattr(ex, "mint_case_runner_token", _no_mint)
    decl = wd.load_query_verbs()[WALK_VERB]
    ex.execute_declared_query(decl, {"fault_code": KNOWN},
                              {"user_jwt": "user-jwt", "authz_id": "alice@x"})
    assert wire["asked"] == [(decl.capability, "alice@x")], wire["asked"]
    [post] = wire["posts"]
    assert post["headers"].get("Authorization") == "Bearer user-jwt", post["headers"]


class _Status(_Resp):
    def __init__(self, status):
        super().__init__({})
        self.status_code, self.text = status, f"status {status}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.text)


@pytest.mark.parametrize("status,terminal", [
    (401, 403), (403, 403), (404, 404), (422, 422), (500, None), (503, None)])
def test_N_A_4XX_IS_TERMINAL_AND_A_5XX_IS_LEFT_TO_RETRY(wire, monkeypatch, status, terminal):
    monkeypatch.setattr(ex.requests, "post", lambda *a, **kw: _Status(status))
    decl = wd.load_query_verbs()[WALK_VERB]
    # ANY exception, then its type: the wrong class escaping is this arm's red, not a crash.
    with pytest.raises(Exception) as exc:
        ex.execute_declared_query(decl, {"fault_code": KNOWN}, {})
    if terminal is None:
        assert type(exc.value) is requests.HTTPError, repr(exc.value)
        return
    assert isinstance(exc.value, ex.StepFailAndRelease), repr(exc.value)
    assert exc.value.status_code == terminal, (status, exc.value.status_code)


def test_G_AN_ANSWER_THAT_DOES_NOT_FIT_ITS_SHAPE_IS_422_NOT_THE_STORES_FIRST_ROW(
        engine_o, monkeypatch):
    """Every row comes back twice: a `one` select now has two candidates, and choosing one would
    be the store's order. Refused, with the select named."""
    client, ran, eo = engine_o
    once = eo.execute_sparql

    async def _twice(q, domain="UNSET", **kw):
        rows = await once(q, domain=domain, **kw)
        return rows + rows
    monkeypatch.setattr(eo, "execute_sparql", _twice)
    r = client.post("/declared_query", json={"verb": WALK_VERB, "params": {"fault_code": KNOWN}})
    assert r.status_code == 422, r.text
    assert "declared `one` and matched 2 rows" in r.json()["detail"], r.text
