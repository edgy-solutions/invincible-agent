"""Engine P — the planning engine. Ten verbs over server-owned plan state.

ADR-0042 §3 is why this service exists at all: a measure is a verb, a verb has a fixed
output type, and a browser-computed row set has neither — so it can never enter `/render_ui`.
Putting the measures here is not a performance choice, it is the only placement from which
they are governable, registrable and contract-validatable.

WHAT THIS SERVICE DELIBERATELY DOES NOT DO:
  * choose an archetype, a view, or a chart type — `select_presentation` does that, from the
    PAYLOAD, against the CALLER'S menu (ADR-0042 §2). Responses carry `output_uri` and rows.
  * call an LLM. Intent routing and narration live in the BFF, pinned internal with no cloud
    fallback. This engine computes; it never speaks.
  * persist. The store is in-memory for this cycle and becomes Postgres in Phase 4 — the
    PLACEMENT is the fixed contract, the store behind it is the placeholder.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

try:  # flat in the image (/app), packaged in the repo — see tests/test_agent_modules_survive_flat_layout.py
    import measures
    from slots import slots_for
    from seed import build_seed, check_consistency
    from state import (
        MoveProject, MoveSiteImpact, PlanStore, SetCommitment, SetCost, UnknownTarget,
    )
    from entities import Interval
except ImportError:
    from agent_fleet.planning_agent import measures
    from agent_fleet.planning_agent.slots import slots_for
    from agent_fleet.planning_agent.seed import build_seed, check_consistency
    from agent_fleet.planning_agent.state import (
        MoveProject, MoveSiteImpact, PlanStore, SetCommitment, SetCost, UnknownTarget,
    )
    from agent_fleet.planning_agent.entities import Interval

IDP = "http://invincible-agent/idp#"

# The single in-process store. Phase 4 swaps what is behind this name, never the name.
STORE = PlanStore(build_seed())


# ─────────────────────────────────────────────────────────────────────────────
# Verb catalogue — the registration source, so the mesh and the routes cannot
# disagree about which verbs exist. One table, read twice.
# ─────────────────────────────────────────────────────────────────────────────

VERBS: list[dict[str, Any]] = [
    {"fn": "plan_cost_curve", "verb": "mesh:planCostCurve", "input_uri": IDP + "Portfolio",
     "desc": "Time-phased funding requirement per fiscal period, split capex/expense, against the governed cap line. Answers spend-versus-plan: are we spending more than planned. NOT whether commitments cover requirements - that is planFundingGap. NOT site change-load, which is disruption rather than money - that is planSiteLoad. OWNS the phrasings: over budget, overspent, exceeds the cap, capex versus expense, how the money is phased.",
     "synonyms": ["cost curve", "spend by quarter", "over budget", "underwater", "capital plan", "time-phased spend"]},
    {"fn": "plan_funding_gap", "verb": "mesh:planFundingGap", "input_uri": IDP + "Portfolio",
     "desc": "Required minus committed funding per organization or initiative per period. Answers commitments-versus-requirements: do commitments cover what is required, who owes what they have not committed. NOT spend against a plan or cap - that is planCostCurve. NOT what nothing is working on - that is planCoverageGap, which is never about money. OWNS the phrasings: underfunded, funding short, under-committed, has not put up their share.",
     "synonyms": ["funding gap", "unfunded", "shortfall", "who is paying", "commitment gap"]},
    {"fn": "plan_site_load", "verb": "mesh:planSiteLoad", "input_uri": IDP + "Site",
     "desc": "Concurrent change-load per site per period against that site's governance-defined saturation threshold. NOT a labour or headcount measure. Answers which sites are affected, when, and which exceed their threshold. OWNS the phrasings: which sites are affected, who is taking the hit, overloaded, over capacity, slammed, which sites are carrying the most change.",
     "synonyms": ["site load", "overloaded sites", "change saturation", "which sites are hammered"]},
    {"fn": "plan_dependency_violations", "verb": "mesh:planDependencyViolations", "input_uri": IDP + "Portfolio",
     "desc": "Scheduling dependencies whose successor violates its FS/SS/FF/SF constraint plus lag, with the shortfall in days. CONSTRAINT EVALUATION over the whole portfolio, taking NO project parameter: it answers 'which sequencing rules are currently broken', and returns NOTHING when the schedule is clean. Does NOT answer what one named item depends on, waits on, or feeds into - that is a traversal and belongs to planDependencyNeighborhood, which reports every neighbour whether or not anything is violated. A question naming ONE item is almost never this verb. OWNS the phrasings: which dependencies are violated, what is out of sequence, which constraints are broken, how many days short.",
     "synonyms": ["broken dependency", "sequence violation", "constraint violation", "out of sequence", "schedule conflict"]},
    {"fn": "plan_dependency_neighborhood", "verb": "mesh:planDependencyNeighborhood", "input_uri": IDP + "Portfolio",
     "desc": "Every dependency neighbour of one item on the named side (upstream = what it waits on, downstream = what waits on it), each carrying its own satisfied/violated/unresolvable state. TRAVERSAL, not constraint evaluation: it reports every edge with its answer, where planDependencyViolations reports only the subset currently failing. Answers 'what does this wait on' truthfully when nothing is violated.",
     "synonyms": ["what blocks this", "what does this depend on", "predecessors", "successors", "what waits on this", "dependency chain", "upstream", "downstream", "knock-on"]},
    {"fn": "plan_commit_scenario", "verb": "mesh:planCommitScenario", "input_uri": IDP + "Portfolio",
     "desc": "Commit a scenario to baseline with a REQUIRED rationale, producing a decision record: the ops as disposed items, the rationale as the override-reason, the alternatives as the considered-set. MUTATES — it is the one verb that writes, and it refuses without a reason.",
     "synonyms": ["commit this", "approve the scenario", "make it the plan", "adopt this", "sign off", "lock it in", "accept the change"]},
    {"fn": "plan_maturity_grid", "verb": "mesh:planMaturityGrid", "input_uri": IDP + "Capability",
     "desc": "Capability by site maturity level versus target, from the latest append-only assessment at or before an as-of date. The word target here means a MATURITY LEVEL, never a funding target - a question about money versus target is planCostCurve or planFundingGap. OWNS the phrasings: maturity versus target, where are we against where we said we would be.",
     "synonyms": ["maturity", "capability level", "assessment grid", "how mature"]},
    {"fn": "plan_capability_path", "verb": "mesh:planCapabilityPath", "input_uri": IDP + "Capability",
     "desc": "The projects maturing a capability ordered by completion, against the plateaus of every process it enables. Answers which projects advance a capability and by when. OWNS the phrasings: who is doing the work on it, what gets this to target, which projects mature this, what is the path for that capability.",
     "synonyms": ["capability path", "what matures this", "how do we get this capability"]},
    {"fn": "plan_process_evolution", "verb": "mesh:planProcessEvolution", "input_uri": IDP + "BusinessProcess",
     "desc": "A business process's plateaus on a timeline with the capabilities enabling it and their maturity trajectory. Answers how a process evolves over time and which capabilities enable it. OWNS the phrasings: where is it headed, how does this evolve, what feeds it, what has to be in place for it, show the plateaus.",
     "synonyms": ["process evolution", "plateaus", "how does this process change", "target state"]},
    {"fn": "plan_tech_footprint", "verb": "mesh:planTechFootprint", "input_uri": IDP + "Technology",
     "desc": "The capabilities a technology enables and the projects it participates in, with their windows.",
     "synonyms": ["technology footprint", "where is this used", "what depends on this tech"]},
    {"fn": "plan_schedule", "verb": "mesh:planSchedule", "input_uri": IDP + "Portfolio",
     "desc": "Initiative to phase to project rows with planned and actual intervals. The timeline's data.",
     "synonyms": ["schedule", "timeline", "gantt", "what is happening when", "projects in window"]},
    {"fn": "plan_coverage_gap", "verb": "mesh:planCoverageGap", "input_uri": IDP + "Portfolio",
     "desc": "What nothing is working on. Capabilities no project contributes to, and the processes those gaps leave exposed, reported separately from processes with no capability modelled at all. An absence query about the plan's STRUCTURE. NEVER a money question despite the word gap - funding shortfalls are planFundingGap and spend is planCostCurve. OWNS the phrasings: nobody is working on, no project is advancing, processes with no capability behind them.",
     "synonyms": ["coverage gap", "what is not covered", "gaps", "nobody is working on", "uncovered capabilities", "blind spots"]},
    {"fn": "plan_diff", "verb": "mesh:planDiff", "input_uri": IDP + "Portfolio",
     "desc": "The consequences of one plan state versus another — what improved, what degraded, each with a computed magnitude and the named things affected. Never a before-and-after of two states: a comparison, so the price of a change is visible beside its benefit.",
     "synonyms": ["diff", "what changed", "consequences", "trade-off", "compare scenarios", "what does this cost"]},
    {"fn": "plan_session_changes", "verb": "mesh:planSessionChanges", "input_uri": IDP + "Portfolio",
     "desc": "The ops accumulated in a scenario rendered as a change log. The meeting's memory.",
     "synonyms": ["what changed", "session changes", "what did we decide", "summarize session"]},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Register every verb as its own predicate edge.

    ONE CALL PER VERB, per the mesh's existing idiom — `register_engine_to_mesh` takes a
    single verb, and ten calls is the honest shape rather than a bulk endpoint invented for
    this engine. Registration is opt-in via MESH_REGISTER_ON_STARTUP, so a local run or a
    unit test does not need the mesh to exist.
    """
    problems = check_consistency(STORE.baseline)
    if problems:
        # FAIL LOUD AT BOOT. A seed with dangling references produces measures that are
        # quietly wrong rather than absent, which is the failure mode with no symptom.
        raise RuntimeError("planning seed is inconsistent: " + "; ".join(problems[:5]))

    # FLAT FIRST. In the image /app IS this directory, so `utils` is a sibling top-level
    # module and `agent_fleet` does not exist at all. The packaged path is the repo form.
    # Getting this backwards cost a full roll: the import failed, the helper became None,
    # and twelve registrations were skipped while the engine reported perfectly healthy.
    try:
        from utils.mesh_registration import engine_mint, register_engine_to_mesh
    except ImportError:
        try:
            from agent_fleet.utils.mesh_registration import engine_mint, register_engine_to_mesh
        except ImportError:  # pragma: no cover — local runs without the fleet extra
            register_engine_to_mesh = None

    if register_engine_to_mesh is None:
        # SAY SO. A registration that silently does not happen leaves an engine that passes
        # every probe and answers nothing, which is the failure mode with no symptom.
        print("[engine-p] mesh registration helper unavailable — NO verbs registered")

    if register_engine_to_mesh is not None:
        # The SERVICE is iagent-engine-p (templates/engines.yaml names it by component,
        # not by image). The image is called planning-agent; the service is not.
        base = os.getenv("ENGINE_P_PUBLIC_URL", "http://iagent-engine-p:8095")
        # ONE STATEMENT OF THIS ENGINE'S IDENTITY, used by every registration below.
        #
        # The client id is `iagent-planning-agent` — the SERVICE name, which is not the
        # deployment name (`iagent-engine-p`) and not the image name (`planning-agent`).
        # The provider registration below was first written with the deployment name,
        # copied from engine-o's block, and minting failed 401 while the fourteen verb
        # registrations beside it succeeded — a half-registered engine whose verbs route
        # and whose resolver does not. The warning against exactly that is three lines
        # down: identity is an ARGUMENT, never derived from the component name. Hoisted so
        # there is one place to be wrong rather than two.
        _mint = engine_mint(client_id="iagent-planning-agent",
                            secret_env="ENGINE_P_CLIENT_SECRET")
        for v in VERBS:
            try:
                register_engine_to_mesh(
                    # REGISTERS AS ITSELF (2026-08-24). Every other engine passes a mint;
                    # this one did not, so it registered UNAUTHENTICATED — and registration
                    # IS routing authority: the manifest names the endpoint URL a verb
                    # resolves to. Unauthenticated, the registrar learns only that SOMETHING
                    # called, while "which engine" stays a self-asserted payload string.
                    # Identity is an ARGUMENT here, never derived from the component name —
                    # deriving it is how mint_service_token() made the supervisor dispatch
                    # as the review starter.
                    mint=_mint,
                    name="engine_p_planning",
                    description=v["desc"],
                    verb=v["verb"],
                    input_uri=v["input_uri"],
                    output_uri=measures.OUTPUT_URI[v["fn"]],
                    verb_synonyms=v["synonyms"],
                    endpoint_url=f"{base}/measure/{v['fn']}",
                    owner_persona="PORTFOLIO_LEAD",
                    domains=["PORTFOLIO_PLANNING"],
                    cost_class="fast",
                    # DERIVED from the measure's signature, never hand-transcribed — the enum
                    # values cannot drift from the `Literal` because they are read out of it.
                    slots=slots_for(v["fn"]),
                )
            except Exception as exc:  # pragma: no cover
                # Best-effort, matching the fleet's existing posture: a failed registration
                # means this verb is not routable yet, NOT that the engine is down.
                print(f"[engine-p] registration failed for {v['verb']}: {exc}")

        # THE PROVIDER REGISTRATION, and it is what makes the resolver reachable.
        #
        # Engine P owns the only copy of the planning entities and was not a
        # `mesh:resolveInstance` provider, so "the Aurora site" had nowhere to resolve and
        # the filler emitted the NAME into an id slot — 5 of 48 corpus cases, the single
        # largest failure class. The mechanism was never missing, only the participant.
        #
        # Self-registered every boot rather than hand-seeded, per the same rule the other
        # providers follow: reproducible, survives a re-prime, and is not a Cypher someone
        # ran once (`bootstrap-state-debt`).
        try:
            register_engine_to_mesh(
                mint=_mint,
                name="engine_p_planning_resolve_instance",
                description=(
                    "Resolves a spoken planning name — a site, capability, initiative, "
                    "project, business process, technology or organization — to its "
                    "instance id in the portfolio model, by exact match then "
                    "contained-phrase then token overlap. Returns candidates with class "
                    "URI, label and score, highest first. An empty list is a first-class "
                    "answer: the provider abstains below its floor rather than offering a "
                    "least-bad match, because a least-bad id is how a confidently wrong "
                    "answer reaches a verb."
                ),
                verb="mesh:resolveInstance",
                input_uri="http://invincible-agent/mesh#InstanceIdentifier",
                output_uri="http://invincible-agent/mesh#InstanceResolution",
                verb_synonyms=["which site", "which initiative", "which project",
                               "resolve name", "look up by name"],
                endpoint_url=base.rstrip("/") + "/resolve_instance",
                owner_persona="PORTFOLIO_LEAD",
                domains=["PORTFOLIO_PLANNING"],
                cost_class="fast",
                requires_human_approval=False,
                provider="engine_p_planning",
                timeout_s=5.0,
            )
        except Exception as exc:  # pragma: no cover
            print(f"[engine-p] resolveInstance provider registration failed: {exc}")

        # THE ENUMERATE PROVIDER — the option source, not the resolver.
        #
        # `resolveInstance` scores candidates against something the SPEAKER said. A slot the
        # phrase never filled has no such string, so no number of resolve providers builds a
        # menu for it. All four spoken-mandatory slots in this engine are instance-kind, so
        # the ask trigger fires on them and every menu it could offer was blocked on this.
        #
        # CONTRACT D: mesh:InstanceClass and mesh:InstanceEnumeration must already exist as
        # :OntologyClass nodes or this registration is a PERMANENT 422 — declared in
        # setup/ontologies/mesh_system.ttl and landed by the ontology seed. Checked before
        # writing this, because the neighbouring registration failed silently once already
        # this session and a half-registered engine looks healthy from outside.
        try:
            register_engine_to_mesh(
                mint=_mint,
                name="engine_p_planning_enumerate_instances",
                description=(
                    "Lists the members of a planning class — sites, capabilities, "
                    "initiatives, projects, business processes, technologies, "
                    "organizations — so an elicitation can offer a menu for a slot the "
                    "speaker never filled. Answers with one of three outcomes: members "
                    "(the list, and a menu is legitimate), too_many (the class is real and "
                    "larger than a menu, with its count), or unsupported (this provider "
                    "does not hold that class). The refusal is a first-class answer: free "
                    "text is permitted where a provider REPORTS unboundedness, never where "
                    "nobody attempted enumeration."
                ),
                verb="mesh:enumerateInstances",
                input_uri="http://invincible-agent/mesh#InstanceClass",
                output_uri="http://invincible-agent/mesh#InstanceEnumeration",
                verb_synonyms=["which sites", "list capabilities", "what projects",
                               "show me the options", "enumerate"],
                endpoint_url=base.rstrip("/") + "/enumerate_instances",
                owner_persona="PORTFOLIO_LEAD",
                domains=["PORTFOLIO_PLANNING"],
                cost_class="fast",
                requires_human_approval=False,
                provider="engine_p_planning",
                timeout_s=5.0,
            )
        except Exception as exc:  # pragma: no cover
            print(f"[engine-p] enumerateInstances provider registration failed: {exc}")
    yield


