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
    import instances
    import measures
    import slots as slot_decls
    from entities import (
        COST, CostState, NotInModel, SourceUnavailable, Unentitled, VintageRequired,
    )
    from pricing import CompositionError
    from seed import build_state, check_consistency
    from utils.subject_coverage import assert_subject_coverage as _assert_coverage
except ImportError:
    from agent_fleet.cost_agent import instances
    from agent_fleet.cost_agent import measures
    from agent_fleet.cost_agent import slots as slot_decls
    from agent_fleet.cost_agent.entities import (
        COST, CostState, NotInModel, SourceUnavailable, Unentitled, VintageRequired,
    )
    from agent_fleet.cost_agent.pricing import CompositionError
    from agent_fleet.cost_agent.seed import build_state, check_consistency
    from agent_fleet.utils.subject_coverage import assert_subject_coverage as _assert_coverage

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
# Verb catalog - the registration source, read twice
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
                          "what is the labor split"],
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
        "synonyms": ["labor split for a lot", "touch versus support hours",
                     "how much is program management", "what is the labor mix"],
        "anti_synonyms": ["what did the lot cost in total", "how did the price build up",
                          "what are the material costs"],
    },
    {
        "fn": "cost_price_composition",
        "verb": "mesh:costPriceComposition",
        "synonyms": ["how did the price build up", "show the burden stack",
                     "what is in the price", "base to price walk"],
        "anti_synonyms": ["what did the lot cost by category", "is unit price falling",
                          "what is the labor split"],
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
        "anti_synonyms": ["what did lot 4 cost", "what were the labor hours",
                          "show the burden stack", "which rates were applied"],
    },
    {
        "fn": "cost_supplier_concentration",
        "verb": "mesh:costSupplierConcentration",
        "synonyms": ["how concentrated is purchasing", "which suppliers are above the threshold",
                     "are we dependent on one supplier", "supplier concentration"],
        "anti_synonyms": ["what did material cost", "where did the money go by category",
                          "what is the labor split"],
    },
    {
        "fn": "cost_rate_assumptions",
        "verb": "mesh:costRateAssumptions",
        "synonyms": ["what rates are we using", "the rate table",
                     "what escalation was applied", "which assumptions produced this"],
        "anti_synonyms": ["did the rates move against the estimate", "what did the lot cost"],
    },
    {
        "fn": "package_export",
        "verb": "mesh:packageExport",
        "synonyms": ["export a validation package for a customer",
                     "produce the customer package", "release the cost figures to a customer",
                     "package the lots this customer may see"],
        # A DISCLOSURE IS NOT A REPORT. Every anti-synonym here is a question about figures
        # the asker may already see; this verb is about RELEASING a bounded set to an outside
        # party, and the two must not collide because one of them leaves the building.
        "anti_synonyms": ["what did lot 4 cost", "where did the money go",
                          "show me the price build-up", "which suppliers are concentrated"],
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
    # BOTH DIRECTIONS OF SUBJECT COVERAGE, and neither failure has a symptom at the engine.
    # "Can every verb's subject be FOUND?" — a gap appears only when a speaker omits the slot
    # and the elicitation offers free text. "Does every findable subject LEAD somewhere?" — a
    # name resolves, the router sets a subject, and the question dies one hop later with
    # nothing to blame. Engine F shipped `unsupported` for a class it ROUTED ON and found it
    # by running the engine rather than reading it; this raises at startup instead.
    _assert_coverage(
        component=COMPONENT,
        resolvable=instances._RESOLVABLE,
        verb_subjects=_all_subjects(),
        no_verb_by_design=instances._NO_VERB_BY_DESIGN,
        not_enumerable=instances._NOT_ENUMERABLE,
        resolvable_name="instances._RESOLVABLE",
    )
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

    # ── THE INSTANCE PROVIDER ───────────────────────────────────────────────────────────
    # WITHOUT THESE TWO, THIS ENGINE MAKES NO CLAIM ON ITS OWN LOTS. Measured 2026-09-11:
    # four cost questions carrying "lot 4" and "lot 3" were preempted onto `fin:WBSElement`
    # at exactly 0.500 — engine-fin's scorer matching THE BARE DIGIT against `instance_id`,
    # a hit `banana 4` reproduces — and the post-preemption check correctly abstained. The
    # classifier had already resolved `cost:Supplier` at 0.92 and that answer was discarded,
    # because a phone-book hit OVERRIDES `resolved_uri` and cost had no competing claim.
    #
    # A SCOPE RULE NEEDS SOMETHING TO PREFER. That is what registering these supplies.
    for spec in (
        {
            "name": "engine_cost_production_cost_resolve_instance",
            "verb": "mesh:resolveInstance",
            "input_uri": MESH + "InstanceIdentifier",
            "output_uri": MESH + "InstanceResolution",
            "endpoint": "resolve_instance",
            "synonyms": ["which lot", "which supplier", "which rate table",
                         "resolve name", "look up by name"],
            "description": (
                "Resolves a spoken production-cost name — a production lot, supplier, "
                "program, cost category, rate table or disclosure recipient — to its "
                "identifier in the cost model, by exact match then contained phrase then "
                "token overlap. Returns candidates with class URI, label and score, highest "
                "first. An empty list is a first-class answer: the provider abstains below "
                "its floor rather than offering a least-bad match. A BARE NUMBER IS NOT A "
                "NAME here unless the caller supplies the class — this engine's lot "
                "identifiers are bare integers, and a provider that claimed every digit in "
                "the fleet is the defect this one was built in response to."
            ),
        },
        {
            "name": "engine_cost_production_cost_enumerate_instances",
            "verb": "mesh:enumerateInstances",
            "input_uri": MESH + "InstanceClass",
            "output_uri": MESH + "InstanceEnumeration",
            "endpoint": "enumerate_instances",
            "synonyms": ["which lots", "list suppliers", "what rate tables",
                         "show me the options", "enumerate"],
            "description": (
                "Lists the members of a production-cost class — lots, suppliers, cost "
                "categories, rate tables, disclosure recipients — so an elicitation can "
                "offer a menu for a slot the speaker never filled. Answers with one of "
                "three outcomes: members (the list, and a menu is legitimate), too_many "
                "(the class is real and larger than a menu, with its count), or unsupported "
                "(this provider does not hold that class). The refusal is a first-class "
                "answer: free text is permitted where a provider REPORTS unboundedness, "
                "never where nobody attempted enumeration."
            ),
        },
    ):
        try:
            # CONTRACT D: mesh:InstanceIdentifier, mesh:InstanceResolution, mesh:InstanceClass
            # and mesh:InstanceEnumeration must ALREADY EXIST as :OntologyClass nodes or this
            # is a PERMANENT 422 with no retry. All four are declared in
            # setup/ontologies/mesh_system.ttl and engine-fin already registers against them,
            # which is why this engine can register against them without a new declaration.
            register_engine_to_mesh(
                mint=_mint,
                name=spec["name"],
                description=spec["description"],
                verb=spec["verb"],
                input_uri=spec["input_uri"],
                output_uri=spec["output_uri"],
                verb_synonyms=spec["synonyms"],
                endpoint_url=f"{base}/{spec['endpoint']}",
                owner_persona=OWNER_PERSONA,
                domains=DOMAINS,
                cost_class="fast",
                provider="engine_cost_production_cost",
                timeout_s=5.0,
            )
            registered.append(spec["verb"])
        except Exception as exc:  # pragma: no cover
            failed.append(spec["verb"])
            log.error("[engine-cost] %s provider registration failed: %s", spec["verb"], exc)

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

# ── /version ────────────────────────────────────────────────────────────────────────
# ONE IMPLEMENTATION, MOUNTED PER SERVICE. The import dance matches the other utils:
# engine images flatten `agent_fleet/utils` -> `/app/utils`, the bff image keeps the
# package path. Reports the sha BAKED INTO THE IMAGE, never one a chart injected.
try:  # pragma: no cover - import path differs by runtime
    from utils.version_endpoint import mount_version as _mount_version
except ImportError:  # pragma: no cover
    from agent_fleet.utils.version_endpoint import mount_version as _mount_version
_mount_version(app, COMPONENT)


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
    # THE CATALOGUE IS THE FIFTH TABLE, and it was the blind axis. This check compared four and
    # let the fifth drift: a verb present in VERBS and absent from CATALOGUE is servable by
    # direct call and INVISIBLE TO THE MESH — the engine boots, reports healthy, answers when
    # addressed by name, and is never routed to. That is the same shape as the reregister
    # hook's hand-kept directory map, which stopped at one engine and hid every later one.
    catalogued = {e["fn"] for e in CATALOGUE}
    described = set(_DESCRIPTIONS)
    if not (servable == outputs == inputs == declared == catalogued == described):
        raise RuntimeError(
            "verb tables disagree — servable=%s outputs=%s inputs=%s declared=%s "
            "catalogued=%s described=%s"
            % (sorted(servable), sorted(outputs), sorted(inputs), sorted(declared),
               sorted(catalogued), sorted(described))
        )


def _all_subjects() -> set[str]:
    """Every class this engine registers a verb ON — primary and also-askable alike.

    THE COVERAGE CHECK MUST USE THIS, NOT `INPUT_URI` DIRECTLY. Engine F's note applies
    unchanged: after `also_askable_of`, the primary subject is no longer the set of classes
    that route somewhere, and reading `input_uri` alone would make the check blind to a
    secondary subject nothing can resolve — exactly the silent gap it exists to catch.

    This engine declares no `also_askable_of` today. It is read anyway, so the first entry
    that adds one is covered by the commit that adds it rather than by someone remembering.
    """
    return (set(measures.INPUT_URI.values())
            | {s for e in CATALOGUE for s in e.get("also_askable_of", ())})


class MeasureRequest(BaseModel):
    """A dispatched verb call. `params` carries the declared slots, nothing else."""
    params: dict[str, Any] = {}


class ResolveRequest(BaseModel):
    """The mesh's resolveInstance request. THE FIELD IS `identifier`, NOT `text`.

    ⛔ ENGINE F SHIPPED THIS WRONG AND THE PROVIDER WAS UNCALLABLE. It registered as a
    `mesh:resolveInstance` provider and could not be called by one: Engine O's fan-out sends
    `{"identifier": ..., "query": ...}` (`ontology_service/main.py::_call_resolver`) and the
    model required `text`, so every real call was a **422** while the graph said the provider
    was registered, by name, at the right endpoint.

    REGISTERED IS NOT PARTICIPATING. A registration describes an edge and says nothing about
    the payload the consumer actually sends. Copied here field-for-field from the four
    providers that already work, rather than re-derived — the contract's whole value is that
    they agree.
    """
    identifier: str = ""
    query: str = ""
    class_uri: Optional[str] = None


class EnumerateRequest(BaseModel):
    class_uri: str
    #: ⚠ THIS WAS 8 — THE FLEET DEFAULT — AND IT PUT "9 exist" ON A CARD WITH NO MENU.
    #:
    #: Measured on the live fleet 2026-09-12, walking Q5: the lot ask rendered as free text
    #: saying "9 exist". That string is this engine's own `count`, and the members list beside
    #: it was EMPTY, because nine lots against a bound of eight answers `too_many`.
    #:
    #: I PREDICTED THIS IN THIS COMMENT AND SHIPPED IT ANYWAY, reasoning that the bound is the
    #: caller's declaration of what fits and that diverging from the neighbours was the worse
    #: error. Both halves were wrong. The caller OMITS the limit, so the provider's default is
    #: what applies — the "fleet default" was never a caller's judgement about what fits, it
    #: was a number each provider invented for itself. And a provider knows its own
    #: cardinality where the caller cannot.
    #:
    #: TWO OF SIX CLASSES REFUSED AT 8, which is what makes it a defect rather than a taste:
    #: ProductionLot (9) and RateTable (12). `too_many` is for a class that is GENUINELY
    #: larger than a menu; using it for nine turns a refusal designed to protect an ask into
    #: the reason the ask has nothing to show.
    #:
    #: 25 covers this engine's largest class with headroom and stays small enough to be a menu
    #: rather than a dump. If a class ever exceeds it, that is a real signal.
    #:
    #: THE DURABLE FIX IS NOT MINE: the disposition should SEND the limit it can render, and
    #: then this default stops mattering. Raised here because the card is broken today and a
    #: correct-by-contract refusal is no comfort to the person looking at it.
    limit: int = 25


@app.post("/resolve_instance")
def resolve_instance(req: ResolveRequest) -> dict[str, Any]:
    """Resolve a spoken production-cost name to an identifier in this model."""
    return {
        "output_uri": MESH + "InstanceResolution",
        "query": req.identifier,
        "candidates": instances.resolve(STATE, req.identifier, req.class_uri),
        "provider": "engine_cost_production_cost",
    }


@app.post("/enumerate_instances")
def enumerate_instances(req: EnumerateRequest) -> dict[str, Any]:
    """List the members of a cost class, or refuse in one of two named ways."""
    return instances.enumerate_class(STATE, req.class_uri, req.limit)


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
        #
        # AND AN ASK MUST CARRY ITS OPTIONS WHERE THE ENGINE KNOWS THEM. This branch fires
        # BEFORE the verb, so the verb's own richer refusals never run — `VintageRequired`
        # names both vintages and was unreachable through this route for as long as it has
        # existed. Measured on the wire, not inferred. A refusal that withholds the options
        # is a dead end wearing a refusal's clothes.
        options = {
            slot: opts for slot in missing
            if (opts := measures.options_for(STATE, fn_name, slot, req.params)) is not None
        }
        return _refusal(
            "slot_required",
            f"{fn_name} needs {', '.join(missing)}",
            missing=missing,
            declarations=slot_decls.slots_for(fn_name),
            # OMITTED ENTIRELY WHEN NOTHING IS COMPUTABLE, rather than sent as {}. An empty
            # map would read as "asked and there are none"; absence reads as "not asked",
            # which is the truth when the caller supplied nothing to compute from.
            **({"options": options} if options else {}),
        )

    # ⚠ AN UNDECLARED PARAM USED TO BE A 500. The branch above checks that mandatory slots are
    # PRESENT and nothing checked that supplied ones are DECLARED, so a param this verb does
    # not take reached `fn(**params)` and raised TypeError — the exact shape that branch's own
    # comment says it exists to prevent, arriving from the opposite direction.
    #
    # DROPPED RATHER THAN REFUSED, and the response says which. Once bound slots accumulate
    # across an interview's hops, a chain that answered `rate_vintage` for one verb will
    # legitimately carry it into a neighbour that has no such slot; refusing there would turn
    # a correct interview into a dead end. Silently dropping would be worse than either — the
    # answer would not reflect the question asked, with nothing to show for it.
    declared = {d["name"] for d in slot_decls.slots_for(fn_name)}
    accepted = {k: v for k, v in req.params.items() if k in declared}
    ignored = sorted(set(req.params) - declared)

    try:
        out = fn(STATE, **accepted)
        return {"refused": False, **out, **({"ignored_params": ignored} if ignored else {})}
    except VintageRequired as e:
        return _refusal("vintage_required", str(e), available=e.available)
    except NotInModel as e:
        return _refusal("not_in_model", str(e))
    except Unentitled as e:
        return _refusal("unentitled", str(e))
    except SourceUnavailable as e:
        return _refusal("unavailable", str(e))
    except CompositionError as e:
        # ⚠ A WELL-FORMED VALUE FOR THE WRONG LOT USED TO BE A 500, AND IT REACHED A USER.
        #
        # Measured on a live card 2026-09-12: the ask said "Which rate vintage?" with a free
        # text box, the answer `2021-02-01` was typed because that is what the PREVIOUS
        # question used, and lot 4 is FY2022. `rates_for` raised CompositionError, nothing
        # caught it, and the card rendered EMPTY. An unhandled exception is the one refusal
        # shape this engine promised never to produce — ADR-0049 Ruling 4 exists so a
        # composing verb can tell refusals apart, and a 500 tells it nothing at all.
        #
        # THE OPTIONS ARE RECOMPUTED FOR THE REFUSAL rather than echoed back, because the
        # caller's value was WRONG — repeating it is what produced the loop. `available` is
        # what this lot actually accepts, which for lot 4 is a single vintage. Same key as
        # VintageRequired above, so a consumer reads one field for "what may I say instead".
        available = measures.options_for(STATE, fn_name, "rate_vintage", req.params) or []
        return _refusal("not_in_model", str(e), available=available)


@app.get("/verbs")
async def verbs() -> dict[str, Any]:
    """The catalog: one table, read by the route and by the registration.

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
        "What one numbered lot cost, split into labor, material, other direct charges, "
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
        "How one lot's total divides proportionally across labor, material, other direct "
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
    "package_export":
        "Produce and record a validation package for a named outside party, containing only "
        "the quantities that party is entitled to see, carrying the pricing algorithm itself "
        "so the recipient can reproduce every figure, and leaving an audit line naming what "
        "was released to whom under which version. The subject is the RECIPIENT, not a lot: "
        "this answers what may be released to a party. NOT a report of figures to someone who "
        "may already see them, and NOT a cost, share, trend or rate question.",
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
