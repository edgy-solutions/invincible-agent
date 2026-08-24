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
    from seed import build_seed, check_consistency
    from state import (
        MoveProject, MoveSiteImpact, PlanStore, SetCommitment, SetCost, UnknownTarget,
    )
    from entities import Interval
except ImportError:
    from agent_fleet.planning_agent import measures
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
        from utils.mesh_registration import register_engine_to_mesh
    except ImportError:
        try:
            from agent_fleet.utils.mesh_registration import register_engine_to_mesh
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
        for v in VERBS:
            try:
                register_engine_to_mesh(
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
                )
            except Exception as exc:  # pragma: no cover
                # Best-effort, matching the fleet's existing posture: a failed registration
                # means this verb is not routable yet, NOT that the engine is down.
                print(f"[engine-p] registration failed for {v['verb']}: {exc}")
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
        "rows": rows,
    }


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
