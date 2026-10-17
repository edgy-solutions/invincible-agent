"""A same-class tie asks; a subclass wins -- RULED 2026-10-15 (Chris), roll 190.

THE RULING.
  1. Two or more DISTINCT instances of ONE class sharing the top score is `ambiguous_in_class`, a
     refusal of the INSTANCE bind carrying the tied candidates. `decide()` used to take the first.
  2. Candidates of different classes on ONE `rdfs:subClassOf` chain: the MOST SPECIFIC class wins.
     The chain is read from the ontology (`_CLASS_CHAIN_CYPHER`, `subClassOf*0..5`).
  3. `ambiguous_in_domain` stays for classes NOT on one chain, and for a chain that could not be
     read (graph down) -- which says so (`instance_class_axis_status: unavailable`).

THE CASE. PN-8802 is `safety#SafetyCriticalItem` CSI-5002 (engine_safety_sustainment) AND the
`pcn#Component` http://internal/components/PN-8802 (engine_o_sustainment), and
`SafetyCriticalItem rdfs:subClassOf pcn:Component` (setup/ontologies/safety_extension.ttl). One
part, seen twice. Before: two claimants, two subjects, `ambiguous_in_domain`. After: CSI-5002.

SAF'S TIE RECIPE (lane/saf's 2026-10-15 packet). Two critical items with an identical
`part_number` both score 1.0; "PN-9001" vs "pn 9001" asked as "PN_9001" both score 0.9.

WHAT IS REAL. The pure `decide`; engine-o's real `_resolve_instance` and `_call_resolver`; saf's
real `/resolve_instance` and engine-o's own `/resolve_instance`, both reached over a real
`httpx.AsyncClient` on an ASGI transport that routes by host; the class chains, computed with
rdflib from the TTL files the prime manifest loads. WHAT IS STUBBED: the provider registry,
engine-o's SPARQL, the model's slot extraction, and the Neo4j driver (a double that answers
`_CLASS_CHAIN_CYPHER` from those files).
The wiring (`wire`, `two`, `resolve`, the driver double) lives in
`tests/_helpers/sustainment_resolution.py`, shared with lane/saf (RULED 2026-10-16).

Run: uv run pytest tests/routing/test_a_same_class_tie_asks_and_a_subclass_wins.py -v
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent_fleet.ontology_service.instance_resolution import (
    InstanceCandidate,
    decide,
    most_specific_class,
    normalise_identifier,
    narrow_to_most_specific,
)
from agent_fleet.safety_agent import instances
from agent_fleet.safety_agent.slots import slots_for

from tests._helpers.sustainment_resolution import (  # noqa: F401 (eo is a fixture)
    COMPONENT,
    EO_PART,
    SAFETY_ITEM,
    chain as _chain,
    eo,
    outcomes as _outcomes,
    resolve as _resolve,
    two as _two,
    wire as _wire,
)


# -- the double the helpers wire in reads the real files ---------------------------------------

def test_the_double_reads_the_real_axiom():
    assert _chain(SAFETY_ITEM)[:2] == [SAFETY_ITEM, COMPONENT]
    assert _chain(COMPONENT)[0] == COMPONENT


# -- pure arms --------------------------------------------------------------------------------

def _c(iid, cls=SAFETY_ITEM, score=1.0, provider="p"):
    return InstanceCandidate(instance_id=iid, class_uri=cls, label=iid, score=score, provider=provider)


def test_1_an_exact_same_class_tie_asks():
    d = decide([_c("CSI-7001"), _c("CSI-7002")])
    assert d.provenance["instance_match"] == "ambiguous_in_class"
    assert d.provenance["instance_resolved"] is False
    assert d.subject_uri == SAFETY_ITEM
    assert {t["instance_id"] for t in d.provenance["instance_top_candidates"]} == {"CSI-7001", "CSI-7002"}


def test_2_a_normalised_tie_asks():
    d = decide([_c("CSI-7001", score=0.9), _c("CSI-7002", score=0.9)])
    assert d.provenance["instance_match"] == "ambiguous_in_class"
    assert d.provenance["instance_score"] == 0.9


def test_3_exact_beats_normalised():
    d = decide([_c("CSI-7002", score=0.9), _c("CSI-7001", score=1.0)])
    assert d.provenance["instance_match"] == "exact"
    assert d.provenance["instance_id"] == "CSI-7001"


def test_4_the_same_instance_twice_is_not_a_tie():
    d = decide([_c("CSI-7001"), _c("CSI-7001")])
    assert d.provenance["instance_match"] == "exact" and d.provenance["instance_id"] == "CSI-7001"


def test_4b_a_tie_offers_each_instance_once():
    # test_4 cannot see the dedupe -- the tie counts DISTINCT ids. The menu can: /fill_slots
    # builds its choices from instance_top_candidates, so one instance reached by two terms
    # must be one choice, and instance_n counts instances, not arrivals.
    d = decide([_c("CSI-7001", provider="a"), _c("CSI-7001", provider="b"), _c("CSI-7002")])
    assert d.provenance["instance_match"] == "ambiguous_in_class"
    assert [c["instance_id"] for c in d.provenance["instance_top_candidates"]] == ["CSI-7001", "CSI-7002"]
    assert d.provenance["instance_n"] == 2


def test_5_cross_class_on_a_chain_the_subclass_wins():
    chains = {SAFETY_ITEM: _chain(SAFETY_ITEM), COMPONENT: _chain(COMPONENT)}
    d = decide([_c("CSI-5002"), _c(EO_PART, cls=COMPONENT)], class_chains=chains)
    assert d.subject_uri == SAFETY_ITEM and d.provenance["instance_id"] == "CSI-5002"
    assert d.provenance["instance_class_axis"]["kept_class"] == SAFETY_ITEM
    assert d.provenance["instance_class_axis"]["dropped_classes"] == [COMPONENT]
    # CONTROL: without the chains the pure table does not narrow (the caller reads the axis).
    assert "instance_class_axis" not in decide(
        [_c("CSI-5002"), _c(EO_PART, cls=COMPONENT)]).provenance


def test_6_most_specific_class():
    chains = {"a": ["a", "b", "c"], "b": ["b", "c"], "c": ["c"], "u": ["u"]}
    assert most_specific_class(["a", "b", "c"], chains) == "a"
    assert most_specific_class(["a", "zz"], chains) is None, "a missing chain"
    assert most_specific_class(["a", "u"], chains) is None, "unrelated"
    assert most_specific_class(["a", "a"], chains) is None, "fewer than two distinct classes"
    cyc = {"x": ["x", "y"], "y": ["y", "x"]}
    assert most_specific_class(["x", "y"], cyc) is None, "a cycle"
    assert most_specific_class(["a", "b", ""], chains) is None, "a classless candidate blocks"
    kept, info = narrow_to_most_specific([_c("1", "a"), _c("2", "b")], chains)
    assert [k.instance_id for k in kept] == ["1"] and info["dropped_n"] == 1
    same, none = narrow_to_most_specific([_c("1", "a"), _c("2", "u")], chains)
    assert len(same) == 2 and none is None


def test_7_a_matched_on_the_identifier_does_not_name_is_still_refused():
    c = InstanceCandidate(instance_id="CSI-5002", class_uri=SAFETY_ITEM,
                          label="PN-8802 - Fuel quantity probe seal kit.", score=1.0,
                          matched_on="PN-8802")
    assert decide([c], identifier="PN-8802").provenance["instance_match"] == "exact"
    assert decide([c], identifier="PN-8803").provenance["instance_match"] == "not_specific"
    bare = replace(c, matched_on="")
    assert decide([bare], identifier="PN-8802").provenance["instance_match"] == "not_specific"


def test_7b_a_normalised_spelling_of_matched_on_is_the_same_identifier():
    """RULED 2026-10-16: `PN_9001`, `PN-9001`, `pn 9001` are one identifier at decide(), as in
    safety's provider. Normalising is case-fold plus collapsing runs of `-`, `_` and whitespace --
    NOT dropping them, so a different number is still a different identifier."""
    assert normalise_identifier("PN_9001") == normalise_identifier("pn 9001") == normalise_identifier(" PN-_9001 ")
    for spelled in ("PN-9001", "pn 9001", "Pn__9001"):
        c = InstanceCandidate(instance_id="CSI-7001", class_uri=SAFETY_ITEM,
                              label="Fuel quantity probe seal kit.", score=0.9, matched_on=spelled)
        assert decide([c], identifier="PN_9001").provenance["instance_match"] == "fuzzy", spelled
    # CONTROLS, each differing in one thing: another number, and no matched_on (ids and labels keep
    # the 2026-08-30 segment rule -- the label spells the part number, normalised, and is refused).
    other = InstanceCandidate(instance_id="CSI-7001", class_uri=SAFETY_ITEM,
                              label="Fuel quantity probe seal kit.", score=0.9, matched_on="PN-90011")
    assert decide([other], identifier="PN_9001").provenance["instance_match"] == "not_specific"
    # COLLAPSED, NOT DROPPED -- safety's provider maps `PN9001` to `pn9001`, not `pn-9001`, so the
    # layers agree only if this gate refuses it too.
    unseparated = replace(other, matched_on="PN9001")
    assert decide([unseparated], identifier="PN_9001").provenance["instance_match"] == "not_specific"
    by_label = InstanceCandidate(instance_id="CSI-7001", class_uri=SAFETY_ITEM,
                                 label="pn 9001", score=0.9)
    assert decide([by_label], identifier="PN_9001").provenance["instance_match"] == "not_specific"


# -- through the service ----------------------------------------------------------------------

def test_8_the_axis_never_narrows_to_a_class_the_gate_would_empty():
    chains = {SAFETY_ITEM: _chain(SAFETY_ITEM), COMPONENT: _chain(COMPONENT)}
    csi = InstanceCandidate(instance_id="CSI-5002", class_uri=SAFETY_ITEM,
                            label="PN-8802 - Fuel quantity probe seal kit.", score=1.0)
    part = InstanceCandidate(instance_id=EO_PART, class_uri=COMPONENT, label="PN-8802", score=1.0)
    kept, info = narrow_to_most_specific([csi, part], chains, "PN-8802")
    assert info is None and len(kept) == 2, "the subclass has no name the gate keeps"
    # CONTROL, differing only in the subclass candidate's matched_on: now it narrows.
    kept, info = narrow_to_most_specific([replace(csi, matched_on="PN-8802"), part], chains, "PN-8802")
    assert info["kept_class"] == SAFETY_ITEM and [k.instance_id for k in kept] == ["CSI-5002"]


def test_S1_pn_8802_binds_the_critical_item(eo, monkeypatch):
    _wire(eo, monkeypatch)
    subject, prov = _resolve(eo, "PN-8802")
    out = _outcomes(prov)
    assert {p: out[p]["status"] for p in out} == {
        "engine_safety_sustainment": "ok", "engine_o_sustainment": "ok"}, out
    assert all(o["n_candidates"] >= 1 for o in out.values()), "both providers must answer for PN-8802"
    assert subject == SAFETY_ITEM
    assert prov["instance_id"] == "CSI-5002" and prov["instance_match"] == "exact"
    assert prov["instance_class_axis"]["kept_class"] == SAFETY_ITEM


def test_S1_control_without_matched_on_the_gate_refuses_the_critical_item(eo, monkeypatch):
    """`matched_on` is what passes the gate: strip it from saf's candidates and CSI-5002 (label
    ends "seal kit.") has no name the gate keeps. The axis then does NOT narrow to it (it never
    narrows to a class the gate would empty), so the answer is the base's `ambiguous_in_domain`,
    not a `not_specific` that hid the Component the gate keeps (measured before that rule)."""
    _wire(eo, monkeypatch)
    real = instances.resolve

    def _stripped(*a, **k):
        return [{kk: v for kk, v in c.items() if kk != "matched_on"} for c in real(*a, **k)]

    monkeypatch.setattr(instances, "resolve", _stripped)
    subject, prov = _resolve(eo, "PN-8802")
    assert subject is None and prov["instance_match"] == "ambiguous_in_domain", prov
    assert prov["instance_class_axis_status"] == "read", "the axis was read, and declined to narrow"


def test_S2_control_the_graph_down_is_todays_ambiguous_in_domain(eo, monkeypatch):
    _wire(eo, monkeypatch, graph_down=True)
    subject, prov = _resolve(eo, "PN-8802")
    assert subject is None and prov["instance_match"] == "ambiguous_in_domain"
    assert prov["instance_class_axis_status"] == "unavailable"


def test_S3_a_same_class_exact_tie_asks(eo, monkeypatch):
    _wire(eo, monkeypatch, eo_rows=())
    _two(monkeypatch, "PN-9001", "PN-9001")
    subject, prov = _resolve(eo, "PN-9001")
    assert subject == SAFETY_ITEM and prov["instance_match"] == "ambiguous_in_class"
    assert not prov["instance_resolved"]
    assert {t["instance_id"] for t in prov["instance_top_candidates"]} == {"CSI-7001", "CSI-7002"}


def test_S4_a_normalised_tie_asks(eo, monkeypatch):
    # Was a strict xfail until the 2026-10-16 ruling: the gate now compares matched_on normalised.
    _wire(eo, monkeypatch, eo_rows=())
    _two(monkeypatch, "PN-9001", "pn 9001")
    subject, prov = _resolve(eo, "PN_9001")
    assert prov["instance_match"] == "ambiguous_in_class" and prov["instance_score"] == 0.9
    assert {t["instance_id"] for t in prov["instance_top_candidates"]} == {"CSI-7001", "CSI-7002"}


def _fill(eo, monkeypatch, value):
    filled = SimpleNamespace(slots_json=json.dumps({"part_number": value}), confidence=0.9, reasoning="stub")

    async def _fake(**kw):
        return filled

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(
        query=f"what failed on {value}", verb_iri="mesh:whatFailedOnThisPart",
        declarations=json.dumps(slots_for("what_failed_on_this_part")),
        acting_domains=["SUSTAINMENT"], subject_uri="",
        # A person: /fill_slots refuses a caller with none (190, PR #59).
        user_email="tester@example.com")
    return asyncio.run(eo.fill_slots(req))


def test_S5_fill_slots_binds_the_critical_item_for_a_component_slot(eo, monkeypatch):
    _wire(eo, monkeypatch)
    r = _fill(eo, monkeypatch, "PN-8802")
    assert r.slots.get("part_number") == "CSI-5002", (r.slots, r.refused, r.resolution)
    assert r.resolution["part_number"]["outcome"] == "exact"


def test_S5_control_without_the_chain_the_guard_still_says_wrong_class(eo, monkeypatch):
    """Only saf holds PN-8802 here (engine-o rows empty), so the fan-out resolves CSI-5002 cleanly
    and the verdict rests on the chain alone. NOTE the spec's control (the S1 setup with the graph
    down) cannot reach `wrong_class`: the fan-out itself refuses as `ambiguous_in_domain` first."""
    _wire(eo, monkeypatch, graph_down=True, eo_rows=())
    r = _fill(eo, monkeypatch, "PN-8802")
    assert r.resolution["part_number"]["outcome"] == "wrong_class", r.resolution
    assert "part_number" not in r.slots


def test_S5_control_pair_with_the_graph_up_the_same_request_binds(eo, monkeypatch):
    _wire(eo, monkeypatch, eo_rows=())
    assert _fill(eo, monkeypatch, "PN-8802").slots.get("part_number") == "CSI-5002"


def test_S6_fill_slots_does_not_break_a_tie_by_the_referent(eo, monkeypatch):
    _wire(eo, monkeypatch, eo_rows=())
    _two(monkeypatch, "PN-9001", "PN-9001")
    r = _fill(eo, monkeypatch, "PN-9001")
    res = r.resolution["part_number"]
    assert "part_number" not in r.slots and res["instance_id"] is None
    assert res["outcome"] == "ambiguous_in_class"
    assert {c["instance_id"] for c in res["candidates"]} == {"CSI-7001", "CSI-7002"}


@pytest.mark.parametrize("csi_score,component_score", [(1.0, 0.95), (0.96, 1.0)])
def test_S7_a_subclass_winner_is_not_re_picked_by_the_referent(eo, monkeypatch, csi_score, component_score):
    """decide() chose CSI-5002; it is already a Component by the chain, so the referent pick must
    not run again and swap in another instance (the second case scores the other one HIGHER)."""
    _wire(eo, monkeypatch, eo_rows=())

    async def _fake(*a, **k):
        return SAFETY_ITEM, {
            "instance_resolved": True, "instance_match": "exact", "instance_id": "CSI-5002",
            "instance_label": "PN-8802", "instance_score": csi_score,
            "instance_class_uri": SAFETY_ITEM,
            "instance_top_candidates": [
                {"instance_id": "CSI-5002", "class_uri": SAFETY_ITEM, "label": "PN-8802", "score": csi_score},
                {"instance_id": EO_PART, "class_uri": COMPONENT, "label": "PN-8802", "score": component_score},
            ]}

    monkeypatch.setattr(eo, "_resolve_instance", _fake)
    r = _fill(eo, monkeypatch, "PN-8802")
    assert r.slots.get("part_number") == "CSI-5002", (r.slots, r.resolution)
    assert r.resolution["part_number"]["outcome"] == "exact"
