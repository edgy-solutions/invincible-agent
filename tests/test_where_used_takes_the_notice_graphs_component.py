"""The hop from a notice's part to where-used: the Component the notice graph carries, read as a Part.

TWO HALVES, AND THEY ANSWER DIFFERENTLY (measured 2026-11-10).

1. THE READ RESOLVES IT. Given the IRI the notice graph mints for the part (`component_iri`, the
   form `(:Component)-[:SUBJECT_TO]->` uses) as `resolved_instance_id`, `/where_used` resolves it
   to the fixture's Part through a DECLARED alias row (scheme `graph_component`), not a branch in
   the read, and serves alice both end items and bob only the end item on their program. Deleting the alias row
   turns this half red with `unknown_part`.

2. THE ROUTER WOULD NOT SEND IT. `/find_compatible_verbs` walks the instance's class up
   `rdfs:subClassOf*` to a verb's input. `pcn:Component` has no declared path to `ps:Part`, the
   where-used input, so a question grounded on the notice's Component is never offered this verb.
   The missing piece is a DECLARATION, either an ontology row (`subClassOf`) or a second
   registration of the verb on `pcn:Component` (the `whatFailedOnThisPart` form). Choosing one is
   the architect's. The tripwire below fails when a subClassOf path lands. Then replace it with a
   positive assertion.

Run: uv run pytest tests/test_where_used_takes_the_notice_graphs_component.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import rdflib
import yaml
from fastapi.testclient import TestClient
from rdflib.namespace import RDFS

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


def test_TRIPWIRE_NO_DECLARED_PATH_TAKES_THE_NOTICE_COMPONENT_TO_THE_WHERE_USED_INPUT():
    """Today the router's subClassOf walk cannot reach the where-used input from the notice's
    Component. When this fails, a declaration landed: replace this with an assertion that the
    path exists, and measure the live route."""
    component = rdflib.URIRef(np_.INPUT_URI.rsplit("#", 1)[0] + "#Component")
    part = rdflib.URIRef(w.INPUT_URI)
    g = _declared_ontology()
    assert (component, None, None) in g, "the notice's Component class is not declared where read"
    assert (part, None, None) in g, "the where-used input class is not declared where read"
    ancestors = set(g.transitive_objects(component, RDFS.subClassOf))
    assert part not in ancestors, "a subClassOf path now takes Component to Part: assert it instead"
