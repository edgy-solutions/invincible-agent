"""Lot 3's vintage: the model's correct read binds, without asking.

THE REGRESSION. The census row `cost-rate-comparison-lot-3-vintage` passed until roll #12 and
asks since. Measured 2026-10-03 (roll #16): the model extracts `rate_vintage="2021-02-01"`
correctly, `/fill_slots` logs `outcome=empty candidates=0`, and the ask then offers two chips,
one of them the value the model had read. bcaf2455 gave `rate_vintage` a referent
(`cost#RateTable`) so its chips could be lot-scoped, which also sent the spoken value through
the UNSCOPED `resolveInstance` fan-out, whose RateTable ids are `<fy>-<vintage>`. A bare
vintage can never equal one.

WHAT IS REAL HERE: the declarations (`slots_for`, so `referent` and `narrowed_by` are what
production sends), and the scoped menu (engine-cost's own `enumerate_class` over its own
STATE). WHAT IS STUBBED: the model's extraction, the provider registry, and the fan-out, which
answers `empty` for the bare vintage as it did live.

Run: uv run --frozen pytest tests/cost/test_the_models_vintage_read_binds_without_asking.py -v
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agent_fleet.cost_agent import instances
from agent_fleet.cost_agent.main import STATE
from agent_fleet.cost_agent.slots import slots_for

COST = "http://invincible-agent/cost#"
RATE_TABLE = COST + "RateTable"
PRODUCTION_LOT = COST + "ProductionLot"
VERB = "mesh:costRateComparison"
FN = "cost_rate_comparison"
LOT_3_VINTAGES = ["2021-02-01", "2021-08-01"]


def _eo():
    from agent_fleet.ontology_service import main as eo
    return eo


@pytest.fixture
def eo(monkeypatch):
    mod = _eo()
    calls = SimpleNamespace(fanout=[], enumerate=[], drop_scoped_by=False)

    async def _fanout(identifier, query, asked_domains=None):
        calls.fanout.append(identifier)
        if identifier.strip().lower() in ("lot 3", "3"):
            return PRODUCTION_LOT, {"instance_resolved": True, "instance_id": "3",
                                    "instance_class_uri": PRODUCTION_LOT,
                                    "instance_match": "exact", "instance_label": "Lot 3"}
        return None, {"instance_match": "empty"}

    monkeypatch.setattr(mod, "_resolve_instance", _fanout)
    monkeypatch.setattr(mod, "_discover_enumerate_providers", lambda refresh=False: SimpleNamespace(
        outcome="ok", detail=None,
        rows=[{"provider": "engine_cost_production_cost", "endpoint_url": "http://cost/enumerate"}]))

    class _CostClient:
        """engine-cost's enumeration, answered by its own `enumerate_class` over its own STATE."""

        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            calls.enumerate.append(json)
            body = instances.enumerate_class(STATE, json["class_uri"],
                                             bound_slots=json.get("bound_slots"))
            if calls.drop_scoped_by:
                body = {k: v for k, v in body.items() if k != "scoped_by"}
            return SimpleNamespace(status_code=200, json=lambda: body)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _CostClient)
    mod._test_calls = calls
    return mod


def _fill(eo, monkeypatch, slots: dict):
    filled = SimpleNamespace(slots_json=json.dumps(slots), confidence=0.9, reasoning="stub")

    async def _fake(**kw):
        return filled

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(
        query="did the rates move against the estimate on lot 3, using the 2021-02-01 vintage",
        verb_iri=VERB, declarations=json.dumps(slots_for(FN)),
        acting_domains=["PRODUCTION_COST"], subject_uri="")
    return asyncio.run(eo.fill_slots(req))


def test_the_production_declaration_is_the_one_that_regressed():
    """The fixture is the shipped declaration, or every arm below seals a slot nobody sends."""
    decl = next(d for d in slots_for(FN) if d["name"] == "rate_vintage")
    assert decl.get("referent") == RATE_TABLE
    assert decl.get("narrowed_by") == ["lot"]


def test_the_models_correct_read_binds_without_asking(eo, monkeypatch):
    # rate_vintage FIRST: the model's key order must not decide whether `lot` is resolved yet.
    r = _fill(eo, monkeypatch, {"rate_vintage": "2021-02-01", "lot": "lot 3"})
    assert r.slots.get("rate_vintage") == "2021-02-01", (r.slots, r.refused, r.resolution)
    assert r.slots.get("lot") == "3"
    res = r.resolution["rate_vintage"]
    assert res["outcome"] == "exact" and res["bound_from"] == "scope", res
    assert [c["instance_id"] for c in res["candidates"]] == LOT_3_VINTAGES
    assert "2021-02-01" not in eo._test_calls.fanout, "the bind came from the fan-out, not the scope"
    assert eo._test_calls.enumerate[-1]["bound_slots"] == {"lot": "3"}, "scoped by the RESOLVED lot"


def test_a_real_vintage_outside_the_lot_still_asks(eo, monkeypatch):
    """The scope is what binds, not the vintage's existence: another year's vintage is real,
    is in the class-wide list, and is not lot 3's -- so it falls through and is not bound."""
    other = sorted({t["instance_id"].split("-", 1)[1] for t in instances._rate_tables(STATE)}
                   - set(LOT_3_VINTAGES))
    assert other, "the control needs a vintage lot 3 does not accept"
    r = _fill(eo, monkeypatch, {"rate_vintage": other[0], "lot": "lot 3"})
    assert "rate_vintage" not in r.slots, (other[0], r.slots)
    assert other[0] in eo._test_calls.fanout


def test_a_provider_that_does_not_say_it_scoped_binds_nothing(eo, monkeypatch):
    """Absent `scoped_by` is class-wide by contract, and a class-wide list is not what the verb
    accepts. Same members, same value: only the claim differs, and the bind must refuse."""
    eo._test_calls.drop_scoped_by = True
    r = _fill(eo, monkeypatch, {"rate_vintage": "2021-02-01", "lot": "lot 3"})
    assert "rate_vintage" not in r.slots, r.slots
