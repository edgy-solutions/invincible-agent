"""A slot that declares `binds: identifier` receives the bare identifier, not the instance IRI.

RULED (architect, 192 item 3, Option 1): "declared per slot ... the slot declares what it wants; the
definitions decide, not the router." Safety's `part_number` was bound to
`http://internal/sustainment/pcn#5530-184` and the verb parsed the last segment off it (9ba26b68);
that parse stays as the fallback. The arms: the declaration (a, b), the bind through the real
`/fill_slots` (c-f), the menu and its validation (g), and the registration round trip (h).
"""
from __future__ import annotations

import asyncio
import json

import pytest

# engine-o's module must import FIRST: it pulls authlib, which subclasses httpx.Client, and the
# program-filter double wraps httpx.Client (metaclass conflict otherwise).
pytest.importorskip("rdflib")
from agent_fleet.ontology_service import main as _EO_MAIN  # noqa: F401,E402
from agent_fleet.safety_agent import entities as safety_entities  # noqa: E402
from agent_fleet.safety_agent import main as safety_main  # noqa: E402
from agent_fleet.safety_agent import slots as safety_slots
from agent_fleet.utils.slot_declarations import derive_slots
from iagent_pure import slot_disposition as sd
from iagent_pure.slot_acceptance import decode_declarations
from tests._helpers.sustainment_resolution import eo, wire  # noqa: F401 (eo is a fixture)
from tests.safety import _program_filter as pf

VERB = "what_failed_on_this_part"
IRI = "http://internal/sustainment/pcn#5530-184"
COMPONENT = "http://internal/sustainment/pcn#Component"


def _part_slot():
    return next(s for s in safety_slots.slots_for(VERB) if s["name"] == "part_number")


# -- (a) the declaration ---------------------------------------------------------------------

#: The referent slots of Engine S's verbs, as of the Day 2 order (architect, overnight 10-17):
#: "binds: identifier for the remaining safety slots". Stated so the census below cannot pass on
#: an empty or shrunken population.
REFERENT_SLOTS = {
    ("assess_deferral_risk", "work_order_id"),
    ("draft_risk_assessment", "hazard_id"),
    ("failure_trend_for_this_platform_by_month", "platform_id"),
    (VERB, "part_number"),
}


def test_every_safety_referent_slot_declares_binds_identifier_and_no_other_slot_does():
    """Was "part_number and no other slot" (192 item 3); widened by the Day 2 order. The population
    is derived from every registered verb, so a new referent slot without `binds` reds here."""
    assert _part_slot()["binds"] == "identifier"
    assert set(safety_slots._BINDS) == set(safety_slots._REFERENT_KIND)
    seen = set()
    for fn in sorted({v["fn"] for v in safety_main.VERBS}):
        for s in safety_slots.slots_for(fn):
            if "referent" in s:
                seen.add((fn, s["name"]))
                assert s.get("binds") == "identifier", (fn, s)
            else:
                assert "binds" not in s, (fn, s)
    assert seen == REFERENT_SLOTS


# -- (b) derive time refusals ------------------------------------------------------------------

def _fn(a: str, b: str = "x", h: str = "H"):
    return None


def test_derive_slots_refuses_binds_on_a_handle_a_referentless_slot_and_an_unknown_value():
    ref = {"a": COMPONENT}
    ok = derive_slots(_fn, handles={"h"}, referents=ref, binds={"a": "identifier"})
    assert next(r for r in ok if r["name"] == "a")["binds"] == "identifier"
    with pytest.raises(ValueError):
        derive_slots(_fn, handles={"h"}, referents=ref, binds={"h": "identifier"})
    with pytest.raises(ValueError):
        derive_slots(_fn, referents=ref, binds={"b": "identifier"})  # spoken, no referent
    with pytest.raises(ValueError):
        derive_slots(_fn, referents=ref, binds={"a": "iri"})
    # a name that is no parameter of this verb is skipped, so one engine map serves every verb
    assert all("binds" not in r for r in derive_slots(_fn, referents=ref, binds={"nope": "identifier"}))


def test_unnamed_slots_carry_no_binds_key_at_all():
    recs = derive_slots(_fn, referents={"a": COMPONENT}, binds={"a": "identifier"})
    assert all("binds" not in r for r in recs if r["name"] != "a")
    assert all("binds" not in r for r in derive_slots(_fn, referents={"a": COMPONENT}))


# -- (c-f) through the real /fill_slots ------------------------------------------------------------

@pytest.fixture(autouse=True)
def _alice(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)


