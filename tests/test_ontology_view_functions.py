"""Tests for the ADR-0009 Step E' view-functions in
``agent_fleet/ontology_service/registry_views.py``.

Specifically:
- ``fetch_active_personas(driver)`` reads distinct ``r.owner_persona``
  from Neo4j.
- ``fetch_active_domains(driver)`` reads distinct ``r.domains`` UNWIND'd
  from Neo4j.
- Both fall back gracefully when ``driver`` is ``None``, the graph is
  empty, or Cypher raises.

The view-functions take ``driver`` as an explicit parameter so we can
test them without booting Engine O's full module (rdflib, weaviate,
baml_client). Engine O's ``main.py`` shims them with the module-level
``_NEO4J_DRIVER``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.ontology_service import registry_views as views  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Neo4j driver — captures Cypher queries and returns scripted rows
# ---------------------------------------------------------------------------
class _FakeSession:
    def __init__(self, scripted: list[dict]):
        self._scripted = scripted

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def run(self, _cypher):
        return iter(self._scripted)


class _FakeDriver:
    def __init__(self, scripted: list[dict]):
        self._scripted = scripted

    def session(self):
        return _FakeSession(self._scripted)


class _BrokenDriver:
    def session(self):
        class _S:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def run(self, _cypher): raise RuntimeError("neo4j down")
        return _S()


# ---------------------------------------------------------------------------
# fetch_active_personas
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_personas_from_graph():
    rows = [{"persona": "MECHANIC"}, {"persona": "AUDITOR"}, {"persona": "DATA_STEWARD"}]
    personas = await views.fetch_active_personas(_FakeDriver(rows))
    assert personas == ["MECHANIC", "AUDITOR", "DATA_STEWARD"]


@pytest.mark.asyncio
async def test_personas_fallback_when_no_driver():
    """driver=None → fall back to the UI-metadata keys so /route_and_plan
    still has something to classify into in local dev."""
    personas = await views.fetch_active_personas(None)
    assert set(personas) == set(views.PERSONA_UI_METADATA.keys())


@pytest.mark.asyncio
async def test_personas_fallback_when_graph_empty():
    """Driver works but graph is empty → fall back to UI-metadata keys."""
    personas = await views.fetch_active_personas(_FakeDriver([]))
    assert set(personas) == set(views.PERSONA_UI_METADATA.keys())


@pytest.mark.asyncio
async def test_personas_fallback_when_cypher_raises():
    """Transient Neo4j error → fall back, do not propagate."""
    personas = await views.fetch_active_personas(_BrokenDriver())
    assert set(personas) == set(views.PERSONA_UI_METADATA.keys())


# ---------------------------------------------------------------------------
# fetch_active_domains
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_domains_from_graph():
    rows = [{"domain": "MAINTENANCE"}, {"domain": "DATA_ENGINEERING"}]
    domains = await views.fetch_active_domains(_FakeDriver(rows))
    assert domains == ["MAINTENANCE", "DATA_ENGINEERING"]


@pytest.mark.asyncio
async def test_domains_fallback_when_no_driver():
    domains = await views.fetch_active_domains(None)
    assert set(domains) == set(views.LEGACY_DOMAIN_PROMPTS.keys())


@pytest.mark.asyncio
async def test_domains_fallback_when_graph_empty():
    domains = await views.fetch_active_domains(_FakeDriver([]))
    assert set(domains) == set(views.LEGACY_DOMAIN_PROMPTS.keys())


@pytest.mark.asyncio
async def test_domains_fallback_when_cypher_raises():
    domains = await views.fetch_active_domains(_BrokenDriver())
    assert set(domains) == set(views.LEGACY_DOMAIN_PROMPTS.keys())


# ---------------------------------------------------------------------------
# get_baml_persona_string / get_baml_domain_string (legacy formatters)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_persona_string_dresses_with_legacy_prompts():
    rows = [{"persona": "MECHANIC"}, {"persona": "DATA_STEWARD"}]
    s = await views.get_baml_persona_string(_FakeDriver(rows))
    assert "- MECHANIC:" in s
    assert "- DATA_STEWARD:" in s


@pytest.mark.asyncio
async def test_persona_string_uses_generic_fallback_for_unknown():
    """A persona that doesn't have a legacy prompt still gets a usable line."""
    rows = [{"persona": "NEW_CUSTOM_PERSONA"}]
    s = await views.get_baml_persona_string(_FakeDriver(rows))
    assert "NEW_CUSTOM_PERSONA" in s
    assert "specialist" in s.lower()


@pytest.mark.asyncio
async def test_domain_string_from_graph():
    rows = [{"domain": "MAINTENANCE"}, {"domain": "DATA_ENGINEERING"}]
    s = await views.get_baml_domain_string(_FakeDriver(rows))
    assert "- MAINTENANCE:" in s
    assert "- DATA_ENGINEERING:" in s


# ---------------------------------------------------------------------------
# Step E' completion check — no master dicts left in main.py
# ---------------------------------------------------------------------------
def test_no_master_dicts_in_main():
    """ADR-0009 Step E' completion check: the MASTER_* names must not be
    importable from main.py. We don't import main directly here (it pulls
    rdflib + weaviate + baml_client which are heavy and env-dependent);
    instead we grep the source file."""
    main_path = _REPO / "agent_fleet" / "ontology_service" / "main.py"
    src = main_path.read_text(encoding="utf-8")
    assert "MASTER_PERSONAS = {" not in src
    assert "MASTER_DOMAINS = {" not in src
    assert "MASTER_INTENTS = {" not in src
