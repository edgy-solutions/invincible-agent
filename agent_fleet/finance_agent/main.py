"""Engine F — the finance engine. Six deterministic verbs over program financial data.

ADR-0045 is the whole design and it is Accepted; nothing here relitigates it.

WHY THIS IS A SEPARATE ENGINE AND NOT SIX VERBS IN ENGINE P (ADR-0045 Decision 1, from
ADR-0035's two planes): finance analysis is governed READING. An EAC is computed from actuals
that already exist; it does not author a scenario, it cannot be dragged, and committing it
means nothing. Engine P's whole surface — fork, append_op, commit, the in-memory PlanStore —
is machinery for state that a room CREATES. None of it applies, and there is no coherent
answer to what "committing" a variance analysis would mean.

WHAT THIS SERVICE DELIBERATELY DOES NOT DO — Engine P's list, and it holds unchanged:
  * choose an archetype, a view, or a chart type — `select_presentation` does that, from the
    PAYLOAD, against the CALLER'S menu (ADR-0042 §2). Responses carry `output_uri` and rows.
  * call an LLM. This engine computes; it never speaks.
  * hold a standing credential or a connection string of its own (ADR-0045 Decision 5).

── THE COMPONENT IS `engine-fin`, NOT `engine-f` ──────────────────────────────────────────
ADR-0045 names this engine "Engine F" in prose. The component name `engine-f` was ALREADY
TAKEN by the presentation agent (`PRESENTATION_AGENT_SVC_URL`, `NOTES.txt`'s "Engine F (UX
Proxy)", `tests/test_engine_names.py`, the reregister list). Reusing it would have pointed
the fleet's presentation URL at a finance engine and taken `/render_ui` down everywhere, with
the first symptom three layers away. Prose names and component names are different registries
— see §0 of `docs/runbooks/adding-an-engine.md`.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    import measures
    from entities import FISCAL_PERIODS, MethodRequired, NotInModel
    from seed import build_seed, check_consistency, notional_banner
    from slots import missing_mandatory, refusal_for, slots_for, with_live_vocabularies
except ImportError:
    from agent_fleet.finance_agent import measures
    from agent_fleet.finance_agent.entities import FISCAL_PERIODS, MethodRequired, NotInModel
    from agent_fleet.finance_agent.seed import build_seed, check_consistency, notional_banner
    from agent_fleet.finance_agent.slots import (
        missing_mandatory, refusal_for, slots_for, with_live_vocabularies,
    )

FIN = "http://invincible-agent/fin#"
MESH = "http://invincible-agent/mesh#"

#: THE SEMANTIC DOMAIN, STATED ONCE. It appears on every registration below AND on this
#: engine's entry in `setup/prime_databases.py`'s ONTOLOGIES list, and the two MUST agree:
#: the resolver queries by semantic domain name, so a class whose domain does not match what
#: the resolver asks for produces a SILENT UNKNOWN CASCADE — no error anywhere, just an
#: answer that never arrives. Hoisted to a constant because a fact repeated at three call
#: sites is a fact that can disagree with itself, and `tests/finance/` compares this name
#: against the prime manifest rather than against a literal typed twice.
DOMAINS = ["PROGRAM_FINANCE"]

#: The persona these verbs are owned by. Same reasoning: named once, read three times.
OWNER_PERSONA = "PROGRAM_FINANCE_ANALYST"

#: The notional model. Read-only for the life of the process — no verb here mutates it, which
#: is ADR-0045 Decision 1 expressed in the one place it cannot be argued with.
STATE = build_seed()


# ─────────────────────────────────────────────────────────────────────────────
# Verb catalogue — the registration source, read twice
# ─────────────────────────────────────────────────────────────────────────────
#
# ONE TABLE, READ BY THE ROUTES AND BY THE REGISTRATION, so the mesh and the served surface
# cannot disagree about which verbs exist. Engine P's idiom, kept.
#
# THE DESCRIPTIONS ARE THE ROUTING SIGNAL, and they are written the way the ontology's
# definitions are: for the VERB, never for a query, and without naming a sibling verb in a
# way that competes for its traffic. Each says what it OWNS and what it is NOT — the
# not-clauses are load-bearing, because the six finance verbs are far closer to each other
# than the twelve planning verbs are, and "variance", "spend" and "money" appear in the
# natural phrasing of at least four of them.

VERBS: list[dict[str, Any]] = [
    {
        "fn": "fin_variance_analysis",
        "verb": "mesh:finVarianceAnalysis",
        "input_uri": FIN + "Program",
        "desc": (
            "A cost or schedule variance decomposed into the parts that produced it, drilled "
            "recursively until each part is explained, with the contributors that fall below "
            "the materiality floor reported as a residual rather than dropped. Answers WHY a "
            "variance exists and where it was incurred. NOT a ranked list of contributors on "
            "its own - that is finVarianceDrivers, which is flat and ordered where this is "
            "nested and explanatory. NOT a forecast of the finish - that is "
            "finEacCalculation. OWNS the phrasings: why are we over, what is driving the "
            "variance, break down the overrun, explain the number, where did it go wrong."
        ),
        "synonyms": ["variance analysis", "why are we over budget", "break down the variance",
                     "what is driving the overrun", "explain the cost variance",
                     "root cause of the variance"],
        "anti_synonyms": ["what will it cost at the end", "estimate at completion",
                          "how much money is left", "when do we run out"],
    },
    {
        "fn": "fin_eac_calculation",
        "verb": "mesh:finEacCalculation",
        "input_uri": FIN + "Program",
        "desc": (
            "The forecast total cost at the finish by ONE NAMED FORMULA, stated together with "
            "the formula and the inputs it consumed, plus the variance at completion and the "
            "estimate to complete. THE METHOD IS MANDATORY AND HAS NO DEFAULT: the formulas "
            "disagree materially on the same program, so a bare request is refused with the "
            "choice named. Answers what the finish will cost. NOT what has been spent so far "
            "or how fast - that is finBurnRate. NOT why the current variance exists - that is "
            "finVarianceAnalysis. OWNS the phrasings: estimate at completion, EAC, what will "
            "this cost when it is done, forecast at completion, where will we land."
        ),
        "synonyms": ["EAC", "estimate at completion", "forecast at completion",
                     "what will it cost when done", "where will we land",
                     "variance at completion", "VAC"],
        "anti_synonyms": ["how fast are we spending", "burn rate", "how much is authorized",
                          "why are we over"],
    },
    {
        "fn": "fin_performance_indices",
        "verb": "mesh:finPerformanceIndices",
        "input_uri": FIN + "PerformanceMeasurementBaseline",
        "desc": (
            "Cost and schedule performance indices reported period by period, both per-period "
            "and cumulative, with the budgeted, claimed and actual quantities each ratio was "
            "computed from. Answers how efficiently the work is converting money and time "
            "into claimed value, and which way that is trending. These are DIMENSIONLESS "
            "RATIOS, never amounts. NOT the money going out per period - that is finBurnRate, "
            "which counts cash rather than efficiency. OWNS the phrasings: CPI, SPI, "
            "performance index, how efficiently are we working, are we getting better or "
            "worse, is it improving."
        ),
        "synonyms": ["CPI", "SPI", "performance indices", "cost performance index",
                     "schedule performance index", "are we improving", "efficiency trend"],
        "anti_synonyms": ["how much have we spent", "how much is left", "what will it cost",
                          "which account is worst"],
    },
    {
        "fn": "fin_burn_rate",
        "verb": "mesh:finBurnRate",
        "input_uri": FIN + "PerformanceMeasurementBaseline",
        "desc": (
            "Money leaving per period beside the money the plan phased for that period, with "
            "the cumulative position, the budget remaining, and the runway in periods implied "
            "by the trailing rate. Counts CASH LEAVING, not value claimed, which is why it "
            "can look healthy while performance is poor. Answers how fast money is going out "
            "and when it runs out at this rate. NOT how efficiently the money is converting "
            "into progress - that is finPerformanceIndices. NOT how much was appropriated - "
            "that is finFundingStatus. OWNS the phrasings: burn rate, how fast are we "
            "spending, when do we run out, spend per month, runway."
        ),
        "synonyms": ["burn rate", "how fast are we spending", "when do we run out",
                     "spend per month", "runway", "cash out the door"],
        "anti_synonyms": ["CPI", "how much is authorized", "why are we over",
                          "estimate at completion"],
    },
    {
        "fn": "fin_variance_drivers",
        "verb": "mesh:finVarianceDrivers",
        "input_uri": FIN + "ControlAccount",
        "desc": (
            "The control accounts or work packages contributing to a variance, ranked by how "
            "much of it each accounts for, each with its signed magnitude, its share of the "
            "total, and the earned value technique that decides whether the row is worth "
            "chasing. FAVOURABLE CONTRIBUTORS ARE RANKED TOO, so the magnitudes sum to the "
            "variance they explain. Answers WHO or WHAT is responsible, ordered. NOT the "
            "nested explanation of how the variance decomposes - that is "
            "finVarianceAnalysis. OWNS the phrasings: which account is worst, who is driving "
            "it, biggest contributors, worst offenders, rank the drivers."
        ),
        "synonyms": ["variance drivers", "which control account is worst",
                     "biggest contributors", "worst offenders", "who is driving it",
                     "rank the drivers", "top contributors"],
        "anti_synonyms": ["what will it cost at the end", "how fast are we spending",
                          "how much is obligated"],
    },
    {
        "fn": "fin_funding_status",
        "verb": "mesh:finFundingStatus",
        "input_uri": FIN + "FundingLine",
        "desc": (
            "Authorized, obligated and expended amounts per funding line per period, with the "
            "unobligated and unexpended balances and a stated verdict on each cell. The three "
            "quantities are a LADDER, each a subset of the one above. Answers how much money "
            "is available, how much has been placed under obligation, how much has actually "
            "been paid out, and where a balance is at risk of going unused. NOT what the work "
            "is forecast to cost - that is finEacCalculation. NOT the rate at which cash is "
            "leaving - that is finBurnRate. OWNS the phrasings: funding status, how much is "
            "authorized, unobligated balance, obligation rate, is the money committed, "
            "expiring funds."
        ),
        "synonyms": ["funding status", "how much is authorized", "unobligated balance",
                     "obligated versus expended", "is the money committed",
                     "expiring funds", "appropriation status"],
        "anti_synonyms": ["what will it cost", "why are we over", "CPI",
                          "which account is worst"],
    },
]

#: Verbs by function name, so the routes and the catalogue cannot drift.
BY_FN = {v["fn"]: v for v in VERBS}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Register every verb as its own predicate edge, then the two provider verbs.

    ONE CALL PER VERB, per the mesh's existing idiom — `register_engine_to_mesh` takes a
    single verb, and eight calls is the honest shape rather than a bulk endpoint invented
    for this engine. Registration is opt-in via MESH_REGISTER_ON_STARTUP, so a local run or
    a unit test does not need the mesh to exist.
    """
    problems = check_consistency(STATE)
    if problems:
        # FAIL LOUD AT BOOT. A seed with dangling references or a broken funding ladder
        # produces measures that are QUIETLY WRONG rather than absent, which is the failure
        # mode with no symptom. Engine P's rule, and the reason is identical.
        raise RuntimeError("finance seed is inconsistent: " + "; ".join(problems[:5]))

    dead_ends = _dead_end_classes()
    if dead_ends:
        # A FINDABLE SUBJECT THAT LEADS NOWHERE. The resolver reports success, the router
        # sets the subject, and the question dies a hop later with nothing to blame. Raised
        # beside the forward check so the two directions fail the same way.
        raise RuntimeError(
            "engine-fin resolves classes that no verb routes on, and they are not declared: "
            + ", ".join(dead_ends)
            + " — register a verb on them, or add them to _NO_VERB_BY_DESIGN with the reason"
        )

    unroutable = _unroutable_classes()
    if unroutable:
        # AN INPUT CLASS NOBODY CAN ENUMERATE IS A VERB NOBODY CAN BE ASKED FOR. The verb
        # registers, /health is green, and the only symptom is an elicitation offering free
        # text where it should have offered a menu — because this provider answered
        # `unsupported`, which reads to the ask as a considered refusal. Caught at boot,
        # where it is one line, rather than at a demo, where it is a shrug.
        raise RuntimeError(
            "engine-fin registers verbs on classes it can neither resolve nor enumerate: "
            + ", ".join(unroutable)
            + " — add them to _RESOLVABLE, or to _NOT_ENUMERABLE with a stated reason"
        )

    # FLAT FIRST. In the image, /app IS this directory, so `utils` is a sibling top-level
    # module and `agent_fleet` does not exist at all. The packaged path is the repo form.
    # Engine P got this backwards once and paid a full roll: the import failed, the helper
    # became None, and twelve registrations were skipped while the engine reported healthy.
    register_engine_to_mesh = None
    engine_mint = None
    try:
        from utils.mesh_registration import engine_mint, register_engine_to_mesh
    except ImportError:
        try:
            from agent_fleet.utils.mesh_registration import engine_mint, register_engine_to_mesh
        except ImportError:  # pragma: no cover — local runs without the fleet extra
            register_engine_to_mesh = None

    if register_engine_to_mesh is None:
        # SAY SO. A registration that silently does not happen leaves an engine that passes
        # every probe and answers nothing — the failure mode with no symptom.
        print("[engine-fin] mesh registration helper unavailable — NO verbs registered")
        yield
        return

    # The SERVICE is iagent-engine-fin. The IMAGE is finance-agent. The two differ, exactly
    # as they do for Engine P, and that difference is why its URL was wrong three times.
    base = os.getenv("ENGINE_FIN_PUBLIC_URL", "http://iagent-engine-fin:8096").rstrip("/")

    # ONE STATEMENT OF THIS ENGINE'S IDENTITY, used by every registration below.
    #
    # IDENTITY IS AN ARGUMENT, NEVER DERIVED FROM THE COMPONENT NAME. Both the client id and
    # the env var holding its secret are named HERE, at this call site. Engine P's provider
    # registration was first written with the DEPLOYMENT name copied from a neighbour, and
    # minting failed 401 while the verb registrations beside it succeeded — a half-registered
    # engine whose verbs route and whose resolver does not, and the 401 was silent. The same
    # general-name-over-specific-behaviour is how `mint_service_token()` once made the
    # supervisor dispatch as the review starter.
    #
    # The client id is `iagent-finance-agent` — after the IMAGE, matching the convention the
    # planning engine's `iagent-planning-agent` follows, while the env var is named after the
    # SERVICE. Both names are written down in §6 of the runbook precisely because grepping
    # either one finds only half the wiring.
    _mint = engine_mint(client_id="iagent-finance-agent",
                        secret_env="ENGINE_FIN_CLIENT_SECRET")

    for v in VERBS:
        try:
            register_engine_to_mesh(
                mint=_mint,
                name="engine_fin_finance",
                description=v["desc"],
                verb=v["verb"],
                input_uri=v["input_uri"],
                output_uri=measures.OUTPUT_URI[v["fn"]],
                verb_synonyms=v["synonyms"],
                verb_anti_synonyms=v.get("anti_synonyms"),
                endpoint_url=f"{base}/measure/{v['fn']}",
                owner_persona=OWNER_PERSONA,
                domains=DOMAINS,
                cost_class="fast",
                # DECLARED FROM DAY ONE. This engine is the first to register slots on its
                # first registration rather than acquire them later — which is what makes
                # `fin_eac_calculation`'s refusal reachable by the router at all, instead of
                # a rule only this process knows.
                slots=with_live_vocabularies(
                    slots_for(v["fn"]),
                    periods=[p for p in FISCAL_PERIODS
                             if any(f.period == p for f in STATE.facts)],
                ),
            )
        except Exception as exc:  # pragma: no cover
            # Best-effort, matching the fleet's posture: a failed registration means this
            # verb is not routable yet, NOT that the engine is down.
            print(f"[engine-fin] registration failed for {v['verb']}: {exc}")

    # THE RESOLVER PROVIDER — without it, four of six verbs cannot be filled from a phrase.
    #
    # Every spoken-mandatory slot in this engine is instance-kind (`program_id`), and a
    # speaker says "Meridian", not "NP-MERIDIAN". Engine P measured what happens without a
    # provider: the filler emitted the NAME into an id slot at 0.92 confidence and the engine
    # answered `422 unknown site 'Aurora'` — an honest refusal to a perfectly answerable
    # question, and the largest single failure class in its corpus.
    try:
        register_engine_to_mesh(
            mint=_mint,
            name="engine_fin_finance_resolve_instance",
            description=(
                "Resolves a spoken finance name — a program, control account, work package, "
                "WBS element or organizational element — to its identifier in the program "
                "financial model, by exact match then contained phrase then token overlap. "
                "Returns candidates with class URI, label and score, highest first. An empty "
                "list is a first-class answer: the provider abstains below its floor rather "
                "than offering a least-bad match, because a least-bad id is how a "
                "confidently wrong answer reaches a verb."
            ),
            verb="mesh:resolveInstance",
            input_uri=MESH + "InstanceIdentifier",
            output_uri=MESH + "InstanceResolution",
            verb_synonyms=["which program", "which control account", "which work package",
                           "resolve name", "look up by name"],
            endpoint_url=f"{base}/resolve_instance",
            owner_persona=OWNER_PERSONA,
            domains=DOMAINS,
            cost_class="fast",
            provider="engine_fin_finance",
            timeout_s=5.0,
        )
    except Exception as exc:  # pragma: no cover
        print(f"[engine-fin] resolveInstance provider registration failed: {exc}")

    # THE ENUMERATE PROVIDER — the option source, not the resolver.
    #
    # `resolveInstance` scores candidates against something the SPEAKER said. A slot the
    # phrase never filled has no such string, so no number of resolve providers builds a menu
    # for it — and the ask that would offer one is blocked until something can enumerate.
    #
    # CONTRACT D: mesh:InstanceClass and mesh:InstanceEnumeration must ALREADY EXIST as
    # :OntologyClass nodes or this registration is a PERMANENT 422 (no retry — the ontology
    # has to be fixed first). Both are declared in setup/ontologies/mesh_system.ttl by Lane
    # 1, and Engine F's seed queues BEHIND them in the same prime window. Checked before
    # writing this, because a neighbouring registration failing silently leaves a
    # half-registered engine that looks healthy from outside.
    try:
        register_engine_to_mesh(
            mint=_mint,
            name="engine_fin_finance_enumerate_instances",
            description=(
                "Lists the members of a finance class — programs, control accounts, work "
                "packages, WBS elements, organizational elements, funding lines — so an "
                "elicitation can offer a menu for a slot the speaker never filled. Answers "
                "with one of three outcomes: members (the list, and a menu is legitimate), "
                "too_many (the class is real and larger than a menu, with its count), or "
                "unsupported (this provider does not hold that class). The refusal is a "
                "first-class answer: free text is permitted where a provider REPORTS "
                "unboundedness, never where nobody attempted enumeration."
            ),
            verb="mesh:enumerateInstances",
            input_uri=MESH + "InstanceClass",
            output_uri=MESH + "InstanceEnumeration",
            verb_synonyms=["which programs", "list control accounts", "what work packages",
                           "show me the options", "enumerate"],
            endpoint_url=f"{base}/enumerate_instances",
            owner_persona=OWNER_PERSONA,
            domains=DOMAINS,
            cost_class="fast",
            provider="engine_fin_finance",
            timeout_s=5.0,
        )
    except Exception as exc:  # pragma: no cover
        print(f"[engine-fin] enumerateInstances provider registration failed: {exc}")

    yield


