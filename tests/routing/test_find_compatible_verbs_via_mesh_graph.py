"""`/find_compatible_verbs` THROUGH `MeshGraph.verbs_for`, AS THE PERSON: THE FLAG ON/OFF SEAL.

`COMPATIBLE_VERBS_VIA_MESH` moves LEG 1 (coverage) onto `Neo4jGraph.verbs_for`, whose statement
`tests/test_mesh_graph_conforms.py::test_verbs_for_IS_THE_ROUTES_LEG_1` holds equal to the route's
own, and reads LEG 3's universal-referent confirmation from Jena as the person the request names
in `on_behalf_of`. With the flag off, LEG 3's read is made as `_POOL_READ_INITIATOR`, a service,
and is refused before it is sent (`test_the_pool_reaches_the_universal_referent.py` seals that).

WHAT THE FLAG MAY CHANGE, AND NOTHING ELSE:

- WHO the reads are attributed to: the person, on LEG 1 and on LEG 3's Jena read;
- a request with no person is a 400, and a hop bound `verbs_for` does not walk is a 400;
- a substrate failure is a 503 rather than a 500.

THE ANSWER IS THE SAME ANSWER. With the same rows in the store, every verb is the same verb in the
same order, field for field. LEG 3 is read as the person and its rows are NOT ADMITTED (main.py's
`_NOT_ADMITTED`): `mesh:explain` registers with no domains, so nothing else would keep it out of
every class subject's pool. The identity arm runs both paths against one leg-aware double that
answers each leg by what the statement it was handed contains, with Jena CONFIRMING the universal
referent, so the filter has a row to remove and a split that dropped or duplicated a leg answers
differently. `required_args` is folded by one function on both paths, and the double holds it in
all three shapes the store does (comma-joined, absent, a list).

`on_behalf_of` HERE IS THE GATEWAY'S WORD, NOT THE SDK'S. It names the person (the caller's
authz_id), and the route mints `Initiator(subject=person, kind="person")`. The SDK's
`Initiator.on_behalf_of` makes a delegate, which `MeshGraph` and `MeshOntology` reads refuse.

Run: uv run --frozen --extra agent-fleet pytest tests/routing/test_find_compatible_verbs_via_mesh_graph.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import re
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


def _row(verb: str, compatibility: str, *, hops: int = 1, domains=("COST",),
         required_args=("lot,period")) -> dict:
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
        "required_args": required_args,
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
    "subject": [
        _row("costLotBreakdown", "subject", hops=0),
        _row("costVariance", "subject", required_args=None),
    ],
    "referent": [
        _row("costLotBreakdown", "referent"),
        _row("lotYield", "referent", required_args=["lot", " "]),
        _row("fxRevalue", "referent", domains=("FIN",)),
    ],
    "universal": [_explain_row()],
}


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
            rows.extend(dict(r) for r in _LEG_ROWS[leg])
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


def _verbs(r) -> list[dict]:
    assert r.status_code == 200, r.text
    return r.json()["verbs"]


# ── the default ──────────────────────────────────────────────────────────────────────────────


def test_THE_FLAG_DEFAULTS_OFF():
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
    assert defaults == ["false"], f"{_FLAG} is read {len(defaults)}x with defaults {defaults!r}"


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


# ── flag on: the same answer, read as the person ─────────────────────────────────────────────


@pytest.mark.parametrize("entitled", [[], ["COST"], ["DOCS"]], ids=["unscoped", "COST", "DOCS"])
def test_FLAG_ON_IS_THE_FLAG_OFF_ANSWER_EXACTLY(engine_o, monkeypatch, entitled):
    """THE IDENTITY SEAL. Jena confirms the universal referent, so LEG 3 runs and answers
    `mesh:explain`; the flag-on answer is still the flag-off answer, field for field."""
    off = _Stage(engine_o, monkeypatch, flag=False).ask(on_behalf_of=PERSON, entitled_domains=entitled)
    s = _Stage(engine_o, monkeypatch, flag=True)
    on = s.ask(on_behalf_of=PERSON, entitled_domains=entitled)
    assert _verbs(on) == _verbs(off)
    assert {k: v for k, v in on.json().items() if k != "cypher_executed"} == {
        k: v for k, v in off.json().items() if k != "cypher_executed"}

    # THE CONTROL: the filter had something to remove. LEG 3 was handed the confirmed referent,
    # and the double answers that leg with `mesh:explain` whenever it is.
    (_, _), (rest, params) = s.driver.statements
    assert "universal" in _legs_in(rest) and params["universal_referents"] == [THING]
    assert "mesh:explain" not in {v["verb_iri"] for v in _verbs(on)}

    if entitled == ["DOCS"]:
        # The scope where an admitted `mesh:explain` would be the WHOLE answer: no domains.
        assert _verbs(on) == [], "a COST verb passed a DOCS-scoped filter"
        return
    # The fold ran on both paths, over all three shapes the store holds.
    folded = {v["verb_local"]: v["required_args"] for v in _verbs(on)}
    assert folded["costLotBreakdown"] == ["lot", "period"]
    assert folded["costVariance"] == []
    if "lotYield" in folded:
        assert folded["lotYield"] == ["lot"]


def test_FLAG_ON_WHEN_JENA_CONFIRMS_NOTHING_IS_THE_FLAG_OFF_ANSWER_EXACTLY(engine_o, monkeypatch):
    off = _Stage(engine_o, monkeypatch, flag=False).ask(on_behalf_of=PERSON, entitled_domains=["COST"])
    on = _Stage(engine_o, monkeypatch, flag=True, flagged=False).ask(
        on_behalf_of=PERSON, entitled_domains=["COST"])
    assert _verbs(on) == _verbs(off)
    names = [v["verb_local"] for v in _verbs(on)]
    # The shared tail ran on both: deduped with subject winning, filtered, required_args folded.
    assert names == ["costLotBreakdown", "costVariance", "lotYield"], names
    assert _verbs(on)[0]["compatibility"] == "subject"
    assert _verbs(on)[0]["required_args"] == ["lot", "period"]


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
    # Read as the person, and not admitted: the leg's rows never reach the pool.
    assert "universal" not in {v["compatibility"] for v in verbs}
    assert "not admitted" in s.ask(on_behalf_of=PERSON).json()["cypher_executed"]


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

#: Every module that posts to the route, and EVERY ONE NAMES THE PERSON. The spo callers left
#: the old `_NO_PERSON_YET` register on 2026-10-08: the interview sends its author, the step
#: verifier its run's `authz_id`. There is no exemption list to append to; a new poster that
#: sends no person reds below, before the flag can 400 it.
_POSTERS = {
    "src/iagent/verb_lookup.py",
    "agent_fleet/restate_analyst/spo_interview.py",
    "agent_fleet/restate_analyst/spo_step_executor.py",
}


def _url_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return ""


def _posts_to_route(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and any(_url_text(a).endswith(_ROUTE_TAIL) for a in node.args)


def _names_the_person(source: str) -> bool:
    """Whether EVERY function that posts to the route sends `on_behalf_of`: the key as a string
    constant, or a keyword of that name, in that function's body. Read from the AST, so a comment
    or a docstring that mentions the word is not a body that carries it. False when nothing posts.
    """
    tree = ast.parse(source)
    posting = [
        fn for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_posts_to_route(n) for n in ast.walk(fn))
    ]

    def carries(fn) -> bool:
        body = [n for stmt in fn.body for n in ast.walk(stmt)]
        if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant):
            docstring = fn.body[0].value
            body = [n for n in body if n is not docstring]
        return any(
            (isinstance(n, ast.Constant) and n.value == "on_behalf_of")
            or (isinstance(n, ast.keyword) and n.arg == "on_behalf_of")
            for n in body
        )

    return bool(posting) and all(carries(fn) for fn in posting)


#: THE DETECTOR'S NEGATIVE: posts to the route, and mentions the word only where a body does not
#: carry it (a docstring, a comment, a parameter name it never sends).
_SILENT_POSTER = '''
def ask(subject, on_behalf_of=""):
    """on_behalf_of"""
    # on_behalf_of
    return post(f"{URL}/find_compatible_verbs", json={"subject_uri": subject})
'''


def _posters() -> set[str]:
    """Every shipped module with a call whose argument is a URL ending in the route: derived from
    the AST of `src/` and `agent_fleet/`, never listed, so a new caller joins the population."""
    found: set[str] = set()
    for root in ("src", "agent_fleet"):
        for path in (_REPO / root).rglob("*.py"):
            if path == _SVC / "main.py" or "__pycache__" in path.parts or ".venv" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if _posts_to_route(node):
                    found.add(path.relative_to(_REPO).as_posix())
    return found


def test_EVERY_CALLER_OF_THE_ROUTE_NAMES_THE_PERSON():
    posters = _posters()
    assert "src/iagent/verb_lookup.py" in posters, "the derivation no longer finds the known caller"
    assert posters == _POSTERS, (
        f"the route's callers changed: {sorted(posters)}. A new one must send on_behalf_of "
        f"(through verb_lookup, or by itself) and join _POSTERS."
    )
    assert not _names_the_person(_SILENT_POSTER), "the detector reads a docstring as a body"
    assert _names_the_person(_SILENT_POSTER.replace(
        '{"subject_uri": subject}', '{"subject_uri": subject, "on_behalf_of": on_behalf_of}'
    )), "the detector cannot see a sender"
    silent = [rel for rel in sorted(_POSTERS)
              if not _names_the_person((_REPO / rel).read_text(encoding="utf-8", errors="replace"))]
    assert silent == [], f"posts to the route without the person: {silent}"


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
            if _THREADED[name] not in {k.arg for k in node.keywords}:
                missing.append(f"{path.relative_to(_REPO).as_posix()}:{node.lineno} {name}")
    assert set(seen) == set(_THREADED), f"a wrapper has no call site left: {seen}"
    assert missing == [], f"calls that drop the person: {missing}"


#: The spo wrappers, and what each call site in `restate_analyst/main.py` must hand them: the
#: interview's AUTHOR, the run's `authz_id`. The VALUE is checked, not only the keyword, so a call
#: that passes some other name (a service id, a literal) reds.
_SPO_THREADED = {
    "authorized_verbs": "caller_email",
    "verify_spo_step": "ident['authz_id']",  # as ast.unparse spells it
}


def test_THE_PERSON_IS_HANDED_DOWN_AT_EVERY_SPO_CALL():
    path = _REPO / "agent_fleet/restate_analyst/main.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    seen: dict[str, int] = {}
    wrong: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee(node)
        if name not in _SPO_THREADED:
            continue
        seen[name] = seen.get(name, 0) + 1
        sent = {k.arg: ast.unparse(k.value) for k in node.keywords}.get("on_behalf_of")
        if sent != _SPO_THREADED[name]:
            wrong.append(f"{node.lineno} {name} on_behalf_of={sent}")
    assert set(seen) == set(_SPO_THREADED), f"an spo wrapper has no call site left: {seen}"
    assert wrong == [], f"spo calls that do not hand down the person: {wrong}"


# ── the spo callers send the person only when they have one ───────────────────────────────────


class _SpoResp:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {"verbs": []}
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _spo(monkeypatch, module: str, client: str, status: int = 200, payload=None):
    mod = pytest.importorskip(f"agent_fleet.restate_analyst.{module}")
    sent: list[dict] = []

    def post(url, *, json, timeout, headers):
        assert url.endswith(_ROUTE_TAIL), url
        sent.append(json)
        return _SpoResp(status, payload)

    monkeypatch.setattr(mod, client, type("_Client", (), {"post": staticmethod(post)}))
    monkeypatch.setattr(mod, "outbound_auth_headers", lambda **_: {})
    return mod, sent


def test_THE_INTERVIEW_SENDS_ITS_AUTHOR_ONLY_WHEN_SET(monkeypatch):
    si, sent = _spo(monkeypatch, "spo_interview", "httpx")
    si.authorized_verbs(SUBJECT, workflow_domain="COST", engine_o_url="http://onto.invalid")
    si.authorized_verbs(SUBJECT, workflow_domain="COST", engine_o_url="http://onto.invalid",
                        on_behalf_of=PERSON)
    assert "on_behalf_of" not in sent[0]
    assert sent[1]["on_behalf_of"] == PERSON
    assert {k: v for k, v in sent[1].items() if k != "on_behalf_of"} == sent[0]


def test_THE_STEP_VERIFIER_SENDS_THE_RUNS_PERSON_ONLY_WHEN_SET(monkeypatch):
    verb = {"verb_iri": "cost:costVariance", "arity": None}
    ex, sent = _spo(monkeypatch, "spo_step_executor", "requests", payload={"verbs": [verb]})
    assert ex.verify_spo_step(SUBJECT, "cost:costVariance", ["COST"]) == verb
    assert ex.verify_spo_step(SUBJECT, "cost:costVariance", ["COST"], on_behalf_of=PERSON) == verb
    assert "on_behalf_of" not in sent[0]
    assert sent[1]["on_behalf_of"] == PERSON
    assert {k: v for k, v in sent[1].items() if k != "on_behalf_of"} == sent[0]


@pytest.mark.parametrize("status", [400, 403, 422])
def test_A_REFUSED_ELIGIBILITY_READ_FAILS_AND_RELEASES(monkeypatch, status):
    """A run with no person meets the flag-on route's 400. A refusal never heals on retry, so it
    fails and releases with the code engine-o gave, as an ineligible verb does."""
    ex, _ = _spo(monkeypatch, "spo_step_executor", "requests", status=status)
    with pytest.raises(ex.StepFailAndRelease) as caught:
        ex.verify_spo_step(SUBJECT, "cost:costVariance", ["COST"])
    assert caught.value.status_code == status


def test_A_5xx_ON_THE_ELIGIBILITY_READ_STILL_RETRIES(monkeypatch):
    """The control: only a refusal is terminal. A 5xx is transient infra and must stay a plain
    raise that Restate retries, never a fail-and-release."""
    ex, _ = _spo(monkeypatch, "spo_step_executor", "requests", status=503)
    with pytest.raises(Exception) as caught:
        ex.verify_spo_step(SUBJECT, "cost:costVariance", ["COST"])
    assert not isinstance(caught.value, ex.StepFailAndRelease)
