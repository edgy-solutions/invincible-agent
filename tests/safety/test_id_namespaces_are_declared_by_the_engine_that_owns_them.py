"""Engine S declares the identifier namespaces it owns: HAZ-, CSI-, MIT-; never WO-.

RULED 2026-10-12 (architect, lane/saf's Q3): an identifier namespace is claimed by exactly one
engine, declared in that engine's registration; engine-o's fan-out refuses another provider's
FUZZY candidate for an identifier in a declared namespace. engine-o's half is on master
(`instance_resolution.refuse_cross_namespace`, applied in `ontology_service/main.py`'s
resolveInstance fan-out); this file seals the declaring half and the HAZ-1004 outcome.

The declaration is read OFF THE REGISTRATION CALLS the engine's own lifespan makes, not off the
constant, and the prefixes are checked against the ids the fixture actually holds.
"""
from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from agent_fleet.ontology_service.instance_resolution import (
    InstanceCandidate, claimed_namespaces, refuse_cross_namespace)
from agent_fleet.safety_agent import entities, main as safety_main

_RESOLVE = "mesh:resolveInstance"
_EO = "engine_o_sustainment"
_S = "engine_safety_sustainment"
_PCN = "http://internal/sustainment/pcn#Component"


@pytest.fixture
def registrations(monkeypatch):
    """Every register_engine_to_mesh call the real lifespan makes, as kwargs."""
    calls: list[dict] = []

    def _fake(**kw):
        calls.append(kw)

    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    patched = 0
    for modname in ("utils.mesh_registration", "agent_fleet.utils.mesh_registration"):
        try:
            mod = __import__(modname, fromlist=["x"])
        except ImportError:
            continue
        monkeypatch.setattr(mod, "register_engine_to_mesh", _fake)
        patched += 1
    assert patched, "no mesh_registration module importable"

    async def _run():
        async with safety_main.lifespan(safety_main.app):
            pass

    asyncio.run(_run())
    assert calls, "the lifespan registered nothing"
    return calls


def _declared(calls):
    return [c for c in calls if c.get("verb") == _RESOLVE]


def test_the_resolve_instance_row_declares_the_three_prefixes(registrations):
    rows = _declared(registrations)
    assert len(rows) == 1
    assert list(rows[0]["id_namespaces"]) == ["HAZ-", "CSI-", "MIT-"]


def test_no_other_row_declares_a_namespace(registrations):
    others = [c for c in registrations if c.get("verb") != _RESOLVE]
    assert others, "fixture assumption: the engine registers other rows"
    assert not any(c.get("id_namespaces") for c in others)


def test_the_declared_set_is_derived_from_the_ids_the_fixture_holds(registrations):
    """Hazards, critical items and mitigations each begin with exactly one declared prefix."""
    declared = set(_declared(registrations)[0]["id_namespaces"])
    ids = ([h.hazard_id for h in entities.HAZARDS] + [c.csi_id for c in entities.CRITICAL_ITEMS]
           + [m.mitigation_id for h in entities.HAZARDS for m in h.mitigations])
    prefixes = {i.split("-")[0] + "-" for i in ids}
    assert prefixes == declared, (prefixes, declared)


def test_CONTROL_work_orders_exist_in_the_fixture_and_are_not_declared(registrations):
    """The WO- absence is a decision, not a gap: the fixture holds work orders, and the maintenance
    plane owns them."""
    declared = set(_declared(registrations)[0]["id_namespaces"])
    wo_prefixes = {w.work_order_id.split("-")[0] + "-" for w in entities.WORK_ORDERS}
    assert wo_prefixes == {"WO-"}
    assert not (wo_prefixes & declared)


def _resolvers(declared):
    return [
        {"provider": _EO, "id_namespaces": []},
        {"provider": _S, "id_namespaces": list(declared)},
    ]


def test_a_fuzzy_non_owner_match_on_a_wo_identifier_is_kept_while_a_haz_one_is_refused(registrations):
    declared = _declared(registrations)[0]["id_namespaces"]
    fuzzy = lambda label: InstanceCandidate(  # noqa: E731
        f"http://internal/components/{label}", _PCN, label, 0.556, _EO)
    kept, refused, claimed = refuse_cross_namespace(
        [fuzzy("HX3120004Q")], terms=["HAZ-1004"], resolvers=_resolvers(declared))
    assert kept == [] and len(refused) == 1 and "HAZ-" in claimed
    kept, refused, claimed = refuse_cross_namespace(
        [fuzzy("WX3001Q")], terms=["WO-3001"], resolvers=_resolvers(declared))
    assert len(kept) == 1 and refused == [] and claimed == {}
    assert claimed_namespaces(["WO-3001"], _resolvers(declared)) == {}


def test_haz_1004_resolves_to_exactly_one_candidate_across_the_fan_out(registrations):
    """The measured HAZ-1004 defect (two engine-o part numbers on a difflib ratio beside Engine S's
    exact hazard), with Engine S's candidate taken from its REAL route and its declaration taken
    from its REAL registration. Without the declaration the same fan-out keeps all three."""
    declared = _declared(registrations)[0]["id_namespaces"]
    body = TestClient(safety_main.app).post(
        "/resolve_instance", json={"identifier": "HAZ-1004", "query": "HAZ-1004"}).json()
    own = [InstanceCandidate(c["instance_id"], c["class_uri"], c["label"] if "label" in c else
                             c["instance_id"], c["score"], _S) for c in body["candidates"]]
    assert len(own) == 1
    theirs = [InstanceCandidate("http://internal/components/HX3120004Q", _PCN, "HX3120004Q", 0.556, _EO),
              InstanceCandidate("http://internal/components/AZV5001RA4-7", _PCN, "AZV5001RA4-7", 0.5, _EO)]
    kept, refused, _ = refuse_cross_namespace(theirs + own, terms=["HAZ-1004"],
                                              resolvers=_resolvers(declared))
    assert [c.instance_id for c in kept] == ["HAZ-1004"] and len(refused) == 2
    # control: the same fan-out with nothing declared keeps all three (today's ambiguous_in_domain)
    kept0, refused0, _ = refuse_cross_namespace(theirs + own, terms=["HAZ-1004"],
                                                resolvers=_resolvers(()))
    assert len(kept0) == 3 and refused0 == []
