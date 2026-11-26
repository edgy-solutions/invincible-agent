"""THE GATEWAY, THE SUPERVISOR AND ENGINE O NAME NO DOMAIN A CALLER WAS NOT GIVEN (architect,
via Chris, 2026-11-24).

Scope (narrowed by the architect's ruling on #554): these three sites only. Engines N and W
still apply their own default when no domain is sent; there it is a graph label and search
filter as well as prompt text, and it is a recorded follow-up, not sealed here.

The legacy single `domain` used to default to a literal in the gateway's run config, the
supervisor's fallback and engine O's request models. A caller with no entitled domains was
therefore told, in the subject and predicate prompts, that it was classifying for a domain it
may not hold. The rule sealed here: no domain is None, and None is OMITTED -- never replaced
by a literal. Where a domain IS present, behaviour and the rendered prompts are byte-identical.

  a  render identity: both BAML prompts, domain set, equal a golden captured at the unchanged
     templates (tests/fixtures/no_legacy_domain_prompt_golden.json)
  b  domain None: the prompts name no domain at all; control: a set domain is named
  c  supervisor, no entitled domains: /resolve and /classify_predicate carry no `domain` key
  d  gateway run config carries no legacy value and validates with domain None
  e  the fan-out log names the entitled domains, never the echoed plan domain
  f  engine O request models default `domain` to None
  g  supervisor, no config domain: the /plan body carries no `domain` key; control: a set
     domain is sent exactly
  h  supervisor, a predicate with no domains: the specialist payload carries no `domain`
     key; control: the first of the predicate's domains is sent exactly
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_CLIENT = _ROOT / "baml_shared" / "baml_client"
if str(_CLIENT) not in sys.path:
    sys.path.insert(0, str(_CLIENT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

_GOLDEN = json.loads(
    (_ROOT / "tests" / "fixtures" / "no_legacy_domain_prompt_golden.json").read_text(encoding="utf-8")
)
_OLD_DEFAULT = "MAINTEN" + "ANCE"  # what the retired default was


# -- a, b: the two prompts ----------------------------------------------------

def _render(fn: str, **kw):
    from baml_client import b
    from baml_client.type_builder import TypeBuilder

    async def go():
        tb = TypeBuilder()
        if fn == "ClassifyDomainIntent":
            tb.OntologyClass.add_value("urn:x:A")
        else:
            tb.Predicate.add_value("urn:v:A")
        req = await getattr(b.request, fn)(baml_options={"tb": tb}, **kw)
        return req.body.json()["messages"]

    return asyncio.run(go())


def _intent(domain):
    return _render("ClassifyDomainIntent", query="q1", domain=domain)


def _pred(domain):
    return _render("ClassifyPredicate", query="q1", subject_uri="urn:s",
                   subject_reasoning="why", domain=domain)


@pytest.mark.parametrize("dom", ["A_DOM", _OLD_DEFAULT])
def test_a_the_subject_prompt_is_byte_identical_when_a_domain_is_set(dom):
    assert _intent(dom) == _GOLDEN[f"intent|{dom}"]


@pytest.mark.parametrize("dom", ["A_DOM", _OLD_DEFAULT])
def test_a_the_predicate_prompt_is_byte_identical_when_a_domain_is_set(dom):
    assert _pred(dom) == _GOLDEN[f"pred|{dom}"]


def _text(msgs) -> str:
    return json.dumps(msgs)


def test_b_no_domain_the_subject_prompt_names_none():
    t = _text(_intent(None))
    assert "You are a semantic classifier." in t
    assert "{{" not in t and "None" not in t and "for the" not in t


def test_b_no_domain_the_predicate_prompt_has_no_domain_heading():
    t = _text(_pred(None))
    assert "DOMAIN:" not in t and "{{" not in t and "None" not in t
    assert "GUIDANCE:" in t


def test_b_control_a_set_domain_is_named():
    assert "A_DOM" in _text(_intent("A_DOM"))
    assert "DOMAIN:" in _text(_pred("A_DOM")) and "A_DOM" in _text(_pred("A_DOM"))


# -- c: the supervisor with no entitled domains --------------------------------

class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Ctx:
    run_id = "run-1"
    log = _Log()

    def get_mapping_key(self):
        return "task_0"

    def log_event(self, ev):
        pass

    def add_output_metadata(self, *a, **k):
        pass


class _Cfg:
    user_query = "who owns the thing"
    user_persona = "PORTFOLIO_LEAD"
    user_email = ""
    trace_id = "t"
    session_id = "s"
    thread_id = "th"
    entitled_domains: list = []
    entity_refs = None
    pre_resolved = None
    predicate_fallback_score_threshold = 0.5
    slots = None
    spoken_slot = ""
    spoken_answer = ""
    bound_slots = None


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _resp(url, body):
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def wire(monkeypatch):
    """Captures the REQUEST bodies posted to engine O's /resolve and /classify_predicate."""
    seen: dict[str, dict] = {}

    def post(url, json=None, **_k):
        path = "/" + url.rsplit("/", 1)[-1]
        seen[path] = json
        if path == "/resolve":
            return _resp(url, {"resolved_uri": "mesh:Thing", "confidence_score": 0.9,
                               "reasoning": "r"})
        raise RuntimeError("stop after the payload is captured")

    monkeypatch.setattr(ds.requests, "post", post)
    monkeypatch.setattr(ds, "_resolve_serialized", lambda ctx: _Null())
    monkeypatch.setattr(ds, "_find_compatible_verbs",
                        lambda *a, **k: ([{"iri": "mesh:verb", "name": "v", "input_uri": "mesh:Thing",
                                           "domains": ["X"]}], None))
    return seen


