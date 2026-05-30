"""Tests for ``agent_fleet.utils.mesh_registration`` (ADR-0004 Step D.1).

Same skip-default / fail-soft / payload-contract semantics as the SDK's
``MeshTool`` lifespan, packaged for engines that don't go through the SDK.

We mock the ``datahub`` package the same way ``tests/test_core.py`` in
``iagent-mesh-sdk`` does — by stuffing fake modules into ``sys.modules``
before the helper performs its lazy import.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest


# Make agent_fleet importable from the iagent repo root.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.utils import mesh_registration  # noqa: E402


# ---------------------------------------------------------------------------
# Fake acryl-datahub classes — capture-only stand-ins
# ---------------------------------------------------------------------------
class _FakeEmittedMcp:
    def __init__(self, entityUrn=None, aspect=None, **kwargs):
        self.entityUrn = entityUrn
        self.aspect = aspect


class _FakeMlModelProps:
    def __init__(self, description=None, customProperties=None, **kwargs):
        self.description = description
        self.customProperties = customProperties or {}


class _FakeEmitter:
    instances: list = []

    def __init__(self, gms_server=None, token=None, **kwargs):
        self.gms_server = gms_server
        self.token = token
        self.emitted: list = []
        _FakeEmitter.instances.append(self)

    def emit(self, mcp):
        self.emitted.append(mcp)


@pytest.fixture
def fake_datahub(monkeypatch):
    """Inject fake ``datahub.*`` modules so the helper's lazy import resolves."""
    _FakeEmitter.instances = []

    mcp_mod = types.ModuleType("datahub.emitter.mcp")
    mcp_mod.MetadataChangeProposalWrapper = _FakeEmittedMcp

    rest_mod = types.ModuleType("datahub.emitter.rest_emitter")
    rest_mod.DatahubRestEmitter = _FakeEmitter

    schema_mod = types.ModuleType("datahub.metadata.schema_classes")
    schema_mod.MLModelPropertiesClass = _FakeMlModelProps

    parent = types.ModuleType("datahub")
    parent_emitter = types.ModuleType("datahub.emitter")
    parent_metadata = types.ModuleType("datahub.metadata")

    monkeypatch.setitem(sys.modules, "datahub", parent)
    monkeypatch.setitem(sys.modules, "datahub.emitter", parent_emitter)
    monkeypatch.setitem(sys.modules, "datahub.metadata", parent_metadata)
    monkeypatch.setitem(sys.modules, "datahub.emitter.mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "datahub.emitter.rest_emitter", rest_mod)
    monkeypatch.setitem(sys.modules, "datahub.metadata.schema_classes", schema_mod)


# ---------------------------------------------------------------------------
# A minimal valid argument set every test starts from
# ---------------------------------------------------------------------------
def _call_kwargs(**overrides):
    base = dict(
        name="engine_a_test",
        description="test engine",
        verb="mesh:analyzeWithCodeAgent",
        input_uri="mesh:AgentTask",
        output_uri="mesh:AgentResponse",
        endpoint_url="http://engine-a:8081/analyze",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Skip-by-default behavior
# ---------------------------------------------------------------------------
def test_skips_when_register_env_unset(monkeypatch, caplog):
    monkeypatch.delenv("MESH_REGISTER_ON_STARTUP", raising=False)

    with caplog.at_level("INFO", logger="mesh_registration"):
        mesh_registration.register_engine_to_mesh(**_call_kwargs())

    assert any(
        "Skipping DataHub registration" in r.getMessage() for r in caplog.records
    )


@pytest.mark.parametrize("val", ["false", "FALSE", "0", "no", "off", "anything"])
def test_only_explicit_truthy_values_enable_registration(monkeypatch, val, caplog):
    """Only ``true|1|yes|on`` (case-insensitive) actually enable. Anything
    else — including unrecognized strings — is treated as opt-out."""
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", val)
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://datahub-gms:8080")

    with caplog.at_level("INFO", logger="mesh_registration"):
        mesh_registration.register_engine_to_mesh(**_call_kwargs())

    assert any(
        "Skipping DataHub registration" in r.getMessage() for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Missing GMS URL — clear warning, no crash
# ---------------------------------------------------------------------------
def test_missing_gms_url_warns_and_returns(monkeypatch, caplog):
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.delenv("DATAHUB_GMS_URL", raising=False)

    with caplog.at_level("WARNING", logger="mesh_registration"):
        mesh_registration.register_engine_to_mesh(**_call_kwargs())

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("DATAHUB_GMS_URL" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# Missing acryl-datahub package — clear warning, no crash
# ---------------------------------------------------------------------------
def test_missing_acryl_datahub_warns_and_returns(monkeypatch, caplog):
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://datahub-gms:8080")

    # Force the ``from datahub...`` block to raise ImportError.
    for mod_name in [
        "datahub", "datahub.emitter", "datahub.emitter.mcp",
        "datahub.emitter.rest_emitter", "datahub.metadata",
        "datahub.metadata.schema_classes",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _refuse(name, *args, **kwargs):
        if name.startswith("datahub"):
            raise ImportError(f"refusing {name} for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _refuse)

    with caplog.at_level("WARNING", logger="mesh_registration"):
        mesh_registration.register_engine_to_mesh(**_call_kwargs())

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("acryl-datahub is not installed" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# Happy path — emits one MCP with the full predicate payload
# ---------------------------------------------------------------------------
def test_emits_full_predicate_payload(fake_datahub, monkeypatch, caplog):
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://fake-gms:8080")
    monkeypatch.setenv("DATAHUB_TOKEN", "fake-token")

    with caplog.at_level("INFO", logger="mesh_registration"):
        mesh_registration.register_engine_to_mesh(
            **_call_kwargs(
                verb="mro:applyDiagnostics",
                input_uri="mro:Symptom",
                output_uri="mro:FaultReport",
                verb_synonyms=["diagnose", "troubleshoot"],
                owner_persona="MECHANIC",
                cost_class="medium",
                requires_human_approval=True,
                version="1.2.3",
            )
        )

    assert _FakeEmitter.instances, "expected exactly one emitter constructed"
    emitter = _FakeEmitter.instances[0]
    assert emitter.gms_server == "http://fake-gms:8080"
    assert emitter.token == "fake-token"
    assert len(emitter.emitted) == 1

    mcp = emitter.emitted[0]
    assert mcp.entityUrn == "urn:li:mlModel:(urn:li:dataPlatform:mesh,engine_a_test,PROD)"

    props = mcp.aspect.customProperties
    assert props["mesh_is_registration"] == "true"
    assert props["mesh_tool_kind"] == "Engine"  # distinguishes from SDK MeshTool
    assert props["mesh_verb_iri"] == "mro:applyDiagnostics"
    assert json.loads(props["mesh_verb_synonyms"]) == ["diagnose", "troubleshoot"]
    assert props["mesh_input_uri"] == "mro:Symptom"
    assert props["mesh_output_uri"] == "mro:FaultReport"
    assert props["mesh_namespace_authority"] == "domain"  # mro: -> domain
    assert props["mesh_owner_persona"] == "MECHANIC"
    assert props["mesh_cost_class"] == "medium"
    assert props["mesh_requires_human_approval"] == "true"
    assert props["mesh_endpoint_url"] == "http://engine-a:8081/analyze"
    assert json.loads(props["mesh_openapi_schema"]) == {}
    assert props["mesh_sdk_version"] == "0.0.0"  # engine emit, not SDK
    assert props["mesh_tool_version"] == "1.2.3"


def test_mesh_prefix_resolves_to_platform_authority(fake_datahub, monkeypatch):
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://fake-gms:8080")

    mesh_registration.register_engine_to_mesh(**_call_kwargs(verb="mesh:foo"))

    props = _FakeEmitter.instances[0].emitted[0].aspect.customProperties
    assert props["mesh_namespace_authority"] == "platform"


def test_unknown_prefix_resolves_to_domain_authority(fake_datahub, monkeypatch):
    """Per ADR-0005 default: anything not in ``mesh:`` is a domain namespace."""
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://fake-gms:8080")

    mesh_registration.register_engine_to_mesh(
        **_call_kwargs(verb="future-domain:doStuff")
    )

    props = _FakeEmitter.instances[0].emitted[0].aspect.customProperties
    assert props["mesh_namespace_authority"] == "domain"


# ---------------------------------------------------------------------------
# Emit failure must not crash the engine (ADR-0006 fail-soft)
# ---------------------------------------------------------------------------
def test_emit_failure_is_swallowed(fake_datahub, monkeypatch, caplog):
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://fake-gms:8080")

    class _ExplodingEmitter(_FakeEmitter):
        def emit(self, mcp):
            raise RuntimeError("DataHub unreachable")

    monkeypatch.setattr(
        sys.modules["datahub.emitter.rest_emitter"],
        "DatahubRestEmitter",
        _ExplodingEmitter,
    )

    # The call must complete without raising.
    with caplog.at_level("WARNING", logger="mesh_registration"):
        mesh_registration.register_engine_to_mesh(**_call_kwargs())

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "Failed to register" in r.getMessage()
        and "DataHub unreachable" in r.getMessage()
        for r in warnings
    )