# TRANSPORT AUTH (OBSERVE) — the birth rule. An engine born without it is an unauthenticated
# inbound surface that looks finished, which is exactly the class `unminted-caller-enumeration`
# found across five repos. One implementation, from the mesh membership package: validate
# whatever arrives, log the caller posture per request, REFUSE NOTHING until
# REQUIRE_TRANSPORT_AUTH flips. The announcement is the pre-positioned string the fresh-deploy
# gauge reads — an engine that takes the dependency but loses the announcement has a real
# posture nothing can observe.
from iagent_mesh.transport_auth import announce as _announce_transport_auth  # noqa: E402
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs  # noqa: E402
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth  # noqa: E402

_announce_transport_auth(component="engine-fin")

app = FastAPI(
    title="Engine F — Program Finance",
    **_docs_kwargs(),  # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth("engine-fin"))],
    lifespan=lifespan,
)


class MeasureRequest(BaseModel):
    """The envelope. `params` carries the slots; there is no state ref.

    NO `state_ref`, AND THE ABSENCE IS THE POINT. Engine P's envelope carries one because a
    planning question can be asked of a scenario that does not yet exist. A finance question
    is asked of what was reported; there is no forkable state, so there is nothing to name.
    """
    params: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus what this process believes about itself — AND NOTHING MORE.

    ⛔ `verbs` HERE IS NOT EVIDENCE OF REGISTRATION, and the field carries the warning
    because the number is otherwise irresistible. It counts this engine's OWN IN-PROCESS
    TABLE, built from the hardcoded catalogue above at import time. It reads 6:

      * when the mesh holds bare endpoints instead of FQDNs
      * when the engine never re-registered at all
      * when the reregister hook never ran

    It measures the engine's opinion of itself, not the mesh's record of it, and it would
    green-light exactly the failure it looks like it detects. Engine P's `verbs: 14` was
    written into a prep doc as "the signature that matters most" and was later struck out for
    precisely this. VERIFY IN THE GRAPH — see §9 of docs/runbooks/adding-an-engine.md.
    """
    return {
        "status": "ok",
        "engine": "engine-fin",
        "verbs": len(VERBS),
        "verbs_are_not_proof_of_registration": (
            "in-process table only; verify verb edges in Neo4j by name — runbook §9"
        ),
        "data": notional_banner(),
        "reported_periods": sorted({f.period for f in STATE.facts}),
    }


@app.get("/verbs")
def list_verbs() -> dict[str, Any]:
    """The catalogue as this process holds it, with each verb's declared slots.

    Useful for spot-checking a declaration against a signature WITHOUT a cluster — which is
    the one thing this endpoint is good for. It is not a registration check either.
    """
    return {"verbs": [
        {
            "verb": v["verb"],
            "fn": v["fn"],
            "input_uri": v["input_uri"],
            "output_uri": measures.OUTPUT_URI[v["fn"]],
            "slots": with_live_vocabularies(slots_for(v["fn"])),
        }
        for v in VERBS
    ]}


@app.post("/measure/{fn}")
def run_measure(fn: str, req: MeasureRequest, request: Request) -> dict[str, Any]:
    """Execute one verb.

    The response carries `output_uri` and rows and NOTHING about presentation. What archetype
    draws this is `select_presentation`'s decision, made from the payload against the caller's
    registered menu (ADR-0042 §2). An engine that named a view here would re-open
    `archetype-chosen-before-data` from the other end.
    """
    if fn not in measures.OUTPUT_URI:
        raise HTTPException(status_code=404, detail=f"unknown measure {fn!r}")
    func = getattr(measures, fn, None)
    if func is None:  # pragma: no cover — OUTPUT_URI and the module agree by construction
        raise HTTPException(status_code=500, detail=f"measure {fn!r} declared but not implemented")

    params = dict(req.params)

    # ── THE DECLARED REFUSAL, FIRED FROM THE DECLARATION ─────────────────────────────────
    #
    # A missing spoken-mandatory slot is refused BEFORE the call, with a message built from
    # `slots_for` — so the three EAC method names in the refusal come out of the `Literal`
    # rather than out of a string someone typed, and a fourth formula appears in the refusal
    # on the same edit that adds it.
    #
    # 422 WITH A NAMED CHOICE, not 400 "bad params". This is ADR-0045's designed behaviour:
    # a bare "what's the EAC" is REFUSED, and the refusal names the choice, because the cost
    # of guessing here is an unrequested ASSERTION — a number somebody repeats in a meeting.
    missing = missing_mandatory(fn, params)
    if missing:
        raise HTTPException(status_code=422, detail={
            "needs_slots": [m["name"] for m in missing],
            "question": refusal_for(fn, missing),
            "slots": missing,
        })

    try:
        rows = func(STATE, **params)
    except MethodRequired as exc:
        # THE SECOND GATE. Unreachable through this route (the declaration check above fires
        # first) and kept anyway, because ADR-0045 requires the refusal to live in the VERB
        # rather than in the caller's discipline — a caller reaching the function directly
        # must get the same answer this route gives.
        raise HTTPException(status_code=422, detail={
            "needs_slots": ["method"], "question": str(exc),
        }) from exc
    except NotInModel as exc:
        # 422, not 404, and never an empty result. "The model does not capture X" is an
        # ANSWER the refusal path renders; an empty row set renders as "none found", which is
        # a false statement about something that does not exist.
        raise HTTPException(status_code=422, detail={"not_in_model": str(exc)}) from exc
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"bad params for {fn}: {exc}") from exc

    return {
        "measure": fn,
        "output_uri": measures.OUTPUT_URI[fn],
        # DECLARED, NEVER INFERRED. A verb absent from VALUE_UNIT emits no such key and the
        # renderer keeps showing a bare number rather than guessing a currency this payload
        # never sent — which is why `fin_performance_indices` has none: CPI is a ratio, and
        # a dollar sign on 0.85 is a lie the producer told.
        **({"value_unit": measures.VALUE_UNIT[fn]} if fn in measures.VALUE_UNIT else {}),
        **({"value_label": measures.VALUE_LABEL[fn]} if fn in measures.VALUE_LABEL else {}),
        # THE DISCLOSURE RIDES ON THE PAYLOAD, not only in a docstring. A finance figure that
        # leaves this engine without saying it is notional is a figure somebody can paste
        # into a deck, and a docstring is not visible from a screenshot.
        "data_provenance": notional_banner(),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# POST /resolve_instance — the mesh:resolveInstance provider for PROGRAM_FINANCE
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    """The mesh's resolveInstance request. THE FIELD IS `identifier`, NOT `text`.

    ⛔ THIS WAS WRONG AND IT MADE THE PROVIDER UNCALLABLE. Engine F registered as a
    `mesh:resolveInstance` provider and could not be called by one: Engine O's fan-out sends
    `{"identifier": ..., "query": ...}` (`ontology_service/main.py` `_call_resolver`) and this
    model required `text`, so every real call was a **422** while the graph said the provider
    was registered, by name, at the right endpoint.

    REGISTERED IS NOT PARTICIPATING. The registration set read 8-by-name and non-null — the
    check I wrote and ran — and the provider still could not answer, because a registration
    describes an edge and says nothing about the payload the consumer actually sends.

    NO `text` ALIAS. Accepting both spellings would leave two correct answers in the fleet and
    guarantee the next engine copies the wrong one; the contract is set by the four providers
    that already work, and `query` is carried because the fan-out sends it.
    """
    identifier: str = ""
    query: str = ""
    class_uri: Optional[str] = None

    # ⚠ A CALLER SENDING THE OLD `{"text": ...}` GETS 200 WITH AN EMPTY LIST, NOT A REFUSAL.
    # `identifier` has a default, pydantic drops the unknown field, and an empty needle scores
    # nothing — so a mis-implemented caller reads "no match" rather than "wrong field". That is
    # the same silent shape the rename fixed, surviving one layer down.
    #
    # LEFT AS-IS DELIBERATELY: engine-p's ResolveInstanceRequest defaults `identifier` the same
    # way, and diverging would make Engine F the odd provider in a contract whose whole value
    # is that the four existing ones agree. The exposure is bounded — engine-o's fan-out always
    # sends `identifier` — and an empty list IS a first-class answer in this contract. Recorded
    # rather than fixed, because the reason it is safe is not obvious from the code.


#: The classes this provider holds, and the collection + id/label fields for each. ONE MAP,
#: so the resolver and the enumerator below cannot disagree about what this engine offers —
#: two lists of the same thing is the second-registry shape this codebase keeps paying for.
#:
#: ── fin:FundingLine WAS MISSING FROM THIS MAP, AND IT IS THE ONE THAT MATTERED ─────────
#: Found by running the engine, not by reading it: `enumerate_instances` answered
#: `unsupported` for fin:FundingLine — WHICH IS THE `input_uri` OF `fin_funding_status`.
#: So the one class a registered verb routes on was the one class this provider refused to
#: build a menu for, and the refusal is a legitimate-looking answer: an ask reading
#: `unsupported` falls back to free text believing a provider considered the question.
#:
#: THE CHECK THAT CATCHES THIS is not "did I list the obvious classes" but "is every
#: `input_uri` in VERBS present here" — the enumerable set is DERIVED FROM WHAT THE ENGINE
#: ROUTES ON, not from what looked worth listing. `_unroutable_classes()` below asserts it
#: at boot, so a seventh verb on a new class fails at start rather than at an elicitation.
_RESOLVABLE: dict[str, tuple[str, str, str]] = {
    FIN + "Program":        ("programs", "program_id", "name"),
    FIN + "ControlAccount": ("control_accounts", "ca_id", "name"),
    FIN + "WorkPackage":    ("work_packages", "wp_id", "name"),
    FIN + "WBSElement":     ("wbs", "wbs_id", "name"),
    FIN + "OBSElement":     ("obs", "obs_id", "name"),
    # PERIOD-SCOPED ROWS, DEDUPED BY IDENTITY. The funding collection holds one row per line
    # PER PERIOD, so a naive listing offers the same three appropriations six times each.
    # `_members_of` dedupes on the id field, which is why both the resolver and the
    # enumerator go through it rather than iterating the collections themselves.
    FIN + "FundingLine":    ("funding", "line_id", "name"),
}

#: fin:PerformanceMeasurementBaseline is the `input_uri` of two verbs and is DELIBERATELY
#: absent above: it names a series, not a set of addressable things, so there is no menu to
#: offer and no name to resolve. Listing it as enumerable would be worse than omitting it —
#: an ask would request a menu, get an empty one, and read that as "there are none".
_NOT_ENUMERABLE = {FIN + "PerformanceMeasurementBaseline"}


def _members_of(class_uri: str) -> list[dict[str, Any]]:
    """The distinct members of one class, deduped by identity, in a stable order.

    ONE IMPLEMENTATION FOR BOTH PROVIDERS. The resolver scores against these and the
    enumerator lists them; two separate walks of the same collections is how one of them
    ends up holding a stale idea of what this engine offers.
    """
    spec = _RESOLVABLE.get(class_uri)
    if spec is None:
        return []
    attr, id_field, label_field = spec
    seen: dict[str, dict[str, Any]] = {}
    for item in getattr(STATE, attr):
        ident = getattr(item, id_field)
        if ident not in seen:
            seen[ident] = {
                # `instance_id` — and THIS is the half that failed SILENTLY. The disposition
                # builds options from `m.get("instance_id")` and FILTERS OUT any member
                # lacking it (`slot_disposition.py`), so engine-fin answered "here are 5
                # members" and the consumer built ZERO options with no error anywhere. An ask
                # on a finance instance slot fell to free text while a good five-item menu sat
                # one field name away.
                "instance_id": ident,
                "label": getattr(item, label_field),
                "class_uri": class_uri,
            }
    return [seen[k] for k in sorted(seen)]


#: Classes this engine RESOLVES but no verb ROUTES ON, declared as deliberate.
#:
#: FOUND 2026-08-30 by measuring the resolver across the whole finance name surface, not by
#: reading the code. `OBSElement`, `WBSElement` and `WorkPackage` are resolvable and
#: enumerable — 19 members between them — and **no verb takes any of them as `input_uri`**.
#: A spoken name landing on one of them sets a routing subject that nothing serves.
#:
#: THAT IS INTENTIONAL HERE, and the reason is the variance tree: a work package is a
#: DRILL-DOWN REFERENT inside `fin_variance_analysis`'s decomposition, addressable in an
#: answer without being a top-level question. "What is WP-3101" is a follow-up, not an
#: opening. Same for the two axes: they organise the effort, they are not asked about alone.
#:
#: DECLARED RATHER THAN LEFT UNNOTICED, which is the whole point. `_unroutable_classes()`
#: below seals the FORWARD direction — a verb whose input class nothing can enumerate. This
#: is the REVERSE direction, and it was unsealed: a class that resolves and goes nowhere is
#: invisible to that check, and would have stayed invisible. Absence-by-decision and
#: absence-by-oversight look identical unless one of them is written down.
_NO_VERB_BY_DESIGN = {
    FIN + "OBSElement",
    FIN + "WBSElement",
    FIN + "WorkPackage",
}


def _dead_end_classes() -> list[str]:
    """Classes that resolve to a subject no verb serves, and were not declared as such.

    THE REVERSE OF `_unroutable_classes()`. That one asks "can every verb's subject be
    found?"; this asks "does every findable subject lead somewhere?" Both failures are
    silent, and neither is visible from the other direction.

    A name resolving to an undeclared dead end is worse than an unresolvable one: the
    resolver reports success, the router sets a subject, and the question dies one hop later
    with nothing to blame.
    """
    return sorted(set(_RESOLVABLE) - {v["input_uri"] for v in VERBS} - _NO_VERB_BY_DESIGN)


def _unroutable_classes() -> list[str]:
    """Input classes this engine registers verbs on but can neither resolve nor enumerate.

    DERIVED FROM `VERBS`, never from a second list. The failure it prevents has no symptom
    at the engine: the verb registers, `/health` is green, and the gap appears only when a
    speaker omits the slot and the elicitation offers free text because a provider said
    `unsupported`. Checked at boot, beside the seed check, for the same reason.
    """
    return sorted(
        {v["input_uri"] for v in VERBS} - set(_RESOLVABLE) - _NOT_ENUMERABLE
    )


def _candidates(text: str, class_uri: Optional[str]) -> list[dict[str, Any]]:
    """Exact, then case-insensitive, then contained phrase, then token overlap.

    DETERMINISTIC, NO MODEL, and each tier carries a DISTINCT score so the caller's gate can
    tell them apart. A single blended score would make "exact match" and "shared one common
    word" indistinguishable at the threshold, which is where a least-bad id gets promoted
    into a confident answer.
    """
    needle = text.strip().lower()
    if not needle:
        return []
    out: list[dict[str, Any]] = []
    for uri in _RESOLVABLE:
        if class_uri and class_uri != uri:
            continue
        for member in _members_of(uri):
            # `_members_of` now emits `instance_id`; this is its INTERNAL consumer and it
            # broke with the rename. The law that caught it is the same one that produced the
            # rename: read the consumer of what you fixed — including the ones inside your
            # own module, which a contract test against the HTTP surface would still miss.
            ident, label = member["instance_id"], member["label"]
            hay_id, hay_label = ident.lower(), label.lower()
            if needle in (hay_id, hay_label):
                score = 1.0
            elif needle == hay_id.replace("-", " ") or needle == hay_label:
                score = 0.95
            elif needle in hay_label or needle in hay_id:
                score = 0.75
            else:
                tokens_n = set(needle.split())
                tokens_h = set(hay_label.split()) | {hay_id}
                overlap = tokens_n & tokens_h
                if not overlap:
                    continue
                score = 0.4 + 0.2 * (len(overlap) / max(len(tokens_n), 1))
            out.append({
                # `instance_id`, NEVER `identity`. Engine O parses
                # `c.get("instance_id")` and coerces a miss to "" — so the wrong key
                # produced candidates that resolved "successfully" with no usable id.
                "instance_id": ident, "label": label,
                "class_uri": uri, "score": round(score, 3),
            })
    out.sort(key=lambda c: (-c["score"], c["instance_id"]))
    return out


#: Below this, the provider abstains. AN EMPTY LIST IS A FIRST-CLASS ANSWER — offering a
#: least-bad match is how a confidently wrong id reaches a verb and comes back as a number.
_RESOLVE_FLOOR = 0.5


@app.post("/resolve_instance")
def resolve_instance(req: ResolveRequest) -> dict[str, Any]:
    """Resolve a spoken finance name to an identifier in this model."""
    cands = [c for c in _candidates(req.identifier, req.class_uri)
             if c["score"] >= _RESOLVE_FLOOR]
    return {
        "output_uri": MESH + "InstanceResolution",
        "query": req.identifier,
        "candidates": cands,
        "provider": "engine_fin_finance",
    }


# ---------------------------------------------------------------------------
# POST /enumerate_instances — the mesh:enumerateInstances provider
# ---------------------------------------------------------------------------

class EnumerateRequest(BaseModel):
    class_uri: str
    limit: int = 8


@app.post("/enumerate_instances")
def enumerate_instances(req: EnumerateRequest) -> dict[str, Any]:
    """List the members of a finance class, or refuse in one of two named ways.

    THREE OUTCOMES, AND TWO OF THEM ARE REFUSALS THAT MEAN DIFFERENT THINGS:

      * `members`     — here they are, and a menu is legitimate.
      * `too_many`    — the class is real and larger than a menu, WITH ITS COUNT. An ask may
                        fall back to free text on the strength of this, because a provider
                        REPORTED unboundedness.
      * `unsupported` — this provider does not hold that class. Free text here would be
                        falling back because nobody attempted enumeration, which is the case
                        the distinction exists to refuse.
    """
    if req.class_uri not in _RESOLVABLE:
        return {
            "output_uri": MESH + "InstanceEnumeration",
            "class_uri": req.class_uri,
            "outcome": "unsupported",
            "reason": (
                "engine-fin holds no addressable members of this class. Classes it does "
                "enumerate: " + ", ".join(sorted(_RESOLVABLE))
            ),
            # CARRIED EMPTY, matching engine-p. A consumer doing `.get("members") or []`
            # should not have to special-case which outcome it is reading.
            "members": [],
            "provider": "engine_fin_finance",
        }
    members = _members_of(req.class_uri)
    if len(members) > req.limit:
        return {
            "output_uri": MESH + "InstanceEnumeration",
            "class_uri": req.class_uri,
            "outcome": "too_many",
            # THE COUNT IS THE POINT. "too many" without a number is indistinguishable from
            # "I did not look", and the ask downstream has to decide whether free text is
            # legitimate on exactly that difference. (The disposition reads `count` and
            # renders "N to choose from".)
            "count": len(members),
            # `bound`, matching engine-p's spelling rather than inventing `limit`. Nothing
            # reads it today; a second spelling for one concept is how the next reader picks
            # the wrong one.
            "bound": req.limit,
            "members": [],
            "provider": "engine_fin_finance",
        }
    return {
        "output_uri": MESH + "InstanceEnumeration",
        "class_uri": req.class_uri,
        "outcome": "members",
        "members": members,
        "count": len(members),
        "provider": "engine_fin_finance",
    }


# ---------------------------------------------------------------------------
# Mesh reads — ADR-0044's per-user path, exercised by a second consumer
# ---------------------------------------------------------------------------
#
# ENGINE F IS ADR-0044'S FIRST CONSUMER PROOF ON THE PER-USER PATH (ADR-0045 Decision 5). It
# holds NO standing credential and NO connection string of its own: when a governed dataset
# backs the model, the ticket is obtained PER REQUEST, carrying the CALLER'S identity, and
# it is the broker that mints it.
#
# THE IDENTITY IS READ OFF THE REQUEST, NEVER OFF THE PROCESS. This is the same law as
# `engine_mint`'s "identity is an argument", one plane over: a ticket minted from ambient
# process credentials would narrow rows for whoever the ENGINE is, not for whoever ASKED —
# which is the on_behalf_of laundering shape at the data plane, and it is invisible in every
# test where the two happen to be the same person.
#
# TODAY THE MODEL IS THE NOTIONAL SEED and this path is not on the hot route. That is stated
# rather than hidden: `FIN_DATASET_URN` unset means the in-process seed answers, and the
# engine says so on every response via `data_provenance`. What is NOT deferred is the
# credential posture — there is nowhere in this file a standing secret could be read from,
# so the degraded mode cannot silently become the privileged one.


def mesh_ticketed_read(urn: str, request: Request):  # pragma: no cover — needs the broker
    """Obtain a per-request ticket for `urn` on behalf of THIS request's caller.

    Raises rather than degrading if the caller's identity is absent: a read that cannot say
    who it is for must not be performed, because the narrowing that makes it safe is keyed on
    exactly that. `LLM_BASE_URL` degraded silently for 67 days on this fleet and cost a
    measured zero only by luck; a data read that degrades to "unscoped" costs more than an
    LLM that degrades to "unused".
    """
    try:
        from dag_tools.cortex_data.client import CortexDataClient
    except ImportError:  # pragma: no cover
        from cortex_data.client import CortexDataClient

    jwt = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    originator_sub = request.headers.get("x-originator-sub")
    originator_email = request.headers.get("x-originator-email")
    if not (jwt and (originator_sub or originator_email)):
        raise HTTPException(status_code=401, detail=(
            "a governed finance read requires the caller's identity on the request "
            "(Authorization + X-Originator-Sub/Email); engine-fin holds no standing "
            "credential to fall back on, by design (ADR-0044, ADR-0045 Decision 5)"
        ))
    client = CortexDataClient(
        broker_url=os.environ["CENTRAL_GATEWAY_URL"],
        jwt_token=jwt,
        originator_sub=originator_sub,
        originator_email=originator_email,
    )
    return client.get_dataframe(urn)