def _fill(eo, monkeypatch, said, declarations, name="part_number"):
    class _Filled:
        slots_json = json.dumps({name: said})
        confidence = 0.9
        reasoning = "stub"

    async def _fake(**kw):
        return _Filled()

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(query="what failed on " + said, verb_iri="mesh:whatFailedOnThisPart",
                              declarations=json.dumps(declarations), user_email="alice@example.com",
                              acting_domains=["SUSTAINMENT"])
    return asyncio.run(eo.fill_slots(req))


def _without_binds():
    return [{k: v for k, v in s.items() if k != "binds"} for s in safety_slots.slots_for(VERB)]


def test_a_pcn_component_binds_the_bare_part_number_not_its_iri(eo, monkeypatch):
    wire(eo, monkeypatch, eo_rows=(IRI,))
    r = _fill(eo, monkeypatch, "5530-184", safety_slots.slots_for(VERB))
    assert r.slots == {"part_number": "5530-184"}, r
    assert r.resolution["part_number"]["instance_id"] == IRI, "the IRI must stay in provenance"


def test_a_safety_csi_candidate_binds_the_part_number_it_matched_on(eo, monkeypatch):
    wire(eo, monkeypatch, eo_rows=())
    r = _fill(eo, monkeypatch, "PN-8802", safety_slots.slots_for(VERB))
    assert r.slots == {"part_number": "PN-8802"}, r
    assert r.resolution["part_number"]["instance_id"] == "CSI-5002"


def test_a_candidate_with_empty_matched_on_falls_back_to_the_instance_id(eo, monkeypatch):
    wire(eo, monkeypatch, eo_rows=())  # a CSI spoken by its id: the id tier sets matched_on ""
    r = _fill(eo, monkeypatch, "CSI-5002", safety_slots.slots_for(VERB))
    assert r.slots == {"part_number": "CSI-5002"}, r


def test_CONTROL_the_same_fixture_without_the_declaration_still_binds_the_iri(eo, monkeypatch):
    wire(eo, monkeypatch, eo_rows=(IRI,))
    r = _fill(eo, monkeypatch, "5530-184", _without_binds())
    assert r.slots == {"part_number": IRI}, r


@pytest.mark.parametrize("fn,name,said", [
    ("draft_risk_assessment", "hazard_id", "HAZ-1003"),
    ("failure_trend_for_this_platform_by_month", "platform_id", safety_entities.PLATFORM_IDS[0]),
])
@pytest.mark.parametrize("declared", [True, False], ids=["binds", "CONTROL-no-binds"])
def test_a_safety_owned_referent_binds_the_bare_id_either_way(eo, monkeypatch, fn, name, said, declared):
    """saf's provider publishes the bare id as `instance_id` with `matched_on` empty, so the
    declaration is a no-op on its own classes: the same bare id with and without it."""
    wire(eo, monkeypatch, eo_rows=())
    decls = [s for s in safety_slots.slots_for(fn) if s["name"] == name]
    assert decls[0]["binds"] == "identifier"
    if not declared:
        decls = [{k: v for k, v in s.items() if k != "binds"} for s in decls]
    r = _fill(eo, monkeypatch, said, decls, name=name)
    assert r.slots == {name: said}, r
    assert r.resolution[name]["instance_id"] == said, r.resolution


def test_the_two_bound_value_rules_agree(eo):
    for decl in ({"binds": "identifier"}, {}):
        for cand in ({"instance_id": IRI, "matched_on": "5530-184"}, {"instance_id": "CSI-1"},
                     {"instance_id": "CSI-1", "matched_on": ""}):
            assert eo._bound_value(decl, cand) == sd.bound_value(decl, cand)


# -- (g) the menu and its validation ------------------------------------------------------------

def _decls():
    return json.dumps(safety_slots.slots_for(VERB))


CANDS = [{"instance_id": IRI, "class_uri": COMPONENT, "label": "5530-184", "score": 0.9,
          "matched_on": "5530-184"},
         {"instance_id": "CSI-5002", "class_uri": COMPONENT, "label": "Pump", "score": 0.8,
          "matched_on": ""}]


def test_the_menu_offers_matched_on_for_a_binds_slot_and_the_id_otherwise():
    opts, _ = sd._from_candidates(CANDS, referent=COMPONENT, menu_bound=8, decl={"binds": "identifier"})
    assert [o.value for o in opts] == ["5530-184", "CSI-5002"]
    opts, _ = sd._from_candidates(CANDS, referent=COMPONENT, menu_bound=8)
    assert [o.value for o in opts] == [IRI, "CSI-5002"]


