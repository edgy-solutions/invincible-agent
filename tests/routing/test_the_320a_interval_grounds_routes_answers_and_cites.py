"""THE 320A VERB: "what is the inspection interval for the array module" grounds, routes, answers and cites.

THE ORDER (architect, via Chris, 2026-10-23): "plannedInspectionInterval(subject) on the maintenance
engine -- resolve the array module / platform, read the 320A planning module's interval and the
module it cites, return {interval, evidence_ref: DMC}, refuse with `no_planned_inspection` when none
is recorded. Register with its input class declared so the admission rule admits it. Seal: the ask
as atlantia grounds, routes to the verb, and renders with the citation; the refusal case; a control
that a cost ask is unaffected."

DECISIONS, AND WHY.
  * HOST = engine-o (agent_fleet/ontology_service), not Engine E. The interval lives only in Jena's
    MAINTENANCE instance graph, the graph the fault walk reads through `execute_sparql`; Engine E's
    Neo4j holds :DataModule nodes and no interval.
  * THE SPARQL IS DECLARED DATA (policy/overlays/openddil-lab/verbs/planned_inspection_interval.yaml);
    planned_inspection.py names no mil: IRI and no query text, it shapes rows.
  * INPUT CLASS = mil:PlanningInterval, the class the interval hangs on (the range of
    mil:hasPlanningInterval). The SUBJECT (array module / platform) is the verb's parameter, resolved
    inside the verb from the question's text, because no instance resolver covers mil: parts. Output
    class mesh:PlannedInspectionInterval, declared in mesh_system.ttl.
  * RENDER = the deterministic KNOWLEDGE_DOCUMENT path: an output_uri the menu cannot draw goes to
    `_render_document_deterministic`, which writes `summary` + `structured_data`; a refused body gets
    the refusal envelope. No presentation_agent change, no capabilities row.

WHAT IS REAL. engine-o's route (TestClient), the declared-query registry read from the real policy
tree, `build_selects`, `execute_sparql`'s scope wrap, `shape_selects`, the REAL `eo.resolve()`
(productive-option gate, input-declared pool, admission rule), the REAL supervisor `_classify_route`,
the REAL presentation_agent `render_ui`, the cost engine's real CATALOGUE/measures.
WHAT IS DOUBLED. The Jena transport (an rdflib Dataset holding tests/fixtures/s1000d_mrad/mrad.ttl in
MAINTENANCE_INSTANCES); and, around `resolve()`, exactly what the dead-end rig doubles: the RECALL
POOLS and VERB ROWS ARE ASSUMED -- nothing live is readable (the sandbox is frozen), so the arms cover
EACH PATH the admission rule allows rather than claim which one the live recall takes -- the served
set (`_served_class_uris`, domain-scoped, derived from the registrations), the model's pick, the
supervisor's compat-walk wire (/find_compatible_verbs, domain-scoped over the registrations) and its
/classify_predicate pick, and the menu registry in P. The dispatch body is built by hand from the
fields `dynamic_supervisor` assembles inline (there is no builder to call): user_query,
entitled_domains, user_email, resolved_instance_id, params.

Run: uv run pytest tests/routing/test_the_320a_interval_grounds_routes_answers_and_cites.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
import rdflib
import yaml
from fastapi import Response
from fastapi.testclient import TestClient
from rdflib import OWL, RDF, RDFS, URIRef

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.ontology_service import planned_inspection as pi  # noqa: E402
from tests.routing.test_a_dead_end_pool_grounds_on_the_input_the_question_names import (  # noqa: E402,F401
    MESH, SAFETY, _renderer, rig,
)
from tests.routing.test_the_router_takes_the_verb_the_input_declared_subject_carries import (  # noqa: E402,F401
    _Ctx, _Resp, sup,
)
from tests.test_engine_o_registers_when_its_stores_answer import boot, mr  # noqa: E402,F401
from tests.test_the_fault_walk_reads_through_the_domain_scope import (  # noqa: E402
    INSTANCES, SCOPE, _Jena, _dataset, _MRAD_TTL,
)

MIL = rdflib.Namespace("http://edgy-solutions.com/ontology/mil#")
VERB = pi.VERB
Q_ARRAY = "what is the inspection interval for the array module"
Q_GASKET = "what is the inspection interval for the connector gasket"
Q_FLUX = "what is the inspection interval for the flux capacitor"
Q_PLATFORM = "what is the inspection interval for the ODMRAD"
Q_COST = "how concentrated is purchasing on lot 4"


# ---------------------------------------------------------------------------- derived, never typed
def _yaml(rel):
    return yaml.safe_load((_REPO / rel).read_text(encoding="utf-8"))


def _cell_domains(user, persona):
    """The domains of the cells `persona` holds for this user, through the user's groups."""
    groups = _yaml("policy/groups.yaml")["groups"]
    return sorted({g["domain"] for name in user.get("groups", []) for g in (groups[name].get("grants") or [])
                   if g["persona"] == persona})


