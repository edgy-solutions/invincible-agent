"""Engine-o's instance resolution wired end to end against saf's real resolver, for tests.

Moved here from `tests/routing/test_a_same_class_tie_asks_and_a_subclass_wins.py` (roll 190) so
lane/saf's end-to-end arms import the same wiring rather than a copy. RULED 2026-10-16 (Chris):
"Move the shared test helpers (_wire, _two, _resolve) into tests/_helpers/ ...; saf imports from
there."

WHAT IS REAL. engine-o's `_resolve_instance` and `_call_resolver`; saf's real `/resolve_instance`
and engine-o's own `/resolve_instance`, both reached over a real `httpx.AsyncClient` on an ASGI
transport that routes by host; the class chains, computed with rdflib from the TTL files the prime
manifest loads. WHAT IS STUBBED: the provider registry, engine-o's SPARQL, and the Neo4j driver
(a double that answers `_CLASS_CHAIN_CYPHER` from those files).

Use:
    from tests._helpers.sustainment_resolution import eo, resolve, two, wire  # noqa: F401 (fixture)

    def test_x(eo, monkeypatch):
        wire(eo, monkeypatch)
        subject, prov = resolve(eo, "PN-8802")
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

from agent_fleet.ontology_service.sustainment_instance_provider import (
    _COMPONENT_CLASS as COMPONENT,
)
from agent_fleet.safety_agent import entities, instances
from agent_fleet.safety_agent import main as safety_main

_REPO = Path(__file__).resolve().parents[2]
SAFETY_ITEM = safety_main.SAFETY + "SafetyCriticalItem"
EO_PART = "http://internal/components/PN-8802"


# -- the ontology, read from the real files ---------------------------------------------------

def loaded_ttl() -> Path:
    """The file the prime manifest actually loads (setup/prime_databases.py), not a guessed path."""
    manifest = (_REPO / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    m = re.search(r'"name":\s*"safety_extension",\s*"s3_key":\s*"[^"]+",\s*"path":\s*"([^"]+)"', manifest)
    assert m, "safety_extension is not in the prime manifest"
    return _REPO / "setup" / m.group(1)


GRAPH = Graph()
GRAPH.parse(loaded_ttl(), format="turtle")
GRAPH.parse(_REPO / "setup" / "ontologies" / "pcn_extension.ttl", format="turtle")


def chain(uri: str, depth: int = 5) -> list:
    """`subClassOf*0..depth` from `uri`, itself first -- the reach of `_CLASS_CHAIN_CYPHER`."""
    out, frontier = [uri], [uri]
    for _ in range(depth):
        nxt = [str(o) for f in frontier for o in GRAPH.objects(URIRef(f), RDFS.subClassOf)
               if isinstance(o, URIRef) and str(o) not in out]
        out.extend(nxt)
        frontier = nxt
    return out


class _Session:
    def __init__(self, drv):
        self._d = drv

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, cypher, **params):
        self._d.calls.append((cypher, params))
        if self._d.fail:
            raise RuntimeError("graph down")
        return [{"uri": u, "chain": chain(u)} for u in params["uris"]
                if (URIRef(u), None, None) in GRAPH]


class Driver:
    """The Neo4j driver double: answers the class-chain read from GRAPH, or fails ("graph down")."""

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def session(self):
        return _Session(self)


# -- the wiring -------------------------------------------------------------------------------

@pytest.fixture()
def eo():
    return pytest.importorskip(
        "agent_fleet.ontology_service.main",
        reason="ontology_service not importable here; run under the agent-fleet extra")


_REAL_CLIENT = httpx.AsyncClient


def wire(eo, monkeypatch, *, graph_down=False, eo_rows=(EO_PART,)):
    """Real `_call_resolver` -> real saf and engine-o apps over an ASGI transport routed by host.
    `eo_rows` are the component subjects engine-o's SPARQL returns; `()` leaves saf the only
    provider with a candidate. Returns the driver double (its `.calls` are the chain reads)."""
    drv = Driver(fail=graph_down)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", drv)
    # saf declares no id_namespaces (grep agent_fleet/safety_agent), so neither row does.
    rows = [
        {"provider": "engine_safety_sustainment", "endpoint_url": "http://safety.test/resolve_instance",
         "timeout_s": None, "domains": ["SUSTAINMENT"], "id_namespaces": []},
        {"provider": "engine_o_sustainment", "endpoint_url": "http://eo.test/resolve_instance",
         "timeout_s": None, "domains": ["SUSTAINMENT"], "id_namespaces": []},
    ]
    monkeypatch.setattr(eo, "_discover_instance_resolvers", lambda *a, **k: SimpleNamespace(
        outcome="ok", detail=None, rows=rows))

    async def _sparql(query, *a, **k):
        if query == eo._SUSTAINMENT_INSTANCES_QUERY:
            return [{"s": s, "type": COMPONENT} for s in eo_rows]
        return []  # the subjectToNotice link query

    monkeypatch.setattr(eo, "execute_sparql", _sparql)
    apps = {"safety.test": safety_main.app, "eo.test": eo.app}

    async def dispatcher(scope, receive, send):
        host = dict(scope["headers"])[b"host"].decode().split(":")[0]
        await apps[host](scope, receive, send)

    def _factory(*a, timeout=None, **k):
        return _REAL_CLIENT(transport=httpx.ASGITransport(app=dispatcher), timeout=timeout)

    monkeypatch.setattr(eo.httpx, "AsyncClient", _factory)
    return drv


def two(monkeypatch, a, b):
    """saf's tie recipe: two critical items, CSI-7001 and CSI-7002, with part numbers `a` and `b`."""
    base = entities.SAFETY_ITEMS[0]
    monkeypatch.setattr(instances, "SAFETY_ITEMS", (
        replace(base, csi_id="CSI-7001", part_number=a), replace(base, csi_id="CSI-7002", part_number=b)))


def resolve(eo, identifier):
    """engine-o's real fan-out for `identifier` in SUSTAINMENT: `(subject, provenance)`."""
    return asyncio.run(eo._resolve_instance(identifier, "q", ["SUSTAINMENT"]))


def outcomes(prov):
    """`instance_provider_outcomes`, keyed by provider."""
    return {o["provider"]: o for o in prov["instance_provider_outcomes"]}
