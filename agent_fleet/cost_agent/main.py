"""engine-cost — per-lot production cost accounting over notional data.

A deterministic, typed, mesh-registered engine on the ADR-0045 template. Six verbs, both
Contract D ends declared in `setup/ontologies/cost_extension.ttl`, slots declared from the
first registration.

WHY THIS ENGINE EXISTS, and it gates two ADR chains:
  * ADR-0049 — affordability's THIRD SOURCE. Under mesh-mediated composition a composing
    verb calls sibling VERBS; without these there is nothing to call.
  * ADR-0047 — the computation its export package CARRIES. `pricing.py` is shipped
    byte-identical to a recipient, which is why that module imports nothing from this one.

THE DIRECTION OF IMPORT IS A CONSTRAINT, NOT A HABIT: pricing.py -> (nothing here).
entities/seed/measures may import pricing; pricing may never import them. If that arrow
ever inverts, the export stops being isolable and ADR-0047 §3's premise quietly becomes
false with no test failing.

DO NOT VERIFY REGISTRATION BY ASKING THIS ENGINE ABOUT ITSELF. `/health` reports this
process's in-process verb table and returns the full count when the mesh holds bare
endpoints, when the engine never re-registered, and when the reregister job was never
created — all three measured on Engine F. Ask the GRAPH, by name (runbook §9).
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Optional

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    import measures
    import slots as slot_decls
    from entities import (
        COST, CostState, NotInModel, SourceUnavailable, Unentitled, VintageRequired,
    )
    from seed import build_state, check_consistency
except ImportError:
    from agent_fleet.cost_agent import measures
    from agent_fleet.cost_agent import slots as slot_decls
    from agent_fleet.cost_agent.entities import (
        COST, CostState, NotInModel, SourceUnavailable, Unentitled, VintageRequired,
    )
    from agent_fleet.cost_agent.seed import build_state, check_consistency

# TRANSPORT AUTH (OBSERVE). One implementation, from the mesh membership package: validate
# whatever arrives, log the caller posture per request, REFUSE NOTHING until
# REQUIRE_TRANSPORT_AUTH flips. The announcement is the pre-positioned string the contract
# phase's fresh-deploy test asserts against — an engine that takes the dependency but loses
# the announcement has a real posture the gauge cannot read.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth

log = logging.getLogger("engine-cost")

COMPONENT = "engine-cost"
DOMAIN = "PRODUCTION_COST"          # MUST match the prime manifest entry, or the resolver
                                    # asks for a domain the classes are not in and gets a
                                    # silent UNKNOWN cascade (setup/prime_databases.py).
PORT = int(os.getenv("PORT", "8097"))

#: The persona these verbs are owned by. Named once, read at every registration.
OWNER_PERSONA = "COST_ANALYST"
DOMAINS = [DOMAIN]

MESH = "http://invincible-agent/mesh#"

_announce_transport_auth(component=COMPONENT)


# -----------------------------------------------------------------------------
# Verb catalogue - the registration source, read twice
# -----------------------------------------------------------------------------
#
# ONE TABLE, READ BY THE ROUTES AND BY THE REGISTRATION, so the mesh and the served surface
# cannot disagree about which verbs exist.
#
# THE DESCRIPTIONS ARE THE ROUTING SIGNAL and the ANTI-SYNONYMS ARE LOAD-BEARING: they keep
# a verb out of traffic that belongs to its neighbour. The sharpest pair here is
# `cost_lot_breakdown` against `cost_price_composition` - BOTH decompose the same total, one
# by accounting bucket and one by burden step, and a question aimed at either would
# otherwise reach both.
CATALOGUE: list[dict[str, Any]] = [
    {
        "fn": "cost_lot_breakdown",
        "verb": "mesh:costLotBreakdown",
        "synonyms": ["what did lot 4 cost", "cost breakdown for a lot",
                     "where did the money go on a lot", "lot cost by category"],
        "anti_synonyms": ["how did the price build up", "what is the overhead rate",
                          "is cost per unit falling", "which rates were assumed"],
    },
    {
        "fn": "cost_unit_price_trend",
        "verb": "mesh:costUnitPriceTrend",
        "synonyms": ["is cost per unit falling", "unit price across lots",
                     "are we getting cheaper", "unit cost trend"],
        "anti_synonyms": ["what did one lot cost", "how did the price build up",
                          "what is the labour split"],
    },
    {
        "fn": "cost_rate_comparison",
        "verb": "mesh:costRateComparison",
        "synonyms": ["applied versus estimated rates", "did the rates move",
                     "how do actual rates compare to the estimate"],
        "anti_synonyms": ["what is the rate table", "what did the lot cost",
                          "is unit price falling"],
    },
    {
        "fn": "cost_labor_composition",
        "verb": "mesh:costLaborComposition",
        "synonyms": ["labour split for a lot", "touch versus support hours",
                     "how much is programme management", "what is the labour mix"],
        "anti_synonyms": ["what did the lot cost in total", "how did the price build up",
                          "what are the material costs"],
    },
    {
        "fn": "cost_price_composition",
        "verb": "mesh:costPriceComposition",
        "synonyms": ["how did the price build up", "show the burden stack",
                     "what is in the price", "base to price walk"],
        "anti_synonyms": ["what did the lot cost by category", "is unit price falling",
                          "what is the labour split"],
    },
    {
        "fn": "cost_category_breakdown",
        "verb": "mesh:costCategoryBreakdown",
        "synonyms": ["where did the money go", "which cost bucket grew",
                     "what proportion was material", "how does the cost split by category",
                     "how did the price build up"],
        # THE SHARPEST ANTI-SYNONYM PAIR IN THIS ENGINE. cost_lot_breakdown reports what each
        # bucket COST; this reports what SHARE each bucket IS and how that share MOVED. A
        # question aimed at either would otherwise reach both, because they decompose the
        # same total along the same axis.
        "anti_synonyms": ["what did lot 4 cost", "what were the labour hours",
                          "show the burden stack", "which rates were applied"],
    },
    {
        "fn": "cost_supplier_concentration",
        "verb": "mesh:costSupplierConcentration",
        "synonyms": ["how concentrated is purchasing", "which suppliers are above the threshold",
                     "are we dependent on one supplier", "supplier concentration"],
        "anti_synonyms": ["what did material cost", "where did the money go by category",
                          "what is the labour split"],
    },
    {
        "fn": "cost_rate_assumptions",
        "verb": "mesh:costRateAssumptions",
        "synonyms": ["what rates are we using", "the rate table",
                     "what escalation was applied", "which assumptions produced this"],
        "anti_synonyms": ["did the rates move against the estimate", "what did the lot cost"],
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot checks, then register every verb with the mesh.

    FLAT FIRST. In the image, /app IS this directory, so `utils` is a sibling top-level
    module and `agent_fleet` does not exist at all. Engine P got this backwards once and
    paid a full roll: the import failed, the helper became None, and twelve registrations
    were skipped WHILE THE ENGINE REPORTED HEALTHY.
    """
    check_consistency(STATE)
    _assert_declarations_cover_verbs()
    log.info(
        "engine-cost boot OK: %d lots, %d rate sets, %d verbs",
        len(STATE.lots), len(STATE.rates), len(measures.VERBS),
    )

    register_engine_to_mesh = None
    engine_mint = None
    try:
        from utils.mesh_registration import engine_mint, register_engine_to_mesh
    except ImportError:
        try:
            from agent_fleet.utils.mesh_registration import engine_mint, register_engine_to_mesh
        except ImportError:  # pragma: no cover - local runs without the fleet extra
            register_engine_to_mesh = None

    if register_engine_to_mesh is None:
        # SAY SO. A registration that silently does not happen leaves an engine that passes
        # every probe and answers nothing - the failure mode with no symptom, and exactly
        # what ADR-0046 documented about Engine B.
        log.warning("[engine-cost] mesh registration helper unavailable - NO verbs registered")
        yield
        return

    # The SERVICE is iagent-engine-cost. The IMAGE is cost-agent. The two differ on purpose.
    base = os.getenv("ENGINE_COST_PUBLIC_URL", "http://iagent-engine-cost:8097").rstrip("/")

    # IDENTITY IS AN ARGUMENT, NEVER DERIVED FROM THE COMPONENT NAME. Both the client id and
    # the env var holding its secret are named HERE, at this call site. Engine P's provider
    # registration was first written with a neighbour's deployment name and minting failed
    # 401 SILENTLY while the verb registrations beside it succeeded.
    _mint = engine_mint(client_id="iagent-cost-agent",
                        secret_env="ENGINE_COST_CLIENT_SECRET")

    registered, failed = [], []
    for entry in CATALOGUE:
        fn_name = entry["fn"]
        try:
            register_engine_to_mesh(
                mint=_mint,
                # ONE NAME PER (VERB, SUBJECT). The registration NAME is the tool_urn, and
                # the registrar's compensate-on-rescope sweep DELETES rows matching
                # (tool_urn, verb_iri) whose input_uri differs - so registering a second
                # subject under one name silently replaces the first rather than adding.
                name="engine_cost_production_cost",
                description=_DESCRIPTIONS[fn_name],
                verb=entry["verb"],
                input_uri=measures.INPUT_URI[fn_name],
                output_uri=measures.OUTPUT_URI[fn_name],
                verb_synonyms=entry["synonyms"],
                verb_anti_synonyms=entry.get("anti_synonyms"),
                endpoint_url=f"{base}/measure/{fn_name}",
                owner_persona=OWNER_PERSONA,
                domains=DOMAINS,
                cost_class="fast",
                # DECLARED FROM DAY ONE - what makes `rate_vintage`'s refusal reachable by
                # the router at all, rather than a rule only this process knows.
                slots=slot_decls.slots_for(fn_name),
            )
            registered.append(entry["verb"])
        except Exception as exc:  # pragma: no cover
            # Best-effort, matching the fleet's posture: a failed registration means this
            # verb is not routable yet, NOT that the engine is down. But SAY WHICH.
            failed.append(entry["verb"])
            log.error("[engine-cost] registration failed for %s: %s", entry["verb"], exc)

    log.info("[engine-cost] registered %d verb(s): %s", len(registered), registered)
    if failed:
        log.error("[engine-cost] %d verb(s) NOT registered: %s", len(failed), failed)
    yield


