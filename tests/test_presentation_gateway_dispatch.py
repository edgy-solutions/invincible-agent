"""PRESENTATIONS GO THROUGH THE GATEWAY — and the fallback admits what it is.

WHY THE FALLBACK IS THE DANGEROUS PART. Per ADR-0006 §Addendum the mesh-registrar
is SOLE WRITER of predicate edges into Neo4j + Weaviate. A presentation that goes
through it lands a rendersAs row; one that falls back to direct DataHub emit lands
an AUDIT RECORD and nothing else -- the DataHub->Weaviate materialiser was retired
2026-06-13, so those emissions reach nothing.

So a SILENT fallback rebuilds this arc's founding failure exactly:

    gateway refuses -> engine emits direct -> log says registered -> rendersAs
    stays 0 -> three components report success while nothing is written.

That is the same shape as doc-tools' linker returning SUCCESS on a 401 skip, and
as `outbound_auth_headers` sending token-less on mint failure. A fallback that
does not announce its own degradation is a dead path dressed as a working one.

WHAT THIS SEALS:
  * the gateway is TRIED FIRST when MESH_REGISTRAR_URL is set -- it is the writer,
    and direct emit is not a second writer;
  * success returns WITHOUT a direct emit, so one registration never produces two
    DataHub writes with different provenance;
  * the three refusal CLASSES are discriminated, because they have OPPOSITE
    repairs behind ONE symptom (rendersAs stays 0):
      - STALE-IMAGE  -> ship the registrar image; direct emit cannot help
      - REFUSED      -> fix the registration; direct emit records the same bad claim
      - unreachable  -> network/credential; direct emit is a real stopgap
  * the IRI convention is inherited: predicate COMPACT, subject/object FULL.

Run: uv run --frozen --with pytest pytest tests/test_presentation_gateway_dispatch.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "agent_fleet" / "utils" / "mesh_registration.py"
_MOD_NAME = "mesh_registration__gateway_dispatch_test"


def _mod():
    cached = sys.modules.get(_MOD_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_MOD_NAME, None)
        pytest.skip(f"mesh_registration not importable: {type(exc).__name__}: {exc}")
    return m


_MESH = "http://invincible-agent/mesh#"


# ── the refusal classifier: three futures, one symptom ──────────────────────

def test_a_STALE_IMAGE_422_is_named_as_such():
    """An old registrar ignores the presentation fields and refuses because the
    VERB-shaped fields it still requires are absent. That is a deploy problem,
    and direct emit cannot fix it -- saying so is the point."""
    m = _mod()
    cls, detail = m._classify_gateway_refusal(
        422, "verb_iri: field required; endpoint_url: field required"
    )
    assert cls == "gateway-rejected-STALE-IMAGE"
    assert "ship the registrar image" in detail


def test_a_REFUSED_422_is_named_differently():
    """A CURRENT gateway refusing is a registration problem. Same status code,
    opposite repair -- which is exactly why the class exists."""
    m = _mod()
    cls, detail = m._classify_gateway_refusal(
        422, "Contract D: output_uri not found as :OntologyClass"
    )
    assert cls == "gateway-rejected-REFUSED"
    assert "fix the registration" in detail


def test_the_two_422_classes_are_NOT_the_same():
    """THE DISCRIMINATING PAIR. If one 422 answered for both, the log would send
    an operator to ship an image when the manifest is malformed, or to debug a
    manifest when the image is simply old."""
    m = _mod()
    stale, _ = m._classify_gateway_refusal(422, "input_uri: field required")
    refused, _ = m._classify_gateway_refusal(422, "Contract D violation")
    assert stale != refused


@pytest.mark.parametrize("status", [None, 500, 502, 503])
def test_non_422_failures_are_unreachable(status):
    """Transport and credential failures are the ONLY class where direct emit is
    a genuine stopgap, so they must not be conflated with a refusal."""
    m = _mod()
    cls, detail = m._classify_gateway_refusal(status, "connection refused")
    assert cls == "gateway-unreachable"
    assert "stopgap" in detail


# ── the dispatch: gateway first, and success writes ONCE ───────────────────

def _stub_transport(monkeypatch, m, *, registered, status_code=None, reason=""):
    """Install a fake iagent_mesh transport and capture the manifest sent."""
    import types

    captured = {}

    class _Result:
        def __init__(self):
            self.registered = registered
            self.status_code = status_code
            self.reason = reason

    def _register_with_mesh(url, manifest, component=None, mint=None, timeout=None):
        captured["url"] = url
        captured["manifest"] = manifest
        captured["mint"] = mint
        return _Result()

    fake = types.ModuleType("iagent_mesh.registration_transport")
    fake.register_with_mesh = _register_with_mesh
    pkg = types.ModuleType("iagent_mesh")
    monkeypatch.setitem(sys.modules, "iagent_mesh", pkg)
    monkeypatch.setitem(sys.modules, "iagent_mesh.registration_transport", fake)
    return captured


def test_a_successful_gateway_registration_returns_True(monkeypatch):
    m = _mod()
    cap = _stub_transport(monkeypatch, m, registered=True)
    out = m._emit_presentation_to_registrar(
        registrar_url="http://iagent-mesh-registrar:8080",
        name="presentation_knowledge_document_for_ownershipfact",
        description="renders ownership facts",
        subject_uri="mesh:OwnershipFact",
        object_uri="mesh:KnowledgeDocument",
        archetype="KNOWLEDGE_DOCUMENT",
        expected_fields=["owner"],
        persona_fit=["AUDITOR"],
        domain_fit=["DATA_ENGINEERING"],
        version="0.1.0",
    )
    assert out is True
    assert cap["manifest"]["tool_kind"] == "Presentation"


def test_the_manifest_inherits_the_PER_POSITION_iri_convention(monkeypatch):
    """Predicate COMPACT, subject/object FULL — matching all 24 existing rows.

    Compact inputs are expanded at the ends and the predicate is left alone;
    expanding it would make presentations the only row type with a full verb_iri.
    """
    m = _mod()
    cap = _stub_transport(monkeypatch, m, registered=True)
    m._emit_presentation_to_registrar(
        registrar_url="http://r:8080",
        name="p", description="d",
        subject_uri="mesh:OwnershipFact",       # compact in
        object_uri="mesh:KnowledgeDocument",    # compact in
        archetype="KNOWLEDGE_DOCUMENT",
        expected_fields=[], persona_fit=[], domain_fit=[], version="0.1.0",
    )
    man = cap["manifest"]
    assert man["subject_uri"] == f"{_MESH}OwnershipFact", "subject must go out FULL"
    assert man["object_uri"] == f"{_MESH}KnowledgeDocument", "object must go out FULL"
    assert man["predicate_iri"] == "mesh:rendersAs", "predicate must stay COMPACT"


def test_a_refusal_returns_its_CLASS_not_a_bare_false(monkeypatch):
    """A bare False would collapse three repairs into one silent fallback."""
    m = _mod()
    _stub_transport(monkeypatch, m, registered=False, status_code=422,
                    reason="verb_iri: field required")
    out = m._emit_presentation_to_registrar(
        registrar_url="http://r:8080",
        name="p", description="d",
        subject_uri=f"{_MESH}OwnershipFact",
        object_uri=f"{_MESH}KnowledgeDocument",
        archetype="KNOWLEDGE_DOCUMENT",
        expected_fields=[], persona_fit=[], domain_fit=[], version="0.1.0",
    )
    assert out is not True
    assert out[0] == "gateway-rejected-STALE-IMAGE"


def test_a_transport_exception_does_not_escape(monkeypatch):
    """Registration failure must never crash the engine (ADR-0006): serving
    continues, the verb simply does not route."""
    import types

    m = _mod()

    def _boom(*a, **k):
        raise OSError("connection refused")

    fake = types.ModuleType("iagent_mesh.registration_transport")
    fake.register_with_mesh = _boom
    monkeypatch.setitem(sys.modules, "iagent_mesh", types.ModuleType("iagent_mesh"))
    monkeypatch.setitem(sys.modules, "iagent_mesh.registration_transport", fake)

    out = m._emit_presentation_to_registrar(
        registrar_url="http://r:8080",
        name="p", description="d",
        subject_uri=f"{_MESH}OwnershipFact",
        object_uri=f"{_MESH}KnowledgeDocument",
        archetype="KNOWLEDGE_DOCUMENT",
        expected_fields=[], persona_fit=[], domain_fit=[], version="0.1.0",
    )
    assert out[0] == "gateway-unreachable"


# ── the retirement trigger must stay findable ──────────────────────────────

def test_the_fallback_carries_a_RETIREMENT_TRIGGER():
    """A fallback with no removal condition becomes permanent, and a permanent
    fallback is what ADR-0006's preserved linker turned into: months of SUCCESS
    while writing nothing. This pins that the condition and its check survive
    refactoring — delete the trigger and this goes red."""
    src = _SRC.read_text(encoding="utf-8")
    assert "RETIREMENT TRIGGER" in src, "the fallback lost its removal condition"
    assert "manifest_species" in src, "the trigger lost the fact it checks"
    assert "kubectl" in src, "the trigger lost the command that checks it"


def test_the_trigger_does_NOT_key_on_a_log_line():
    """THE REGRESSION ARM, from a trigger that shipped dead on arrival.

    The first version required `kubectl logs | grep "VIA GATEWAY"`. This
    module's logger propagated to a root uvicorn had replaced, so engine-f
    registered ten presentations through the gateway and printed nothing — the
    condition could not be observed even when it was TRUE, which makes it not a
    condition. A trigger must key on a fact a server states about itself, not on
    a string a logger might swallow.
    """
    src = _SRC.read_text(encoding="utf-8")
    trigger = src.split("RETIREMENT TRIGGER", 1)[1].split("WHY A TRIGGER", 1)[0]
    assert "grep" not in trigger or "manifest_species" in trigger, (
        "the retirement condition is grep-on-logs again — it cannot be observed "
        "when the logger is silent, which is exactly how it shipped dead"
    )


def test_this_module_uses_a_UVICORN_SAFE_logger():
    """THE META-DEFECT'S SEAL. A bare getLogger here propagates to a root that
    uvicorn replaces at startup, so every record this module emits is DROPPED —
    including the three-way fallback classification whose entire purpose is
    telling an operator which repair they need.

    Two engines each hand-rolled this fix on their own named logger and neither
    reached this shared module, which is the one that does the announcing."""
    src = _SRC.read_text(encoding="utf-8")
    assert "ensure_stdout_logger" in src, (
        "mesh_registration went back to a bare getLogger — its records will be "
        "dropped under uvicorn and the fallback classification goes inaudible"
    )
    assert 'logging.getLogger("mesh_registration")' not in src


def test_a_contract_d_refusal_NAMING_a_verb_field_is_still_REFUSED():
    """THE FALSE-POSITIVE ARM, from a bug this suite caught in its own subject.

    'output_uri not found as :OntologyClass' MENTIONS a stale-image field name
    while being the opposite diagnosis. Matching the name alone classified it as
    a stale image and would have sent an operator to ship a perfectly current
    registrar. The signature is the field being reported REQUIRED/MISSING, not
    the field being named.
    """
    m = _mod()
    cls, _ = m._classify_gateway_refusal(
        422, "Contract D: output_uri not found as :OntologyClass in Neo4j"
    )
    assert cls == "gateway-rejected-REFUSED", (
        "a Contract D refusal that happens to name a verb field was misread as a "
        "stale image — the two repairs are opposite"
    )


def test_a_genuine_stale_image_message_still_classifies_as_STALE():
    """The positive control for the tightened signature: pydantic's actual
    'field required' shape must still be recognised."""
    m = _mod()
    for reason in (
        "verb_iri: field required",
        "endpoint_url\n  Field required [type=missing]",
        "input_uri: value is missing",
    ):
        cls, _ = m._classify_gateway_refusal(422, reason)
        assert cls == "gateway-rejected-STALE-IMAGE", f"missed stale signature: {reason!r}"
