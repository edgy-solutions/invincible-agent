"""A cross-engine ambiguity hands the referent its candidates -- safety sheet Q6, roll 195.

THE DEFECT, MEASURED LIVE ON 195. "what failed on this part PN-8801" (bob, SAFETY_ENGINEER,
SUSTAINMENT) left `part_number` unbound. The fan-out saw two claimants of four classes:
engine_safety_sustainment's CSI-5001 (`safety#SafetyCriticalItem`, matched on PN-8801, score 1.0)
and engine_o_sustainment's fuzzy notice hits (PCN26-180 at 0.625, PDN-23_0120 at 0.556, ...).
Those classes are not on one `rdfs:subClassOf` chain, so `_resolve_instance` refused as
`ambiguous_in_domain` -- correctly -- but that refusal carried only `instance_ambiguous_options`
tuples, no `instance_top_candidates` and no `instance_id`. `/fill_slots` builds its candidates
from exactly those two fields, so `cands` was empty and the referent pass ("the declaration
disambiguated a cross-class tie the scorers could not") was never reached. Engine O logged
"could not resolve 'PN-8801' (ambiguous_in_domain), 0 candidate(s)".

The slot declares `pcn#Component`, and CSI-5001's chain holds it, so the declaration was the
discriminator the whole time. `binds: identifier` is NOT the cause: the refusal is upstream of
the bind.

THE FIX. The `ambiguous_in_domain` refusal carries `instance_top_candidates` (the same shape
`decide()` emits on its ask branches). It stays a refusal of the INSTANCE; only the slot's
referent can turn it into a bind, and a same-score tie inside the referent still asks (S6's rule).

WHAT IS REAL and WHAT IS STUBBED: as in test_a_same_class_tie_asks_and_a_subclass_wins.py, with
engine-o's SPARQL answering TYPED notice rows (the live claimant set) instead of the helper's
single Component, and the notice-origin visibility gate answering "visible" for every notice.

Run: uv run pytest tests/routing/test_a_cross_engine_ambiguity_hands_the_referent_its_candidates.py -v
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agent_fleet.safety_agent.slots import slots_for
from tests._helpers.sustainment_resolution import (  # noqa: F401 (eo is a fixture)
    COMPONENT,
    SAFETY_ITEM,
    eo,
    outcomes as _outcomes,
    resolve as _resolve,
    two as _two,
    wire as _wire,
)

PCN = COMPONENT.rsplit("#", 1)[0] + "#"
DOC = "http://internal/sustainment/doc/"
# The live claimant set's notice hits (engine-o's fan-out log on 195), typed as the graph types them.
NOTICES = (
    (DOC + "PCN26-180", PCN + "ProcessChangeNotification"),
    (DOC + "PDN-23_0120", PCN + "ProductDiscontinuationNotice"),
    (DOC + "PCN-2683", PCN + "ProcessChangeNotification"),
)
HAZARD = SAFETY_ITEM.rsplit("#", 1)[0] + "#Hazard"


def _wire_notices(eo, monkeypatch, rows=NOTICES):
    """`wire`, then engine-o's SPARQL answers typed notice rows, and no Component named PN-8801."""
    drv = _wire(eo, monkeypatch, eo_rows=())

    async def _sparql(query, *a, **k):
        if query == eo._SUSTAINMENT_INSTANCES_QUERY:
            return [{"s": s, "type": t} for s, t in rows]
        return []

    monkeypatch.setattr(eo, "execute_sparql", _sparql)
    # The notice-origin gate (`notice_parts.visible_notice_ids`) reads Neo4j in a READ session the
    # shared double does not model. Live, these notices were visible claimants (seeded), so every
    # id is visible here; the gate's own seals live with notice_parts.
    monkeypatch.setattr(eo._notice_parts, "visible_notice_ids", lambda _drv, ids, **_k: set(ids))
    return drv


def _fill(eo, monkeypatch, value, *, referent=None):
    filled = SimpleNamespace(slots_json=json.dumps({"part_number": value}), confidence=0.9, reasoning="stub")

    async def _fake(**kw):
        return filled

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    decls = slots_for("what_failed_on_this_part")
    if referent is not None:
        decls = [dict(d, referent=referent) if d.get("name") == "part_number" else d for d in decls]
    req = eo.FillSlotsRequest(
        query=f"what failed on this part {value}", verb_iri="mesh:whatFailedOnThisPart",
        declarations=json.dumps(decls), acting_domains=["SUSTAINMENT"], subject_uri="",
        user_email="tester@example.com")
    return asyncio.run(eo.fill_slots(req))