def test_validate_bound_slots_accepts_the_menu_value_and_refuses_one_in_no_candidate():
    resolve = lambda name, referent: CANDS  # noqa: E731
    out, refusals, _ = sd.validate_bound_slots(
        {"part_number": "5530-184"}, declared=_decls(), resolve_identifier=resolve)
    assert out == {"part_number": "5530-184"} and not refusals, refusals
    out, refusals, _ = sd.validate_bound_slots(
        {"part_number": "9999-999"}, declared=_decls(), resolve_identifier=resolve)
    assert out == {} and refusals, "a value in no candidate must still be refused"


# -- (h) the registration round trip -----------------------------------------------------------

def test_binds_survives_the_registrar_and_decode_declarations():
    from agent_fleet.mesh_registrar.main import RegistrationManifest, _build_rel_props_for_saga
    decl = safety_slots.slots_for(VERB)
    m = RegistrationManifest(
        name="engine_safety_what_failed", verb_iri="mesh:whatFailedOnThisPart",
        input_uri=COMPONENT, output_uri="mesh:Out", endpoint_url="http://safety:8000",
        owner_persona="SAFETY_ENGINEER", domains=["SUSTAINMENT"], cost_class="fast",
        requires_human_approval=False, version="0.1.0", slots=decl)
    props = _build_rel_props_for_saga(manifest=m, provider="engine_safety", tool_urn="urn:li:mlModel:(x)")
    back = {d["name"]: d for d in decode_declarations(props["slots"])}
    assert back["part_number"]["binds"] == "identifier"
    assert back == {d["name"]: d for d in decl}


# -- the other binding sites: the DOCS pool (two) and the scoped menu ----------------------------------

def _decl(name, **kw):
    return {"name": name, "kind": "spoken-mandatory", "type": "str", "required": True, **kw}


def _fill_many(eo, monkeypatch, said, declarations):
    class _Filled:
        slots_json = json.dumps(said)
        confidence = 0.9
        reasoning = "stub"

    async def _fake(**kw):
        return _Filled()

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(query="q", verb_iri="mesh:whatFailedOnThisPart",
                              declarations=json.dumps(declarations), user_email="alice@example.com",
                              acting_domains=["SUSTAINMENT"])
    return asyncio.run(eo.fill_slots(req))


_BOUND = {"outcome": "exact", "spoken": "x", "instance_id": IRI, "matched_on": "5530-184"}


def _docs(eo, monkeypatch):
    async def _page(spoken, query):
        return dict(_BOUND)

    monkeypatch.setattr(eo, "_docs_pool_applies", lambda *a, **k: True)
    monkeypatch.setattr(eo, "_docs_pool_accepts", lambda *a, **k: True)
    monkeypatch.setattr(eo, "_bind_docs_slot", _page)


@pytest.mark.parametrize("binds,want", [({"binds": "identifier"}, "5530-184"), ({}, IRI)])
def test_the_docs_pool_bind_for_an_unspoken_slot_follows_the_declaration(eo, monkeypatch, binds, want):
    _docs(eo, monkeypatch)
    r = _fill_many(eo, monkeypatch, {}, [_decl("part_number", referent=COMPONENT, **binds)])
    assert r.slots == {"part_number": want}, r


@pytest.mark.parametrize("binds,want", [({"binds": "identifier"}, "5530-184"), ({}, IRI)])
def test_the_docs_pool_bind_for_a_spoken_slot_follows_the_declaration(eo, monkeypatch, binds, want):
    _docs(eo, monkeypatch)
    r = _fill_many(eo, monkeypatch, {"part_number": "5530-184"},
                   [_decl("part_number", referent=COMPONENT, **binds)])
    assert r.slots == {"part_number": want}, r


@pytest.mark.parametrize("binds,want", [({"binds": "identifier"}, "5530-184"), ({}, IRI)])
def test_the_scoped_menu_bind_follows_the_declaration(eo, monkeypatch, binds, want):
    async def _scoped(*a, **k):
        return dict(_BOUND)

    monkeypatch.setattr(eo, "_bind_from_scope", _scoped)
    r = _fill_many(eo, monkeypatch, {"lot": "L1", "part_number": "5530-184"},
                   [_decl("lot"), _decl("part_number", referent=COMPONENT, narrowed_by=["lot"], **binds)])
    assert r.slots == {"lot": "L1", "part_number": want}, r
