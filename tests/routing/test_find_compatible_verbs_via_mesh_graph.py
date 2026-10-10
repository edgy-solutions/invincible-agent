"""`/find_compatible_verbs` THROUGH `MeshGraph.verbs_for`, AS THE PERSON: THE FLAG ON/OFF SEAL.

`COMPATIBLE_VERBS_VIA_MESH` moves LEG 1 (coverage) onto `Neo4jGraph.verbs_for`, whose statement
`tests/test_mesh_graph_conforms.py::test_verbs_for_IS_THE_ROUTES_LEG_1` holds equal to the route's
own, and reads LEG 3's universal-referent confirmation from Jena as the person the request names
in `on_behalf_of`. With the flag off, LEG 3's read is made as `_POOL_READ_INITIATOR`, a service,
and is refused before it is sent (`test_the_pool_reaches_the_universal_referent.py` seals that).

WHAT THE FLAG MAY CHANGE, AND NOTHING ELSE:

- the pool gains the universal leg's rows, because the explain read is finally made as someone;
- a request with no person is a 400, and a hop bound `verbs_for` does not walk is a 400;
- a substrate failure is a 503 rather than a 500.

Every other verb, with the same rows in the store, is the same verb in the same order. The arm
that says so runs both paths against one leg-aware double that answers each leg by what the
statement it was handed contains, so a split that dropped or duplicated a leg answers differently.

`on_behalf_of` HERE IS THE GATEWAY'S WORD, NOT THE SDK'S. It names the person (the caller's
authz_id), and the route mints `Initiator(subject=person, kind="person")`. The SDK's
`Initiator.on_behalf_of` makes a delegate, which `MeshGraph` and `MeshOntology` reads refuse.

THE FLAG IS ON BY DEFAULT. What stood between it and its default was two callers that posted with no
person (`restate_analyst/spo_interview.py`, `spo_step_executor.py`); both now hand it down, and the
arms below derive the callers from the AST and hold every one to naming the person.

Run: uv run --frozen --extra agent-fleet pytest tests/routing/test_find_compatible_verbs_via_mesh_graph.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from iagent_mesh import Initiator
from tests.conftest import stub_modules

_REPO = Path(__file__).resolve().parents[2]
_SVC = _REPO / "agent_fleet" / "ontology_service"
_MOD_NAME = "engine_o_main__compatible_verbs_via_mesh_test"
_TEST_JENA_ENDPOINT = "http://ontology.invalid/ds/sparql"
_FLAG = "COMPATIBLE_VERBS_VIA_MESH"

PERSON = "seal-person@example.invalid"
SUBJECT = "http://invincible-agent/cost#ProductionLot"
#: A subclass two hops below SUBJECT: the same legs reach it at a greater distance.
CHILD_SUBJECT = "http://invincible-agent/cost#ProductionLotChild"
THING = "http://invincible-agent/mesh#Thing"

# Installed UNCONDITIONALLY, for this module's arms only, and put back after them by `stub_modules`:
# a guard that yields to whatever got there first makes the load depend on collection order
# (`tests/test_the_stub_harness_puts_sys_modules_back.py`). Nothing here asserts on what these
# recorded. `rdflib` is never replaced -- the explain arms parse real Turtle through it.
_ORIGINAL: dict[str, type] = {}

_SHIMMED = (
    "weaviate", "weaviate.classes", "weaviate.classes.query",
    "neo4j", "baml_client", "baml_client.types", "baml_client.type_builder",
    "llm_utils", "utils", "utils.weaviate_utils",
)


@pytest.fixture(scope="module")
def engine_o():
    """`main.py` under a unique name, with every `sys.modules` entry this load installs put back
    after the last arm (through `stub_modules`, which restores absence as well as values)."""
    doubles: dict[str, object] = {n: MagicMock() for n in _SHIMMED}
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _SVC / "main.py")
    mod = importlib.util.module_from_spec(spec)
    doubles[_MOD_NAME] = mod
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(_REPO))
        mp.syspath_prepend(str(_SVC))
        with stub_modules(doubles):
            spec.loader.exec_module(mod)
            # Taken once, so a second stage in one arm wraps the real ones, not the first's spies.
            # A module without the flag still loads and is staged (`raising=False` below), so
            # every arm reaches its own assertion against a route that predates the flag.
            graph = getattr(mod, "Neo4jGraph", None)
            if graph is None:
                from agent_fleet.ontology_service.mesh_graph import Neo4jGraph as graph
            _ORIGINAL.update(jena=type(mod._JENA_ONTOLOGY), graph=graph)
            yield mod


# ── the doubles ──────────────────────────────────────────────────────────────────────────────


def _row(verb: str, compatibility: str, *, hops: int = 1, domains=("COST",)) -> dict:
    return {
        "verb_iri": f"http://invincible-agent/cost#{verb}",
        "verb_local": verb,
        "input_uri": SUBJECT,
        "output_uri": SUBJECT,
        "endpoint_url": f"http://engine.invalid/{verb}",
        "owner_persona": None,
        "domains": list(domains),
        "cost_class": "fast",
        "requires_human_approval": False,
        "arity": None,
        "required_args": "lot,period",
        "slots": "[]",
        "hops": hops,
        "compatibility": compatibility,
    }


def _explain_row() -> dict:
    return {
        "verb_iri": "mesh:explain",
        "verb_local": "explains",
        "input_uri": "http://invincible-agent/mesh#DocPage",
        "output_uri": "http://invincible-agent/mesh#DocPage",
        "endpoint_url": "http://engine-docs.invalid/explain",
        "owner_persona": None,
        "domains": [],
        "cost_class": "fast",
        "requires_human_approval": False,
        "arity": None,
        "required_args": [],
        "slots": "[]",
        "hops": 10**6,
        "compatibility": "universal",
    }


#: What the store holds, per leg. `costLotBreakdown` is reachable both ways (the dedupe's case);
#: `fxRevalue` is outside COST, so the entitled-domain filter has something to remove.
_LEG_ROWS = {
    "subject": [_row("costLotBreakdown", "subject", hops=0), _row("costVariance", "subject")],
    "referent": [
        _row("costLotBreakdown", "referent"),
        _row("lotYield", "referent"),
        _row("fxRevalue", "referent", domains=("FIN",)),
    ],
    "universal": [_explain_row()],
}


def _child_rows(rows: list[dict]) -> list[dict]:
    """The same store seen from a subclass two hops below: every non-universal row is two hops
    further away (a distance 0 on the subject itself stays 0), and takes the child as its input."""
    out = []
    for r in rows:
        r = dict(r)
        if r["compatibility"] != "universal":
            r["hops"] = r["hops"] + 2 if r["hops"] else 0
            r["input_uri"] = CHILD_SUBJECT
        out.append(r)
    return out


#: Every subject the leg double can answer, and what the store holds for it per leg.
_ROWS_BY_SUBJECT = {
    SUBJECT: _LEG_ROWS,
    CHILD_SUBJECT: {leg: _child_rows(rows) for leg, rows in _LEG_ROWS.items()},
}
_HOPS = list(range(1, 9))  # the closed range `_VERBS_FOR_HOP_BOUNDS`, asserted equal below


def _legs_in(cypher: str) -> list[str]:
    flat = re.sub(r"\s+", " ", cypher)
    return [leg for leg in ("subject", "referent", "universal") if f"'{leg}' AS compatibility" in flat]


class _LegSession:
    def __init__(self, driver: "_LegDriver") -> None:
        self._d = driver

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, cypher: str, **params):
        self._d.statements.append((cypher, params))
        legs = _legs_in(cypher)
        if self._d.raise_on & set(legs):
            raise RuntimeError("store down")
        rows: list[dict] = []
        for leg in legs:
            if leg == "universal" and THING not in (params.get("universal_referents") or []):
                continue
            rows.extend(dict(r) for r in _ROWS_BY_SUBJECT[params["subject_uri"]][leg])
        return rows


class _LegDriver:
    """Answers each leg present in the statement it is handed, and LEG 3 only when the confirmed
    list it is handed contains the candidate -- as the real join on `$universal_referents` does."""

    def __init__(self, raise_on: tuple[str, ...] = ()) -> None:
        self.statements: list[tuple[str, dict]] = []
        self.raise_on = set(raise_on)

    def session(self):
        return _LegSession(self)


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text


class _Post:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[str] = []

    def __call__(self, url, *, data, headers):
        self.calls.append(url)
        return _Resp(200, self._text)


def _turtle(flagged: bool) -> str:
    body = "@prefix mesh: <http://invincible-agent/mesh#> .\n"
    body += "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    body += "mesh:Thing a owl:Class .\n"
    if flagged:
        body += 'mesh:Thing mesh:universalReferent "true" .\n'
    return body


class _JenaSpy:
    """The real `JenaMeshOntology` over a recording POST, with every initiator it was asked as."""

    def __init__(self, real) -> None:
        self._real = real
        self.initiators: list[Initiator] = []

    def construct(self, initiator, **kw):
        self.initiators.append(initiator)
        return self._real.construct(initiator, **kw)


class _Stage:
    def __init__(self, mod, monkeypatch, *, flag: bool, flagged: bool = True,
                 raise_on: tuple[str, ...] = ()) -> None:
        self.driver = _LegDriver(raise_on)
        self.post = _Post(_turtle(flagged))
        self.jena = _JenaSpy(_ORIGINAL["jena"](endpoint=_TEST_JENA_ENDPOINT, post=self.post))
        self.graph_initiators: list[Initiator] = []
        real_graph = _ORIGINAL["graph"]
        seen = self.graph_initiators

        class _Graph(real_graph):
            def verbs_for(self, initiator, subject, *, max_hops):
                seen.append(initiator)
                return super().verbs_for(initiator, subject, max_hops=max_hops)

        monkeypatch.setattr(mod, "_NEO4J_DRIVER", self.driver)
        monkeypatch.setattr(mod, "_JENA_ONTOLOGY", self.jena)
        monkeypatch.setattr(mod, "Neo4jGraph", _Graph, raising=False)
        monkeypatch.setattr(mod, _FLAG, flag, raising=False)
        self.client = TestClient(mod.app)

    def ask(self, **body):
        return self.client.post("/find_compatible_verbs", json={"subject_uri": SUBJECT, **body})


def _hops_walked(stage: "_Stage") -> list[int]:
    """The `*0..N` bounds in every statement the stage sent: the hop count made observable to the
    double (it ignores `max_hops` in what it answers, so this is what says both paths walked the
    same distance)."""
    flat = " ".join(re.sub(r"\s+", " ", c) for c, _ in stage.driver.statements)
    return sorted(int(n) for n in re.findall(r"\*\d+\.\.(\d+)\]", flat))


def _verbs(r) -> list[dict]:
    assert r.status_code == 200, r.text
    return r.json()["verbs"]


# ── the default ──────────────────────────────────────────────────────────────────────────────


def test_THE_FLAG_DEFAULTS_ON():
    """Read from the statement that sets it, so a default flipped in the source reds here even on
    a box whose environment sets the flag."""
    tree = ast.parse((_SVC / "main.py").read_text(encoding="utf-8"))
    defaults = [
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "getenv"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == _FLAG
    ]
    assert defaults == ["true"], f"{_FLAG} is read {len(defaults)}x with defaults {defaults!r}"


# ── flag off: today's route, exactly ─────────────────────────────────────────────────────────


def test_FLAG_OFF_IS_ONE_STATEMENT_AND_THE_EXPLAIN_READ_IS_STILL_REFUSED(engine_o, monkeypatch):
    s = _Stage(engine_o, monkeypatch, flag=False)
    without = _verbs(s.ask())
    with_person = _verbs(s.ask(on_behalf_of=PERSON))
    assert without == with_person, "with the flag off, on_behalf_of changed the answer"

    assert len(s.driver.statements) == 2, "flag off should send one statement per ask"
    for cypher, params in s.driver.statements:
        assert _legs_in(cypher) == ["subject", "referent", "universal"]
        assert params["universal_referents"] == []
    assert s.graph_initiators == [], "flag off read through MeshGraph"
    assert {i.kind for i in s.jena.initiators} == {"service"}
    assert s.post.calls == [], "the service read reached Jena"
    assert "mesh:explain" not in {v["verb_iri"] for v in without}


# ── flag on: the same verbs, plus the leg that is finally read as someone ────────────────────


def test_THE_HOP_RANGE_THE_PARITY_ARMS_WALK_IS_THE_CLOSED_RANGE_verbs_for_WALKS(engine_o):
    lo, hi = engine_o._VERBS_FOR_HOP_BOUNDS
    assert _HOPS == list(range(lo, hi + 1)), (_HOPS, (lo, hi))


@pytest.mark.parametrize("subject", list(_ROWS_BY_SUBJECT), ids=["subject", "child"])
@pytest.mark.parametrize("hops", _HOPS)
def test_FLAG_ON_ANSWERS_THE_SAME_VERBS_PLUS_ONLY_THE_UNIVERSAL_LEG(
    engine_o, monkeypatch, hops, subject
):
    """Over every hop bound `verbs_for` walks and every subject the double can answer: the flag-on
    pool is the flag-off pool plus `mesh:explain` and nothing else, and both paths walked `hops`."""
    # A stage patches the module, so each is built and asked before the next is built.
    off_s = _Stage(engine_o, monkeypatch, flag=False)
    off = _verbs(off_s.ask(on_behalf_of=PERSON, max_hops=hops, subject_uri=subject))
    on_s = _Stage(engine_o, monkeypatch, flag=True)
    on = _verbs(on_s.ask(on_behalf_of=PERSON, max_hops=hops, subject_uri=subject))
    assert [v for v in on if v["compatibility"] != "universal"] == off
    assert [v["verb_iri"] for v in on if v["compatibility"] == "universal"] == ["mesh:explain"]
    walked_off, walked_on = _hops_walked(off_s), _hops_walked(on_s)
    assert walked_off and set(walked_off) == {hops}, walked_off
    assert walked_on == walked_off, f"the paths walked different hops: {walked_on} v {walked_off}"


@pytest.mark.parametrize("subject", list(_ROWS_BY_SUBJECT), ids=["subject", "child"])
@pytest.mark.parametrize("hops", _HOPS)
def test_FLAG_ON_WHEN_JENA_CONFIRMS_NOTHING_IS_THE_FLAG_OFF_ANSWER_EXACTLY(
    engine_o, monkeypatch, hops, subject
):
    # A stage patches the module, so each is built and asked before the next is built.
    off_s = _Stage(engine_o, monkeypatch, flag=False)
    off = off_s.ask(on_behalf_of=PERSON, entitled_domains=["COST"], max_hops=hops,
                    subject_uri=subject)
    on_s = _Stage(engine_o, monkeypatch, flag=True, flagged=False)
    on = on_s.ask(on_behalf_of=PERSON, entitled_domains=["COST"], max_hops=hops,
                  subject_uri=subject)
    assert _verbs(on) == _verbs(off)
    names = [v["verb_local"] for v in _verbs(on)]
    # The shared tail ran on both: deduped with subject winning, filtered, required_args folded.
    assert sorted(names) == ["costLotBreakdown", "costVariance", "lotYield"], names
    if subject == SUBJECT:
        assert names == ["costLotBreakdown", "costVariance", "lotYield"], names
    assert _verbs(on)[0]["compatibility"] == "subject"
    assert _verbs(on)[0]["required_args"] == ["lot", "period"]
    assert _hops_walked(on_s) == _hops_walked(off_s) and set(_hops_walked(on_s)) == {hops}


def test_FLAG_ON_READS_LEG_1_THROUGH_verbs_for_AS_THE_PERSON(engine_o, monkeypatch):
    s = _Stage(engine_o, monkeypatch, flag=True)
    r = s.ask(on_behalf_of=f"  {PERSON} ", max_hops=4)
    assert r.status_code == 200, r.text
    assert [(i.subject, i.kind) for i in s.graph_initiators] == [(PERSON, "person")]
    (leg1, p1), (rest, p2) = s.driver.statements
    assert _legs_in(leg1) == ["subject"] and p1 == {"subject_uri": SUBJECT}
    assert "*0..4]" in leg1
    assert _legs_in(rest) == ["referent", "universal"]
    assert p2["subject_uri"] == SUBJECT and p2["universal_referents"] == [THING]
    assert "$MAXHOPS$" not in rest and "$UNREACHABLE$" not in rest
    assert "MeshGraph.verbs_for" in r.json()["cypher_executed"]


def test_FLAG_ON_THE_EXPLAIN_LEG_IS_READ_AS_THE_PERSON(engine_o, monkeypatch):
    s = _Stage(engine_o, monkeypatch, flag=True)
    verbs = _verbs(s.ask(on_behalf_of=PERSON))
    assert [(i.subject, i.kind) for i in s.jena.initiators] == [(PERSON, "person")]
    assert s.post.calls, "the person's read never reached Jena"
    assert ("mesh:explain", "universal") in {(v["verb_iri"], v["compatibility"]) for v in verbs}


# ── flag on: what it refuses ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("body", [{}, {"on_behalf_of": ""}, {"on_behalf_of": "   "}],
                         ids=["missing", "blank", "whitespace"])
def test_FLAG_ON_WITHOUT_A_PERSON_IS_A_400_AND_READS_NOTHING(engine_o, monkeypatch, body):
    s = _Stage(engine_o, monkeypatch, flag=True)
    r = s.ask(**body)
    assert r.status_code == 400 and "on_behalf_of" in r.json()["detail"], r.text
    assert s.driver.statements == [] and s.jena.initiators == [] and s.graph_initiators == []


@pytest.mark.parametrize("hops", [9, 10])
def test_FLAG_ON_A_HOP_BOUND_verbs_for_DOES_NOT_WALK_IS_A_400(engine_o, monkeypatch, hops):
    s = _Stage(engine_o, monkeypatch, flag=True)
    r = s.ask(on_behalf_of=PERSON, max_hops=hops)
    assert r.status_code == 400 and "max_hops" in r.json()["detail"], r.text
    assert s.driver.statements == []
    # The control: the bound is the flag's. Flag off clamps and answers.
    assert _Stage(engine_o, monkeypatch, flag=False).ask(max_hops=hops).status_code == 200


@pytest.mark.parametrize("leg", ["subject", "referent"])
def test_FLAG_ON_A_STORE_FAILURE_ON_EITHER_STATEMENT_IS_A_503(engine_o, monkeypatch, leg):
    s = _Stage(engine_o, monkeypatch, flag=True, raise_on=(leg,))
    r = s.ask(on_behalf_of=PERSON)
    assert r.status_code == 503 and "store down" in r.json()["detail"], r.text


# ── the caller sends the person only when it has one ─────────────────────────────────────────


def test_verb_lookup_SENDS_on_behalf_of_ONLY_WHEN_SET(monkeypatch):
    vl = pytest.importorskip("iagent.verb_lookup", reason="iagent.verb_lookup not importable here")
    sent: list[dict] = []

    class _Ok:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"verbs": []}

    def post(url, *, json, timeout):
        sent.append(json)
        return _Ok()

    monkeypatch.setattr(vl.requests, "post", post)
    vl.find_compatible_verbs(SUBJECT, ["COST"], ontology_url="http://onto.invalid")
    vl.find_compatible_verbs(SUBJECT, ["COST"], ontology_url="http://onto.invalid",
                             on_behalf_of=PERSON)
    assert "on_behalf_of" not in sent[0]
    assert sent[1]["on_behalf_of"] == PERSON
    assert {k: v for k, v in sent[1].items() if k != "on_behalf_of"} == sent[0]


# ── who asks, and whether they can name the person ───────────────────────────────────────────

_ROUTE_TAIL = "/find_compatible_verbs"

def _url_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return ""


def _posts_to_route(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and any(_url_text(a).endswith(_ROUTE_TAIL) for a in node.args)


def _names_the_person(path: Path) -> bool:
    """Whether a function that posts to the route sends `on_behalf_of`: the key as a string
    constant, or a keyword of that name, anywhere in that function. Read from the AST, so a comment
    or a docstring that mentions the word is not a body that carries it."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_posts_to_route(n) for n in ast.walk(fn)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Constant) and n.value == "on_behalf_of":
                return True
            if isinstance(n, ast.keyword) and n.arg == "on_behalf_of":
                return True
    return False


