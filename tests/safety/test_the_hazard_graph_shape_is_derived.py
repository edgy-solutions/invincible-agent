"""The hazard node shape is derived from the fixture and the ontology, and the engine's own
resolver already claims every fixture hazard (HAZ-1004 included) with NO graph seeding.

The last test is the one that waits: the seeded-graph routing path is not this engine's half.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.safety_agent import entities, graph_shape, instances

_TTL = Path(__file__).resolve().parents[2] / "setup" / "ontologies" / "safety_extension.ttl"


def test_there_is_a_node_per_fixture_hazard_with_derived_values():
    nodes = graph_shape.hazard_nodes()
    assert [n["props"]["identifier"] for n in nodes] == [h.hazard_id for h in entities.HAZARDS]
    assert len(nodes) >= 8  # positive control: the loop below is not over an empty set
    for n, h in zip(nodes, entities.HAZARDS):
        p = n["props"]
        assert p["hazardStatus"] == h.status and p["platform"] == h.platform
        assert p.get("severity") == h.severity and p.get("probability") == h.probability


def test_an_unassessed_hazard_has_no_severity_or_probability_key():
    """HAZ-1006 is not_assessed. Omitted, not seeded to a matrix corner."""
    p = next(n["props"] for n in graph_shape.hazard_nodes() if n["props"]["identifier"] == "HAZ-1006")
    assert p["hazardStatus"] == "not_assessed"
    assert "severity" not in p and "probability" not in p
    # CONTROL: an assessed hazard carries both.
    q = next(n["props"] for n in graph_shape.hazard_nodes() if n["props"]["identifier"] == "HAZ-1004")
    assert q["severity"] == "III" and q["probability"] == "B"


def test_property_names_are_declared_in_the_ontology_except_the_two_named_undeclared():
    ttl = _TTL.read_text(encoding="utf-8")
    declared = set(re.findall(r"^safety:(\w+) a owl:DatatypeProperty", ttl, re.MULTILINE))
    assert "hazardStatus" in declared  # positive control for the regex
    assert set(graph_shape.ONTOLOGY_PROPS) <= declared
    used = {k for n in graph_shape.hazard_nodes() for k in n["props"]}
    assert used - declared == set(graph_shape.UNDECLARED_PROPS)
    assert re.search(rf"^safety:{graph_shape.LABEL} a owl:Class", ttl, re.MULTILINE)


@pytest.mark.parametrize("hazard_id", [h.hazard_id for h in entities.HAZARDS])
def test_the_engines_own_resolver_claims_every_fixture_hazard_without_any_seeding(hazard_id):
    hits = instances.resolve(hazard_id, graph_shape.SAFETY + "Hazard")
    assert hits and hits[0]["instance_id"] == hazard_id


def test_the_resolver_control_a_hazard_not_in_the_fixture_is_not_claimed():
    assert instances.resolve("HAZ-9999", graph_shape.SAFETY + "Hazard") == []


@pytest.mark.skip(
    reason="WAITS ON lane 7f / doc-tools: (1) which seeder writes safety:Hazard nodes, (2) which "
    "store (Jena SUSTAINMENT_INSTANCES vs Neo4j), (3) a seeded store or double of the ontology-"
    "service resolve route. Until then no seeded-graph routing path exists to assert against, and "
    "the in-process resolver tests above already pass WITHOUT seeding. Control to write with it: "
    "the same ask against the unseeded store does not resolve."
)
def test_routing_resolves_HAZ_1004_from_a_seeded_graph_and_not_from_an_unseeded_one():
    raise AssertionError("unwritten: waits on the seeder half named in the skip reason")
