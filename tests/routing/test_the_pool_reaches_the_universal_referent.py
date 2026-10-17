"""LEG 3 - THE UNIVERSAL REFERENT. A verb whose REQUIRED slot's referent is flagged
`universal_referent` is compatible with EVERY class subject, not because it covers the
subject's ancestor chain (LEG 2's rule) but because the referent declares itself unconstrained.

WHY THIS LEG EXISTS. `mesh:explain` answers about `mesh:DocPage` - its own registered subject
- for ANY question a caller asks, whatever class that question resolves to. No single domain
class is an honest ancestor-coverage referent for "explain this concept", and NOTHING IS
`subClassOf mesh:Thing` by design (`setup/ontologies/mesh_system.ttl:736`: asserting that
hierarchy would be a ratified superclass over ~24,000 nodes for one verb's benefit). So
universality is a DECLARED FLAG, never a position in the class tree, and LEG 3 admits on the flag
rather than on coverage.

THE FLAG'S SOURCE (architect ruling 2026-10-17, on 7f's ruling 5): the Neo4j node property
`universal_referent` (snake_case, written by doc-tools' ontology sync), absent = false. It was a
Jena CONSTRUCT before, refused for the service initiator on every call, so LEG 3 never fired. These
arms hold the STATEMENT TEXT (both statements that carry LEG 3), that no Jena read is made, and
that the endpoint sends no `universal_referents` parameter.

`docs/measurements/docs-walk-sheet.md` names the dependency directly: "until [this leg] lands,
`mesh:explain` cannot enter the candidate pool at all and every question below abstains before
reaching this engine." This file is the seal for the leg that unblocks that census.

WHAT THIS FILE CAN AND CANNOT PROVE. Declaration arms read the Cypher text out of `main.py`.
Endpoint arms drive `/find_compatible_verbs` through a fake Neo4j driver that returns SCRIPTED
rows: a fake driver's `session.run` returns canned rows regardless of the query text, so the join
conditions are checked STATICALLY and never EXECUTED here (the leg-aware double in
`test_find_compatible_verbs_via_mesh_graph.py` evaluates the flag per statement text). Only a live
Neo4j run closes the rest.

Run: uv run --frozen --extra agent-fleet pytest tests/routing/test_the_pool_reaches_the_universal_referent.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from iagent_pure.walk_census import load_rows, verb_names

_REPO = Path(__file__).resolve().parents[2]
_ONTO = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"
_CONST = "_FIND_COMPAT_VERBS_CYPHER = "
_FENCE = chr(34) * 3

FLAG_TEST = "coalesce(ref.universal_referent, false) = true"


# ── reading the query text, the same convention the parameterisation seal uses ────────────────

_MOD_NAME = "engine_o_main__universal_referent_test"


def _cypher() -> str:
    src = _ONTO.read_text(encoding="utf-8")
    i = src.index(_CONST) + len(_CONST) + len(_FENCE)
    return src[i:src.index(_FENCE, i)]


def _legs() -> list[str]:
    return _cypher().split("UNION ALL")


def _leg3() -> str:
    legs = _legs()
    assert len(legs) == 3, (
        f"expected exactly 3 legs (coverage, parameterisation, universal referent); found "
        f"{len(legs)} - LEG 3 is missing, or a fourth leg landed and this file was not told"
    )
    return legs[2]


def _columns(text: str) -> list[str]:
    i = text.index("RETURN DISTINCT")
    return sorted(re.findall(r"AS ([a-z_]+)", text[i:]))


# ── declaration arms: the query text ───────────────────────────────────────────────────────────


def test_LEG_3_EXISTS_AND_IS_LABELLED():
    leg3 = _leg3()
    assert "universal" in leg3
    assert "AS compatibility" in leg3


def test_ALL_THREE_LEGS_RETURN_THE_SAME_COLUMNS():
    """A UNION with mismatched columns is a runtime SyntaxError - this query's own history is a
    comment character taking routing down with a 500, so this is checked statically."""
    legs = _legs()
    cols = [_columns(leg) for leg in legs]
    assert cols[1] == cols[0], f"leg 2 columns differ: {cols[0]} vs {cols[1]}"
    assert cols[2] == cols[0], f"leg 3 columns differ: {cols[0]} vs {cols[2]}"


def test_LEG_3_ONLY_ADMITS_A_REQUIRED_SLOT():
    """An OPTIONAL slot's referent would drag in every verb that can merely MENTION the universal
    referent - unconstrained twice over, once by the flag and once by the missing filter."""
    leg3 = _leg3()
    assert re.search(r"coalesce\(p\.required,\s*false\)\s*=\s*true", leg3), (
        "LEG 3 does not filter on `required`; an optional slot referencing a universal class "
        "would widen the pool to every verb that merely mentions it"
    )


def test_LEG_3_JOINS_ON_VERB_IRI_AND_TOOL_URN():
    """Identity for a registered verb is the PAIR (iri, _tool_urn) - joining on iri alone would
    let one provider's parameterisation admit another provider's verb, the same measured defect
    LEG 2's own comment records (13 verbs registered by more than one provider)."""
    leg3 = _leg3()
    assert "r.iri = p.verb_iri" in leg3
    assert "r._tool_urn = p._tool_urn" in leg3
    assert "p._tool_urn IS NOT NULL" in leg3


