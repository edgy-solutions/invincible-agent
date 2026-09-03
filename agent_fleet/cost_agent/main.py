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

from fastapi import Depends, FastAPI
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

_announce_transport_auth(component=COMPONENT)

app = FastAPI(
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


@app.on_event("startup")
async def _boot() -> None:
    """Refuse to serve a seed that would make a verb vacuous or an arithmetic claim false.

    RAISES rather than warns. Engine F measured what the alternative costs twice over: a
    seed defect that does not raise at start becomes a demo over data indistinguishable
    from a bug.
    """
    check_consistency(STATE)
    _assert_declarations_cover_verbs()
    log.info(
        "engine-cost boot OK: %d lots, %d rate sets, %d verbs",
        len(STATE.lots), len(STATE.rates), len(measures.VERBS),
    )


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


class InvokeRequest(BaseModel):
    """A dispatched verb call. `params` carries the declared slots, nothing else."""
    verb: str
    params: dict[str, Any] = {}


def _refusal(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    """The three refusal states ADR-0049 Ruling 4 requires a composing verb to tell apart.

    `outcome` is the DISCRIMINANT and is always one of empty | unavailable | unentitled |
    not_in_model | vintage_required. A composing verb reads this field; it must never have
    to parse a message, and the three must never collapse into one shape.
    """
    return {"refused": True, "outcome": kind, "reason": message, **extra}


@app.post("/invoke")
async def invoke(req: InvokeRequest) -> dict[str, Any]:
    """Run one declared verb. Refusals are typed; nothing here improvises an answer."""
    fn = measures.VERBS.get(req.verb)
    if fn is None:
        return _refusal(
            "not_in_model",
            f"{req.verb!r} is not a verb this engine serves",
            served=sorted(measures.VERBS),
        )

    missing = [s for s in slot_decls.mandatory_slots(req.verb) if s not in req.params]
    if missing:
        # A MISSING MANDATORY SLOT IS AN ASK, NOT A PYTHON ERROR. Calling through with a
        # gap raises TypeError and shows a caller "missing 1 required keyword-only
        # argument" — a signature error rendered to a person who asked a question.
        return _refusal(
            "slot_required",
            f"{req.verb} needs {', '.join(missing)}",
            missing=missing,
            declarations=slot_decls.slots_for(req.verb),
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
