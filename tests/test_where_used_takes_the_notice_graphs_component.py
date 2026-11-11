"""The hop from a notice's part to where-used: the Component the notice graph carries, read as a Part.

TWO HALVES.

1. THE READ RESOLVES IT. Given the IRI the notice graph mints for the part (`component_iri`, the
   form `(:Component)-[:SUBJECT_TO]->` uses) as `resolved_instance_id`, `/where_used` resolves it
   to the fixture's Part through a DECLARED alias row (scheme `graph_component`), not a branch in
   the read. alice gets both end items; bob gets only the end item on their program. Deleting the
   alias row turns this half red with `unknown_part`.

2. THE ROUTER IS OFFERED IT BY A SECOND REGISTRATION. `/find_compatible_verbs` walks the
   instance's class up `rdfs:subClassOf*` to a verb's input, and `pcn:Component` has no declared
   path to `ps:Part`. Measured 2026-11-10: a question grounded on the notice's Component was never
   offered this verb. RULED 2026-11-10: register the verb a second time on `pcn:Component` (the
   `whatFailedOnThisPart` form), and do NOT put Component under `ps:Part`, which over-claims.
   Whether Component sits under `ps:ManufacturerPart` is a separate ontology item. The seals below
   hold both halves of the ruling.

Run: uv run pytest tests/test_where_used_takes_the_notice_graphs_component.py -q
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import rdflib
import yaml
from fastapi.testclient import TestClient
from rdflib.namespace import OWL, RDF, RDFS

from agent_fleet.ontology_service import main as eo
from agent_fleet.ontology_service import notice_parts as np_
from agent_fleet.ontology_service import where_used as w
from agent_fleet.ontology_service.sustainment_instance_match import component_iri

REPO = Path(__file__).resolve().parents[1]
ALICE, BOB = "alice@example.com", "bob@example.com"
_FIXTURE = yaml.safe_load((REPO / w.SHIPPED_LOCATOR).read_text(encoding="utf-8"))


def _grants() -> dict:
    programs = yaml.safe_load((REPO / "policy/program_members.yaml").read_text(encoding="utf-8"))["programs"]
    return {k: set(v.get("grant_to") or []) for k, v in programs.items()}


def _notice_numbers() -> dict:
    """label -> the number the notice prints, read from the fixture."""
    return {i["label"]: a["value"] for i in _FIXTURE["identities"] for a in i["aliases"]
            if a["scheme"] == "notice_part_number"}


def _identity_label(ident: str) -> str:
    return next(i["label"] for i in _FIXTURE["identities"] if i["identity"] == ident)


def _program_of(label: str) -> str:
    ident = next(i["identity"] for i in _FIXTURE["identities"] if i["label"] == label)
    return next(r["program"] for r in _FIXTURE["sustained_under"] if r["end_item"] == ident)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(eo, "_notice_parts_can_view_program",
                        lambda program, caller: caller in _grants().get(program, set()))
    return TestClient(eo.app)  # no `with`: the lifespan (stores, registration) is not run


def _from_the_graph(client, label: str, caller: str) -> dict:
    """POST as the dispatcher does after grounding on the notice's Component: no `part` slot,
    only the resolved instance."""
    iri = component_iri(_notice_numbers()[label])
    assert iri.startswith(np_.COMPONENT_IRI_PREFIX), "the IRI is the one the notice graph carries"
    r = client.post("/where_used", json={
        "params": {}, "resolved_instance_id": iri,
        "entitled_domains": [w.DOMAIN], "user_email": caller})
    assert r.status_code == 200, r.text
    return r.json()


def _rows(got: dict) -> dict:
    return {_identity_label(r["end_item"]): r for r in got["where_used"]}


def test_THE_FIXTURE_HAS_THE_NOTICE_PARTS():
    assert set(_notice_numbers()) == {"N-182", "N-183"}


def test_ALICE_FROM_THE_COMPONENT_GETS_BOTH_END_ITEMS(client):
    got = _from_the_graph(client, "N-182", ALICE)
    assert got["status"] == "ok", got
    rows = _rows(got)
    assert set(rows) == {"E1", "E2"}
    assert (rows["E1"]["qty_per"], rows["E2"]["qty_per"]) == (12, 6)
    assert (rows["E1"]["program"], rows["E2"]["program"]) == (_program_of("E1"), _program_of("E2"))


def test_BOB_FROM_THE_COMPONENT_GETS_ONLY_THEIR_PROGRAM(client):
    got = _from_the_graph(client, "N-182", BOB)
    assert got["status"] == "ok", got
    assert set(_rows(got)) == {"E1"}


def test_THE_SECOND_COMPONENT_IS_E1_ONLY(client):
    got = _from_the_graph(client, "N-183", ALICE)
    assert got["status"] == "ok" and set(_rows(got)) == {"E1"}


def _declared_ontology() -> rdflib.Graph:
    g = rdflib.Graph()
    for ttl in sorted((REPO / "setup/ontologies").glob("*.ttl")):
        g.parse(ttl, format="turtle")
    return g


#: The class the notice graph types its parts as: the notice verb's own namespace, read from it.
_NOTICE_COMPONENT = np_.INPUT_URI.rsplit("#", 1)[0] + "#Component"


def test_RULED_COMPONENT_IS_NOT_PUT_UNDER_PART():
    """RULED 2026-11-10: `pcn:Component rdfs:subClassOf ps:Part` over-claims. The second
    registration is the route in, never an ontology row."""
    component, part = rdflib.URIRef(_NOTICE_COMPONENT), rdflib.URIRef(w.INPUT_URI)
    g = _declared_ontology()
    assert (component, None, None) in g, "the notice's Component class is not declared where read"
    assert (part, None, None) in g, "the where-used input class is not declared where read"
    assert part not in set(g.transitive_objects(component, RDFS.subClassOf)), (
        "a subClassOf path takes Component to Part; ruled 2026-11-10 that it over-claims")


def test_THE_VERB_IS_REGISTERED_ON_PART_AND_ON_THE_NOTICE_GRAPHS_COMPONENT():
    names = [n for n, _ in w.REGISTRATIONS]
    inputs = [i for _, i in w.REGISTRATIONS]
    assert len(set(names)) == len(names), "one verb under one name twice deletes the first edge"
    assert inputs == [w.INPUT_URI, _NOTICE_COMPONENT]
    assert w.COMPONENT_INPUT_URI == _NOTICE_COMPONENT
    assert (rdflib.URIRef(_NOTICE_COMPONENT), RDF.type, OWL.Class) in _declared_ontology()


def _the_registration_under_the_loop() -> tuple[ast.For, ast.Call]:
    tree = ast.parse(Path(eo.__file__).read_text(encoding="utf-8"))
    for loop in ast.walk(tree):
        if isinstance(loop, ast.For) and ast.unparse(loop.iter) == "_where_used.REGISTRATIONS":
            for node in ast.walk(loop):
                if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("register_engine_to_mesh"):
                    return loop, node
    raise AssertionError("no register_engine_to_mesh call under a loop over _where_used.REGISTRATIONS")


def test_THE_LIFESPAN_REGISTERS_EVERY_ROW_UNDER_ITS_OWN_NAME_AND_INPUT():
    """Each row's name and input reach the call, and every other field is shared, so the verb keeps
    one description across its subjects (tests/routing/test_multi_subject_verb_descriptions.py)."""
    loop, call = _the_registration_under_the_loop()
    name_var, input_var = (t.id for t in loop.target.elts)
    kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert (kw["name"], kw["input_uri"]) == (name_var, input_var)
    loop_vars = {name_var, input_var}
    shared = {k: v for k, v in kw.items() if k not in ("name", "input_uri")}
    assert not [k for k, v in shared.items() if loop_vars & set(re.findall(r"\w+", v))], shared