app = FastAPI(
    lifespan=lifespan,
    **_docs_kwargs(),   # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth(COMPONENT))],
    title="engine-cost — production cost accounting",
    description=(
        "Per-lot cost accounting over notional data. Deterministic verbs, declared slots, "
        "and a pricing composition written to be exported byte-identical (ADR-0047)."
    ),
    version="0.1.0",
)

#: Built once at import of the module's state, not at request time. `build_state` performs
#: no I/O and no clock read, so this is deterministic across replicas — two pods answer
#: identically, which a composing verb depends on.
STATE: CostState = build_state()


def _assert_declarations_cover_verbs() -> None:
    """Every servable verb must be declared and typed, and vice versa.

    DERIVED, NOT REMEMBERED. Engine F's `unsupported`-for-a-routed-class defect came from a
    set someone listed instead of computing; this asserts the three tables against each
    other at boot so a seventh verb cannot be added to one and forgotten in the others.
    """
    servable = set(measures.VERBS)
    outputs = set(measures.OUTPUT_URI)
    inputs = set(measures.INPUT_URI)
    declared = set(slot_decls.all_declarations())
    if not (servable == outputs == inputs == declared):
        raise RuntimeError(
            "verb tables disagree — servable=%s outputs=%s inputs=%s declared=%s"
            % (sorted(servable), sorted(outputs), sorted(inputs), sorted(declared))
        )