def _posters(base: Path = _REPO,
             roots: tuple[str, ...] = ("src", "agent_fleet", "scripts")) -> set[str]:
    """Every shipped module with a call whose argument is a URL ending in the route: derived from
    the AST of `src/`, `agent_fleet/` and `scripts/`, never listed, so a new caller joins the
    population."""
    found: set[str] = set()
    for root in roots:
        for path in (base / root).rglob("*.py"):
            if path == _SVC / "main.py" or "__pycache__" in path.parts or ".venv" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if _posts_to_route(node):
                    found.add(path.relative_to(base).as_posix())
    return found


def test_EVERY_CALLER_OF_THE_ROUTE_NAMES_THE_PERSON():
    """The default is ON, so a caller that posts with no `on_behalf_of` is refused (400) in
    production. Every poster is derived, never listed, and each must send the person."""
    posters = _posters()
    assert "src/iagent/verb_lookup.py" in posters, "the derivation no longer finds the known caller"
    assert _names_the_person(_REPO / "src/iagent/verb_lookup.py"), "the detector cannot see a sender"
    anonymous = sorted(rel for rel in posters if not _names_the_person(_REPO / rel))
    assert anonymous == [], f"callers that post to the route without on_behalf_of: {anonymous}"


def test_A_POSTER_WITHOUT_on_behalf_of_READS_AS_NOT_NAMING_THE_PERSON(tmp_path):
    """The negative control for the arm above: the same detector over a module that posts to a URL
    ending in the route with no person, so the arm can fail. The sibling that names it reads true."""
    (tmp_path / "scripts").mkdir()
    anon = tmp_path / "scripts" / "anon.py"
    anon.write_text(
        "import requests\n\n\ndef ask(base):\n"
        "    # on_behalf_of is only a comment here\n"
        "    return requests.post(f\"{base}/find_compatible_verbs\", json={'subject_uri': 'x'})\n",
        encoding="utf-8",
    )
    named = tmp_path / "scripts" / "named.py"
    named.write_text(
        "import requests\n\n\ndef ask(base):\n"
        "    return requests.post(f\"{base}/find_compatible_verbs\", json={'on_behalf_of': 'p'})\n",
        encoding="utf-8",
    )
    assert _posters(tmp_path, ("scripts",)) == {"scripts/anon.py", "scripts/named.py"}
    assert not _names_the_person(anon)
    assert _names_the_person(named)


