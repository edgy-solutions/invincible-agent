"""REASONING EFFORT ON THE SUBJECT, VERB AND SLOTS CALLS IS OFF UNLESS CONFIGURED.

Architect ruling (via Chris, 2026-11-16): the effort is a per-call setting read from
configuration, unset by default, so merging changes nothing. `IAGENT_ROUTING_EFFORT_SUBJECT`
(ClassifyDomainIntent, /resolve), `_VERB` (ClassifyPredicate, /classify_predicate) and `_SLOTS`
(FillVerbSlots, /fill_slots): low | medium | high.

Every arm drives the REAL route with the model client replaced by a recorder, then renders what the
route passed with the REAL generated BAML client (`request.<Function>`) and asserts on the HTTP
request body -- not on our own dict. Nothing here is a mock of the render.

Run: uv run pytest tests/routing/test_routing_effort_is_off_by_default.py -q -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

pytest.importorskip("rdflib")

CALLS = {"SUBJECT": "ClassifyDomainIntent", "VERB": "ClassifyPredicate", "SLOTS": "FillVerbSlots"}
VARS = [f"IAGENT_ROUTING_EFFORT_{c}" for c in CALLS]
CLASS_URI = "http://internal/sustainment/safety#SafetyCriticalItem"
VERB_IRI = "mesh:queryKnowledgeGraph"


class _Rec:
    """Stands in for engine-o's `b`: records the kwargs each routed call is made with."""

    def __init__(self):
        self.calls = {}

    async def ClassifyDomainIntent(self, **kw):  # noqa: N802
        self.calls["ClassifyDomainIntent"] = kw

        class _R:
            resolved_uri = CLASS_URI
            confidence_score = 0.9
            reasoning = ""
            instance_identifier = None
        return _R()

    async def ClassifyPredicate(self, **kw):  # noqa: N802
        self.calls["ClassifyPredicate"] = kw

        class _R:
            resolved_verb_iri = "UNKNOWN"
            confidence_score = 0.05
            reasoning = "stub"
        return _R()

    async def FillVerbSlots(self, **kw):  # noqa: N802
        self.calls["FillVerbSlots"] = kw

        class _R:
            slots_json = "{}"
            confidence = 0.9
            reasoning = "stub"
        return _R()


@pytest.fixture
def eo():
    return pytest.importorskip("agent_fleet.ontology_service.main",
                               reason="ontology_service not importable here")


@pytest.fixture
def real_raw(eo):
    """The real generated client (un-wrapped, un-configured). No stand-in is accepted."""
    inner = getattr(eo.b, "_inner", None)
    assert inner is not None and hasattr(inner, "request"), "engine-o's `b` is not the real client"
    from baml_client import b as raw  # noqa: PLC0415
    assert hasattr(raw, "request")
    return raw


@pytest.fixture
def drive(eo, monkeypatch, real_raw):
    """Run the three real routes against a recorder; return {Function: kwargs}."""
    async def _docs(request):
        return None

    async def _pool(**kw):
        return [{"uri": CLASS_URI, "label": "SafetyCriticalItem", "description": "d", "score": None}], "hybrid"

    async def _served(domains, include_referents=False):
        return frozenset({CLASS_URI})

    async def _verbs(**kw):
        return [{"verb_iri": VERB_IRI, "input_uri": CLASS_URI, "output_uri": "", "endpoint": "http://e/x",
                 "score": 0.9, "description": "a verb"}]

    monkeypatch.setattr(eo, "_resolve_docs_subject", _docs)
    monkeypatch.setattr(eo, "class_pool_with_mode", _pool)
    monkeypatch.setattr(eo, "_served_class_uris", _served)
    monkeypatch.setattr(eo, "predicate_hybrid_search", _verbs)
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", False)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: True)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", None)

    def run():
        rec = _Rec()
        monkeypatch.setattr(eo, "b", rec)
        asyncio.run(eo.resolve(eo.ResolveRequest(
            query="what failed on this part", domain="SUSTAINMENT", domains=["SUSTAINMENT"],
            user_email="bob@example.com")))
        asyncio.run(eo.classify_predicate(eo.ClassifyPredicateRequest(
            query="what failed on this part", subject_uri=CLASS_URI, subject_reasoning="r",
            entitled_domains=[], domain="SUSTAINMENT", compatible_verb_iris=[VERB_IRI])))
        asyncio.run(eo.fill_slots(eo.FillSlotsRequest(
            query="what failed on 5530-184", verb_iri="mesh:whatFailedOnThisPart",
            declarations=json.dumps([{"name": "part_number", "type": "str", "required": True}]),
            user_email="alice@example.com", acting_domains=["SUSTAINMENT"])))
        assert set(rec.calls) == set(CALLS.values()), rec.calls.keys()
        return rec.calls
    return run


async def _await(x):
    return await x if hasattr(x, "__await__") else x


def _render(raw, provider, monkeypatch, fn, kw):
    """The real client's HTTP body for the kwargs a route passed, under the engine's own registry."""
    from agent_fleet.llm_utils import init_baml_client  # noqa: PLC0415
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", provider)
    client = init_baml_client(raw)
    return asyncio.run(_await(getattr(client.request, fn)(**kw))).body.json()


def _clear(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)


def _bodies(drive, raw, provider, monkeypatch):
    calls = drive()
    return calls, {fn: _render(raw, provider, monkeypatch, fn, kw) for fn, kw in calls.items()}


