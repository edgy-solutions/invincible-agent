"""Engine S — sustainment safety assessment (ADR-0051).

WHY THIS IS A SEPARATE ENGINE AND NOT VERBS IN ENGINE O. Engine O is the SUSTAINMENT
resolver and owns `SUSTAINMENT_INSTANCES`; safety assessment is governed READING that
composes over the maintenance and product-structure planes. ADR-0035's two planes, and
ADR-0045's ruling applied a third time: analysis engines read, they do not mutate the plane
they read. Engine S does NOT register `mesh:resolveInstance` for SUSTAINMENT — that provider
exists (`ontology_service/main.py:598`) and a second one is a second truth.

**SCOPED 2026-09-14, because the sentence above was read as broader than it is and the walk
proved it had to be.** Engine S now DOES register `mesh:resolveInstance` — for its own
`safety:` classes only. Those are two different claims and the distinction is the whole rule:
Engine O resolves SUSTAINMENT's instances and remains the only truth about them; nothing
resolved `safety:Hazard`, so "draft a risk assessment for HAZ-1003" answered *"no provider in
the mesh recognizes it"* while the identifier sat in this engine's own fixture. A SECOND
PROVIDER FOR ONE CLASS IS A SECOND TRUTH; A FIRST PROVIDER FOR AN UNCLAIMED CLASS IS THE
ABSENCE BEING FIXED. `maint:WorkOrder` is deliberately left unclaimed for exactly this reason —
see `instances.py`, where the open scope question is written down rather than answered by
convenience.

THE REFUSAL THIS ENGINE IS BUILT AROUND. No verb here can accept a risk. Acceptance is a
HumanTask disposition by an entitled authority (ADR-0051 §5, §7), and seal 4 enumerates the
mesh's registered verbs to assert that none of them writes `acceptance_status = accepted`.
An engine that could accept its own drafts would make the authority ladder decorative.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# TRANSPORT AUTH IS A BIRTH RULE (runbook §6), and this engine was born without it until the
# fleet-wide seals said so. OBSERVE posture: accept whatever arrives, log the caller posture per
# request, refuse nothing until REQUIRE_TRANSPORT_AUTH flips. The ANNOUNCEMENT is separate and
# equally required — an engine that takes the dependency but loses the announcement has a real
# posture the fleet gauge cannot read, which is a correct engine that reports as unknown.
#
# `app_docs_kwargs()` turns /docs, /redoc and /openapi.json off in deployment. It is NOT
# cosmetic: FastAPI registers those through Starlette's `add_route`, so an app-level
# `dependencies=` NEVER REACHES THEM — they would be served unauthenticated even under REQUIRE.
# That is the Starlette-bypass class, and it is why the kwargs are a separate call rather than
# something the dependency covers.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth

COMPONENT = "engine-safety"

try:  # flat in the image (/app), packaged in the repo — runbook §5, FLAT FIRST.
    # Getting this order backwards cost Engine P a full roll: the import failed, the helper
    # became None, and twelve registrations were skipped while the engine reported healthy.
    import instances as instances_mod
    import measures
    import slots as slots_mod
except ImportError:
    from agent_fleet.safety_agent import instances as instances_mod  # type: ignore[no-redef]
    from agent_fleet.safety_agent import measures  # type: ignore[no-redef]
    from agent_fleet.safety_agent import slots as slots_mod  # type: ignore[no-redef]

SAFETY = "http://internal/sustainment/safety#"
MESH = "http://invincible-agent/mesh#"

# ── THE WORK-ORDER SUBJECT IS THE STANDARD'S CLASS, NOT A HOUSE SYNONYM ──────
#
# `assessDeferralRisk` declared `maint:WorkOrder` — `http://internal/maintenance#WorkOrder` —
# and Contract D refused the registration 422, `missing: [that IRI]`, because NO TTL
# ANYWHERE DECLARES IT. The fix is not to author it: `mro:MaintenanceWorkOrder` already
# exists (`agent_fleet/ontology_service/iof_mro.ttl:32`) under the IOF Maintenance Reference
# Ontology, and ADR-0007's survey-before-mint answers the rest — minting a house synonym for
# a class the standard already names forfeits the citation and creates a second truth about
# one thing.
#
# SAME RULING `product_structure_extension.ttl` MADE FOR S3000L: the standard's own names
# where the standard covers the need, house convention only where it does not and labelled
# as such. A cited-but-invented IRI is worse than an empty slot.
#
# ⚠️ THIS IRI IS DECLARED ON DISK AND IS NOT IN THE PRIME MANIFEST (verified: zero matches
# for `iof_mro` in `setup/prime_databases.py`). A TTL on disk and absent from the manifest is
# UNDECLARED AT A FRESH CLUSTER — seal 1's whole lesson, and the `mesh:proposeDisposition`
# failure exactly: sandbox had the node, every fresh cluster did not, and the registrar
# refused the edge forever. So this registration still 422s until the eo lane lands
# `iof_mro.ttl` in the manifest. Changing the IRI here is necessary and NOT sufficient, and
# saying so is the difference between a fix and a fix that looks finished.
MRO = "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/"

# ─────────────────────────────────────────────────────────────────────────────
# THE ENGINE'S SCOPE — and these two names must EXIST IN THE POLICY VOCABULARIES,
# which is a coupling nothing in the suite checked until 2026-09-14.
#
# `DOMAINS` is the one that gates. `/find_compatible_verbs` intersects a verb's
# domains with the caller's entitled domains and SKIPS the check entirely when a
# verb declares none — so omitting this makes an engine's verbs visible to every
# caller in the fleet, silently, with a shorter call as the only tell.
#
# `OWNER_PERSONA` does NOT gate: src/iagent/auth.py flattens entitlements to
# `{c.domain for c in cells}` and the persona half never reaches a filter. It is
# the answering VOICE, and it is set because an answer should say who is speaking.
#
# BOTH must appear in policy/personas.yaml and policy/domains.yaml or the sync
# refuses every group grant naming them — which is exactly how engine-cost's
# COST_ANALYST was caught, and it is caught only INDIRECTLY, once somebody writes
# the grant. `tests/safety/test_engine_scope_exists_in_policy.py` makes it direct.
# ─────────────────────────────────────────────────────────────────────────────
OWNER_PERSONA = "SAFETY_ENGINEER"
DOMAINS = ["SUSTAINMENT"]

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
        "input_uri": MRO + "MaintenanceWorkOrder",
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
    {
        "fn": "draft_risk_assessment",
        "verb": "mesh:draftRiskAssessment",
        "input_uri": SAFETY + "Hazard",
        "output_uri": SAFETY + "RiskAssessmentDraft",
        "desc": (
            "A DRAFTED severity and probability statement over one hazard, with a citation for "
            "every figure, the risk level resolved from the ratified matrix, and the acceptance "
            "authority that level implies. Answers WHAT IS THE RISK and WHO HAS TO ACCEPT IT. "
            "DRAFTS ONLY - it cannot accept, reject or close anything; acceptance is a human "
            "task disposition by an entitled authority and this verb opens that review rather "
            "than resolving it. A hazard whose severity or probability is not assessed is "
            "reported as not_assessed with the missing half named, never inferred from a "
            "neighbour and never defaulted. NOT a list of what is unattended - that is "
            "findOrphanedHazards. OWNS the phrasings: assess this hazard, what is the risk "
            "level, who has to accept this, draft the risk assessment."
        ),
        "synonyms": [
            "assess this hazard", "what is the risk level", "draft a risk assessment",
            "who has to accept this risk", "what authority accepts this",
        ],
        "anti_synonyms": [
            "accept this risk", "sign off on this hazard", "close this hazard",
            "what hazards are unattended", "can we defer this work order",
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
    MRO + "MaintenanceWorkOrder": (
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

    attempted, failed = [], []
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
                # THREE PARAMETER NAMES WERE WRONG, SO EVERY REGISTRATION RAISED TypeError.
                # `endpoint=`, `synonyms=`, `anti_synonyms=` are not this function's parameters;
                # it is keyword-only with no **kwargs, so the call could never bind —
                # `TypeError: missing a required argument: 'endpoint_url'`. The handler below
                # caught all three and the engine reported `registered 0/3` +
                # `registration_incomplete`, which is that loop doing exactly its job. Nothing
                # was silently wrong; nothing was registered either, which is why the safety
                # verbs are absent from the verb census.
                # ONE ENDPOINT PER VERB, matching cost and finance. This read `{base}/analyze`
                # — a single body-dispatched route — and the registrar BAKES `endpoint_url`
                # into the mesh PER VERB, so all three safety verbs carried the same URL and
                # the mesh had no way to reach one rather than another. The dispatcher puts the
                # verb in the PATH and sends no `fn`, so every dispatch arrived as a 422 on a
                # field the caller had no reason to send.
                endpoint_url=f"{base}/measure/{v['fn']}",
                description=v["desc"],
                verb_synonyms=v["synonyms"],
                verb_anti_synonyms=v["anti_synonyms"],
                # ── THE REGISTRATION CARRIED NO SCOPE AT ALL, AND THAT IS THE WORSE HALF ──
                #
                # Both of these defaulted to None, and a verb with NO domains is DOMAIN-AGNOSTIC:
                # `/find_compatible_verbs` skips the entitlement intersection entirely for a verb
                # that declares none, so all three safety verbs would have been visible to EVERY
                # caller in the fleet. The opposite of the gate ADR-0051 §5 rests on, arriving
                # through an OMITTED argument rather than a wrong one — which is the harder half
                # to see, because a missing kwarg looks like a shorter call.
                #
                # THIS IS WHY THE `safety-engineers` CELL GRANTS NOTHING WITHOUT THIS LINE. A cell
                # admits a caller only once the verbs declare the domain that cell carries; until
                # then its ABSENCE excludes nobody either, which is a grant that passes readback
                # and means nothing — the shape policy/groups.yaml warns about in its own header.
                #
                # `owner_persona` is the answering VOICE, not a filter: src/iagent/auth.py
                # flattens entitlements to `{c.domain for c in cells}` and discards the persona
                # half before any verb filter runs. Set so the answer says who is speaking.
                owner_persona=OWNER_PERSONA,
                domains=DOMAINS,
                slots=slots_mod.slots_for(v["fn"]),
                mint=_mint,
            )
            attempted.append(v["verb"])
        except Exception as exc:  # noqa: BLE001
            # NO SUCCESS LINE THAT DOES NOT CHECK SUCCESS (runbook §8). A loop that prints
            # "registered" after a call it never checked is how an engine reports healthy with
            # nothing routed.
            failed.append((v["verb"], str(exc)))
            print(f"[engine-safety] REGISTRATION FAILED {v['verb']}: {exc}")

    # ── THE INSTANCE PROVIDERS (ADR-0031), ADDED 2026-09-14 AFTER THE WALK STOPPED ON THEM ──
    #
    # A SCOPE RULE NEEDS SOMETHING TO PREFER — engine-cost's sentence, and the same argument
    # applies here for the same reason. Until these rows exist, `HAZ-1003` is a name no provider
    # claims: the ask falls to General search and ends in an unrelated refusal, which is what the
    # walk measured. Registering them gives the resolver a correct claim to prefer over a
    # phone-book hit from some engine matching a digit.
    provider_specs = (
        {
            "name": "engine_safety_sustainment_resolve_instance",
            "verb": "mesh:resolveInstance",
            "input_uri": MESH + "InstanceIdentifier",
            "output_uri": MESH + "InstanceResolution",
            "endpoint_url": f"{base}/resolve_instance",
            "synonyms": ["which hazard", "which critical item", "which write-up",
                         "resolve hazard", "look up hazard by name"],
            "description": (
                "Resolves a spoken safety name — a hazard, a safety-critical item or a "
                "write-up — to its identifier in the safety model, by exact match then "
                "contained phrase then token overlap. Returns candidates with class URI, "
                "label and score, highest first. An empty list is a first-class answer: the "
                "provider abstains below its floor rather than offering a least-bad match, "
                "because a wrong instance resolved confidently makes the verb answer about "
                "the wrong subject. A BARE NUMBER IS NOT A NAME here: `1003` does not resolve "
                "to HAZ-1003, because a provider that claims every digit in the fleet "
                "displaces every rival's correct answer. Resolves SAFETY classes only — work "
                "orders belong to the maintenance plane and are deliberately not claimed."
            ),
        },
        {
            "name": "engine_safety_sustainment_enumerate_instances",
            "verb": "mesh:enumerateInstances",
            "input_uri": MESH + "InstanceClass",
            "output_uri": MESH + "InstanceEnumeration",
            "endpoint_url": f"{base}/enumerate_instances",
            "synonyms": ["which hazards", "list critical items", "what write-ups",
                         "show me the hazards", "enumerate hazards"],
            "description": (
                "Lists the members of a safety class — hazards, safety-critical items, "
                "write-ups — so an elicitation can offer a menu for a slot the speaker never "
                "filled. Answers with one of three NAMED outcomes: members, too_many (the "
                "class is real and larger than a menu, with its count), or unsupported (this "
                "provider does not hold that class, with the list of classes it does). "
                "`unsupported` is never spelled as an empty member list: a class nobody here "
                "holds and a class held with zero members are different facts, and collapsing "
                "them offers 'no options' for a question this engine was never asked."
            ),
        },
    )
    for spec in provider_specs:
        try:
            register_engine_to_mesh(
                name=spec["name"],
                verb=spec["verb"],
                input_uri=spec["input_uri"],
                output_uri=spec["output_uri"],
                endpoint_url=spec["endpoint_url"],
                description=spec["description"],
                verb_synonyms=spec["synonyms"],
                owner_persona=OWNER_PERSONA,
                domains=DOMAINS,
                mint=_mint,
            )
            attempted.append(spec["verb"])
        except Exception as exc:  # noqa: BLE001
            failed.append((spec["verb"], str(exc)))
            print(f"[engine-safety] REGISTRATION FAILED {spec['verb']}: {exc}")

    # ── THIS SAYS "ATTEMPTED", NOT "REGISTERED", AND THE DIFFERENCE WAS MEASURED ────────
    #
    # The line here used to read `registered {n}/{len(VERBS)}` and it COULD NOT FAIL.
    # `register_engine_to_mesh` catches its own emit failure, logs "⚠️ Failed to register
    # engine ... Engine will keep serving", and RETURNS NORMALLY — so the `except` above never
    # fires for the failure that actually matters and the counter increments on a call that
    # reached nothing.
    #
    # MEASURED 2026-09-14 rather than reasoned about: run against a dead GMS port, this engine
    # printed three emit warnings and then `registered 3/3 verbs`, with
    # `registration_incomplete: None` on /health. A healthy pod, an honest-looking count, and
    # zero verbs in the mesh — precisely the state runbook §8 exists to prevent, arriving
    # through the CALLEE rather than the caller. The comment in the handler above is true
    # about the code it guards and false about the outcome, which is how it survived review.
    #
    # NOT A SAFETY-ENGINE DEFECT: the helper is shared by eleven engines and every one counts
    # the same way. Reported rather than fixed here, because making `register_engine_to_mesh`
    # signal success is a contract change across the fleet and a shared mechanism is not
    # re-specified by its newest caller. What IS mine is declining to print a word I cannot
    # support — the count is of ATTEMPTS, which is exactly what this loop can observe.
    print(
        # THE DENOMINATOR COUNTS THE PROVIDER ROWS TOO. It read `len(VERBS)` and the two
        # instance providers pushed the numerator past it — "5/3", a count that is wrong in the
        # direction that looks like success. Derived from both populations rather than a literal,
        # so a row added to either is counted without an edit here.
        f"[engine-safety] registration ATTEMPTED for "
        f"{len(attempted)}/{len(VERBS) + len(provider_specs)} registrations "
        "(the helper does not report emit success — read the mesh census for what landed)"
    )
    if failed:
        # Readiness must FAIL ON GAVE UP rather than degrade quietly.
        app.state.registration_incomplete = [v for v, _ in failed]
    yield


_announce_transport_auth(component=COMPONENT)

app = FastAPI(
    lifespan=lifespan,
    **_docs_kwargs(),   # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth(COMPONENT))],
    title="engine-safety — sustainment safety assessment",
    description=(
        "Governed reading over the SUSTAINMENT plane (ADR-0051). Drafts risk assessments "
        "against MIL-STD-882E Table III and CANNOT accept one — acceptance is a human task "
        "disposition by the authority the ratified ladder names."
    ),
)

# ONE IMPLEMENTATION, MOUNTED PER SERVICE. Reports the sha BAKED INTO THE IMAGE, never one a
# chart injected. REQUIRED from the first commit (runbook §7).
try:  # pragma: no cover - import path differs by runtime
    from utils.version_endpoint import mount_version as _mount_version
except ImportError:  # pragma: no cover
    from agent_fleet.utils.version_endpoint import mount_version as _mount_version
_mount_version(app, "engine-safety")


class MeasureRequest(BaseModel):
    """A dispatched verb call. `params` carries the declared slots, nothing else.

    ⛔ `fn` WAS A REQUIRED FIELD HERE AND IT MADE EVERY SAFETY VERB UNCALLABLE. This engine
    registered ONE endpoint (`/analyze`) and expected the verb in the envelope; the fleet's
    dispatcher puts the verb in the URL PATH and sends `{"query", "params"}` with no `fn`. So
    every dispatch arrived as a 422 — `{"type":"missing","loc":["body","fn"]}` — replayed
    against the pod on 2026-09-14.

    THE DIVERGENCE WAS THE ENDPOINT SHAPE, NOT A MISSING FIELD IN THE SUPERVISOR:

        cost_agent      endpoint_url = f"{base}/measure/{fn_name}"   verb in the PATH
        finance_agent   endpoint_url = f"{base}/measure/{v['fn']}"   verb in the PATH
        safety_agent    endpoint_url = f"{base}/analyze"             verb in the BODY  <- mine

    engine-cost's own comment gives the affirmative argument I should have read at birth: ONE
    ENDPOINT PER VERB, because the registrar BAKES `endpoint_url` into the mesh per verb, so a
    single body-dispatched route gives every verb the same URL and the mesh has no way to reach
    one rather than another. `/analyze` was not load-bearing for anything — `BY_FN` dispatched
    inside it — so this moves to the fleet shape rather than asking the fleet to learn a second
    one. Copied field-for-field from cost rather than re-derived: the contract's whole value is
    that the engines agree.
    """

    params: Dict[str, Any] = {}
    #: Sent by the dispatcher and unused here — accepted so the envelope round-trips rather than
    #: 422ing on a field the caller legitimately supplies. Engine S measures from slots only.
    query: str = ""


class ResolveRequest(BaseModel):
    """The mesh's resolveInstance request. THE FIELD IS `identifier`, NOT `text`.

    ⛔ COPIED FIELD-FOR-FIELD FROM THE PROVIDERS THAT ALREADY WORK, not re-derived. Engine F
    shipped this model requiring `text`, registered correctly as a `mesh:resolveInstance`
    provider, and was UNCALLABLE BY ONE: Engine O's fan-out sends `{"identifier", "query"}`, so
    every real call was a 422 while the graph said the provider was registered, by name, at the
    right endpoint. Registered is not participating — a registration describes an edge and says
    nothing about the payload the consumer actually sends. The contract's whole value is that
    the providers agree, so agreement beats elegance here.
    """

    identifier: str = ""
    query: str = ""
    class_uri: Optional[str] = None


class EnumerateRequest(BaseModel):
    class_uri: str
    #: 25, MATCHING engine-cost's CORRECTED DEFAULT rather than the fleet's invented 8.
    #:
    #: That 8 was never a caller's judgement about what fits — the caller OMITS the limit, so
    #: each provider's own default applies, and three providers inventing 8 separately is not a
    #: fleet default, it is the same guess made three times. It put "9 exist" on a card beside an
    #: EMPTY menu, because nine members against a bound of eight answers `too_many`: a refusal
    #: designed to protect an ask became the reason the ask had nothing to show.
    #:
    #: A provider knows its own cardinality where the caller cannot. This engine's largest class
    #: is well under 25, so the bound has headroom and `too_many` stays reserved for a class that
    #: is genuinely larger than a menu. The durable fix is the disposition SENDING the limit it
    #: can render, at which point this default stops mattering.
    limit: int = 25


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


@app.post("/resolve_instance", tags=["safety"])
async def resolve_instance(req: ResolveRequest) -> Dict[str, Any]:
    """Resolve a spoken safety name to an identifier in this engine's model."""
    return {
        "output_uri": MESH + "InstanceResolution",
        "query": req.identifier,
        "candidates": instances_mod.resolve(req.identifier, req.class_uri),
        "provider": "engine_safety_sustainment",
    }


