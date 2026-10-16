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

# engine-o's module imports weaviate -> authlib, which subclasses httpx.Client; _program_filter's import
# wraps httpx.Client, so engine-o must be imported FIRST (measured: metaclass conflict otherwise).
try:
    from agent_fleet.ontology_service import main as _EO_MAIN
except Exception:  # not installed here: the end-to-end arms skip
    _EO_MAIN = None

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


def test_a_resolved_component_with_no_records_gets_no_failures_recorded_and_no_task():
    out = measures.what_failed_on_this_part(part_number="5530-184")
    assert out["refused"] is True
    assert out["outcome"] == "no_failures_recorded"
    assert out["part_number"] == "5530-184"
    assert "no failures recorded" in out["reason"] and "5530-184" in out["reason"]
    assert not any("task" in k for k in out)


def test_an_unresolvable_part_gets_unknown_part():
    out = measures.what_failed_on_this_part(part_number="!! not a part ??")
    assert out["refused"] is True and out["outcome"] == "unknown_part"
    assert "unknown part" in out["reason"] and "!! not a part ??" in out["reason"]
    assert not any("task" in k for k in out)


def test_a_component_with_records_and_no_listing_returns_its_records(monkeypatch):
    """The listing is not a gate (ruled 2026-10-15): records on a plain component are returned."""
    from agent_fleet.safety_agent import failure_source as fs
    seed = fs.gather(fs.BY_PART, "PN-8801")[0]
    plain = "5530-190"
    assert plain not in measures.CRITICAL_PART_NUMBERS
    rec = fs.FailureRecord(record_id="FR-T-1", part_number=plain, platform=seed.platform,
                           system_of_record=seed.system_of_record, failure_mode="seized",
                           observed_on=seed.observed_on, citation=seed.citation)
    real = fs.gather
    monkeypatch.setattr(fs, "gather",
                        lambda by, v: [rec] if (by, v) == (fs.BY_PART, plain) else real(by, v))
    out = measures.what_failed_on_this_part(part_number=plain)
    assert out["refused"] is False and out["failure_count"] == 1, out


def test_the_router_hands_over_a_component_iri_and_the_part_number_is_its_last_segment():
    """MEASURED LIVE 2026-10-16 (rev 193): 'http://internal/components/5530-184' reached the verb as
    part_number and was refused unknown_part. The IRI and the bare number must answer the same."""
    iri = measures.what_failed_on_this_part(part_number="http://internal/components/5530-184")
    bare = measures.what_failed_on_this_part(part_number="5530-184")
    assert iri == bare and iri["outcome"] == "no_failures_recorded" and iri["part_number"] == "5530-184"
    listed = measures.what_failed_on_this_part(part_number="http://internal/components/PN-8801")
    assert listed["refused"] is False and listed["failure_count"] == 2, listed


def test_CONTROL_a_string_that_is_no_part_number_is_still_unknown_with_or_without_an_iri():
    out = measures.what_failed_on_this_part(part_number="http://internal/components/!! no ??")
    assert out["outcome"] == "unknown_part"


def test_the_census_reader_reads_the_refusal_it_is_now_sent():
    """The reader takes a refusal only as `refused: true` plus a string `outcome`."""
    from src.iagent_pure import walk_census as wc
    r = measures.what_failed_on_this_part(part_number="5530-184")
    comp = {wc.REFUSAL_FIELD: r}
    assert wc._card_refusals([comp]) == [r]


# ── the end-to-end arms: need lane/74's decide() (#58 at 7e5b2ba2 or later) ─────────────────
# They drive the REAL resolve path (engine-o's _resolve_instance, with Engine S's real
# /resolve_instance over an ASGI transport) through the harness #58's own test file builds. On a
# master WITHOUT #58 they are RED (ModuleNotFoundError or a wrong subject); they are not xfailed.

_TIE = "tests.routing.test_a_same_class_tie_asks_and_a_subclass_wins"


def _harness():
    import importlib
    return importlib.import_module(_TIE)


@pytest.fixture()
def eo_main():
    if _EO_MAIN is None:
        pytest.skip("ontology_service not importable here; run under the agent-fleet extra")
    return _EO_MAIN


def _verbs_on(class_uri):
    return {v["verb"] for v in safety_main.VERBS if v.get("input_uri") == class_uri}


def test_pn_8802_with_the_fracas_verb_is_answered_by_the_safety_item_provider(eo_main, monkeypatch):
    h = _harness()
    h._wire(eo_main, monkeypatch)
    subject, prov = h._resolve(eo_main, "PN-8802")
    assert subject == SAFETY_ITEM, prov
    assert prov["instance_id"] == "CSI-5002" and prov["instance_match"] == "exact"
    assert "mesh:whatFailedOnThisPart" in _verbs_on(subject), "the resolved class must carry the verb"
    # PN-8802 is a listed critical item whose sources hold no failure (fixture: only PN-8801 has
    # records): the provider ANSWERS, by the named refusal, not by unknown_part.
    out = measures.what_failed_on_this_part(part_number="PN-8802")
    assert out["refused"] is True and out["outcome"] == "no_failures_recorded", out


def test_an_unlisted_part_resolves_to_the_component_only_and_gets_the_refusal_end_to_end(eo_main, monkeypatch):
    h = _harness()
    iri = "http://internal/components/5530-184"
    h._wire(eo_main, monkeypatch, eo_rows=(iri,))
    subject, prov = h._resolve(eo_main, "5530-184")
    assert subject == COMPONENT, prov
    assert prov["instance_id"] == iri
    assert "mesh:whatFailedOnThisPart" in _verbs_on(subject), "Component must carry the verb"
    # the router hands the verb the instance id, an IRI: the verb must still settle it by name
    out = measures.what_failed_on_this_part(part_number=prov["instance_id"])
    assert out["refused"] is True and out["outcome"] == "no_failures_recorded", out


def test_a_same_class_tie_between_two_critical_items_asks_with_both_candidates(eo_main, monkeypatch):
    h = _harness()
    h._wire(eo_main, monkeypatch, eo_rows=())
    h._two(monkeypatch, "PN-9001", "PN-9001")
    subject, prov = h._resolve(eo_main, "PN-9001")
    assert subject == SAFETY_ITEM and prov["instance_match"] == "ambiguous_in_class", prov
    assert not prov["instance_resolved"]
    assert {t["instance_id"] for t in prov["instance_top_candidates"]} == {"CSI-7001", "CSI-7002"}