class MeasureRequest(BaseModel):
    """A dispatched verb call. `params` carries the declared slots, nothing else."""
    params: dict[str, Any] = {}


def _refusal(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    """The three refusal states ADR-0049 Ruling 4 requires a composing verb to tell apart.

    `outcome` is the DISCRIMINANT and is always one of empty | unavailable | unentitled |
    not_in_model | vintage_required. A composing verb reads this field; it must never have
    to parse a message, and the three must never collapse into one shape.
    """
    return {"refused": True, "outcome": kind, "reason": message, **extra}


@app.post("/measure/{fn_name}")
async def measure(fn_name: str, req: MeasureRequest) -> dict[str, Any]:
    """Run one declared verb.

    ONE ENDPOINT PER VERB, matching the fleet idiom, because the registrar BAKES
    `endpoint_url` into the mesh per verb — a single body-dispatched route would give every
    verb the same URL and the mesh would have no way to reach one rather than another.
    """
    fn = measures.VERBS.get(fn_name)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"{fn_name!r} is not a verb this engine serves")

    missing = [s for s in slot_decls.mandatory_slots(fn_name) if s not in req.params]
    if missing:
        # A MISSING MANDATORY SLOT IS AN ASK, NOT A PYTHON ERROR. Calling through with a
        # gap raises TypeError and shows a caller "missing 1 required keyword-only
        # argument" — a signature error rendered to a person who asked a question.
        return _refusal(
            "slot_required",
            f"{fn_name} needs {', '.join(missing)}",
            missing=missing,
            declarations=slot_decls.slots_for(fn_name),
        )

    try:
        return {"refused": False, **fn(STATE, **req.params)}
    except VintageRequired as e:
        return _refusal("vintage_required", str(e), available=e.available)
    except NotInModel as e:
        return _refusal("not_in_model", str(e))
    except Unentitled as e:
        return _refusal("unentitled", str(e))
    except SourceUnavailable as e:
        return _refusal("unavailable", str(e))


