"""Engine S — sustainment safety assessment (ADR-0051).

WHY THIS IS A SEPARATE ENGINE AND NOT VERBS IN ENGINE O. Engine O is the SUSTAINMENT
resolver and owns `SUSTAINMENT_INSTANCES`; safety assessment is governed READING that
composes over the maintenance and product-structure planes. ADR-0035's two planes, and
ADR-0045's ruling applied a third time: analysis engines read, they do not mutate the plane
they read. Engine S does NOT register `mesh:resolveInstance` for SUSTAINMENT — that provider
exists (`ontology_service/main.py:598`) and a second one is a second truth.

THE REFUSAL THIS ENGINE IS BUILT AROUND. No verb here can accept a risk. Acceptance is a
HumanTask disposition by an entitled authority (ADR-0051 §5, §7), and seal 4 enumerates the
mesh's registered verbs to assert that none of them writes `acceptance_status = accepted`.
An engine that could accept its own drafts would make the authority ladder decorative.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import FastAPI
from pydantic import BaseModel

try:  # flat in the image (/app), packaged in the repo — runbook §5, FLAT FIRST.
    # Getting this order backwards cost Engine P a full roll: the import failed, the helper
    # became None, and twelve registrations were skipped while the engine reported healthy.
    import measures
    import slots as slots_mod
except ImportError:
    from agent_fleet.safety_agent import measures  # type: ignore[no-redef]
    from agent_fleet.safety_agent import slots as slots_mod  # type: ignore[no-redef]

SAFETY = "http://internal/sustainment/safety#"
MAINT = "http://internal/maintenance#"

# ─────────────────────────────────────────────────────────────────────────────
# THE VERB CATALOGUE — one table, read twice (runbook §3): once by registration
# and once by /verbs. Descriptions are the ROUTING SIGNAL, and the not-clauses
# are load-bearing: a verb that does not say what it is NOT gets routed to for
# the neighbouring question and answers it confidently.
# ─────────────────────────────────────────────────────────────────────────────
VERBS: List[Dict[str, Any]] = [
    {
        "fn": "find_orphaned_hazards",
        "verb": "mesh:findOrphanedHazards",
        "input_uri": SAFETY + "Hazard",
        "output_uri": SAFETY + "OrphanedHazardSet",
        "desc": (
            "Live hazards with no owned, field-verified mitigation, ranked by severity then "
            "age, each carrying WHY it is orphaned: no mitigation recorded, a mitigation with "
            "no owner, or an owner with nothing verified in the field. Answers WHAT IS OPEN "
            "AND UNATTENDED across a fleet, platform or tail. NOT an assessment of a single "
            "hazard's risk - that is draftRiskAssessment. NOT the consequence of deferring "
            "work - that is assessDeferralRisk. Hazards nobody has assessed are reported "
            "SEPARATELY and are never counted as orphans, because a missing assessment and a "
            "missing mitigation need different people. OWNS the phrasings: what hazards are "
            "unattended, which hazards have no owner, what is open and unmitigated."
        ),
        "synonyms": [
            "orphaned hazards", "hazards with no owner", "unmitigated hazards",
            "what hazards are unattended", "open hazards without a mitigation",
            "which mitigations were never verified",
        ],
        "anti_synonyms": [
            "what is the risk of deferring this work order", "assess this hazard",
            "what is the risk level", "who accepts this risk",
        ],
    },
    {
        "fn": "assess_deferral_risk",
        "verb": "mesh:assessDeferralRisk",
        "input_uri": MAINT + "WorkOrder",
        "output_uri": SAFETY + "DeferralRiskCard",
        "desc": (
            "For one deferred work order: whether its item is on the safety-critical items "
            "list, which hazard the deferral re-opens, and the DRAFTED severity and "
            "probability carried from that hazard. Answers WHAT DOES DEFERRING THIS COST. "
            "States explicitly when an item is NOT critical, naming how many critical items "
            "it was checked against, because an empty answer and a completed check are "
            "different facts. REFUSES an unknown work order rather than reporting it as "
            "not-critical - those are the same shape and opposite meanings. Resolves NO risk "
            "level and NO acceptance. OWNS the phrasings: what is the risk of deferring, can "
            "we defer this, what does this deferral re-open."
        ),
        "synonyms": [
            "risk of deferring this work order", "can we defer this",
            "what does deferring this re-open", "is this item safety critical",
        ],
        "anti_synonyms": [
            "what hazards are unattended", "list orphaned hazards",
            "accept this risk", "who signs off on this",
        ],
    },
]

BY_FN = {v["fn"]: v for v in VERBS}

#: Classes this engine registers verbs ON but does not resolve or enumerate, WITH the reason.
#:
#: `maint:WorkOrder` is the MAINTENANCE plane's, and Engine S reads work orders rather than
#: owning them. Declared rather than left implicit, because the boot guard's whole point is
#: that an input class nobody can enumerate is a verb nobody can be asked for — the symptom
#: is an elicitation offering free text where it should offer a menu, and the provider
#: answering `unsupported`, which reads to the ask as a CONSIDERED refusal rather than a gap.
_NOT_ENUMERABLE = {
    MAINT + "WorkOrder": (
        "owned by the maintenance plane; Engine S reads work orders and does not own them. "
        "Minting a safety-namespaced work-order class to make this self-consistent would be "
        "the parallel-vocabulary mistake the ADR-0007 survey avoided one level up."
    ),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Register every verb as its own predicate edge.

    ONE CALL PER VERB, per the mesh's existing idiom. Registration is opt-in via
    MESH_REGISTER_ON_STARTUP so a local run or a unit test does not need the mesh to exist.
    """
    # ── THE BOOT GUARD (runbook §8) ─────────────────────────────────────────
    # Every input class must either be enumerable by somebody, or be declared here with a
    # reason. A class that is neither is a verb that registers, passes /health, and can never
    # be asked for.
    undeclared = [
        v["input_uri"] for v in VERBS
        if not v["input_uri"].startswith(SAFETY) and v["input_uri"] not in _NOT_ENUMERABLE
    ]
    if undeclared:
        raise RuntimeError(
            "engine-safety registers verbs on classes it neither owns nor declares: "
            + ", ".join(undeclared)
            + " — add them to _NOT_ENUMERABLE with a stated reason"
        )

    if os.getenv("MESH_REGISTER_ON_STARTUP", "").lower() not in ("1", "true", "yes"):
        print("[engine-safety] MESH_REGISTER_ON_STARTUP not set — NO verbs registered")
        yield
        return

    # FLAT FIRST — see the module header.
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
        print("[engine-safety] mesh registration helper unavailable — NO verbs registered")
        yield
        return

    # The SERVICE is iagent-engine-safety. The IMAGE is safety-agent. The Keycloak client is
    # iagent-safety-agent. Three names for one engine, which is normal and is exactly why
    # grepping any one of them finds only part of the wiring (runbook §0).
    base = os.getenv("ENGINE_SAFETY_PUBLIC_URL", "http://iagent-engine-safety:8099").rstrip("/")

    # IDENTITY IS AN ARGUMENT, NEVER DERIVED FROM THE COMPONENT NAME (runbook §6). Both the
    # client id and the env var holding its secret are named HERE, at the call site. Engine P's
    # provider registration was first written with a neighbour's deployment name copied in, and
    # minting failed 401 while the verb registrations beside it succeeded — a half-registered
    # engine whose verbs route and whose resolver does not, silently.
    _mint = engine_mint(
        client_id="iagent-safety-agent",
        secret_env="ENGINE_SAFETY_CLIENT_SECRET",
    )

    registered, failed = [], []
    for v in VERBS:
        # ONE NAME PER (VERB, SUBJECT). Registering one verb twice under one name DELETES the
        # first edge — the registrar's compensate-on-rescope sweep removes rows matching
        # (tool_urn, verb_iri) whose input_uri differs from the one being written.
        name = f"engine_safety_{v['fn']}"
        try:
            register_engine_to_mesh(
                name=name,
                verb=v["verb"],
                input_uri=v["input_uri"],
                output_uri=v["output_uri"],
                endpoint=f"{base}/analyze",
                description=v["desc"],
                synonyms=v["synonyms"],
                anti_synonyms=v["anti_synonyms"],
                slots=slots_mod.slots_for(v["fn"]),
                mint=_mint,
            )
            registered.append(v["verb"])
        except Exception as exc:  # noqa: BLE001
            # NO SUCCESS LINE THAT DOES NOT CHECK SUCCESS (runbook §8). A loop that prints
            # "registered" after a call it never checked is how an engine reports healthy with
            # nothing routed.
            failed.append((v["verb"], str(exc)))
            print(f"[engine-safety] REGISTRATION FAILED {v['verb']}: {exc}")

    print(f"[engine-safety] registered {len(registered)}/{len(VERBS)} verbs")
    if failed:
        # Readiness must FAIL ON GAVE UP rather than degrade quietly.
        app.state.registration_incomplete = [v for v, _ in failed]
    yield