def _user_where(pred):
    found = [u for u in _yaml("policy/users.yaml")["users"] if pred(u)]
    assert found, "no user matches"
    return found[0]


#: operator.atlantia: the openddil-maintainers member whose display name says so; acts as MECHANIC.
ATLANTIA = _user_where(lambda u: "openddil-maintainers" in u.get("groups", [])
                       and "operator.atlantia" in u.get("display_name", ""))
ATLANTIA_ID = ATLANTIA["id"]
ATLANTIA_DOMAINS = _cell_domains(ATLANTIA, ATLANTIA["default"]["persona"])
#: a cost analyst: the first user in the cost-analysts group; acts as COST_ANALYST.
COST_USER = _user_where(lambda u: "cost-analysts" in u.get("groups", []))
COST_DOMAINS = _cell_domains(COST_USER, "COST_ANALYST")


def _mrad():
    g = rdflib.Graph()
    g.parse(str(_MRAD_TTL), format="turtle")
    return g


def _plan():
    """The fixture's ONE data module carrying mil:hasPlanningInterval, and what it cites."""
    g = _mrad()
    plans = list(g.subjects(MIL.hasPlanningInterval, None))
    assert len(plans) == 1, plans
    plan = plans[0]
    interval = g.value(plan, MIL.hasPlanningInterval)
    return {
        "evidence_ref": str(g.value(plan, RDFS.label)),
        "refers_to": sorted(str(g.value(o, RDFS.label)) for o in g.objects(plan, MIL.refersToDataModule)),
        "interval": str(g.value(interval, RDFS.label)),
    }


PLAN = _plan()
#: THE CLASS THE INTERVAL HANGS ON, read from the ontology (the range of mil:hasPlanningInterval),
#: so the arms below check the registration against it instead of echoing the registration back.
PI_CLASS = str(rdflib.Graph().parse(str(_REPO / "setup/ontologies/mil_extension.ttl"), format="turtle")
               .value(MIL.hasPlanningInterval, RDFS.range))


# ---------------------------------------------------------------------------------------- harness
@pytest.fixture
def eo(monkeypatch):
    from agent_fleet.ontology_service import main as mod
    monkeypatch.delenv("WORKFLOW_DEFINITIONS_DIR", raising=False)
    return mod


class _Calls(_Jena):
    """The Jena transport, counting how often a client was asked for."""

    def __init__(self, ds):
        super().__init__(ds)
        self.clients = 0


def _store(eo, monkeypatch, ds=None):
    jena = _Calls(ds if ds is not None else _dataset(INSTANCES))

    def client():
        jena.clients += 1
        return jena
    monkeypatch.setattr(eo, "_JENA_ENDPOINT", "http://jena/ds/query")
    monkeypatch.setattr(eo, "_jena_client", client)
    return jena


def _body(question, domains=None, email=ATLANTIA_ID, instance=""):
    """The specialist dispatch body, from the fields dynamic_supervisor assembles inline
    (src/iagent/defs/dynamic_supervisor.py, the payload at the specialist dispatch)."""
    return {"user_query": question, "params": {}, "entitled_domains": list(
        ATLANTIA_DOMAINS if domains is None else domains), "user_email": email,
        "resolved_instance_id": instance, "domain": "MAINTENANCE"}


def _ask(eo, monkeypatch, question, ds=None, domains=None):
    jena = _store(eo, monkeypatch, ds)
    r = TestClient(eo.app).post("/planned_inspection_interval", json=_body(question, domains))
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json(), jena


