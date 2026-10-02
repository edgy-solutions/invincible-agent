"""LEG 3 - THE UNIVERSAL REFERENT. A verb whose REQUIRED slot's referent is flagged
`mesh:universalReferent` is compatible with EVERY class subject, not because it covers the
subject's ancestor chain (LEG 2's rule) but because the referent declares itself unconstrained.

WHY THIS LEG EXISTS. `mesh:explain` answers about `mesh:DocPage` - its own registered subject
- for ANY question a caller asks, whatever class that question resolves to. No single domain
class is an honest ancestor-coverage referent for "explain this concept", and NOTHING IS
`subClassOf mesh:Thing` by design (`setup/ontologies/mesh_system.ttl:736`: asserting that
hierarchy would be a ratified superclass over ~24,000 nodes for one verb's benefit). So
universality is a DECLARED FLAG read from Jena (`mesh:universalReferent true` on `mesh:Thing`),
never a position in the Neo4j class tree, and LEG 3 admits on the flag rather than on coverage.

`docs/measurements/docs-walk-sheet.md` names the dependency directly: "until [this leg] lands,
`mesh:explain` cannot enter the candidate pool at all and every question below abstains before
reaching this engine." This file is the seal for the leg that unblocks that census.

── WHAT THIS FILE CAN AND CANNOT PROVE, GIVEN ITS SEAMS ──────────────────────────────────────
Declaration arms read the Cypher text out of `main.py` (the same fence-slicing convention
`test_the_pool_reaches_parameterised_verbs.py` uses) - these prove the QUERY is shaped right.
Behavioural arms drive `_confirms_universal_referent` / `_universal_referent_iris` through a real
`JenaMeshOntology` with an injected sync POST (the double from
`test_a_mesh_ontology_read_records_what_it_read.py`) - these prove the JENA HALF is right.
Endpoint arms drive `/find_compatible_verbs` through a fake Neo4j driver that returns SCRIPTED
rows - these prove the WIRING between the two is right (the confirmed IRI list reaches the
Cypher call as `universal_referents`, and a LEG-3-shaped row survives the domain filter and the
dedupe). No arm here runs LEG 3's Cypher against a real graph: a fake driver's `session.run`
returns canned rows regardless of the query text, so the join conditions
(`ref.uri IN $universal_referents`, `r.iri = p.verb_iri AND r._tool_urn = p._tool_urn`) are
checked STATICALLY (declaration arms) and never EXECUTED here. That is a real gap, named rather
than papered over: only a live Neo4j run closes it.

── THE IDENTITY: THE CALLER, AND A REFUSED FALLBACK WHEN THERE IS NONE ───────────────────────
Until 2026-10-02 `find_compatible_verbs` carried no caller identity, so the read ran as
`_POOL_READ_INITIATOR` (`kind="service"`, honestly) and `require_person` refused it on every
call: LEG 3 degraded to LEGs 1+2 against a live cluster, always. The route now carries the
caller as `user_email` (the same field `/resolve` reads) and `_universal_referent_iris` mints a
person from it; that pass-through is sealed in `test_the_explain_leg_reads_as_the_caller.py`.
`_POOL_READ_INITIATOR` remains the FALLBACK for a request that names nobody, and
`test_the_REAL_pool_initiator_is_refused_today` still asserts that fallback is refused before any
query is sent. The other behavioural arms here monkeypatch `_POOL_READ_INITIATOR` to a person-kind
identity — the same reader a named caller now gets — to exercise the CONFIRM logic in isolation
from the route.

Run: uv run --frozen --extra agent-fleet pytest tests/routing/test_the_pool_reaches_the_universal_referent.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from iagent_mesh import Initiator
from iagent_mesh.interfaces import ServiceIdentityRefused
from iagent_pure.walk_census import load_rows, verb_names

_REPO = Path(__file__).resolve().parents[2]
_ONTO = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"
_CONST = "_FIND_COMPAT_VERBS_CYPHER = "
_FENCE = chr(34) * 3

THING = "http://invincible-agent/mesh#Thing"
_TEST_JENA_ENDPOINT = "http://ontology.invalid/ds/sparql"
PERSON = Initiator(subject="lane-seal-universal-referent", kind="person")


# ── reading the query text, the same convention the parameterisation seal uses ────────────────


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


def test_LEG_3_ADMITS_ON_THE_CONFIRMED_LIST_not_a_baked_in_class_name():
    leg3 = _leg3()
    assert "ref.uri IN $universal_referents" in leg3, (
        "LEG 3 must admit on the Jena-confirmed IRI list, not a class name written into the "
        "Cypher - a baked-in name cannot be withdrawn if Jena stops confirming it"
    )


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


# ── behavioural arms: `_confirms_universal_referent` / `_universal_referent_iris` ─────────────


@pytest.fixture(scope="module")
def engine_o_module():
    """Load `main.py` under a UNIQUE module name (never bare `main`: 155 files in this repo are
    named that, and evicting a shared cache entry breaks unrelated in-suite tests -
    `tests/test_ontology_routing.py` documents the measured symptom). `agent_fleet*` is
    deliberately NOT stubbed, for the same reason that file gives: a MagicMock shadowing the real
    package breaks `agent_fleet.utils.embed`.

    `rdflib` is ALSO NOT STUBBED here, unlike `test_ontology_routing.py`'s copy of this fixture -
    that file never touches Jena, but this one's whole point is `JenaMeshOntology.construct()`
    parsing real Turtle through `mesh_ontology.py`'s local `from rdflib import Graph`. A stub
    there is a `MagicMock` whose default `__iter__` yields nothing, so every CONSTRUCT read
    would come back `outcome="empty"` regardless of the Turtle handed to the double - a fake
    that agrees with a broken implementation and disagrees with a correct one. `rdflib` is a
    real, already-installed dependency (`agent_fleet_ontology_service` pulls it in), so nothing
    here is skipped for its absence."""
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

    mod_name = "engine_o_main__universal_referent_test"
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


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text

    def json(self):
        import json
        return json.loads(self.text)


class _Post:
    """Records every call, so an arm can assert a query was never sent (the refused-identity
    arm) or was sent exactly once (its control)."""

    def __init__(self, status: int = 200, text: str = "", raises: bool = False) -> None:
        self._status, self._text, self._raises = status, text, raises
        self.calls: list[dict] = []

    def __call__(self, url, *, data, headers):
        self.calls.append({"url": url, "data": data, "headers": headers})
        if self._raises:
            raise OSError("connection refused")
        return _Resp(self._status, self._text)


def _turtle(is_class: bool, flagged: bool) -> str:
    body = "@prefix mesh: <http://invincible-agent/mesh#> .\n"
    body += "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    if is_class:
        body += "mesh:Thing a owl:Class .\n"
    if flagged:
        body += 'mesh:Thing mesh:universalReferent "true" .\n'
    return body


def test_the_REAL_pool_initiator_is_refused_today(engine_o_module):
    """THE FALLBACK IS REFUSED. `_POOL_READ_INITIATOR` is `kind="service"`, so `require_person`
    refuses the read BEFORE any query is sent - even against a Jena double primed to confirm
    `mesh:Thing` cleanly. Until 2026-10-02 this was every call, because the route carried no
    caller; it is now only a request that names nobody (the named caller's read is sealed in
    `test_the_explain_leg_reads_as_the_caller.py`). The name of this arm is kept for the
    citations that point at it. Declaring the fallback `kind="person"` would fabricate an
    identity, so it must stay refused and degrade to `[]` without raising."""
    mod = engine_o_module
    assert mod._POOL_READ_INITIATOR.kind == "service", (
        "the no-caller fallback is no longer service-kind: an anonymous request would now read "
        "Jena as a person nobody named"
    )

    post = _Post(text=_turtle(is_class=True, flagged=True))
    original = mod._JENA_ONTOLOGY
    mod._JENA_ONTOLOGY = type(original)(endpoint=_TEST_JENA_ENDPOINT, post=post)
    try:
        result = mod._universal_referent_iris()
    finally:
        mod._JENA_ONTOLOGY = original

    assert result == [], (
        "the service-kind initiator no longer degrades to an empty confirmed list - either the "
        "boundary check changed or the initiator's kind changed; either way this is worth a "
        "human decision, not a silent pass"
    )
    assert post.calls == [], "a query was sent despite the service-identity refusal — it leaked"


@pytest.fixture
def person_initiator(engine_o_module):
    """Monkeypatches `_POOL_READ_INITIATOR` to a person-kind identity for the duration of one
    test, to exercise the CONFIRM logic in isolation from the identity refusal proven above.
    The reader is the same kind a named caller now gets from the route."""
    original = engine_o_module._POOL_READ_INITIATOR
    engine_o_module._POOL_READ_INITIATOR = PERSON
    try:
        yield
    finally:
        engine_o_module._POOL_READ_INITIATOR = original


def _with_post(engine_o_module, post) -> None:
    original = engine_o_module._JENA_ONTOLOGY
    engine_o_module._JENA_ONTOLOGY = type(original)(endpoint=_TEST_JENA_ENDPOINT, post=post)
    return original


def test_a_class_carrying_the_flag_IS_confirmed(engine_o_module, person_initiator):
    post = _Post(text=_turtle(is_class=True, flagged=True))
    original = _with_post(engine_o_module, post)
    try:
        result = engine_o_module._universal_referent_iris()
    finally:
        engine_o_module._JENA_ONTOLOGY = original
    assert result == [THING]
    assert len(post.calls) == len(engine_o_module._CANDIDATE_UNIVERSAL_REFERENTS)


def test_a_class_WITHOUT_the_flag_is_NOT_confirmed(engine_o_module, person_initiator):
    """THE ARM WITH TEETH for the flag half. Being an `owl:Class` is necessary but not
    sufficient - the pool must never admit on class-membership alone, or every ordinary class
    would be treated as universal."""
    post = _Post(text=_turtle(is_class=True, flagged=False))
    original = _with_post(engine_o_module, post)
    try:
        result = engine_o_module._universal_referent_iris()
    finally:
        engine_o_module._JENA_ONTOLOGY = original
    assert result == []


def test_A_FLAG_ON_A_NON_CLASS_SUBJECT_is_NOT_confirmed(engine_o_module, person_initiator):
    """THE ARM WITH TEETH for the class half. `mesh:universalReferent true` on something that
    is not a registered `owl:Class` must not confirm - the flag alone is not sufficient either."""
    post = _Post(text=_turtle(is_class=False, flagged=True))
    original = _with_post(engine_o_module, post)
    try:
        result = engine_o_module._universal_referent_iris()
    finally:
        engine_o_module._JENA_ONTOLOGY = original
    assert result == []


def test_AN_UNREACHABLE_JENA_DEGRADES_TO_EMPTY_WITHOUT_RAISING(engine_o_module, person_initiator):
    post = _Post(raises=True)
    original = _with_post(engine_o_module, post)
    try:
        result = engine_o_module._universal_referent_iris()
    finally:
        engine_o_module._JENA_ONTOLOGY = original
    assert result == []


def test_A_REFUSED_READ_DEGRADES_TO_EMPTY_WITHOUT_RAISING(engine_o_module, person_initiator):
    post = _Post(status=400, text="Parse error")
    original = _with_post(engine_o_module, post)
    try:
        result = engine_o_module._universal_referent_iris()
    finally:
        engine_o_module._JENA_ONTOLOGY = original
    assert result == []


# ── endpoint arms: the wiring between Jena's confirmed set and the Cypher call ─────────────────


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


def test_AN_EMPTY_CONFIRMED_SET_REACHES_NEO4J_AS_AN_EMPTY_LIST_AND_THE_POOL_STAYS_EMPTY(
    engine_o_module, client
):
    """Nothing confirmed (Jena unreachable, refused, or no candidate flagged) → LEG 3
    contributes zero rows. Exercised end to end: with no other coverage either, the pool comes
    back empty and the endpoint answers 200, not an error - an empty pool is the supervisor's
    signal to fall back to the generalist, never a 5xx."""
    engine_o_module._JENA_ONTOLOGY = _with_post(engine_o_module, _Post(raises=True))
    engine_o_module._NEO4J_DRIVER = _FakeCompatDriver(rows=[])

    r = client.post(
        "/find_compatible_verbs",
        json={"subject_uri": "http://invincible-agent/some#UnrelatedClass"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verbs"] == []
    params = engine_o_module._NEO4J_DRIVER.session_obj.executed[1]
    assert params["universal_referents"] == []


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
    engine_o_module, client, row
):
    """Pool MEMBERSHIP only - not the final draw/abstain outcome. All four rows route to
    `mesh:explain` (they declare `expect_verb: explain`, the spelling `verb_names` produces from
    that IRI - see the arm above, which used to hard-code the mis-spelling `mesh_explain` and so
    pinned the very drift it was written to catch); only the fourth's DISPOSITION differs
    (`slot_required`, because
    `rolling-a-service` declares `explains: none` - a page-instance refusal downstream of this
    endpoint). So this asserts mesh:explain is a CANDIDATE for all four, which is exactly as far
    as `/find_compatible_verbs` can honestly speak, and never asserts which ones draw.

    Uses `person_initiator`-equivalent wiring (a person-kind Jena read) - the reader a named
    caller gets since 2026-10-02 - to check that entitled_domains filtering does not
    accidentally exclude mesh:explain for any of the four personas/domains the census actually
    asks with.
    """
    original_initiator = engine_o_module._POOL_READ_INITIATOR
    engine_o_module._POOL_READ_INITIATOR = PERSON
    original_jena = _with_post(
        engine_o_module, _Post(text=_turtle(is_class=True, flagged=True))
    )
    engine_o_module._NEO4J_DRIVER = _FakeCompatDriver(rows=[_mesh_explain_row()])
    try:
        r = client.post(
            "/find_compatible_verbs",
            json={
                "subject_uri": "http://invincible-agent/some#WhateverTheQuestionResolvedTo",
                "entitled_domains": list(row.domains),
            },
        )
    finally:
        engine_o_module._POOL_READ_INITIATOR = original_initiator
        engine_o_module._JENA_ONTOLOGY = original_jena

    assert r.status_code == 200
    body = r.json()
    verb_iris = {v["verb_iri"] for v in body["verbs"]}
    assert "mesh:explain" in verb_iris, (
        f"{row.id}: mesh:explain did not reach the pool for domains={row.domains!r} "
        f"(persona={row.persona!r}); verbs returned: {sorted(verb_iris)}"
    )
    explain = next(v for v in body["verbs"] if v["verb_iri"] == "mesh:explain")
    assert explain["compatibility"] == "universal"

    params = engine_o_module._NEO4J_DRIVER.session_obj.executed[1]
    assert params["universal_referents"] == [THING], (
        "the Jena-confirmed set did not reach the Cypher call as `universal_referents` - the "
        "wiring between `_universal_referent_iris` and the query params is broken"
    )