app = FastAPI(title="Engine S — sustainment safety", lifespan=lifespan)

# ONE IMPLEMENTATION, MOUNTED PER SERVICE. Reports the sha BAKED INTO THE IMAGE, never one a
# chart injected. REQUIRED from the first commit (runbook §7).
try:  # pragma: no cover - import path differs by runtime
    from utils.version_endpoint import mount_version as _mount_version
except ImportError:  # pragma: no cover
    from agent_fleet.utils.version_endpoint import mount_version as _mount_version
_mount_version(app, "engine-safety")


class MeasureRequest(BaseModel):
    """The envelope. `params` carries the slots; there is no state ref — Engine S reads."""

    fn: str
    params: Dict[str, Any] = {}


@app.get("/health", tags=["ops"])
async def health() -> Dict[str, Any]:
    """Liveness only.

    REPORTS A VERB COUNT AND SAYS EXPLICITLY THAT THE COUNT IS NOT PROOF OF REGISTRATION.
    Engine F's rule, and the reason is the same: a healthy engine with zero registered verbs
    is the failure mode with no symptom, and a /health that implies otherwise hides it.
    """
    return {
        "status": "ok",
        "verbs_declared": len(VERBS),
        "registration_incomplete": getattr(app.state, "registration_incomplete", None),
        "note": "verbs_declared is what this image CARRIES, not what the mesh has registered",
    }


