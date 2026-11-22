"""`/resolve` carries the classifier's RESULT constraint into its HTTP response.

THE DEFECT. `SemanticResolution` (the output of `b.ClassifyDomainIntent`) gained a field
`result: ResultConstraint?` (the kind the person wants back when it differs from the subject, plus
verbatim qualifier words). `/resolve` builds `SemanticResolutionResponse` field by field, so the
classifier's `result` never reached the response and no score or trace could see it.

WHAT THIS SEALS. The response has a `result` field that records the constraint faithfully (recorded
only, nothing routes on it): on the no-identifier path, on the instance-preemption path, and None
when the classifier gave none. A census by AST pins that EVERY `SemanticResolutionResponse(...)`
built in `resolve` after the classifier call passes `result=`, so a new return cannot drop it.

Drives the REAL `eo.resolve`.
Run: uv run --frozen pytest tests/routing/test_the_resolve_response_carries_the_result_constraint.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

SAFETY = "http://internal/sustainment/safety#"
PCN = "http://internal/sustainment/pcn#"
PRODUCT = "http://internal/sustainment/product#"
S3KL = "http://www.lksoft.com/s3kl#"
MESH = "http://invincible-agent/mesh#"

SCI = SAFETY + "SafetyCriticalItem"
COMPONENT = PCN + "Component"
PLATFORM = SAFETY + "Platform"
FAILURE_RECORD = SAFETY + "FailureRecord"

CALLER = "bob" + "@" + "example.com"
Q = "what failed on this part"
POOL = [
    FAILURE_RECORD, S3KL + "FailureMode", PRODUCT + "Part", S3KL + "LSAFailureMode",
    S3KL + "FunctionalFailure",
]
SERVED = frozenset({SCI, COMPONENT, PLATFORM})
ROWS = [
    {"verb_iri": MESH + "whatFailedOnThisPart", "input_uri": SCI, "output_uri": "",
     "endpoint": "http://e/x", "score": 0.923, "description": "failures for one part"},
    {"verb_iri": MESH + "whatFailedOnThisPart", "input_uri": COMPONENT, "output_uri": "",
     "endpoint": "http://e/x", "score": 0.910, "description": "failures for one part"},
]


class _Tb:
    def __init__(self):
        self.values = {}
        tb = self

        class _OC:
            @staticmethod
            def add_value(uri):
                class _V:
                    @staticmethod
                    def description(d):
                        tb.values[uri] = d
                        return _V
                return _V
        self.OntologyClass = _OC


class _RC:
    def __init__(self, kind, qualifiers):
        self.kind = kind
        self.qualifiers = qualifiers


class _Baml:
    def __init__(self):
        self.offered = None
        self.identifier = None
        self.result = None  # a value, or a callable taking (offered, first)

    async def ClassifyDomainIntent(self, **kw):
        self.offered = list(kw["baml_options"]["tb"].values)
        first = self.offered[0]
        outer = self

        class _R:
            resolved_uri = first
            confidence_score = 0.9
            reasoning = ""
            instance_identifier = outer.identifier
            result = outer.result(outer.offered, first) if callable(outer.result) else outer.result
        return _R()


@pytest.fixture(autouse=True)
def _the_caller_is_verified(monkeypatch):
    """The engine binds the VERIFIED caller, never the body's identity (lane 74); this file's
    requests name the caller below, so that is who the token says they are."""
    from agent_fleet.ontology_service import main as _eo_main
    from tests._helpers.verified_caller import install as _install_caller
    return _install_caller(monkeypatch, _eo_main, CALLER, ["SUSTAINMENT"])


@pytest.fixture
def rig(monkeypatch):
    from agent_fleet.ontology_service import main as eo

    class R:
        pass

    r = R()
    r.eo = eo
    r.baml = _Baml()

    async def _docs(request):
        return None

    async def _pool(**kw):
        return [{"uri": u, "label": u.rsplit("#", 1)[-1], "description": "d", "score": None}
                for u in POOL], "hybrid"

    async def _served(domains, include_referents=False):
        return SERVED

    async def _verbs(query, entitled_domains, limit=10, user_email="", verb_iris=None):
        return ROWS

    monkeypatch.setattr(eo, "_resolve_docs_subject", _docs)
    monkeypatch.setattr(eo, "class_pool_with_mode", _pool)
    monkeypatch.setattr(eo, "_served_class_uris", _served)
    monkeypatch.setattr(eo, "predicate_hybrid_search", _verbs)
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", False)
    monkeypatch.setattr(eo, "_can_view_class", lambda email, uri: True)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", None)
    monkeypatch.setattr(eo, "TypeBuilder", _Tb)
    monkeypatch.setattr(eo, "b", r.baml)

    async def run(query=Q):
        return await eo.resolve(eo.ResolveRequest(
            query=query, domain="SUSTAINMENT", domains=["SUSTAINMENT"], user_email=CALLER))
    r.run = run
    return r


def _other_than_subject(offered, first):
    return [u for u in offered if u != first][0] if len(offered) > 1 else PLATFORM


# a
@pytest.mark.asyncio
async def test_a_result_constraint_reaches_the_response_and_the_subject_is_unchanged(rig):
    seen = {}

    def result(offered, first):
        seen["kind"] = _other_than_subject(offered, first)
        seen["first"] = first
        return _RC(seen["kind"], ["by platform"])

    rig.baml.result = result
    resp = await rig.run()
    want = {"kind": seen["kind"], "qualifiers": ["by platform"]}
    assert seen["kind"] != seen["first"]
    assert resp.resolved_uri == seen["first"]
    assert resp.result == want
    assert resp.model_dump(mode="json")["result"] == want


# b
@pytest.mark.asyncio
async def test_no_result_constraint_is_none(rig):
    rig.baml.result = None
    resp = await rig.run()
    assert resp.result is None


# c
@pytest.mark.asyncio
async def test_the_instance_preemption_path_carries_it_too(rig, monkeypatch):
    eo = rig.eo
    subject = SCI

    async def _ri(**kw):
        return subject, {"instance_match": "exact", "instance_provider": "p"}

    async def _unanswerable(uri, domains):
        return False

    monkeypatch.setattr(eo, "_resolve_instance", _ri)
    monkeypatch.setattr(eo, "_preempted_subject_is_unanswerable", _unanswerable)
    rig.baml.identifier = "some-individual"
    rig.baml.result = _RC(PLATFORM, ["by platform"])
    resp = await rig.run()
    assert resp.resolved_uri == subject
    assert resp.result == {"kind": PLATFORM, "qualifiers": ["by platform"]}


# d
def test_every_response_built_after_the_classifier_call_carries_result():
    src = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "resolve")
    call_line = next(
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "ClassifyDomainIntent")
    responses = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "SemanticResolutionResponse"]
    early = [n for n in responses if n.lineno < call_line]
    late = [n for n in responses if n.lineno > call_line]
    assert early, "positive control: the walker must see the returns before the classifier call"
    assert len(late) >= 5, f"census found only {len(late)} responses after the classifier call"
    missing = [n.lineno for n in late if "result" not in {k.arg for k in n.keywords}]
    assert not missing, f"SemanticResolutionResponse without result= at lines {missing}"