# ================================================================================================ V
def test_V1_the_array_module_interval_is_answered_with_the_planning_module_as_evidence(eo, monkeypatch):
    out, jena = _ask(eo, monkeypatch, Q_ARRAY)
    assert out["status"] == "answered", out
    assert out["interval"] == "180 days" == PLAN["interval"]
    assert out["evidence_ref"] == PLAN["evidence_ref"]
    assert out["refers_to"] == PLAN["refers_to"] and len(PLAN["refers_to"]) == 2
    assert out["interval"] in out["summary"] and out["evidence_ref"] in out["summary"]
    assert out["structured_data"]["evidence_ref"] == PLAN["evidence_ref"]
    # It read through the engine's scope, not around it.
    assert jena.posted and all(SCOPE in q for q in jena.posted), jena.posted


def test_V2_a_listed_part_no_planning_module_cites_is_no_planned_inspection(eo, monkeypatch):
    out, _ = _ask(eo, monkeypatch, Q_GASKET)
    assert out["status"] == "refused" and out["reason"] == "no_planned_inspection", out
    assert out["subject"] == "connector gasket"
    assert "interval" not in out and "evidence_ref" not in out


def test_V3_with_every_planning_interval_removed_the_array_module_is_no_planned_inspection(eo, monkeypatch):
    ds = _dataset(INSTANCES)
    g = ds.graph(URIRef(INSTANCES))
    lost = len(list(g.triples((None, MIL.hasPlanningInterval, None))))
    g.remove((None, MIL.hasPlanningInterval, None))
    assert lost == 1 and not list(g.triples((None, MIL.hasPlanningInterval, None)))
    out, _ = _ask(eo, monkeypatch, Q_ARRAY, ds=ds)
    assert out["status"] == "refused" and out["reason"] == "no_planned_inspection", out
    assert "interval" not in out


def test_V4_a_subject_the_manual_does_not_list_is_unknown_subject_not_no_planned_inspection(eo, monkeypatch):
    out, _ = _ask(eo, monkeypatch, Q_FLUX)
    assert out["status"] == "refused" and out["reason"] == "unknown_subject", out


def test_V5_the_platform_is_answered_with_the_same_evidence(eo, monkeypatch):
    out, _ = _ask(eo, monkeypatch, Q_PLATFORM)
    assert out["status"] == "answered", out
    assert out["interval"] == "180 days" and out["evidence_ref"] == PLAN["evidence_ref"]
    assert out["subject"] == "ODMRAD"


def test_V6_a_caller_without_MAINTENANCE_is_refused_and_the_store_is_never_read(eo, monkeypatch):
    assert "MAINTENANCE" in ATLANTIA_DOMAINS
    jena = _store(eo, monkeypatch)
    r = TestClient(eo.app).post("/planned_inspection_interval",
                                json=_body(Q_ARRAY, domains=COST_DOMAINS))
    out = r.json()
    assert "MAINTENANCE" not in COST_DOMAINS
    assert out["status"] == "refused" and out["reason"] == "not_entitled", out
    assert jena.posted == [] and jena.clients == 0


def test_V7_the_declaration_loads_from_the_real_policy_root_and_names_the_verb(eo):
    decl = eo.load_query_verbs(eo.verb_dirs(eo.policy_root()))[pi.QUERY_VERB]
    assert decl.capability == VERB and decl.domain == pi.DOMAIN
    assert pi.SELECT in decl.selects


# ================================================================================================ R
def test_R_the_registration_declares_classes_that_exist_and_the_route_it_names(eo):
    reg = eo.planned_inspection_registration()
    mil = rdflib.Graph().parse(str(_REPO / "setup/ontologies/mil_extension.ttl"), format="turtle")
    sysg = rdflib.Graph().parse(str(_REPO / "setup/ontologies/mesh_system.ttl"), format="turtle")
    inp, out = URIRef(reg["input_uri"]), URIRef(reg["output_uri"])
    assert (inp, RDF.type, OWL.Class) in mil
    # THE CLASS THE INTERVAL HANGS ON, derived: another declared class (mil#Part) would pass the line above.
    assert inp == mil.value(MIL.hasPlanningInterval, RDFS.range), reg["input_uri"]
    assert (out, RDF.type, OWL.Class) in sysg
    assert reg["verb"] == VERB and reg["domains"] == ["MAINTENANCE"]
    path = urlparse(reg["endpoint_url"]).path
    routes = [r for r in eo.app.routes if getattr(r, "path", None) == path]
    assert len(routes) == 1 and "POST" in routes[0].methods, routes
    assert routes[0].endpoint.__name__ == "planned_inspection_route"