@app.get("/verbs", tags=["ops"])
async def verbs() -> Dict[str, Any]:
    """The capability catalogue, read off the same table registration uses."""
    return {
        "verbs": [
            {
                "fn": v["fn"],
                "verb": v["verb"],
                "input_uri": v["input_uri"],
                "output_uri": v["output_uri"],
                "slots": slots_mod.slots_for(v["fn"]),
            }
            for v in VERBS
        ]
    }


@app.post("/analyze", tags=["safety"])
async def analyze(req: MeasureRequest) -> Dict[str, Any]:
    """Run one verb.

    THE REFUSAL IS BUILT FROM THE DECLARATION, which is the point: a missing mandatory slot is
    named from `slots_for`, so a signature change moves the refusal with it and a message and
    a signature that cannot disagree is the only kind that stays true.
    """
    spec = BY_FN.get(req.fn)
    if spec is None:
        return {"refused": True, "reason": f"unknown verb '{req.fn}'",
                "known": sorted(BY_FN)}

    missing = slots_mod.missing_mandatory(req.fn, req.params)
    if missing:
        return {
            "refused": True,
            "reason": "missing required slot(s)",
            "missing": [m["name"] for m in missing],
            "slots": slots_mod.slots_for(req.fn),
        }

    fn = getattr(measures, req.fn)
    result = fn(**req.params)
    result["output_uri"] = spec["output_uri"]
    # NAMES NO ARCHETYPE. The card shape is the presentation layer's decision
    # (ADR-0017); an engine that names one is deciding how it is drawn.
    return result
