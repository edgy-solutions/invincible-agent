"""Tests for Engine O's ``/find_tool`` and ``/find_path`` endpoints
(ADR-0004 Step C).

These exercise the *deterministic* routing path: pure Cypher queries
against a fake Neo4j driver. The NLP-side endpoints (``/resolve``,
``/route_and_plan``) are not exercised here -- they live in a separate
test file.

We use FastAPI's TestClient against the same ``app`` instance the
service starts. The fake driver records what Cypher and parameters the
endpoints emit so we can assert the exact contract doc-tools' AITool
binding side has to satisfy.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers — make Engine O importable from this test
# ---------------------------------------------------------------------------
# The service module sits under ``agent_fleet/ontology_service`` and
# imports ``baml_client``/etc from sibling paths. Pre-mock the heavy
# downstream modules so the import succeeds in a clean test environment.
@pytest.fixture(scope="module")
def engine_o_module():
    # Add agent_fleet/ontology_service to path so ``main`` is importable.
    repo = Path(__file__).resolve().parent.parent
    svc_dir = repo / "agent_fleet" / "ontology_service"
    if str(svc_dir) not in sys.path:
        sys.path.insert(0, str(svc_dir))

    # Stub heavy deps Engine O imports at module-load time. The endpoints
    # under test never touch these so the stubs just need to exist.
    for name in [
        "rdflib", "weaviate", "weaviate.classes", "weaviate.classes.query",
        "neo4j", "baml_client", "baml_client.types", "baml_client.type_builder",
        "llm_utils", "utils", "utils.weaviate_utils",
        "agent_fleet", "agent_fleet.llm_utils",
        "agent_fleet.utils", "agent_fleet.utils.weaviate_utils",
    ]:
        sys.modules.setdefault(name, MagicMock())

    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


@pytest.fixture
def client(engine_o_module):
    return TestClient(engine_o_module.app)


class _FakeRecord(dict):
    """Lets the Cypher result behave like both a dict-record and a row."""


class _FakeResult:
    def __init__(self, record: dict | None):
        self._record = _FakeRecord(record) if record is not None else None

    def single(self):
        return self._record


class _FakeSession:
    def __init__(self, record: dict | None = None, raise_on_run: Exception | None = None):
        self.record_to_return = record
        self.raise_on_run = raise_on_run
        self.executed: tuple[str, dict] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, cypher: str, **params):
        self.executed = (cypher, params)
        if self.raise_on_run is not None:
            raise self.raise_on_run
        return _FakeResult(self.record_to_return)


class _FakeDriver:
    def __init__(self, record: dict | None = None, raise_on_run: Exception | None = None):
        self.session_obj = _FakeSession(record, raise_on_run)

    def session(self):
        return self.session_obj


# ---------------------------------------------------------------------------
# /find_tool
# ---------------------------------------------------------------------------
def test_find_tool_returns_503_when_driver_not_ready(engine_o_module, client):
    """If the lifespan didn't bring Neo4j up, routing endpoints must 503
    -- they cannot fall back to a stale answer."""
    engine_o_module._NEO4J_DRIVER = None

    r = client.post(
        "/find_tool",
        json={"subject_uri": "mro:Symptom", "verb_label": "applyDiagnostics"},
    )
    assert r.status_code == 503
    assert "Neo4j" in r.json()["detail"]


def test_find_tool_happy_path(engine_o_module, client):
    """Cypher emits the right parameters and the response maps every
    field of the predicate edge."""
    engine_o_module._NEO4J_DRIVER = _FakeDriver(record={
        "verb_type":               "applyDiagnostics",
        "verb_iri":                "mro:applyDiagnostics",
        "endpoint":                "http://engine-a.mesh.svc:8081/execute",
        "output_uri":              "mro:FaultReport",
        "owner_persona":           "MECHANIC",
        "cost_class":              "fast",
        "requires_human_approval": False,
        "openapi_schema":          "{}",
    })

    r = client.post(
        "/find_tool",
        json={"subject_uri": "mro:Symptom", "verb_label": "applyDiagnostics"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    step = body["step"]
    assert step["verb_type"] == "applyDiagnostics"
    assert step["verb_iri"] == "mro:applyDiagnostics"
    assert step["endpoint"] == "http://engine-a.mesh.svc:8081/execute"
    assert step["output_uri"] == "mro:FaultReport"
    assert step["owner_persona"] == "MECHANIC"
    assert step["cost_class"] == "fast"
    assert step["requires_human_approval"] is False

    # Assert the Cypher contract — the doc-tools side has to keep matching this.
    cypher, params = engine_o_module._NEO4J_DRIVER.session_obj.executed
    assert "MATCH (s:OntologyClass {uri: $subject_uri})" in cypher
    assert "OR r.iri  = $verb_label" in cypher
    assert "OR $verb_label IN coalesce(r.synonyms, [])" in cypher
    assert params == {"subject_uri": "mro:Symptom", "verb_label": "applyDiagnostics"}


def test_find_tool_not_found_returns_actionable_reason(engine_o_module, client):
    """No matching edge → ``found: false`` + a reason mentioning the
    candidate causes (unknown verb / unknown subject / not yet synced)."""
    engine_o_module._NEO4J_DRIVER = _FakeDriver(record=None)

    r = client.post(
        "/find_tool",
        json={"subject_uri": "mro:Mystery", "verb_label": "doStuff"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["step"] is None
    reason = body["reason"]
    assert "doStuff" in reason
    assert "mro:Mystery" in reason
    # Mention all three plausible causes so debugging starts in the right place.
    assert "not registered" in reason or "not in the graph" in reason or "not yet synced" in reason


def test_find_tool_propagates_neo4j_errors_as_500(engine_o_module, client):
    """A Neo4j-side failure surfaces as 500 with the error in detail —
    routing decisions never fall back to a guess."""
    engine_o_module._NEO4J_DRIVER = _FakeDriver(raise_on_run=RuntimeError("kaboom"))

    r = client.post(
        "/find_tool",
        json={"subject_uri": "mro:Symptom", "verb_label": "applyDiagnostics"},
    )
    assert r.status_code == 500
    assert "kaboom" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /find_path
# ---------------------------------------------------------------------------
def test_find_path_returns_503_when_driver_not_ready(engine_o_module, client):
    engine_o_module._NEO4J_DRIVER = None

    r = client.post(
        "/find_path",
        json={"start_uri": "mro:Symptom", "end_uri": "mro:MaintenanceLog"},
    )
    assert r.status_code == 503


def test_find_path_happy_two_hop(engine_o_module, client):
    """A two-step path round-trips with both steps' metadata preserved."""
    engine_o_module._NEO4J_DRIVER = _FakeDriver(record={
        "hops": 2,
        "total_latency_budget_ms": 8000,
        "steps": [
            {
                "verb_type": "applyDiagnostics",
                "verb_iri": "mro:applyDiagnostics",
                "endpoint": "http://engine-a:8081/execute",
                "output_uri": "mro:FaultReport",
                "owner_persona": "MECHANIC",
                "cost_class": "fast",
                "requires_human_approval": False,
                "openapi_schema": "{}",
            },
            {
                "verb_type": "formatTechnicalNote",
                "verb_iri": "mesh:formatTechnicalNote",
                "endpoint": "http://engine-f:8087/execute",
                "output_uri": "mro:MaintenanceLog",
                "owner_persona": "TECH_WRITER",
                "cost_class": "medium",
                "requires_human_approval": False,
                "openapi_schema": "{}",
            },
        ],
    })

    r = client.post(
        "/find_path",
        json={
            "start_uri": "mro:Symptom",
            "end_uri": "mro:MaintenanceLog",
            "max_hops": 4,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["hops"] == 2
    assert body["total_latency_budget_ms"] == 8000
    assert len(body["steps"]) == 2
    assert body["steps"][0]["verb_iri"] == "mro:applyDiagnostics"
    assert body["steps"][1]["verb_iri"] == "mesh:formatTechnicalNote"

    cypher, params = engine_o_module._NEO4J_DRIVER.session_obj.executed
    # max_hops is template-interpolated (Cypher can't take it as a param).
    assert "*1..4" in cypher
    assert "endNode(r).uri" in cypher  # each step's output_uri comes from the next node
    # cost class filter is parameterized
    assert params["allowed_cost_classes"] == ["fast", "medium", "slow"]
    assert params["exclude_human_approval"] is False


def test_find_path_validates_max_hops_range(client):
    """max_hops is bounded so the Cypher's variable-length match can't
    explode. Out-of-range gets a 422 from Pydantic."""
    r = client.post(
        "/find_path",
        json={"start_uri": "a:b", "end_uri": "c:d", "max_hops": 99},
    )
    assert r.status_code == 422


def test_find_path_rejects_unknown_cost_class(engine_o_module, client):
    """An unknown cost class in the filter is a 422 with a clear list of
    valid values — keeps invalid strings out of Neo4j."""
    engine_o_module._NEO4J_DRIVER = _FakeDriver(record=None)

    r = client.post(
        "/find_path",
        json={
            "start_uri": "a:b",
            "end_uri": "c:d",
            "allowed_cost_classes": ["lightning"],
        },
    )
    assert r.status_code == 422
    assert "lightning" in r.json()["detail"]


def test_find_path_honors_exclude_human_approval(engine_o_module, client):
    """The flag is forwarded into the Cypher parameters so the WHERE
    clause filters HITL-required edges."""
    engine_o_module._NEO4J_DRIVER = _FakeDriver(record=None)

    r = client.post(
        "/find_path",
        json={
            "start_uri": "a:b",
            "end_uri": "c:d",
            "exclude_human_approval": True,
        },
    )
    assert r.status_code == 200
    # not_found case is fine — we're checking the wire only
    _, params = engine_o_module._NEO4J_DRIVER.session_obj.executed
    assert params["exclude_human_approval"] is True


def test_find_path_not_found_returns_actionable_reason(engine_o_module, client):
    engine_o_module._NEO4J_DRIVER = _FakeDriver(record=None)

    r = client.post(
        "/find_path",
        json={"start_uri": "a:b", "end_uri": "c:d", "max_hops": 3},
    )
    body = r.json()
    assert body["found"] is False
    assert body["steps"] == []
    assert "a:b" in body["reason"] and "c:d" in body["reason"]
    assert "max_hops=3" in body["reason"]


def test_find_path_propagates_neo4j_errors_as_500(engine_o_module, client):
    engine_o_module._NEO4J_DRIVER = _FakeDriver(raise_on_run=RuntimeError("graph offline"))

    r = client.post(
        "/find_path",
        json={"start_uri": "a:b", "end_uri": "c:d"},
    )
    assert r.status_code == 500
    assert "graph offline" in r.json()["detail"]