@app.get("/verbs")
async def verbs() -> dict[str, Any]:
    """The catalogue: one table, read by the route and by the registration.

    Descriptions are the ROUTING SIGNAL and are written for the verb, never for a query.
    The not-clauses are load-bearing: they keep a verb out of traffic that belongs to its
    neighbour, which is the sibling-bleed rule applied to verbs rather than to classes.
    """
    return {
        "component": COMPONENT,
        "domain": DOMAIN,
        "verbs": [
            {
                "verb": name,
                "input_uri": measures.INPUT_URI[name],
                "output_uri": measures.OUTPUT_URI[name],
                "slots": slot_decls.slots_for(name),
                "description": _DESCRIPTIONS[name],
            }
            for name in sorted(measures.VERBS)
        ],
    }


_DESCRIPTIONS: dict[str, str] = {
    "cost_lot_breakdown":
        "What one numbered lot cost, split into labour, material, other direct charges, "
        "warranty and contracted effort, with hours where the bucket is worked rather than "
        "purchased. NOT a comparison across lots and NOT a price build-up.",
    "cost_unit_price_trend":
        "How cost per unit has moved from one lot to the next across the whole production "
        "run, so direction is readable. NOT a single lot's cost and NOT a rate table.",
    "cost_rate_comparison":
        "The rates actually applied to a lot set against the rates assumed when it was "
        "estimated, factor by factor. NOT the rate table itself and NOT a price.",
    "cost_labor_composition":
        "How a lot's worked effort divides between hands-on production, indirect support "
        "and engineering or management effort, with hours and applied rate for each. NOT "
        "total cost and NOT purchased content.",
    "cost_price_composition":
        "The ordered build-up from base cost to final price for one lot — fringe, overhead, "
        "G&A, cost of money and profit, each naming what it added. NOT a category "
        "breakdown, which divides the same total a different way.",
    "cost_category_breakdown":
        "How one lot's total divides proportionally across labour, material, other direct "
        "charges, warranty and contracted effort, and how each proportion moved against the "
        "preceding lot. NOT what each bucket cost in money — that is a different question "
        "with different assumptions behind it — and NOT the burden build-up.",
    "cost_supplier_concentration":
        "How a lot's purchased value is distributed across suppliers, naming those whose "
        "share exceeds a stated bound, with the bound reported alongside. NOT what material "
        "cost in total, and NOT a category split.",
    "cost_rate_assumptions":
        "The rate and escalation assumptions in force at a stated point in time, so any "
        "figure computed elsewhere can be reproduced. NOT what a lot cost.",
}


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness only.

    THE VERB COUNT BELOW IS NOT EVIDENCE OF REGISTRATION and the payload says so, because
    Engine P's `verbs: 14` was written into a prep doc as "the signature that matters most"
    and struck out the next day. It reads THIS PROCESS'S table. Registration lives in the
    graph; ask the graph, by name (runbook §9).
    """
    return {
        "status": "ok",
        "engine": COMPONENT,
        "domain": DOMAIN,
        "verbs": len(measures.VERBS),
        "lots": len(STATE.lots),
        "warning": (
            "`verbs` is this process's in-process table and is NOT evidence of mesh "
            "registration — verify by name in the graph (adding-an-engine.md §9)."
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