def test_LEG_3_RETURNS_THE_VERBS_OWN_SUBJECT_not_the_asking_subject():
    """`mesh:explain`'s answer is about `mesh:DocPage`, never about `start` - whatever class
    actually asked the question. Returning `start.uri` here would invert the binding exactly the
    way LEG 2's own seal names for `costSupplierConcentration`."""
    leg3 = _leg3()
    assert "vsubj.uri" in leg3 and "AS input_uri" in leg3
    assert "start.uri" not in leg3.split("RETURN DISTINCT")[1]


def test_LEG_3_IS_SCOPED_TO_ONTOLOGY_CLASSES_ON_EVERY_END():
    """A universal-referent IRI that is not itself a graph class must admit nothing - the
    candidate list is Python-side, and only Jena confirming AND Neo4j holding a matching
    `:OntologyClass` node together produce a row."""
    leg3 = _leg3()
    assert "MATCH (start:OntologyClass {uri: $subject_uri})" in leg3
    assert "MATCH (ref:OntologyClass)" in leg3
    assert "MATCH (vsubj:OntologyClass)-[p:PARAMETERISED_BY]->(ref)" in leg3
    assert "MATCH (vsubj)-[r]->(o:OntologyClass)" in leg3


def test_LEG_3_ADMITS_ON_THE_NODE_FLAG_ABSENT_READING_AS_FALSE_not_on_a_parameter(engine_o_module):
    """STATEMENT TEXT, both statements (the second is derived from the first at import): the flag is read off `ref`, with `coalesce(.., false)` so a
    class whose property was removed (`SET c.prop = null` removes it) reads as not universal, and
    no `$universal_referents` parameter survives anywhere in either statement."""
    for name, text in (("_FIND_COMPAT_VERBS_CYPHER", _leg3()),
                       ("_COMPAT_LEGS_AFTER_COVERAGE", engine_o_module._COMPAT_LEGS_AFTER_COVERAGE)):
        assert FLAG_TEST in text, f"{name}: LEG 3 does not read the node flag"
        assert "$universal_referents" not in text, f"{name}: still takes $universal_referents"
        assert "universalReferent" not in text, f"{name}: reads the camelCase key, which does not exist"


def test_NO_SQL_STYLE_COMMENT_REACHED_LEG_3():
    """The query's own history: a `--` comment took the WHOLE query down with a Neo4j
    SyntaxError and /find_compatible_verbs returned 500 - routing down, from a comment
    character. Checked on LEG 3 specifically because it is the newest text in the file."""
    leg3 = _leg3()
    for line in leg3.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("--"), f"SQL-style comment in LEG 3: {line!r}"


def test_THE_HOPS_SENTINEL_IS_SUBSTITUTED_not_a_re_typed_literal():
    """`UNREACHABLE` has exactly one declaration (module level, `main.py`) - LEG 3 must be
    substituted with it via `$UNREACHABLE$`, never a second `10**6` typed into the Cypher, or the
    two can drift the day one of them changes."""
    leg3 = _leg3()
    assert "$UNREACHABLE$" in leg3
    assert "10**6" not in leg3
    src = _ONTO.read_text(encoding="utf-8")
    decls = re.findall(r"^UNREACHABLE\s*=", src, re.MULTILINE)
    assert len(decls) == 1, f"UNREACHABLE must be declared exactly once at module level, found {len(decls)}"