# TRANSPORT AUTH (OBSERVE) — the birth rule, and the suite caught its absence on the first
# run of tests/test_transport_auth_applied_everywhere.py against this engine. An engine born
# without it is an unauthenticated inbound surface that looks finished, which is exactly the
# class `unminted-caller-enumeration` found across five repos.
#
# One implementation, from the mesh membership package: validate whatever arrives, log the
# caller posture per request, REFUSE NOTHING until REQUIRE_TRANSPORT_AUTH flips. The
# announcement is the pre-positioned string the fresh-deploy gauge reads — an engine that
# takes the dependency but loses the announcement has a real posture nothing can observe.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth

_announce_transport_auth(component="engine-p")

app = FastAPI(
    title="Engine P — Planning",
    **_docs_kwargs(),  # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth("engine-p"))],
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────

class MeasureRequest(BaseModel):
    """`state_ref` is what makes a diff expressible without a session (ADR-0042 OQ2).

    Defaulting to baseline means a caller that does not care about scenarios never has to
    know they exist.
    """
    state_ref: str = "baseline"
    params: dict[str, Any] = Field(default_factory=dict)


class ForkRequest(BaseModel):
    scenario_id: str
    name: str
    base: str = "baseline"
    created_at: str = ""


# Verbs that WRITE, and the endpoint each is reached through. Kept as a MAP rather than a set
# so the refusal can name the alternative — a 400 that says "not here" without saying "there"
# is a dead end wearing a gate's clothes.
MUTATING_VERBS = {
    "plan_commit_scenario": "/scenario/{scenario_id}/commit",
}


class CommitRequest(BaseModel):
    rationale: str = ""
    actor: str = ""
    alternatives: Optional[list[dict[str, Any]]] = None
    question_trail: Optional[list[dict[str, Any]]] = None


class RescheduleRequest(BaseModel):
    """A drag, as the client can honestly describe it: which bar moved, and to where.

    NOTE WHAT IS ABSENT — anything about site impacts. The client has none: site impacts do
    not exist in cortex-ui at all, so a UI that tried to send impact ops would be inventing
    data. The policy derives them server-side, where the state is.
    """
    project_id: str
    start: str
    end: str


class OpRequest(BaseModel):
    op: str
    project_id: Optional[str] = None
    site_id: Optional[str] = None
    org_id: Optional[str] = None
    period: Optional[str] = None
    kind: Optional[str] = None
    amount: Optional[float] = None
    start: Optional[str] = None
    end: Optional[str] = None


def _to_op(r: OpRequest):
    """Translate the wire shape into the closed op union.

    An unknown `op` is a 400, never a no-op. A silently-dropped op is the failure where the
    room believes it made a change, the diff shows nothing, and the decision artifact records
    something that never applied.
    """
    if r.op == "move_project":
        return MoveProject(r.project_id or "", Interval(r.start or "", r.end or ""))
    if r.op == "set_cost":
        return SetCost(r.project_id or "", r.kind or "capex", r.period or "", r.amount or 0.0)  # type: ignore[arg-type]
    if r.op == "set_commitment":
        return SetCommitment(r.project_id or "", r.org_id or "", r.period or "",
                             r.kind or "capex", r.amount or 0.0)  # type: ignore[arg-type]
    if r.op == "move_site_impact":
        return MoveSiteImpact(r.project_id or "", r.site_id or "",
                              Interval(r.start or "", r.end or ""))
    raise HTTPException(status_code=400, detail=f"unknown op {r.op!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "verbs": len(VERBS),
        "baseline_version": STORE.version_of("baseline"),
        "scenarios": len(STORE.scenarios()),
    }


@app.get("/verbs")
def verbs() -> dict[str, Any]:
    """The catalogue, as the engine sees it. Diagnostic: if the mesh and this disagree,
    registration is the thing that failed, and this is how you tell."""
    return {"verbs": [
        {"verb": v["verb"], "fn": v["fn"], "output_uri": measures.OUTPUT_URI[v["fn"]],
         "input_uri": v["input_uri"]}
        for v in VERBS
    ]}


@app.post("/measure/{fn}")
def run_measure(fn: str, req: MeasureRequest) -> dict[str, Any]:
    """Execute one verb over one state ref.

    The response carries `output_uri` and rows and NOTHING about presentation. What archetype
    draws this is `select_presentation`'s decision, made from the payload against the caller's
    registered menu — ADR-0042 §2. An engine that named a view here would re-open
    `archetype-chosen-before-data` from the other end.
    """
    if fn not in measures.OUTPUT_URI:
        raise HTTPException(status_code=404, detail=f"unknown measure {fn!r}")
    if fn in MUTATING_VERBS:
        # A MEASURE IS A READ. plan_commit_scenario writes baseline and archives a scenario,
        # and letting it through here would make "run every verb" — which the route seal does
        # — a destructive operation. It is registered like every other verb so the router can
        # find it; it is reached through its own endpoint.
        raise HTTPException(
            status_code=400,
            detail=f"{fn} MUTATES and is not a measure; POST {MUTATING_VERBS[fn]} instead",
        )
    func = getattr(measures, fn, None)
    if func is None:  # pragma: no cover — OUTPUT_URI and the module agree by construction
        raise HTTPException(status_code=500, detail=f"measure {fn!r} declared but not implemented")

    try:
        state = STORE.resolve(req.state_ref)
    except UnknownTarget as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    params = dict(req.params)
    if fn == "plan_diff":
        # THE TWO-STATE VERB (ADR-0042 OQ2). `vs` names what to compare AGAINST and defaults
        # to baseline, which is the question a room actually asks — "what does my scenario
        # cost me relative to the plan of record". Resolved here rather than passed as rows so
        # the comparison is always against a real, addressable state.
        vs = params.pop("vs", "baseline")
        try:
            params["baseline_state"] = STORE.resolve(vs)
        except UnknownTarget as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    if fn == "plan_cost_curve" and req.state_ref != "baseline":
        # THE BASELINE SERIES is scenario-dependent by design (the diff machinery reaching the
        # period payload). Resolved HERE, where the store is, rather than passed by the caller:
        # a client naming its own baseline could compare against anything and the ghost would
        # be unattributable.
        params["baseline_state"] = STORE.resolve("baseline")

    if fn == "plan_schedule" and req.state_ref != "baseline":
        # "OP-TOUCHED" IS SCENARIO CONTEXT, and a measure is a pure function of what it is
        # handed — ops live on the Scenario, not in PlanState, so the set is computed here and
        # passed in. `getattr` because only some ops name a project (a funding commitment names
        # an org), and a flag for an op that touched no bar would flag nothing.
        try:
            sc = STORE.scenario(req.state_ref)
            params["touched_project_ids"] = {
                pid for pid in (getattr(o, "project_id", None) for o in sc.ops) if pid
            }
        except UnknownTarget:
            pass  # a state_ref that is not a scenario simply has no ops to touch anything

    if fn == "plan_session_changes":
        # The one measure that reads ops rather than state — it is the change log.
        sc = None if req.state_ref == "baseline" else STORE.scenario(req.state_ref)
        params.setdefault("ops", list(sc.ops) if sc else [])
        params.setdefault("scenario_name", sc.name if sc else None)

    try:
        rows = func(state, **params)
    except measures.NotInModel as exc:
        # 422, not 404, and not an empty result. "The model does not capture X" is an
        # ANSWER the refusal path renders; an empty row set would render as "none found",
        # which is a false statement about something that does not exist.
        raise HTTPException(status_code=422, detail={"not_in_model": str(exc)}) from exc
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"bad params for {fn}: {exc}") from exc

    return {
        "measure": fn,
        "output_uri": measures.OUTPUT_URI[fn],
        "state_ref": req.state_ref,
        # The pull trigger's discriminant (ADR-0042 OQ1) and the live view's freshness stamp
        # (§4): a client holding an older version knows to re-request, and the card shows the
        # version this evaluation was true against rather than inheriting its mint-time one.
        "state_version": STORE.version_of(req.state_ref),
        # DECLARED, never inferred. A verb absent from VALUE_UNIT emits no key at all, and the
        # renderer keeps showing `1.5M` rather than guessing a `$` this payload never sent.
        # Absent-means-silent is the whole contract: `total` is money here and a count in
        # plan_site_load, so a generic runner must not read semantics off a field name.
        **({"value_unit": measures.VALUE_UNIT[fn]} if fn in measures.VALUE_UNIT else {}),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# POST /resolve_instance — the mesh:resolveInstance provider for PORTFOLIO_PLANNING
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. Six spoken slots are opaque ids (`site_id`, `capability_id`,
# `project_id`, `process_id`, `tech_id`, `scope_initiative_id`) and a speaker says
# "the Aurora site", not "S1". Measured before this endpoint: the slot-filler emitted
# `site_id="Aurora"` at 0.92 confidence and the engine answered `422 unknown site
# 'Aurora'` — an honest refusal to a perfectly answerable question, and the single
# largest failure class in the corpus (5 of 48).
#
# THE MECHANISM WAS NEVER MISSING, ONLY THE PARTICIPANT. `mesh:resolveInstance` is a
# federated verb with a fan-out, a scoring gate and four registered providers. Engine P
# owned the only copy of the planning entities and was not one of them. This makes it one.
#
# DETERMINISTIC, NO MODEL. Exact, then case-insensitive, then a contained-phrase match,
# each with a distinct score so the caller's gate can tell them apart. Nothing here
# guesses: below the floor it returns NOTHING, because an empty candidate list is a
# first-class answer and "least-bad match" is how a confidently wrong id gets produced.


class ResolveInstanceRequest(BaseModel):
    identifier: str = ""
    query: str = ""


#: (collection attr, id attr, class local name). The class URI is what the router's
#: decision table groups candidates by, so two entities of different kinds scoring alike
#: come back as `mixed` rather than one silently winning.
_RESOLVABLE = [
    ("sites",         "site_id",       "Site"),
    ("capabilities",  "capability_id", "Capability"),
    ("initiatives",   "initiative_id", "Initiative"),
    ("projects",      "project_id",    "Project"),
    ("processes",     "process_id",    "BusinessProcess"),
    ("technologies",  "tech_id",       "Technology"),
    ("organizations", "org_id",        "Organization"),
]

#: Below this, return nothing. The provider abstains rather than offering its least-bad
#: match, per the contract the other providers already follow.
_RESOLVE_FLOOR = 0.6


def _score_name(identifier: str, label: str, entity_id: str) -> float:
    """How well a spoken phrase names this entity. Deterministic and explainable.

    The id itself matches exactly — a caller who says "S1" is naming S1 — because the
    filler legitimately produces ids when the speaker used one, and a resolver that only
    understood labels would reject its own correct answers.
    """
    def _norm(s: str) -> str:
        """Lower-case and flatten separators.

        UNDERSCORES WERE NOT NORMALISED AND HYPHENS WERE, which is an inconsistency that
        cost a live regression: the filler began emitting `order_to_cash` for "Order to
        Cash" — an id-shaped rendering of the right name — and scored 0.0 against its own
        label while `ORDER-TO-CASH` scored 0.8. Same thing spelled differently is the case
        this resolver exists to absorb; which separator a caller happened to use is not a
        fact about the entity.
        """
        return " ".join(str(s or "").replace("_", " ").replace("-", " ").lower().split())

    ident = _norm(identifier)
    if not ident:
        return 0.0
    lab = _norm(label)
    eid = _norm(entity_id)

    if ident == eid or ident == lab:
        return 1.0
    # "Site A - Aurora" contains "aurora"; "the ERP Modernization project" contains
    # "erp modernization". Both directions, because a speaker adds words ("the ... site")
    # and a label adds words ("Site A - ...").
    if ident in lab or lab in ident:
        # Longer overlap is stronger: a two-character token inside a long label is noise.
        ratio = min(len(ident), len(lab)) / max(len(ident), len(lab), 1)
        return 0.75 + 0.2 * ratio
    ident_tokens = {w for w in ident.split() if len(w) > 2}
    lab_tokens = {w for w in lab.split() if len(w) > 2}
    if ident_tokens and lab_tokens:
        overlap = len(ident_tokens & lab_tokens) / len(ident_tokens | lab_tokens)
        if overlap:
            return 0.5 + 0.3 * overlap
    return 0.0


@app.post("/resolve_instance")
def resolve_instance(req: ResolveInstanceRequest) -> dict[str, Any]:
    """Candidates for a spoken name, highest score first.

    An EMPTY list is a first-class answer, not a failure: it means the planning model does
    not contain anything by that name, which is exactly what the caller needs to know in
    order to ask the speaker rather than dispatch a guess.
    """
    state = STORE.resolve("baseline")
    out: list[dict[str, Any]] = []
    for attr, id_attr, class_local in _RESOLVABLE:
        coll = getattr(state, attr, None) or []
        items = list(coll.values()) if isinstance(coll, dict) else list(coll)
        for it in items:
            eid = getattr(it, id_attr, None)
            if not eid:
                continue
            label = getattr(it, "name", "") or ""
            score = _score_name(req.identifier, label, str(eid))
            if score >= _RESOLVE_FLOOR:
                out.append({
                    "instance_id": str(eid),
                    "class_uri": IDP + class_local,
                    "label": label,
                    "score": round(score, 4),
                })
    out.sort(key=lambda c: c["score"], reverse=True)
    return {"candidates": out[:10]}


# ---------------------------------------------------------------------------
# POST /enumerate_instances — the mesh:enumerateInstances provider
# ---------------------------------------------------------------------------
#
# RESOLVE AND ENUMERATE ARE DIFFERENT VERBS. `resolveInstance` takes an `identifier` and
# SCORES candidates against something the speaker said. A slot the phrase never filled has
# no such string, so no number of resolve providers can build a menu for it — which is why
# ADR-0033's fourth option source needed a capability that did not exist.
#
#   resolve   : identifier -> scored candidates
#   enumerate : class      -> its members
#
# THREE OUTCOMES, NOT A LIST, and this is the whole design of the endpoint. `resolve` is
# naturally bounded because a query bounds it; `enumerate` is bounded only by the substrate.
# Nine capabilities is a menu; a DataHub dataset class is unbounded and a menu over it is a
# lie. So a provider must be able to SAY it cannot enumerate, as a first-class answer:
#
#   members     here they are, and the menu is real
#   too_many    the class is real and larger than a menu (count included, it is cheap here)
#   unsupported this provider does not enumerate this class
#
# THAT IS WHAT MAKES ADR-0033'S FREE-TEXT BOUNDARY PRINCIPLED RATHER THAN A FUDGE. Free text
# becomes permitted where a provider REPORTS unboundedness — never where nobody built the
# capability, which is the reading the ADR's "never because enumeration was not attempted"
# clause exists to close. An ask that falls back to free text must carry the provider's own
# reason.
#
# LIVE FROM THE STORE, NO REGISTRY. `[[slot-resolution-entities-in-the-resolver-substrate]]`
# already ruled this shape for `resolve` and it carries over unchanged: no declaration with
# side effects, no seeded copy. An emptied store answering with zero members is CORRECT
# behaviour, not staleness.
#
# NO FILTER IN v1, deliberately. A `prefix`/`contains` parameter turns `too_many` into
# progressive disclosure — which is a search box, which is free text with extra steps, and
# which turns one turn into two when ADR-0033 bounds the turn at one.


class EnumerateInstancesRequest(BaseModel):
    #: The class to enumerate, as an `idp:` class URI. This is the SAME value a slot
    #: declaration carries in `referent`, so the caller passes the declaration through and
    #: needs no vocabulary of its own — the join the enumerate item flagged as "most likely
    #: to be discovered late" is closed by that field already existing.
    class_uri: str = ""


#: THE MENU BOUND — RULED 2026-08-29 at 8, and it is a HUMAN-ATTENTION bound.
#:
#: It is the number of options a person can actually choose from in one turn, which is a
#: fact about readers and not about this substrate. The previous value (15) was chosen so
#: that no class the seed happens to hold would be truncated — a bound fitted to the data,
#: which would have moved every time the seed grew and would have justified itself forever.
#:
#: CONSEQUENCE, STATED BECAUSE IT IS NOT OBVIOUS: at 8, `Capability` (9 members) is
#: `too_many`. The item that ruled this bound used "9 capabilities is a menu" as its example
#: of a menu, so the ruled number and that example disagree — and `capability_id` is one of
#: the four spoken-mandatory slots, so its ask falls to free text rather than a list. That
#: may be intended (nine is genuinely a lot to read back in one turn) or may be an
#: off-by-one against the example; either way the number is the ruling and this comment is
#: the flag, not a silent adjustment.
#:
#: `Project` (14) is now a real `too_many` case, which retires the previous problem that the
#: outcome was only reachable by lowering the bound inside a test.
#:
#: Env-overridable so the bound can be tuned against real readers without a code change.
_MENU_BOUND = int(os.getenv("ENUMERATE_MENU_BOUND", "8"))


def _enumerable() -> dict[str, tuple[str, str, str]]:
    """class_uri -> (collection attr, id attr, label attr). Derived from the same table the
    resolver uses, so a class this engine can resolve is a class it can enumerate."""
    return {IDP + class_local: (attr, id_attr, "name")
            for attr, id_attr, class_local in _RESOLVABLE}


@app.post("/enumerate_instances")
def enumerate_instances(req: EnumerateInstancesRequest) -> dict[str, Any]:
    """The members of a class, or an honest refusal to list them."""
    spec = _enumerable().get((req.class_uri or "").strip())
    if spec is None:
        # NOT an error and NOT an empty menu. "I do not enumerate this" and "this class has
        # no members" are different facts, and collapsing them is how free text becomes a
        # default instead of a reported outcome.
        return {"outcome": "unsupported", "class_uri": req.class_uri,
                "reason": "engine-p does not hold this class", "members": []}

    attr, id_attr, label_attr = spec
    state = STORE.resolve("baseline")
    coll = getattr(state, attr, None) or []
    items = list(coll.values()) if isinstance(coll, dict) else list(coll)
    members = [
        {"instance_id": str(getattr(it, id_attr)), "label": getattr(it, label_attr, "") or ""}
        for it in items if getattr(it, id_attr, None)
    ]
    if len(members) > _MENU_BOUND:
        # The count travels even though the members do not: "there are 400" is a useful
        # thing for an ask to say, and it is cheap here because the collection is in hand.
        return {"outcome": "too_many", "class_uri": req.class_uri,
                "count": len(members), "bound": _MENU_BOUND, "members": []}
    members.sort(key=lambda m: m["instance_id"])
    return {"outcome": "members", "class_uri": req.class_uri,
            "count": len(members), "members": members}


@app.get("/state/{state_ref}/version")
def state_version(state_ref: str) -> dict[str, Any]:
    """The cheap poll behind ADR-0042 OQ1's pull trigger."""
    try:
        return {"state_ref": state_ref, "version": STORE.version_of(state_ref)}
    except UnknownTarget as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/scenario")
def fork(req: ForkRequest) -> dict[str, Any]:
    try:
        sc = STORE.fork(req.scenario_id, req.name, base=req.base, created_at=req.created_at)
    except UnknownTarget as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"scenario_id": sc.scenario_id, "name": sc.name, "base": sc.base, "version": sc.version}


@app.get("/scenario")
def list_scenarios() -> dict[str, Any]:
    return {"scenarios": [
        {"scenario_id": s.scenario_id, "name": s.name, "base": s.base,
         "version": s.version, "ops": len(s.ops), "archived": s.archived}
        for s in STORE.scenarios()
    ]}


@app.post("/scenario/{scenario_id}/op")
def append_op(scenario_id: str, req: OpRequest) -> dict[str, Any]:
    op = _to_op(req)
    try:
        sc = STORE.append_op(scenario_id, op)
    except UnknownTarget as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"scenario_id": sc.scenario_id, "version": sc.version, "ops": len(sc.ops)}