def test_Q1_control_the_fan_out_is_the_live_ambiguous_in_domain(eo, monkeypatch):
    """The fixture reaches the live branch: two claimants, classes on no one chain, a refusal."""
    _wire_notices(eo, monkeypatch)
    subject, prov = _resolve(eo, "PN-8801")
    out = _outcomes(prov)
    assert all(out[p]["n_candidates"] >= 1 for p in ("engine_safety_sustainment", "engine_o_sustainment")), out
    assert subject is None and prov["instance_match"] == "ambiguous_in_domain", prov
    assert prov["instance_class_axis_status"] == "read", prov
    assert not prov.get("instance_id")


def test_Q2_the_refusal_carries_its_candidates(eo, monkeypatch):
    _wire_notices(eo, monkeypatch)
    _subject, prov = _resolve(eo, "PN-8801")
    tops = {c["instance_id"]: c for c in prov.get("instance_top_candidates") or []}
    assert "CSI-5001" in tops, prov
    assert tops["CSI-5001"]["class_uri"] == SAFETY_ITEM and tops["CSI-5001"]["score"] == 1.0
    assert tops["CSI-5001"]["matched_on"] == "PN-8801"
    assert DOC + "PCN26-180" in tops, "every claimant's reading is a candidate, not only the referent's"
    # the options the caller already had are unchanged
    assert ("engine_safety_sustainment", SAFETY_ITEM) in {(p, c) for p, c, _l in prov["instance_ambiguous_options"]}


def test_Q3_fill_slots_binds_part_number_through_the_referent(eo, monkeypatch):
    """Q6's slot: `part_number` declares pcn#Component; CSI-5001 is one by its chain."""
    _wire_notices(eo, monkeypatch)
    r = _fill(eo, monkeypatch, "PN-8801")
    assert r.slots.get("part_number") == "PN-8801", (r.slots, r.refused, r.resolution)
    res = r.resolution["part_number"]
    assert res["instance_id"] == "CSI-5001" and res["referent_disambiguated"] is True, res
    assert res["outcome"] == "ambiguous_in_domain", "the outcome vocabulary is unchanged (see main.py)"


def test_Q3_control_a_referent_nobody_claims_still_refuses(eo, monkeypatch):
    """The referent is the discriminator, not the candidates: declare a class no claimant holds
    and the same fan-out stays a refusal, now with its candidates as the menu."""
    _wire_notices(eo, monkeypatch)
    r = _fill(eo, monkeypatch, "PN-8801", referent=HAZARD)
    res = r.resolution["part_number"]
    assert "part_number" not in r.slots and res["instance_id"] is None, res
    assert res["outcome"] == "ambiguous_in_domain"
    assert "CSI-5001" in {c["instance_id"] for c in res["candidates"]}


def test_Q4_a_tie_inside_the_referent_still_asks(eo, monkeypatch):
    """S6's rule holds across engines: two critical items both PN-8801 at 1.0 is an ask."""
    _wire_notices(eo, monkeypatch)
    _two(monkeypatch, "PN-8801", "PN-8801")
    r = _fill(eo, monkeypatch, "PN-8801")
    res = r.resolution["part_number"]
    assert "part_number" not in r.slots and res["instance_id"] is None, res
    assert res["outcome"] == "ambiguous_in_class"
    assert {"CSI-7001", "CSI-7002"} <= {c["instance_id"] for c in res["candidates"]}


def test_Q5_the_referent_candidate_need_not_rank_first(eo, monkeypatch):
    """The refusal's candidates are unbounded because the referent's reading may rank below the
    others: declare the PDN class and PDN-23_0120 (third of four by score) is the one that binds."""
    _wire_notices(eo, monkeypatch)
    r = _fill(eo, monkeypatch, "PN-8801", referent=PCN + "ProductDiscontinuationNotice")
    res = r.resolution["part_number"]
    assert res["instance_id"] == DOC + "PDN-23_0120" and res["referent_disambiguated"] is True, res
    ranked = [c["instance_id"] for c in res["candidates"]]
    assert ranked.index(DOC + "PDN-23_0120") >= 2, f"the premise: it does not rank first {ranked}"
