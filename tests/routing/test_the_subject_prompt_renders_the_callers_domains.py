"""THE SUBJECT PROMPT RENDERS THE CALLER'S OWN DOMAINS ONLY WHEN CONFIGURED.

`IAGENT_SUBJECT_PROMPT_DOMAINS=caller` makes /resolve hand ClassifyDomainIntent the verified
caller's bound grant (sorted, de-duplicated) instead of the single legacy `domain`. Unset, empty
or any other value is OFF and byte-identical to today.

Each arm drives the REAL /resolve route with the model client replaced by a recorder, then renders
what the route passed with the REAL generated BAML client and asserts on the rendered prompt text.

Run: uv run pytest tests/routing/test_the_subject_prompt_renders_the_callers_domains.py -q -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

pytest.importorskip("rdflib")

VAR = "IAGENT_SUBJECT_PROMPT_DOMAINS"
CLASS_URI = "http://internal/sustainment/safety#SafetyCriticalItem"
LEGACY = "SUSTAINMENT"
GRANT = ["B_DOM", "A_DOM", "B_DOM"]


class _Rec:
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


@pytest.fixture
def eo():
    return pytest.importorskip("agent_fleet.ontology_service.main",
                               reason="ontology_service not importable here")


@pytest.fixture
def real_raw(eo):
    inner = getattr(eo.b, "_inner", None)
    assert inner is not None and hasattr(inner, "request"), "engine-o's `b` is not the real client"
    from baml_client import b as raw  # noqa: PLC0415
    assert hasattr(raw, "request")
    return raw


@pytest.fixture(autouse=True)
def _the_caller_is_verified(monkeypatch, eo):
    """The verified caller holds GRANT; the request body claims something else."""
    from tests._helpers.verified_caller import install  # noqa: PLC0415
    return install(monkeypatch, eo, "bob@example.com", {"bob@example.com": GRANT})


@pytest.fixture
def drive(eo, monkeypatch, real_raw):
    """Run the real /resolve against a recorder; return (model kwargs, recall kwargs)."""
    recall = []

    async def _docs(request):
        return None

    async def _pool(**kw):
        recall.append(kw)
        return [{"uri": CLASS_URI, "label": "SafetyCriticalItem", "description": "d", "score": None}], "hybrid"

    async def _served(domains, include_referents=False):
        return frozenset({CLASS_URI})

    monkeypatch.setattr(eo, "_resolve_docs_subject", _docs)
    monkeypatch.setattr(eo, "class_pool_with_mode", _pool)
    monkeypatch.setattr(eo, "_served_class_uris", _served)
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", False)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: True)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", None)

    def run():
        recall.clear()
        rec = _Rec()
        monkeypatch.setattr(eo, "b", rec)
        asyncio.run(eo.resolve(eo.ResolveRequest(
            query="what failed on this part", domain=LEGACY, domains=GRANT + ["BODY_DOM"],
            user_email="bob@example.com")))
        assert set(rec.calls) == {"ClassifyDomainIntent"}, rec.calls.keys()
        return rec.calls["ClassifyDomainIntent"], [dict(k) for k in recall]
    return run


async def _await(x):
    return await x if hasattr(x, "__await__") else x


def _render(raw, monkeypatch, kw) -> str:
    from agent_fleet.llm_utils import init_baml_client  # noqa: PLC0415
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "ollama")
    client = init_baml_client(raw)
    body = asyncio.run(_await(client.request.ClassifyDomainIntent(**kw))).body.json()
    return json.dumps(body, sort_keys=True)



# 1 -----------------------------------------------------------------------------------------------
def test_off_renders_the_legacy_domain_and_empty_equals_unset(drive, real_raw, monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    kw, _ = drive()
    assert kw["domain"] == LEGACY
    unset = _render(real_raw, monkeypatch, kw)
    assert f"for the {LEGACY} domain" in unset
    monkeypatch.setenv(VAR, "")
    kw2, _ = drive()
    assert _render(real_raw, monkeypatch, kw2) == unset


# 2 -----------------------------------------------------------------------------------------------
def test_on_renders_the_bound_grant_sorted_and_deduplicated(drive, real_raw, monkeypatch):
    monkeypatch.setenv(VAR, " Caller ")  # case and space are forgiven
    kw, _ = drive()
    text = _render(real_raw, monkeypatch, kw)
    assert "for the A_DOM, B_DOM domain" in text
    assert f"for the {LEGACY} domain" not in text
    assert "BODY_DOM" not in text  # bound = body ∩ grant: the extra asked-for domain is gone


# 3 -----------------------------------------------------------------------------------------------
def test_a_bad_value_is_off_with_one_warning_naming_the_variable(drive, real_raw, monkeypatch, caplog):
    monkeypatch.setenv(VAR, "yes")
    with caplog.at_level(logging.WARNING):
        kw, _ = drive()
    assert kw["domain"] == LEGACY
    assert f"for the {LEGACY} domain" in _render(real_raw, monkeypatch, kw)
    named = [r for r in caplog.records if VAR in r.getMessage()]
    assert len(named) == 1, [r.getMessage() for r in caplog.records]


# 4 -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("domains", [[], None, ["", ""]])
def test_on_with_no_domains_returns_the_domain(eo, monkeypatch, domains):
    monkeypatch.setenv(VAR, "caller")
    assert eo.subject_prompt_domain(LEGACY, domains) == LEGACY


def test_unit_off_and_on(eo, monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    assert eo.subject_prompt_domain(LEGACY, GRANT) == LEGACY
    monkeypatch.setenv(VAR, "caller")
    assert eo.subject_prompt_domain(LEGACY, GRANT) == "A_DOM, B_DOM"


# 5 -----------------------------------------------------------------------------------------------
def test_on_changes_only_the_subject_call(drive, monkeypatch):
    """/resolve makes one model call (ClassifyDomainIntent); the other thing it does with
    `request.domain` is the recall, whose kwargs must be the same on and off."""
    monkeypatch.delenv(VAR, raising=False)
    kw_off, recall_off = drive()
    monkeypatch.setenv(VAR, "caller")
    kw_on, recall_on = drive()
    assert recall_on == recall_off and recall_on
    assert kw_on["domain"] != kw_off["domain"]
    assert {k: v for k, v in kw_on.items() if k not in ("domain", "baml_options")} == \
           {k: v for k, v in kw_off.items() if k not in ("domain", "baml_options")}