@app.post("/baseline/op")
def baseline_op(req: OpRequest) -> dict[str, Any]:
    """The 'costs persist' exception — funding ops only. A schedule change here is a 400,
    which is the anti-goal 'no editing baseline directly from a drag' with a stack trace."""
    op = _to_op(req)
    try:
        version = STORE.write_baseline_op(op)
    except UnknownTarget as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"state_ref": "baseline", "version": version}


@app.post("/scenario/{scenario_id}/commit")
def commit_scenario(scenario_id: str, req: CommitRequest) -> dict[str, Any]:
    """The commit ceremony. THE ONE ROUTE THAT WRITES BASELINE FROM A SCENARIO.

    ORDER IS THE CONTRACT, and it is the reason this is a route rather than a measure:

        1. refuse a blank rationale   -- BEFORE anything is applied
        2. resolve the scenario       -- so an unknown id fails before the write too
        3. commit                     -- ops to baseline, scenario archived
        4. build the artifact         -- from a commit that has already happened

    A ceremony that refused at step 4 would have moved the plan by a decision the system
    declined to record: no artifact, no actor, no reason, and a changed baseline. Unattributable
    is worse than ungoverned, so the gate is first and the write is last.
    """
    try:
        measures.check_rationale(req.rationale)
    except measures.NotInModel as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        sc = STORE.scenario(scenario_id)
    except UnknownTarget as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ops = list(sc.ops)
    if not ops:
        raise HTTPException(
            status_code=422,
            detail=f"scenario {scenario_id!r} has no ops - a decision that disposed nothing "
                   f"is not a decision",
        )

    version = STORE.commit(scenario_id)
    artifact = measures.plan_commit_scenario(
        scenario_id=scenario_id,
        scenario_name=sc.name,
        rationale=req.rationale,
        actor=req.actor or "unknown",
        ops=ops,
        baseline_version=version,
        alternatives=req.alternatives,
        question_trail=req.question_trail,
    )
    return {"output_uri": measures.OUTPUT_URI["plan_commit_scenario"], **artifact}