def test_THE_COVERAGE_AND_PARAMETERISATION_LEGS_ARE_STILL_FIRST_AND_SECOND():
    """LEG 3 is an ADDITION, not a replacement - ADR-0018's original rule and the
    parameterisation widening both stay exactly where the existing seal already checks them."""
    legs = _legs()
    assert "subject" in legs[0] and "subClassOf*0..$MAXHOPS$" in legs[0]
    assert "referent" in legs[1] and "PARAMETERISED_BY" in legs[1]


# ── endpoint arms: the statement LEG 3 sends, and that it reads no Jena ─────────────────────────


def _neo4j_double() -> MagicMock:
    """A fake `neo4j` whose `neo4j.exceptions` is a real submodule carrying REAL Exception
    subclasses: main.py imports the outage classes from it and uses them in `except` tuples,
    where a MagicMock attribute raises TypeError."""
    import types
    neo = MagicMock()
    neo.exceptions = types.ModuleType("neo4j.exceptions")
    for _x in ("ServiceUnavailable", "SessionExpired", "TransientError"):
        setattr(neo.exceptions, _x, type(_x, (Exception,), {}))
    return neo


@pytest.fixture(scope="module")
def engine_o_module():
    """Load `main.py` under a UNIQUE module name (never bare `main`: 155 files in this repo are
    named that, and evicting a shared cache entry breaks unrelated in-suite tests).
    `agent_fleet*` and `rdflib` are deliberately NOT stubbed."""
    svc_dir = _REPO / "agent_fleet" / "ontology_service"
    for _p in (str(svc_dir), str(_REPO)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    for name in [
        "weaviate", "weaviate.classes", "weaviate.classes.query",
        "neo4j", "baml_client", "baml_client.types", "baml_client.type_builder",
        "llm_utils", "utils", "utils.weaviate_utils",
    ]:
        sys.modules.setdefault(name, _neo4j_double() if name == "neo4j" else MagicMock())
    sys.modules.setdefault("neo4j.exceptions", sys.modules["neo4j"].exceptions)

    import importlib.util

    cached = sys.modules.get(_MOD_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MOD_NAME, svc_dir / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(_MOD_NAME, None)
        raise
    return mod


class _JenaMustNotBeCalled:
    """A double that raises if LEG 3 (or anything on this route) reads Jena."""

    def __init__(self) -> None:
        self.calls = 0

    def construct(self, *a, **kw):
        self.calls += 1
        raise AssertionError("LEG 3 made a Jena CONSTRUCT read; it reads the Neo4j node flag")

    ask = construct


class _FakeCompatSession:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.executed: tuple[str, dict] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, cypher: str, **params):
        self.executed = (cypher, params)
        return list(self._rows)


class _FakeCompatDriver:
    def __init__(self, rows: list[dict]):
        self.session_obj = _FakeCompatSession(rows)

    def session(self):
        return self.session_obj


def _mesh_explain_row() -> dict:
    """A LEG-3-shaped row: no real hop count (the sentinel), `compatibility: universal`, and
    `mesh:DocPage` as its OWN subject rather than whatever `start` the caller asked about.

    `domains: []`, matching the REAL registration (agent_fleet/docs_agent/main.py ~241,
    "DECLARED AGNOSTIC, never reached by leaving the argument off"). `["DOCS"]` here used to
    agree with every census row by coincidence — they all asked with domains=[DOCS] — until
    the MESH-domain row (the UI's own path; cortex hides DOCS from the picker) asked with
    entitled_domains=['MESH'] and the stale fixture value excluded mesh:explain that this
    endpoint's own filter (`if entitled and verb_domains: ...intersection`, ~line 5118) would
    never exclude for an agnostic verb in production.
    """
    return {
        "verb_iri": "mesh:explain",
        "verb_local": "explains",
        "input_uri": "http://invincible-agent/mesh#DocPage",
        "output_uri": "http://invincible-agent/mesh#DocPage",
        "endpoint_url": "http://engine-docs.mesh.svc:8080/explain",
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


@pytest.fixture
def client(engine_o_module):
    return TestClient(engine_o_module.app)


def test_THE_FLAG_OFF_STATEMENT_CARRIES_THE_NODE_FLAG_AND_NO_PARAMETER_AND_JENA_IS_NOT_CALLED(
    engine_o_module, client, monkeypatch
):
    """The flag-off route sends one statement: its text carries the node-flag test and no
    `$universal_referents`, the parameters carry no `universal_referents`, and no Jena read is
    made (the double raises if one is). No other coverage either: the pool is empty and the
    endpoint answers 200 - an empty pool is the supervisor's signal to fall back, never a 5xx.

    This arm is about the FLAG-OFF route (one statement); `COMPATIBLE_VERBS_VIA_MESH` defaults on
    and would 400 a request with no person."""
    monkeypatch.setattr(engine_o_module, "COMPATIBLE_VERBS_VIA_MESH", False)
    jena = _JenaMustNotBeCalled()
    monkeypatch.setattr(engine_o_module, "_JENA_ONTOLOGY", jena)
    monkeypatch.setattr(engine_o_module, "_NEO4J_DRIVER", _FakeCompatDriver(rows=[]))

    r = client.post(
        "/find_compatible_verbs",
        json={"subject_uri": "http://invincible-agent/some#UnrelatedClass"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verbs"] == []
    cypher, params = engine_o_module._NEO4J_DRIVER.session_obj.executed
    assert FLAG_TEST in cypher and "$universal_referents" not in cypher
    assert "universal_referents" not in params, params
    assert jena.calls == 0


def test_THE_FLAG_ON_ROUTE_SENDS_THE_SAME_TEXT_AND_NO_PARAMETER_AND_JENA_IS_NOT_CALLED(
    engine_o_module, client, monkeypatch
):
    """The flag-on (via MeshGraph) path builds LEG 3 from `_COMPAT_LEGS_AFTER_COVERAGE`; the same
    statement-text and no-Jena claims hold there."""
    class _Coverage:
        outcome, detail, rows = "ok", "", []

    class _Graph:
        def __init__(self, **kw):
            pass

        def verbs_for(self, *a, **kw):
            return _Coverage()

    monkeypatch.setattr(engine_o_module, "COMPATIBLE_VERBS_VIA_MESH", True)
    monkeypatch.setattr(engine_o_module, "Neo4jGraph", _Graph)
    jena = _JenaMustNotBeCalled()
    monkeypatch.setattr(engine_o_module, "_JENA_ONTOLOGY", jena)
    monkeypatch.setattr(engine_o_module, "_NEO4J_DRIVER", _FakeCompatDriver(rows=[]))
    r = client.post("/find_compatible_verbs",
                    json={"subject_uri": "http://invincible-agent/some#X",
                          "on_behalf_of": "lane-seal@example.com"})
    assert r.status_code == 200, r.text
    cypher, params = engine_o_module._NEO4J_DRIVER.session_obj.executed
    assert FLAG_TEST in cypher and "$universal_referents" not in cypher
    assert "universal_referents" not in params, params
    assert jena.calls == 0


_DOCS_CENSUS_ROWS = load_rows(_CENSUS)
_DOCS_ROWS = [r for r in _DOCS_CENSUS_ROWS if r.id.startswith("docs-")]


def test_the_docs_census_still_has_exactly_five_rows_EXPECTING_A_PRODUCIBLE_SPELLING():
    """Read from the source, not restated as a count - if the census grows or shrinks this
    file's own list below must be re-derived, and this arm is what catches the drift.

    ⛔ THIS ARM USED TO PIN THE DEFECT IT WAS WATCHING FOR. Until 2026-09-27 the second half
    read `assert row.expect_verb == "mesh_explain"` - and `mesh_explain` is a spelling
    `verb_names` cannot produce, because every one of the three spellings it offers is taken
    AFTER splitting the IRI on `#`, `/` or `:`. So the count half was derived from the source,
    exactly as the first line of this docstring claims, and the SPELLING half was a restated
    literal wearing the same sentence's authority. It had been green over the mis-spelling for
    as long as the mis-spelling existed, for the plain reason that it AGREED with it, and it
    redded on the fix - a correct-in-form drift red that arrived pointing at the repair.

    So the spelling is now DERIVED from the verb the four rows actually route to. A seal on a
    value must call the producer of that value, or it is a second copy of the thing it guards.
    """
    # Five since docs-how-do-i-add-an-engine-under-mesh joined the census: the UI's own path
    # (domains=[MESH]; cortex hides DOCS from the picker), added beside the DOCS-caller control.
    assert len(_DOCS_ROWS) == 5, sorted(r.id for r in _DOCS_ROWS)
    producible = verb_names({"action": {"iri": "mesh:explain"}})
    assert producible, "verb_names offered no spelling at all - this arm is asserting nothing"
    for row in _DOCS_ROWS:
        assert row.expect_verb in producible, (
            f"{row.id} expects {row.expect_verb!r}, which mesh:explain does not produce "
            f"(it produces {sorted(producible)}). A census expectation no answer can satisfy "
            f"reds every row it is on, and reds it for the instrument's reason, not the "
            f"fleet's."
        )


@pytest.mark.parametrize("row", _DOCS_ROWS, ids=[r.id for r in _DOCS_ROWS])
def test_EVERY_DOCS_CENSUS_QUESTION_REACHES_mesh_explain_THROUGH_LEG_3(
    engine_o_module, client, row, monkeypatch
):
    """Pool MEMBERSHIP only - not the final draw/abstain outcome. All four rows route to
    `mesh:explain` (they declare `expect_verb: explain`, the spelling `verb_names` produces from
    that IRI - see the arm above, which used to hard-code the mis-spelling `mesh_explain` and so
    pinned the very drift it was written to catch); only the fourth's DISPOSITION differs
    (`slot_required`, because
    `rolling-a-service` declares `explains: none` - a page-instance refusal downstream of this
    endpoint). So this asserts mesh:explain is a CANDIDATE for all four, which is exactly as far
    as `/find_compatible_verbs` can honestly speak, and never asserts which ones draw.

    This arm checks that entitled_domains filtering does not exclude mesh:explain for any of the
    personas/domains the census actually asks with.
    """
    monkeypatch.setattr(engine_o_module, "COMPATIBLE_VERBS_VIA_MESH", False)
    monkeypatch.setattr(engine_o_module, "_JENA_ONTOLOGY", _JenaMustNotBeCalled())
    monkeypatch.setattr(engine_o_module, "_NEO4J_DRIVER",
                        _FakeCompatDriver(rows=[_mesh_explain_row()]))
    r = client.post(
        "/find_compatible_verbs",
        json={
            "subject_uri": "http://invincible-agent/some#WhateverTheQuestionResolvedTo",
            "entitled_domains": list(row.domains),
        },
    )

    assert r.status_code == 200
    body = r.json()
    verb_iris = {v["verb_iri"] for v in body["verbs"]}
    assert "mesh:explain" in verb_iris, (
        f"{row.id}: mesh:explain did not reach the pool for domains={row.domains!r} "
        f"(persona={row.persona!r}); verbs returned: {sorted(verb_iris)}"
    )
    explain = next(v for v in body["verbs"] if v["verb_iri"] == "mesh:explain")
    assert explain["compatibility"] == "universal"

    cypher, params = engine_o_module._NEO4J_DRIVER.session_obj.executed
    assert FLAG_TEST in cypher and "universal_referents" not in params


@pytest.fixture(scope="module", autouse=True)
def _put_the_loaded_module_back():
    """PUT sys.modules BACK. This file registers a module it loaded by path under a private
    name; left behind it is a name every later file can resolve to this file's copy. The prior
    state -- present OR absent -- is recorded before the first test and restored after the last."""
    saved = {n: (n in sys.modules, sys.modules.get(n)) for n in (_MOD_NAME,)}
    yield
    for n, (had, prior) in saved.items():
        if had:
            sys.modules[n] = prior
        else:
            sys.modules.pop(n, None)