@pytest.mark.asyncio
async def test_R_the_registration_is_gated_on_jena(boot, mr):
    eo, world = boot
    world["jena"] = False
    await world["run"]()
    assert VERB not in world["registered"]
    gate = [a for c, a in mr.armed if c == "engine_o_planned_inspection_interval:stores"]
    assert len(gate) == 1, mr.armed
    world["jena"] = True
    assert gate[0]() is True and VERB in world["registered"]


# ================================================================================================ G
def _registry(eo):
    """(verb, input_uri, output_uri, endpoint, owner, domains, description) of every verb a
    caller in this test can reach: this one, and the cost engine's, from its own CATALOGUE."""
    from agent_fleet.cost_agent import main as cost_main
    from agent_fleet.cost_agent import measures
    reg = eo.planned_inspection_registration()
    rows = [dict(verb=reg["verb"], input_uri=reg["input_uri"], output_uri=reg["output_uri"],
                 endpoint_url=reg["endpoint_url"], owner_persona=reg["owner_persona"],
                 domains=list(reg["domains"]), description=reg["description"])]
    for entry in cost_main.CATALOGUE:
        fn = entry["fn"]
        if fn not in measures.INPUT_URI:
            continue
        rows.append(dict(verb=entry["verb"], input_uri=measures.INPUT_URI[fn],
                         output_uri=measures.OUTPUT_URI[fn],
                         endpoint_url=f"http://iagent-engine-cost:8097/measure/{fn}",
                         owner_persona=cost_main.OWNER_PERSONA, domains=list(cost_main.DOMAINS),
                         description=fn))
    return rows


def _row(r, score):
    """A recalled verb row, built from a registration (never retyped)."""
    return {"verb_iri": r["verb"], "input_uri": r["input_uri"], "output_uri": r["output_uri"],
            "endpoint": r["endpoint_url"], "score": score, "description": r["description"]}


@pytest.fixture
def world(rig, eo):
    """The dead-end rig, with `_served_class_uris` domain-scoped from the registrations."""
    reg = _registry(eo)
    rig.registry = reg
    rig.planned = reg[0]
    rig.cost = {r["verb"]: r for r in reg[1:]}

    async def served(domains, include_referents=False):
        return {r["input_uri"] for r in reg if set(r["domains"]) & set(domains)}
    rig.eo._served_class_uris = served

    async def resolve(query, domains=None, email=ATLANTIA_ID):
        domains = list(ATLANTIA_DOMAINS if domains is None else domains)
        return await rig.eo.resolve(rig.eo.ResolveRequest(
            query=query, domain=domains[0], domains=domains, user_email=email))
    rig.resolve = resolve
    return rig


MIL_NS = str(MIL)
PART, CATALOG_ITEM = MIL_NS + "Part", MIL_NS + "CatalogItem"
UNSERVED = SAFETY + "SomeClassNoVerbTakes"


def _pool(world, *uris):
    world.pool = list(uris)


def test_G1_recall_holding_the_input_class_among_dead_ends_resolves_to_it(world):
    pi_uri = PI_CLASS
    _pool(world, PART, CATALOG_ITEM, pi_uri, UNSERVED)
    world.rows = [_row(world.planned, 0.9)]
    resp = asyncio.run(world.resolve(Q_ARRAY))
    assert world.baml.offered == [pi_uri], world.baml.offered
    assert resp.resolved_uri == pi_uri
    assert {e["uri"] for e in resp.excluded} >= {PART, CATALOG_ITEM, UNSERVED}


def test_G2_recall_of_only_dead_ends_is_admitted_through_the_verbs_declared_input(world):
    pi_uri = PI_CLASS
    _pool(world, PART, CATALOG_ITEM, UNSERVED)
    world.rows = [_row(world.planned, 0.9)]
    resp = asyncio.run(world.resolve(Q_ARRAY))
    assert world.baml.offered == [pi_uri], (world.baml.offered, resp.provenance)
    assert resp.resolved_uri == pi_uri
    assert {e["uri"]: e["reason"] for e in resp.excluded}.get(PART) == "input_declared_preferred"