@app.post("/enumerate_instances", tags=["safety"])
async def enumerate_instances(req: EnumerateRequest) -> Dict[str, Any]:
    """List the members of a safety class, or refuse in one of two NAMED ways."""
    return instances_mod.enumerate_class(req.class_uri, req.limit)


@app.post("/measure/{fn_name}", tags=["safety"])
async def measure(fn_name: str, req: MeasureRequest) -> Dict[str, Any]:
    """Run one verb.

    THE REFUSAL IS BUILT FROM THE DECLARATION, which is the point: a missing mandatory slot is
    named from `slots_for`, so a signature change moves the refusal with it and a message and
    a signature that cannot disagree is the only kind that stays true.
    """
    spec = BY_FN.get(fn_name)
    if spec is None:
        return {"refused": True, "reason": f"unknown verb '{fn_name}'",
                "known": sorted(BY_FN)}

    fn = getattr(measures, fn_name)

    # ── AN UNEXPECTED KEY IS A 422 NAMING THE ARGUMENT, NEVER A 500 ─────────────────────────
    #
    # `fn(**req.params)` unfiltered raises `TypeError: got an unexpected keyword argument` for
    # ANY key the caller adds, and FastAPI turns that into a 500 with no body. MEASURED against
    # this engine before the guard: `{"subject": "safety:Hazard"}` and `{"hazard_id": "HAZ-1003"}`
    # each killed the call on arrival — and a 500 with no body is indistinguishable, from the
    # surface, from the blank card a missing rendering produces. Two unrelated defects with one
    # symptom is how an afternoon goes.
    #
    # THE GATEWAY'S `accept_slots` PROJECTION IS SUPPOSED TO STOP THIS UPSTREAM, and this guard
    # exists anyway: an engine that dies on an unexpected kwarg is trusting a caller it cannot
    # see. Belt and braces — the same posture the safety task kinds take by keeping `accepted`
    # in the global verb set until the cutover reads rows.
    #
    # THE REFUSAL IS BUILT FROM THE SIGNATURE, not from a hand-kept list, so a slot added to a
    # measure is accepted here the moment it exists and a slot removed stops being accepted in
    # the same edit. A hand-written allowlist would be a second declaration of the signature,
    # and the two would disagree on the first change.
    import inspect

    params = inspect.signature(fn).parameters.values()
    accepted = {
        p.name for p in params if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
    # A MEASURE DECLARING `**kwargs` ACCEPTS ANYTHING, AND THE GUARD MUST SAY SO. Without this
    # the check refuses every key for such a function, because its named set is empty — an
    # over-constrained guard failing HONEST data, which is the kind that gets deleted rather
    # than fixed. No measure takes `**kwargs` today; the seal's own stub does, and that is how
    # this surfaced: the guard answered 422 to a call it had no business refusing.
    takes_any = any(p.kind is p.VAR_KEYWORD for p in params)
    unexpected = [] if takes_any else sorted(set(req.params) - accepted)
    if unexpected:
        return JSONResponse(
            status_code=422,
            content={
                "refused": True,
                "reason": f"{fn_name} does not accept {', '.join(unexpected)}",
                "unexpected": unexpected,
                # WHAT IT *DOES* ACCEPT, from the declaration — a refusal that names only what
                # was wrong makes the caller guess at what would be right.
                "accepts": sorted(accepted - {"state"}),
                "slots": slots_mod.slots_for(fn_name),
            },
        )

    # ── THE MANDATORY-SLOT REFUSAL RUNS *AFTER* THE UNEXPECTED-KEY ONE, DELIBERATELY ────────
    #
    # It used to run first, and the ordering hid the more diagnostic answer: a caller sending
    # `hazard_id` to a verb whose slot is `work_order_id` got back "missing required slot(s)"
    # and no mention of the key it DID send. The seal caught it — `assess_deferral_risk`
    # answered 200 to an unexpected key because its mandatory slot was absent in the same call.
    #
    # An unexpected key means the caller's model of this verb is wrong, which usually EXPLAINS
    # the missing slot rather than being a second independent fault. Naming the wrong key first
    # answers both; naming the missing slot first answers neither.
    missing = slots_mod.missing_mandatory(fn_name, req.params)
    if missing:
        return {
            "refused": True,
            "reason": "missing required slot(s)",
            "missing": [m["name"] for m in missing],
            "slots": slots_mod.slots_for(fn_name),
        }

    # ── AND NO MEASURE MAY DIE WITHOUT WRITING A RESPONSE ───────────────────────────────────
    #
    # The guard above stops the ONE exception we found. This stops the CLASS. An unhandled
    # exception in this handler produces no body, and from the caller's side that is
    # indistinguishable from an engine that is merely slow — 58 seconds of learning nothing
    # that 5 milliseconds could have told it. The artifact reads FAILED with 0 bytes and points
    # at the dispatch, which is the one place the cause is not.
    #
    # NOT A BARE `except` AROUND EVERYTHING: the refusals above are DECIDED answers and return
    # normally. This wraps only the measure call, so a bug inside a measure is reported as a
    # bug inside that measure, by name, with the params that reached it.
    try:
        result = fn(**req.params)
    except Exception as exc:  # noqa: BLE001
        # ── A REFUSAL IS NEVER A 5xx, AND THIS ONE WAS ──────────────────────────────────────
        #
        # This returned `status_code=500` with the honest body above it. THE BODY WAS CORRECT AND
        # NOBODY READ IT: the supervisor discards a 5xx unread, so the engine wrote a precise
        # cause — `FileNotFoundError: /app/safety_risk_matrix.ttl` — into a response that was
        # thrown away, and the walk reported a failure with no reason. **A diagnosis carried on a
        # status code the caller drops is the same as no diagnosis**, which is the defect the
        # honest body was written to end, arriving one field along.
        #
        # 200 WITH `refused: true`, matching engine-cost's `_refusal`: the transport succeeded —
        # the engine received the call, decided, and answered — and the OUTCOME lives in the body
        # where a composing verb reads it. The status code describes the HTTP exchange; the body
        # describes the verb. Conflating them is what made a 5xx look like the honest choice.
        #
        # AND THE DISCRIMINANT IS A FIELD, NOT A MESSAGE. `outcome: "engine_fault"` sits beside
        # the three ADR-0049 states a composing verb must tell apart, so a consumer branches on a
        # value and never parses prose. This one says the engine broke rather than the question
        # being unanswerable — a distinction the caller cannot make from a reason string.
        return JSONResponse(
            status_code=200,
            content={
                "refused": True,
                "outcome": "engine_fault",
                "reason": f"{fn_name} raised {type(exc).__name__}: {exc}",
                "fn": fn_name,
                # THE PARAMS AS RECEIVED, because the first question about a failed dispatch is
                # always "what did it actually get sent" and the answer has been unavailable
                # every time it has been asked.
                "params_received": sorted(req.params),
            },
        )

    result["output_uri"] = spec["output_uri"]
    # NAMES NO ARCHETYPE. The card shape is the presentation layer's decision
    # (ADR-0017); an engine that names one is deciding how it is drawn.
    return result
