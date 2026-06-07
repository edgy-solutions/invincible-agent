"""Tests for the ADR-0009 Step F'.6 predicate-hybrid-search code path in
``agent_fleet/ontology_service/main.py``.

We exercise ``_predicate_hybrid_search_sync`` and the response-model
adaptation directly, with a stub Weaviate client. The full endpoint path
(Cypher fallback when Weaviate empty) is covered by the existing
integration tier; here we lock down:

* Weaviate happy path → returns the right shape (score + source plumbed).
* Empty / unavailable Weaviate → returns ``[]`` so the endpoint falls
  through to the Cypher exact-match path.
* Domain-scope filter handling (the OR-of-two-filters trick that keeps
  domain-agnostic predicates visible to scoped callers).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Stubs to avoid pulling rdflib / weaviate / baml_client at import time
# ---------------------------------------------------------------------------
def _install_stubs():
    """Stub the heavy deps Engine O's ``main.py`` imports at module load,
    so the test file can load the module without an agent-fleet environment."""
    if "rdflib" not in sys.modules:
        rdflib = types.ModuleType("rdflib")
        class _NS:
            def __init__(self, *_a, **_kw): pass
        rdflib.Namespace = _NS
        rdflib.Graph = type("Graph", (), {})
        sys.modules["rdflib"] = rdflib

    # Always overwrite weaviate AND weaviate.classes. Other test modules
    # (notably test_ontology_routing.py) install MagicMock() for both
    # via sys.modules.setdefault, and a MagicMock weaviate module
    # auto-magic-generates a .classes attribute that would shadow our
    # sys.modules["weaviate.classes"] entry when the test's freshly-
    # imported ontology_main does `import weaviate.classes as wvc`.
    # Force-replace both with real ModuleTypes so our stub wins.
    wv = types.ModuleType("weaviate")
    sys.modules["weaviate"] = wv
    wvc = types.ModuleType("weaviate.classes")
    class _Q:
        class Filter:
            @staticmethod
            def any_of(parts): return ("any_of", parts)
            @staticmethod
            def by_property(name, length=False):
                # length kwarg matches the Weaviate v4 API: a length
                # filter projects to the array's len before .equal()
                # is applied. Stub ignores it (the test asserts the
                # final tuple shape only).
                class _P:
                    def contains_any(self, vals): return ("contains_any", name, vals)
                    def equal(self, val): return ("equal", name, val)
                return _P()
        class MetadataQuery:
            def __init__(self, **kw): self.kw = kw
    wvc.query = _Q
    class _CCfg:
        class DataType:
            TEXT = "TEXT"; TEXT_ARRAY = "TEXT_ARRAY"; BOOL = "BOOL"
        class Property:
            def __init__(self, *a, **kw): pass
    wvc.config = _CCfg
    sys.modules["weaviate.classes"] = wvc
    # Also expose .classes on the weaviate module — `import weaviate.classes`
    # binds via sys.modules but `weaviate.classes` attribute access (as may
    # happen indirectly via __init__-driven submodule registration) wants
    # the attribute set on the parent. Without this, a MagicMock could
    # still leak in if anything reads weaviate.classes before the import
    # statement resolves.
    wv.classes = wvc

    if "neo4j" not in sys.modules:
        n = types.ModuleType("neo4j")
        n.GraphDatabase = type("GraphDatabase", (), {"driver": staticmethod(lambda *a, **k: None)})
        sys.modules["neo4j"] = n

    if "baml_client" not in sys.modules:
        bc = types.ModuleType("baml_client")
        bc.b = object()
        sys.modules["baml_client"] = bc
    if "baml_client.types" not in sys.modules:
        t = types.ModuleType("baml_client.types")
        class _R: pass
        t.SemanticResolution = _R
        sys.modules["baml_client.types"] = t
    if "baml_client.type_builder" not in sys.modules:
        tb = types.ModuleType("baml_client.type_builder")
        class _TB:
            def __init__(self): pass
        tb.TypeBuilder = _TB
        sys.modules["baml_client.type_builder"] = tb

    if "utils" not in sys.modules:
        sys.modules["utils"] = types.ModuleType("utils")
    if "utils.weaviate_utils" not in sys.modules:
        m = types.ModuleType("utils.weaviate_utils")
        m.create_weaviate_client = lambda *a, **k: None
        sys.modules["utils.weaviate_utils"] = m


@pytest.fixture(scope="module")
def ontology_main():
    _install_stubs()
    spec = importlib.util.spec_from_file_location(
        "ontology_main_hybrid_test",
        str(_REPO / "agent_fleet" / "ontology_service" / "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fake Weaviate client + collection
# ---------------------------------------------------------------------------
class _FakeMetadata:
    def __init__(self, score: float | None):
        self.score = score


class _FakeObject:
    def __init__(self, properties: dict, score: float | None = None):
        self.properties = properties
        self.metadata = _FakeMetadata(score)


class _FakeHybridResponse:
    def __init__(self, objects: list[_FakeObject]):
        self.objects = objects


class _FakeQuery:
    def __init__(self, scripted: list[_FakeObject]):
        self._scripted = scripted
        self.last_call: dict | None = None

    def hybrid(self, query, limit, filters, return_metadata):
        self.last_call = {
            "query": query, "limit": limit,
            "filters": filters, "return_metadata": return_metadata,
            "mode": "hybrid",
        }
        return _FakeHybridResponse(self._scripted)

    # ADR-0018 sandbox bm25() fallback: the production code falls back to
    # bm25() when hybrid() raises (sandbox Weaviate has no vectorizer
    # configured for the Predicate collection). Mirror the same signature
    # so the mock supports both call paths.
    def bm25(self, query, limit, filters, return_metadata):
        self.last_call = {
            "query": query, "limit": limit,
            "filters": filters, "return_metadata": return_metadata,
            "mode": "bm25",
        }
        return _FakeHybridResponse(self._scripted)


class _FakeCollection:
    def __init__(self, scripted: list[_FakeObject]):
        self.query = _FakeQuery(scripted)


class _FakeCollections:
    def __init__(self, scripted: list[_FakeObject], exists: bool = True):
        self._scripted = scripted
        self._exists = exists
        # Memoize: production code does ``get(name)`` once per query, but
        # tests want to inspect the same collection after the search runs.
        self._cached: dict[str, _FakeCollection] = {}

    def exists(self, name): return self._exists
    def get(self, name):
        key = str(name)
        if key not in self._cached:
            self._cached[key] = _FakeCollection(self._scripted)
        return self._cached[key]


class _FakeClient:
    def __init__(self, scripted: list[_FakeObject], exists: bool = True):
        self.collections = _FakeCollections(scripted, exists)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_hybrid_search_returns_routing_fields(ontology_main, monkeypatch):
    """A Weaviate hit yields a dict with all the routing-required fields
    and the score plumbed through unchanged."""
    obj = _FakeObject(
        properties={
            "verb_iri": "mesh:queryKnowledgeGraph",
            "verb_local": "queryKnowledgeGraph",
            "input_uri": "mesh:GraphQuery",
            "output_uri": "mesh:GraphExpertResponse",
            "endpoint_url": "http://engine-e:8086/query_graph",
            "owner_persona": "AUDITOR",
            "domains": ["MAINTENANCE", "MANUFACTURING"],
            "cost_class": "slow",
            "requires_human_approval": False,
        },
        score=0.87,
    )
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", _FakeClient([obj]))

    hits = ontology_main._predicate_hybrid_search_sync(
        "find me a fix for vibration", entitled_domains=[], limit=5
    )

    assert len(hits) == 1
    h = hits[0]
    assert h["verb_iri"] == "mesh:queryKnowledgeGraph"
    assert h["verb_type"] == "queryKnowledgeGraph"
    assert h["input_uri"] == "mesh:GraphQuery"
    assert h["output_uri"] == "mesh:GraphExpertResponse"
    assert h["endpoint"] == "http://engine-e:8086/query_graph"
    assert h["owner_persona"] == "AUDITOR"
    assert h["domains"] == ["MAINTENANCE", "MANUFACTURING"]
    assert h["cost_class"] == "slow"
    assert h["requires_human_approval"] is False
    assert h["score"] == pytest.approx(0.87)


# ---------------------------------------------------------------------------
# No driver / collection missing → returns []
# ---------------------------------------------------------------------------
def test_no_weaviate_client_returns_empty(ontology_main, monkeypatch):
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", None)
    hits = ontology_main._predicate_hybrid_search_sync("anything", [], 5)
    assert hits == []


def test_collection_missing_returns_empty(ontology_main, monkeypatch):
    """Cold start: client connected but Predicate collection not created
    yet → empty hits, caller falls back to Cypher."""
    monkeypatch.setattr(
        ontology_main, "_WEAVIATE_CLIENT", _FakeClient([], exists=False)
    )
    hits = ontology_main._predicate_hybrid_search_sync("anything", [], 5)
    assert hits == []


# ---------------------------------------------------------------------------
# Exceptions are swallowed (routing accelerator, not crash-critical)
# ---------------------------------------------------------------------------
def test_hybrid_exception_returns_empty(ontology_main, monkeypatch):
    class _Boom:
        @property
        def collections(self):
            raise RuntimeError("weaviate down")
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", _Boom())
    hits = ontology_main._predicate_hybrid_search_sync("q", [], 5)
    assert hits == []


# ---------------------------------------------------------------------------
# Domain scope filter — unscoped caller passes no filter
# ---------------------------------------------------------------------------
def test_unscoped_caller_passes_no_filter(ontology_main, monkeypatch):
    client = _FakeClient([])
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", client)
    ontology_main._predicate_hybrid_search_sync("q", entitled_domains=[], limit=5)
    last = client.collections.get(ontology_main._PREDICATE_COLLECTION).query.last_call
    assert last["filters"] is None


def test_scoped_caller_builds_or_filter(ontology_main, monkeypatch):
    """Scoped caller: keep predicates that EITHER share a domain entry OR
    are domain-agnostic (empty domains array). The fake captures the
    Filter shape so we lock down the structure of the OR composition."""
    client = _FakeClient([])
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", client)
    ontology_main._predicate_hybrid_search_sync(
        "q", entitled_domains=["MAINTENANCE"], limit=5
    )
    last = client.collections.get(ontology_main._PREDICATE_COLLECTION).query.last_call
    assert last["filters"][0] == "any_of"  # tag from our stub Filter
    parts = last["filters"][1]
    assert ("contains_any", "domains", ["MAINTENANCE"]) in parts
    # Production code switched from .equal([]) to a length-filter
    # .by_property("domains", length=True).equal(0) after Weaviate v4
    # rejected empty-list filters. The stub ignores the length kwarg
    # so this still resolves through by_property(name).equal(0).
    assert ("equal", "domains", 0) in parts


# ---------------------------------------------------------------------------
# Score absent → None (gracefully)
# ---------------------------------------------------------------------------
def test_missing_score_yields_none(ontology_main, monkeypatch):
    obj = _FakeObject(
        properties={
            "verb_iri": "mesh:x", "verb_local": "x",
            "input_uri": "mesh:I", "output_uri": "mesh:O",
            "endpoint_url": "", "owner_persona": "", "domains": [],
            "cost_class": "fast", "requires_human_approval": False,
        },
        score=None,
    )
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", _FakeClient([obj]))
    hits = ontology_main._predicate_hybrid_search_sync("q", [], 5)
    assert hits[0]["score"] is None