#: The wrappers between the person and `verb_lookup`, and the keyword each must be handed.
_THREADED = {
    "_find_compatible_verbs": "user_email",
    "_lookup_compatible_verbs": "on_behalf_of",
    "find_compatible_verbs": "on_behalf_of",
    "dispatch_pre_resolved": "on_behalf_of",
}


def _callee(node: ast.Call) -> str | None:
    f = node.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    if name == "partial" and node.args and isinstance(node.args[0], ast.Name):
        return node.args[0].id
    return name


def _hands_down(node: ast.Call, keyword: str) -> bool:
    """The call passes `keyword=` AND its value is not a literal. `on_behalf_of=""` names the
    keyword and drops the person, so presence alone is not the claim."""
    return any(k.arg == keyword and not isinstance(k.value, ast.Constant) for k in node.keywords)


def test_THE_PERSON_IS_HANDED_DOWN_AT_EVERY_CALL_IN_src():
    """Every call in `src/` to a wrapper on the way to `verb_lookup` passes the person on, so a call
    site added without it reds here instead of 400ing only once the flag is on."""
    seen: dict[str, int] = {}
    missing: list[str] = []
    for path in sorted((_REPO / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _callee(node)
            if name not in _THREADED:
                continue
            seen[name] = seen.get(name, 0) + 1
            if not _hands_down(node, _THREADED[name]):
                missing.append(f"{path.relative_to(_REPO).as_posix()}:{node.lineno} {name}")
    assert set(seen) == set(_THREADED), f"a wrapper has no call site left: {seen}"
    assert missing == [], f"calls that drop the person: {missing}"


#: Calls in the restate_analyst runner that reach the route, and the keyword each must pass.
_RESTATE_MAIN = "agent_fleet/restate_analyst/main.py"
_RESTATE_THREADED = {"authorized_verbs": "on_behalf_of", "verify_spo_step": "on_behalf_of"}


def test_THE_PERSON_IS_HANDED_DOWN_AT_EVERY_CALL_IN_THE_RESTATE_RUNNER():
    """Every `authorized_verbs(` and `verify_spo_step(` call in restate_analyst/main.py passes
    `on_behalf_of=`, derived from the AST, so a call added without it reds here instead of
    400ing every run once the flag is on."""
    tree = ast.parse((_REPO / _RESTATE_MAIN).read_text(encoding="utf-8", errors="replace"))
    seen: dict[str, int] = {}
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee(node)
        if name not in _RESTATE_THREADED:
            continue
        seen[name] = seen.get(name, 0) + 1
        if not _hands_down(node, _RESTATE_THREADED[name]):
            missing.append(f"{_RESTATE_MAIN}:{node.lineno} {name}")
    assert sum(seen.values()) > 0 and set(seen) == set(_RESTATE_THREADED), seen
    assert missing == [], f"calls that drop the person: {missing}"


def test_A_LITERAL_PERSON_READS_AS_DROPPING_THE_PERSON():
    """The negative control for both hand-down arms: a literal value names the keyword and drops
    the person; a missing keyword drops it too; a name or an expression hands it down."""
    def call(src: str) -> ast.Call:
        return ast.parse(src).body[0].value

    assert not _hands_down(call('verify_spo_step(s, v, d, on_behalf_of="")'), "on_behalf_of")
    assert not _hands_down(call("verify_spo_step(s, v, d, on_behalf_of=None)"), "on_behalf_of")
    assert not _hands_down(call("verify_spo_step(s, v, d)"), "on_behalf_of")
    assert _hands_down(call("verify_spo_step(s, v, d, on_behalf_of=caller_email)"), "on_behalf_of")
    assert _hands_down(call('verify_spo_step(s, v, d, on_behalf_of=i.get("authz_id", ""))'),
                       "on_behalf_of")


# ── the restate_analyst callers send the person only when they have one ──────────────────────

_RA = _REPO / "agent_fleet" / "restate_analyst"


def _load_restate(name: str):
    """A restate_analyst module under a private name, loaded with its directory importable only
    for the load (the module's own sibling imports resolve there)."""
    spec = importlib.util.spec_from_file_location(f"{name}__via_mesh_test", _RA / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(_RA))
        mp.setitem(sys.modules, spec.name, mod)  # a dataclass resolves its module by name
        spec.loader.exec_module(mod)
    return mod


def test_authorized_verbs_SENDS_on_behalf_of_ONLY_WHEN_SET(monkeypatch):
    """The person ATTRIBUTES the read; the domain scope stays the workflow's, so adding the person
    changes nothing else in the body."""
    si = _load_restate("spo_interview")
    sent: list[dict] = []

    class _Ok:
        def raise_for_status(self):
            return None

        def json(self):
            return {"verbs": []}

    def post(url, *, json, timeout, headers):
        sent.append(json)
        return _Ok()

    monkeypatch.setattr(si.httpx, "post", post)
    si.authorized_verbs(SUBJECT, workflow_domain="COST", engine_o_url="http://onto.invalid")
    si.authorized_verbs(SUBJECT, workflow_domain="COST", engine_o_url="http://onto.invalid",
                        on_behalf_of="   ")
    si.authorized_verbs(SUBJECT, workflow_domain="COST", engine_o_url="http://onto.invalid",
                        on_behalf_of=PERSON)
    assert "on_behalf_of" not in sent[0] and "on_behalf_of" not in sent[1]
    assert sent[2]["on_behalf_of"] == PERSON
    assert sent[2]["entitled_domains"] == ["COST"]
    assert {k: v for k, v in sent[2].items() if k != "on_behalf_of"} == sent[0]


class _EngineOResp:
    def __init__(self, status: int, text: str = "", payload: dict | None = None) -> None:
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} from engine-o")


def test_verify_spo_step_SENDS_on_behalf_of_ONLY_WHEN_SET(monkeypatch):
    ex = _load_restate("spo_step_executor")
    sent: list[dict] = []
    verb = {"verb_iri": "mesh:v", "endpoint_url": "http://e.invalid/v"}

    def post(url, *, json, timeout, headers):
        sent.append(json)
        return _EngineOResp(200, payload={"verbs": [verb]})

    monkeypatch.setattr(ex.requests, "post", post)
    assert ex.verify_spo_step(SUBJECT, "mesh:v", ["COST"]) == verb
    ex.verify_spo_step(SUBJECT, "mesh:v", ["COST"], on_behalf_of="  ")
    ex.verify_spo_step(SUBJECT, "mesh:v", ["COST"], on_behalf_of=PERSON)
    assert "on_behalf_of" not in sent[0] and "on_behalf_of" not in sent[1]
    assert sent[2]["on_behalf_of"] == PERSON
    assert {k: v for k, v in sent[2].items() if k != "on_behalf_of"} == sent[0]


def test_verify_spo_step_A_400_FROM_ENGINE_O_IS_TERMINAL_AND_SAYS_WHY(monkeypatch):
    """A 4xx is about the request, and retrying re-sends it: it must FAIL and RELEASE, with the
    status and engine-o's detail in the message, not raise an HTTPError Restate retries for ever."""
    ex = _load_restate("spo_step_executor")
    detail = "COMPATIBLE_VERBS_VIA_MESH is on and this request carries no on_behalf_of"
    monkeypatch.setattr(ex.requests, "post",
                        lambda *a, **k: _EngineOResp(400, text=f'{{"detail": "{detail}"}}'))
    with pytest.raises(ex.StepFailAndRelease) as exc:
        ex.verify_spo_step(SUBJECT, "mesh:v", ["COST"])
    assert exc.value.status_code == 400
    assert "400" in str(exc.value) and "on_behalf_of" in str(exc.value)


def test_verify_spo_step_A_503_FROM_ENGINE_O_IS_STILL_RETRIED(monkeypatch):
    """The control: a 5xx is transient infra and still surfaces as the HTTPError Restate retries."""
    import requests

    ex = _load_restate("spo_step_executor")
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: _EngineOResp(503, text="down"))
    with pytest.raises(requests.HTTPError) as exc:
        ex.verify_spo_step(SUBJECT, "mesh:v", ["COST"])
    assert not isinstance(exc.value, ex.StepFailAndRelease)