def test_G3_control_with_no_verb_row_above_the_floor_the_class_is_not_offered(world):
    pi_uri = PI_CLASS
    _pool(world, PART, CATALOG_ITEM, UNSERVED)
    world.rows = [_row(world.planned, 0.5), _renderer(0.6)]
    resp = asyncio.run(world.resolve(Q_ARRAY))
    assert world.baml.offered is None and resp.resolved_uri != pi_uri
    assert resp.resolved_uri == "UNKNOWN"


# ================================================================================================ J
def _route(world, sup, monkeypatch, query, domains, email, pick_verb=None):
    """Real resolve() -> real _classify_route. The wire: /resolve answered by the real resolve();
    /find_compatible_verbs by the registrations (exact input_uri, domain-scoped) -- a double;
    /classify_predicate by `pick_verb` among what it was handed -- a double (the model's pick)."""
    seen = {}

    def _post(url, *a, **k):
        suffix = url.rsplit("/", 1)[-1]
        if suffix == "resolve":
            seen["resolve"] = asyncio.run(world.resolve(query, domains, email))
            return _Resp(seen["resolve"].model_dump())
        if suffix == "find_compatible_verbs":
            subject, doms = k["json"]["subject_uri"], set(k["json"].get("entitled_domains") or domains)
            seen["subject"] = subject
            return _Resp({"verbs": [
                {"verb_iri": r["verb"], "input_uri": r["input_uri"], "output_uri": r["output_uri"],
                 "endpoint_url": r["endpoint_url"], "owner_persona": r["owner_persona"],
                 "domains": r["domains"], "cost_class": "fast", "arity": "any", "slots": "[]"}
                for r in world.registry if r["input_uri"] == subject and set(r["domains"]) & doms]})
        if suffix == "classify_predicate":
            handed = list(k["json"]["compatible_verb_iris"])
            seen["handed"] = handed
            pick = pick_verb if pick_verb in handed else (handed[0] if handed and pick_verb is None else "UNKNOWN")
            return _Resp({"resolved_verb_iri": pick, "confidence_score": 0.9, "classify_called": True,
                          "candidate_verb_iris": handed})
        return _Resp({})
    monkeypatch.setattr(sup.requests, "post", _post)
    status, pred, tele = sup._classify_route(
        _Ctx(), query, list(domains), routing_domain=domains[0], user_email=email)
    return seen, status, pred, tele


@pytest.mark.parametrize("pool", ["G1", "G2"], ids=["G1-input-class-recalled", "G2-admitted-by-the-verb-row"])
def test_J_the_ask_routes_to_the_verb_at_its_registered_endpoint_and_the_dispatch_answers(
        world, sup, eo, monkeypatch, pool):
    pi_uri = PI_CLASS
    _pool(world, *([PART, CATALOG_ITEM, pi_uri, UNSERVED] if pool == "G1" else [PART, CATALOG_ITEM, UNSERVED]))
    world.rows = [_row(world.planned, 0.9)]
    seen, status, pred, tele = _route(world, sup, monkeypatch, Q_ARRAY, ATLANTIA_DOMAINS, ATLANTIA_ID)
    assert seen["subject"] == pi_uri and tele["subject_uri"] == pi_uri
    assert seen["handed"] == [VERB], seen["handed"]          # the ONLY compatible verb
    assert pred is not None and pred["verb_iri"] == VERB
    assert pred["endpoint"] == world.planned["endpoint_url"]
    # The dispatch, as the supervisor builds it, to the real route over the fixture.
    jena = _store(eo, monkeypatch)
    r = TestClient(eo.app).post(urlparse(pred["endpoint"]).path, json=_body(
        Q_ARRAY, ATLANTIA_DOMAINS, ATLANTIA_ID, instance=tele.get("subject_instance_id", "")))
    assert r.status_code == 200
    direct, _ = _ask(eo, monkeypatch, Q_ARRAY)
    assert r.json() == direct and r.json()["evidence_ref"] == PLAN["evidence_ref"]
    assert jena.posted


# ================================================================================================ P
_STUBS = ("baml_client", "baml_client.types", "baml_client.type_builder")
_PRESENTATION = "agent_fleet.presentation_agent.main"


