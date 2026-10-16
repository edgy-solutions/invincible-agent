"""PN-8802 is both a SafetyCriticalItem and (in engine-o's vocabulary) a pcn#Component.

RULED 2026-10-15: a critical item IS a component that has a safety listing, so
`safety:SafetyCriticalItem rdfs:subClassOf pcn:Component`; when two classes resolve one subject and
both carry the verb asked, the MOST SPECIFIC class wins (decide() reads the axis; lane/74's code).
`mesh:whatFailedOnThisPart` is registered on BOTH classes; a component the engine does not list
gets the NAMED `unknown_part` refusal (the 5530-184 census row). Verbs are derived from VERBS.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

from agent_fleet.ontology_service import sustainment_instance_provider as eo
from agent_fleet.safety_agent import main as safety_main, measures

from . import _program_filter as pf

_REPO = Path(__file__).resolve().parents[2]
SAFETY_ITEM = safety_main.SAFETY + "SafetyCriticalItem"
COMPONENT = safety_main.PCN + "Component"


def _loaded_ttl() -> Path:
    """The file the prime manifest actually loads (setup/prime_databases.py), not a guessed path."""
    manifest = (_REPO / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    m = re.search(r'"name":\s*"safety_extension",\s*"s3_key":\s*"[^"]+",\s*"path":\s*"([^"]+)"', manifest)
    assert m, "safety_extension is not in the prime manifest"
    return _REPO / "setup" / m.group(1)


def verbs_taking(class_uri):
    """Verb IRIs registered with `class_uri` as input, derived from this engine's VERBS."""
    return {v["verb"] for v in safety_main.VERBS if v["input_uri"] == class_uri}


# ── the axiom ───────────────────────────────────────────────────────────────────────────────

def test_the_subclass_axiom_is_in_the_file_the_prime_manifest_loads():
    g = Graph().parse(_loaded_ttl(), format="turtle")
    assert (URIRef(SAFETY_ITEM), RDFS.subClassOf, URIRef(COMPONENT)) in g


def test_the_pcn_prefix_is_the_iri_engine_o_uses_for_component():
    g = Graph().parse(_loaded_ttl(), format="turtle")
    assert dict(g.namespaces())["pcn"] == URIRef(eo._COMPONENT_CLASS[: -len("Component")])
    assert COMPONENT == eo._COMPONENT_CLASS


def test_the_component_class_the_axiom_points_at_is_primed():
    pcn = (_REPO / "setup" / "ontologies" / "pcn_extension.ttl")
    assert (URIRef(COMPONENT), RDFS.label, None) in Graph().parse(pcn, format="turtle")
    assert "pcn_extension" in (_REPO / "setup" / "prime_databases.py").read_text(encoding="utf-8")


# ── the registration ────────────────────────────────────────────────────────────────────────

def test_the_verb_is_registered_on_both_classes_derived_from_VERBS():
    assert verbs_taking(SAFETY_ITEM) == verbs_taking(COMPONENT) == {"mesh:whatFailedOnThisPart"}


def test_the_two_registrations_have_distinct_names():
    """One verb registered twice under one name DELETES the first edge (the registrar sweep)."""
    names = [v.get("name") or f"engine_safety_{v['fn']}" for v in safety_main.VERBS]
    assert len(names) == len(set(names))


def test_the_measure_route_still_runs_the_one_function_for_both_registrations():
    assert safety_main.BY_FN["what_failed_on_this_part"]["input_uri"] == SAFETY_ITEM


# ── the answer ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _alice(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)


def test_a_listed_part_returns_its_records():
    out = measures.what_failed_on_this_part(part_number="PN-8801")
    assert out["refused"] is False and out["failure_count"] == 2, out


def test_an_unlisted_component_gets_the_named_refusal_and_no_task():
    out = measures.what_failed_on_this_part(part_number="5530-184")
    assert out["refused"] is True
    assert out["outcome"] == "unknown_part"
    assert out["part_number"] == "5530-184"
    assert "unknown part" in out["reason"]
    assert not any("task" in k for k in out)


def test_the_census_reader_reads_the_refusal_it_is_now_sent():
    """The reader takes a refusal only as `refused: true` plus a string `outcome`."""
    from src.iagent_pure import walk_census as wc
    r = measures.what_failed_on_this_part(part_number="5530-184")
    comp = {wc.REFUSAL_FIELD: r}
    assert wc._card_refusals([comp]) == [r]


# ── held: the end-to-end arms, until lane/74's decide() subclass read lands (189) ───────────

@pytest.mark.skip(reason=(
    "BLOCKED on lane/74's decide() change (ruling 2026-10-15): decide() reads rdfs:subClassOf from "
    "the ontology and, when two classes resolve one subject and both carry the verb, the most "
    "specific class wins; same-class tie -> ambiguous_in_class. Unskip when it lands in 189: "
    "PN-8802 as bob + whatFailedOnThisPart through the service binds SafetyCriticalItem."
))
def test_pn_8802_with_the_fracas_verb_is_answered_by_the_safety_item_provider():
    raise AssertionError("unreachable until decide() reads the subclass axis")


@pytest.mark.skip(reason=(
    "BLOCKED on 189 (lane/74's decide() change plus this PR's registration live): an unlisted "
    "part number resolves to pcn:Component only, binds whatFailedOnThisPart, and returns the "
    "named unknown_part refusal through the service (the 5530-184 row). Walk live after 189."
))
def test_an_unlisted_part_resolves_to_the_component_only_and_gets_the_refusal_end_to_end():
    raise AssertionError("unreachable until the registration is live")