# ── every caller's hop bound is one `verbs_for` walks ────────────────────────────────────────


def _hop_literals(rel: str) -> list[int]:
    """The int literals a module puts under a `"max_hops"` key in a dict, plus (for verb_lookup)
    its DEFAULT_MAX_HOPS."""
    tree = ast.parse((_REPO / rel).read_text(encoding="utf-8", errors="replace"))
    out: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "max_hops"
                        and isinstance(v, ast.Constant) and isinstance(v.value, int)):
                    out.append(v.value)
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, int)
                and any(isinstance(t, ast.Name) and t.id == "DEFAULT_MAX_HOPS"
                        for t in node.targets)):
            out.append(node.value.value)
    return out


def test_EVERY_CALLERS_max_hops_LIES_INSIDE_THE_BOUNDS_verbs_for_WALKS(engine_o):
    """The route does `int(request.max_hops or 5)`, so a 0 becomes 5; every other literal is
    checked as sent. Derived from the posters' bodies, never listed."""
    lo, hi = engine_o._VERBS_FOR_HOP_BOUNDS
    population: dict[str, list[int]] = {rel: _hop_literals(rel) for rel in sorted(_posters())}
    found = [h for hs in population.values() for h in hs]
    assert found, f"no max_hops literal found in any poster: {population}"
    assert _hop_literals("src/iagent/verb_lookup.py"), "verb_lookup's DEFAULT_MAX_HOPS not found"
    outside = {rel: hs for rel, hs in population.items()
               if any(not lo <= (h or 5) <= hi for h in hs)}
    assert outside == {}, f"callers sending a hop bound verbs_for does not walk: {outside}"