def _drive(monkeypatch, entitled):
    """execute_subtask with `_classify_route`'s routing_domain recorded; the real function then
    runs against the doubled wire."""
    got = {}
    real = ds._classify_route

    def spy(context, query, ents, routing_domain=None, **k):
        got["routing_domain"] = routing_domain
        return real(context, query, ents, routing_domain=routing_domain, **k)

    class Cfg(_Cfg):
        entitled_domains = entitled

    monkeypatch.setattr(ds, "_classify_route", spy)
    monkeypatch.setattr(ds, "_log_subtask_route_assets", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_call_engine_a_fallback", lambda *a, **k: {"route_status": "fallback"})
    try:
        ds.execute_subtask.compute_fn.decorated_fn(_Ctx(), Cfg(), {"sub_query": "who owns the thing"})
    except BaseException:  # noqa: BLE001 -- only the captured requests matter here
        pass
    return got


def test_c_no_entitled_domains_no_domain_key_on_the_wire(wire, monkeypatch):
    got = _drive(monkeypatch, [])
    assert got["routing_domain"] is None
    assert "/resolve" in wire and "/classify_predicate" in wire
    assert "domain" not in wire["/resolve"]
    assert "domain" not in wire["/classify_predicate"]


def test_c_control_entitled_domains_name_the_first_exactly(wire, monkeypatch):
    got = _drive(monkeypatch, ["X", "Y"])
    assert got["routing_domain"] == "X"
    assert wire["/resolve"]["domain"] == "X"
    assert wire["/classify_predicate"]["domain"] == "X"


# -- d: the gateway's run config ------------------------------------------------

def test_d_the_run_config_carries_no_legacy_domain():
    from src.iagent import gateway as gw
    cfg = gw._supervisor_op_config("q", "thread-1")
    assert "domain" not in cfg
    assert _OLD_DEFAULT not in json.dumps(cfg, default=str)
    assert ds.SupervisorQueryConfig(**cfg).domain is None


def test_d_control_a_given_domain_is_carried():
    from src.iagent import gateway as gw
    assert gw._supervisor_op_config("q", "thread-1", domain="X")["domain"] == "X"


# -- e: the fan-out log -----------------------------------------------------------

def test_e_the_fan_out_log_names_entitled_domains_not_the_echo(monkeypatch, caplog):
    cfg = ds.SupervisorQueryConfig(user_query="q", thread_id="th", entitled_domains=["X"])

    plan = {"tasks": [{"target_persona": "P", "sub_query": "q"}], "domain": "ECHO_DOM",
            "extracted_concepts": []}
    monkeypatch.setattr(ds.requests, "post", lambda url, **k: _resp(url, plan))
    with caplog.at_level(logging.INFO):
        try:
            for _ in ds.create_task_plan.compute_fn.decorated_fn(_Ctx(), cfg):
                pass
        except Exception as exc:  # noqa: BLE001
            print(repr(exc))
    assert "Fanning out" in caplog.text, caplog.text
    assert "ECHO_DOM" not in caplog.text
    assert "entitled domains: ['X']" in caplog.text


# -- f: engine O's request models ---------------------------------------------------

def test_f_engine_o_request_models_default_to_no_domain():
    from agent_fleet.ontology_service import main as eo
    assert eo.PlanRequest(query="q").domain is None
    assert eo.ResolveRequest(query="q").domain is None
    assert eo.ClassifyPredicateRequest(query="q").domain is None


# -- g: the supervisor's /plan body ---------------------------------------------------

def _plan_body(monkeypatch, domain):
    """The REQUEST body `create_task_plan` posts to engine O's /plan (no precomputed plan)."""
    seen = []

    def post(url, json=None, **_k):
        seen.append((url, json))
        return _resp(url, {"tasks": [], "extracted_concepts": []})

    monkeypatch.setattr(ds.requests, "post", post)
    cfg = ds.SupervisorQueryConfig(user_query="q", thread_id="th", entitled_domains=[],
                                   domain=domain)
    list(ds.create_task_plan.compute_fn.decorated_fn(_Ctx(), cfg))
    plans = [body for url, body in seen if url == f"{ds.ONTOLOGY_SVC_URL}/plan"]
    assert len(plans) == 1, seen
    return plans[0]


@pytest.mark.parametrize("domain", [None, ""])
def test_g_no_config_domain_no_domain_key_in_the_plan_body(monkeypatch, domain):
    body = _plan_body(monkeypatch, domain)
    assert body == {"query": "q"}
    assert "domain" not in body


def test_g_control_a_config_domain_is_sent_exactly(monkeypatch):
    assert _plan_body(monkeypatch, "X") == {"query": "q", "domain": "X"}


# -- h: the specialist payload ----------------------------------------------------------

class _EngineResp:
    status_code = 200
    text = ""

    def raise_for_status(self):
        pass

    def json(self):
        return {"answer": "ok", "data": {}, "sources": []}


_ENGINE_URL = "http://engine-x.invalid/do"


def _specialist_payload(monkeypatch, predicate_domains):
    """The payload the real `execute_subtask` posts to the matched predicate's endpoint, for a
    run with no person (the service leg, so no vault redemption is involved)."""
    monkeypatch.setattr("agent_fleet.utils.service_identity.mint_supervisor_token",
                        lambda *a, **k: "svc-token", raising=False)
    predicate = {"verb_iri": "mesh:aVerb", "endpoint": _ENGINE_URL, "owner_persona": "DATA_ENGINEER",
                 "score": 0.99}
    if predicate_domains is not None:
        predicate["domains"] = predicate_domains
    monkeypatch.setattr(ds, "_classify_route",
                        lambda *a, **k: (ds._ROUTING_MATCHED, dict(predicate), {}))
    calls = []

    def post(url, json=None, **_k):
        calls.append((url, json))
        return _EngineResp()

    monkeypatch.setattr(ds.requests, "post", post)
    cfg = ds.SupervisorQueryConfig(user_query="q", user_email="", user_persona="DATA_ENGINEER",
                                   entitled_domains=["X", "Y"], thread_id="t", trace_id="tr",
                                   session_id="s")
    ds.execute_subtask.compute_fn.decorated_fn(_Ctx(), cfg, {"sub_query": "q"})
    payloads = [body for url, body in calls if url == _ENGINE_URL]
    assert len(payloads) == 1, [u for u, _ in calls]
    return payloads[0]


@pytest.mark.parametrize("predicate_domains", [[], None], ids=["empty", "missing"])
def test_h_a_predicate_with_no_domains_sends_no_domain_key(monkeypatch, predicate_domains):
    payload = _specialist_payload(monkeypatch, predicate_domains)
    assert "domain" not in payload, payload.get("domain")
    assert _OLD_DEFAULT not in json.dumps(payload, default=str)


def test_h_control_the_predicates_first_domain_is_sent_exactly(monkeypatch):
    assert _specialist_payload(monkeypatch, ["X", "Y"])["domain"] == "X"