@pytest.fixture(scope="module")
def m():
    mp = pytest.MonkeyPatch()
    for n in _STUBS:
        mp.setitem(sys.modules, n, MagicMock())
    mp.delitem(sys.modules, _PRESENTATION, raising=False)
    mod = importlib.import_module(_PRESENTATION)
    mp.setitem(sys.modules, _PRESENTATION, mod)
    try:
        yield mod
    finally:
        mp.undo()


async def _render(m, monkeypatch, body):
    # The menu cannot draw this output class: a double of the registry, the case the order relies on.
    monkeypatch.setattr(m, "_select_presentation",
                        lambda *a, **k: (None, {"presentation_source": "t", "reason": "menu cannot draw"}))
    resp = Response()
    out = await m.render_ui(m.RenderRequest(
        raw_data=[{"persona": "P", "expert_response": body}], output_uri=pi.OUTPUT_URI,
        user_persona="P"), resp)
    comps = out["components"]
    assert len(comps) == 1 and comps[0]["archetype"] == "KNOWLEDGE_DOCUMENT", comps
    return comps[0], resp.headers.get("X-Presentation-Path")


@pytest.mark.asyncio
async def test_P_the_answer_renders_as_a_document_carrying_the_interval_and_the_citation(
        m, eo, monkeypatch):
    out, _ = _ask(eo, monkeypatch, Q_ARRAY)
    m.b.DesignUI.reset_mock()
    card, path = await _render(m, monkeypatch, out)
    assert "180 days" in card["markdown_content"] and PLAN["evidence_ref"] in card["markdown_content"]
    assert path == m.PRESENTATION_PATH_DETERMINISTIC
    m.b.DesignUI.assert_not_called()
    assert m.REFUSAL_FIELD not in card


@pytest.mark.asyncio
async def test_P_the_refusal_renders_carrying_its_reason(m, eo, monkeypatch):
    out, _ = _ask(eo, monkeypatch, Q_GASKET)
    m.b.DesignUI.reset_mock()
    card, path = await _render(m, monkeypatch, out)
    assert card[m.REFUSAL_FIELD]["reason"] == "no_planned_inspection", sorted(card)
    assert path == m.PRESENTATION_PATH_DETERMINISTIC
    m.b.DesignUI.assert_not_called()


# ================================================================================================ C
def test_C_a_cost_ask_by_a_cost_caller_never_offers_nor_routes_to_the_interval_verb(world, sup, monkeypatch):
    cost = world.cost["mesh:costSupplierConcentration"]
    pi_uri = PI_CLASS
    # PlanningInterval is FIRST in recall and its verb row is present, so a gate that failed would
    # hand it to the (first-offered) model double.
    _pool(world, pi_uri, cost["input_uri"], UNSERVED)
    world.rows = [_row(cost, 0.92), _row(world.planned, 0.55)]
    seen, status, pred, tele = _route(world, sup, monkeypatch, Q_COST, COST_DOMAINS,
                                      COST_USER["id"], pick_verb="mesh:costSupplierConcentration")
    assert pi_uri not in world.baml.offered, world.baml.offered
    assert seen["resolve"].resolved_uri == cost["input_uri"]
    assert "mesh:costSupplierConcentration" in seen["handed"] and VERB not in seen["handed"]
    assert pred["verb_iri"] == "mesh:costSupplierConcentration"
    assert pred["endpoint"] == cost["endpoint_url"] and pred["verb_iri"] != VERB


def test_C_a_MAINTENANCE_only_caller_asking_the_cost_question_does_not_reach_the_interval_verb(
        world, sup, monkeypatch):
    cost = world.cost["mesh:costSupplierConcentration"]
    # Dead ends for MAINTENANCE only, plus the cost rows: the pool empties deterministically
    # (the model is never asked), so nothing here rests on a model pick.
    _pool(world, cost["input_uri"], UNSERVED)
    world.rows = [_row(cost, 0.92), _row(world.planned, 0.55)]
    seen, status, pred, tele = _route(world, sup, monkeypatch, Q_COST, ATLANTIA_DOMAINS, ATLANTIA_ID)
    assert world.baml.offered is None
    assert seen["resolve"].resolved_uri == "UNKNOWN"
    assert "handed" not in seen and "subject" not in seen   # no verb was searched, let alone chosen
    assert (pred or {}).get("verb_iri") != VERB
    assert tele.get("compatible_verb_iris") in (None, [])