@app.post("/scenario/{scenario_id}/reschedule")
def reschedule(scenario_id: str, req: RescheduleRequest) -> dict[str, Any]:
    """A drag, applied as WHAT A RESCHEDULE REALLY IS: two ops, not one.

    `MoveProject` alone moves the BAR and not the LOAD, because site-impact windows are
    deliberately independent of project windows — a rollout's disruptive phase is narrower
    than the rollout. A UI that emitted only the project move would show a schedule change
    with no site consequence, which is a demo that lies about its own model.

    So this endpoint derives BOTH and appends them separately. The ops stay ordinary and
    individually undoable; nothing is fused, and `MoveProject` still never touches an impact.
    """
    try:
        sc = STORE.scenario(scenario_id)
    except UnknownTarget as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        ops = measures.derive_reschedule(
            STORE.resolve(scenario_id),
            project_id=req.project_id,
            new_planned=Interval(req.start, req.end),
        )
    except measures.NotInModel as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for op in ops:
        sc = STORE.append_op(scenario_id, op)

    return {
        "scenario_id": sc.scenario_id,
        "version": sc.version,
        "ops_appended": len(ops),
        # NAMED, so the caller can SEE both ops landed rather than trusting a count. The
        # pre-flight check for beat 2 is exactly "were there two, and what were they".
        "ops": [type(o).__name__ for o in ops],
    }