# 1 -----------------------------------------------------------------------------------------------
def test_off_renders_todays_body_and_slots_passes_no_baml_options(drive, real_raw, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "ollama")
    calls, bodies = _bodies(drive, real_raw, "ollama", monkeypatch)
    for fn, body in bodies.items():
        assert "reasoning_effort" not in body, fn
    assert "baml_options" not in calls["FillVerbSlots"]
    assert set(calls["ClassifyDomainIntent"]["baml_options"]) == {"tb"}
    assert set(calls["ClassifyPredicate"]["baml_options"]) == {"tb"}


# 2 -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("which", list(CALLS))
def test_on_renders_the_effort_on_that_call_only(which, provider, drive, real_raw, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", provider)
    monkeypatch.setenv(f"IAGENT_ROUTING_EFFORT_{which}", " Low ")  # case and space are forgiven
    _, bodies = _bodies(drive, real_raw, provider, monkeypatch)
    for call, fn in CALLS.items():
        if call == which:
            assert bodies[fn].get("reasoning_effort") == "low", (call, list(bodies[fn]))
        else:
            assert "reasoning_effort" not in bodies[fn], call


# 3 -----------------------------------------------------------------------------------------------
def test_a_bad_value_is_off_with_one_warning_naming_the_variable(drive, real_raw, monkeypatch, caplog):
    _clear(monkeypatch)
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "ollama")
    monkeypatch.setenv("IAGENT_ROUTING_EFFORT_VERB", "fast")
    with caplog.at_level(logging.WARNING):
        _, bodies = _bodies(drive, real_raw, "ollama", monkeypatch)
    assert all("reasoning_effort" not in b for b in bodies.values())
    named = [r for r in caplog.records if "IAGENT_ROUTING_EFFORT_VERB" in r.getMessage()]
    assert len(named) == 1, [r.getMessage() for r in caplog.records]


# 4 -----------------------------------------------------------------------------------------------
def test_the_coalescing_key_differs_with_and_without_the_effort(eo, real_raw, monkeypatch):
    from agent_fleet.llm_utils import init_baml_client, routing_call_options  # noqa: PLC0415
    from agent_fleet.ontology_service.inflight import CoalescingClient  # noqa: PLC0415
    from baml_client.type_builder import TypeBuilder  # noqa: PLC0415
    _clear(monkeypatch)
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "ollama")
    client = CoalescingClient(init_baml_client(real_raw))

    def tb():
        t = TypeBuilder()
        t.OntologyClass.add_value(CLASS_URI)
        return t

    async def key():
        return await client._key("ClassifyDomainIntent", (), dict(
            query="q", domain="D", baml_options={"tb": tb(), **routing_call_options("SUBJECT")}))

    async def keys():
        off = await key()
        monkeypatch.setenv("IAGENT_ROUTING_EFFORT_SUBJECT", "low")
        return off, await key(), await key()

    off, on, same = asyncio.run(keys())
    assert off is not None and on is not None
    assert off != on
    assert on == same  # the key still joins identical calls


# 5 -----------------------------------------------------------------------------------------------
def _pre_refactor_init(client, provider_env):
    """REFERENCE: the body of `init_baml_client` as it was before the refactor (git 74e26cce), kept
    inline so the comparison does not depend on the code under test."""
    import os
    from baml_py import ClientRegistry
    mapping = {"openrouter": "OpenRouter", "ollama": "Ollama", "openai": "OpenAI"}
    active_client = mapping.get(provider_env, "OpenRouter")
    cr = ClientRegistry()
    cr.set_primary(active_client)
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
    ollama_model = os.getenv("OLLAMA_MODEL") or os.getenv("SMOLAGENTS_MODEL", "gpt-oss-120b")
    cr.add_llm_client(name="Ollama", provider="openai", options={
        "base_url": ollama_url, "api_key": "ollama", "model": ollama_model, "temperature": 0})
    openai_base_url = os.getenv("OPENAI_BASE_URL")
    openai_options = {"api_key": os.getenv("OPENAI_API_KEY") or "any",
                      "model": os.getenv("OPENAI_MODEL") or os.getenv("SMOLAGENTS_MODEL", "gpt-4o"),
                      "temperature": 0}
    if openai_base_url:
        openai_options["base_url"] = openai_base_url
    cr.add_llm_client(name="OpenAI", provider="openai", options=openai_options)
    cr.add_llm_client(name="MainAgent", provider="fallback", options={"strategy": [active_client]})
    return client.with_options(client_registry=cr)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_init_baml_client_renders_what_it_rendered_before(provider, drive, real_raw, monkeypatch):
    from agent_fleet.llm_utils import init_baml_client  # noqa: PLC0415
    _clear(monkeypatch)
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", provider)
    calls = drive()
    old = _pre_refactor_init(real_raw, provider)
    new = init_baml_client(real_raw)
    for fn, kw in calls.items():
        a = asyncio.run(_await(getattr(old.request, fn)(**kw))).body.json()
        b = asyncio.run(_await(getattr(new.request, fn)(**kw))).body.json()
        assert a == b, fn


@pytest.fixture(autouse=True)
def _the_caller_is_verified(monkeypatch):
    """The engine binds the VERIFIED caller, never the body's identity (lane 74); this file's
    requests name bob@example.com, so that is who the token says they are."""
    from agent_fleet.ontology_service import main as _eo_main
    from tests._helpers.verified_caller import install as _install_caller
    return _install_caller(monkeypatch, _eo_main, "bob@example.com", {"bob@example.com": ["SUSTAINMENT"], "alice@example.com": ["SUSTAINMENT"]})
