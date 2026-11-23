"""The live path's verb pick writes its routing_decision audit row (Engine O /classify_predicate).

MEASURED by Lane 1 on the live sandbox: `_emit_routing_decision` was called only from
`/search_predicates`, which the supervisor no longer calls (the verb is picked in
`/classify_predicate`). Engine O logged 0 rows since the roll, so the row's `user_id` and
`entitled_domains` -- the audit of the question -- never appeared for a supervisor-routed question.

Defended per EXIT, not per happy path: the Contract-B short-circuit, no candidates (with and
without a compat set), the classifier's UNKNOWN, the classifier's error (502 still raised, row
written before it) and a search error each write EXACTLY ONE row. The control that the capture
works is the pick test, which reads its row through the same handler as every other.

Rows are captured with a handler on `iagent.routing.audit` (propagate=False, so caplog cannot).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.routing.test_adr0019_engine_o_contract_a import (  # noqa: E402,F401
    _BAMLRecorder,
    ontology_main,
)
from tests.routing.test_adr0019_contracts import (  # noqa: E402,F401
    ClassifyStub,
    ResolveStub,
    VerbStub,
    _CallCounter,
    _FakeCtx,
    _build_dispatcher,
    supervisor_mod,
)

_AUDIT = "iagent.routing.audit"

# Two ranked candidates, the second the lower score. Everything the asserts compare is derived
# from this list, never retyped.
CANDS = [
    {"verb_iri": "mesh:verbHigh", "endpoint": "http://engine-high/x", "score": 0.9,
     "domains": ["MAINTENANCE"], "cost_class": "cheap", "input_uri": "mro:Thing",
     "description": "high", "verb_type": "ObjectProperty", "owner_persona": "AUDITOR"},
    {"verb_iri": "mesh:verbLow", "endpoint": "http://engine-low/x", "score": 0.5,
     "domains": [], "cost_class": "slow", "input_uri": "mro:Thing",
     "description": "low", "verb_type": "ObjectProperty", "owner_persona": "AUDITOR"},
]


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.rows: list[dict] = []

    def emit(self, record):
        self.rows.append(json.loads(record.getMessage()))


@pytest.fixture
def rows():
    h = _Capture()
    lg = logging.getLogger(_AUDIT)
    lg.addHandler(h)
    try:
        yield h.rows
    finally:
        lg.removeHandler(h)


def _stub(eo, monkeypatch, *, pick="UNKNOWN", cands=CANDS, confidence=0.77,
          reasoning="stub reasoning", baml_raises=False, search_raises=False):
    class _B(_BAMLRecorder):
        async def ClassifyPredicate(self, **kw):
            if baml_raises:
                raise RuntimeError("baml down")
            return await super().ClassifyPredicate(**kw)

    monkeypatch.setattr(eo, "b", _B(response_iri=pick, response_confidence=confidence,
                                    response_reasoning=reasoning))

    async def _search(*a, **k):
        if search_raises:
            raise RuntimeError("weaviate down")
        return [dict(c) for c in cands]
    monkeypatch.setattr(eo, "predicate_hybrid_search", _search)

    # A VERIFIED caller: `_bound` replaces the body's identity and grant with the token's. Here
    # the verified caller is the one the body names, so the row's user_id and domains are the
    # request's own and the asserts can compare against what was sent.
    async def _bound_as_sent(request, **kw):
        return request, None
    monkeypatch.setattr(eo, "_bound", _bound_as_sent)


def _req(eo, **over):
    # compatible_verb_iris names the candidates, so the request is NOT the Contract-B
    # short-circuit (a resolved subject with an empty compat list is).
    kw = dict(query="what feeds this table", subject_uri="mro:Thing",
              compatible_verb_iris=[c["verb_iri"] for c in CANDS],
              user_email="alice@example.invalid", entitled_domains=["maintenance", "Data_Eng"],
              request_id="req-123", audit_source="canary")
    kw.update(over)
    return eo.ClassifyPredicateRequest(**kw)


def _run(eo, **over):
    return asyncio.run(eo.classify_predicate(_req(eo, **over)))


def test_a_pick_writes_one_row_that_names_the_person_and_the_pick(ontology_main, monkeypatch, rows):
    eo = ontology_main
    picked = CANDS[0]
    _stub(eo, monkeypatch, pick=picked["verb_iri"])
    req = _req(eo)
    resp = asyncio.run(eo.classify_predicate(req))
    assert resp.resolved_verb_iri == picked["verb_iri"]
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "routing_decision"
    assert row["endpoint"] == "/classify_predicate"
    assert row["user_id"] == req.user_email
    assert row["entitled_domains"] == [d.upper() for d in req.entitled_domains]
    assert row["request_id"] == req.request_id
    assert row["source"] == req.audit_source
    assert row["sub_query"] == req.query
    assert row["picked_verb"] == picked["verb_iri"]
    assert row["picked_engine"] == picked["endpoint"]
    assert row["pick_score"] == picked["score"]
    assert row["pick_margin"] == pytest.approx(picked["score"] - CANDS[1]["score"])
    assert row["fallback_reason"] is None
    assert [c["verb_iri"] for c in row["candidates_raw"]] == [c["verb_iri"] for c in CANDS]
    assert set(row["candidates_raw"][0]) == {"verb_iri", "endpoint", "score", "domains", "cost_class"}
    assert row["classifier_confidence"] == 0.77
    assert row["classifier_reasoning"] == "stub reasoning"
    assert row["search_ms"] >= 0 and row["total_ms"] >= row["search_ms"]


def test_a_lower_ranked_pick_has_a_negative_margin(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, pick=CANDS[1]["verb_iri"])
    _run(eo)
    assert len(rows) == 1
    assert rows[0]["picked_verb"] == CANDS[1]["verb_iri"]
    assert rows[0]["pick_margin"] == pytest.approx(CANDS[1]["score"] - CANDS[0]["score"])
    assert rows[0]["pick_margin"] < 0


def _assert_non_pick(rows, reason):
    assert len(rows) == 1, rows
    assert rows[0]["fallback_reason"] == reason
    assert rows[0]["picked_verb"] is None and rows[0]["picked_engine"] is None
    assert rows[0]["pick_score"] is None and rows[0]["pick_margin"] is None
    assert rows[0]["endpoint"] == "/classify_predicate"
    assert rows[0]["user_id"] == "alice@example.invalid"
    assert rows[0]["entitled_domains"] == ["MAINTENANCE", "DATA_ENG"]


def test_contract_b_short_circuit_writes_its_row(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch)
    resp = _run(eo, compatible_verb_iris=[])
    assert resp.classify_called is False
    _assert_non_pick(rows, "contract_b_no_compatible_verb")
    assert rows[0]["candidates_raw"] == []
    assert rows[0]["classifier_confidence"] == 0.0
    assert rows[0]["classifier_reasoning"] == resp.reasoning


def test_no_candidates_with_an_empty_compat_set(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, cands=[])
    resp = _run(eo, subject_uri="UNKNOWN", compatible_verb_iris=[])
    _assert_non_pick(rows, "no_predicate_matched")
    assert rows[0]["classifier_reasoning"] == resp.reasoning
    assert rows[0]["classifier_confidence"] == 0.0


def test_no_candidates_with_a_compat_set_is_the_conjunctive_read_invariant(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, cands=CANDS)
    # none of the candidates is in the compat set -> the intersection is empty
    _run(eo, compatible_verb_iris=["mesh:notRegistered"])
    _assert_non_pick(rows, "conjunctive_read_invariant")


def test_a_classifier_unknown_writes_its_row(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, pick="UNKNOWN", confidence=0.1, reasoning="declined")
    resp = _run(eo)
    assert resp.resolved_verb_iri == "UNKNOWN"
    _assert_non_pick(rows, "classifier_unknown")
    assert len(rows[0]["candidates_raw"]) == len(CANDS)
    assert rows[0]["classifier_confidence"] == 0.1
    assert rows[0]["classifier_reasoning"] == "declined"


def test_a_classifier_error_writes_its_row_and_still_raises_502(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, baml_raises=True)
    with pytest.raises(HTTPException) as ei:
        _run(eo)
    assert ei.value.status_code == 502
    _assert_non_pick(rows, "classifier_error")
    assert rows[0]["classifier_reasoning"] == "RuntimeError"  # the type, never the message
    assert "baml down" not in str(rows[0])


def test_a_search_error_writes_its_row_and_raises_the_same_error(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, search_raises=True)
    with pytest.raises(RuntimeError, match="weaviate down"):
        _run(eo)
    _assert_non_pick(rows, "search_error")
    assert rows[0]["classifier_reasoning"] == "RuntimeError"  # the type, never the message
    assert "weaviate down" not in str(rows[0])


def test_defaults_when_no_request_id_or_source_is_sent(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, pick=CANDS[0]["verb_iri"])
    _run(eo, request_id=None, audit_source=None)
    assert rows[0]["source"] == "user_request"
    assert isinstance(rows[0]["request_id"], str) and rows[0]["request_id"]


def test_an_emit_failure_never_fails_the_request(ontology_main, monkeypatch, rows):
    eo = ontology_main
    _stub(eo, monkeypatch, pick=CANDS[0]["verb_iri"])
    good = _run(eo).model_dump()
    assert len(rows) == 1

    class _Boom(logging.Handler):
        def emit(self, record):
            raise RuntimeError("audit sink down")

    boom = _Boom()
    lg = logging.getLogger(_AUDIT)
    lg.addHandler(boom)
    try:
        after = _run(eo).model_dump()
    finally:
        lg.removeHandler(boom)
    assert after == good


def _hits():
    return [{**c, "output_uri": "mro:Out", "requires_human_approval": False} for c in CANDS]


def test_search_predicates_row_keeps_its_shape_with_null_classifier_fields(ontology_main, monkeypatch, rows):
    """Absence with its control: the control that the capture works is the pick test above."""
    eo = ontology_main

    class _Cs:
        def exists(self, n):
            return True

    class _Client:
        collections = _Cs()

    monkeypatch.setattr(eo, "_WEAVIATE_CLIENT", _Client())
    # the module is loaded by path in a fixture; its response models need it importable by name
    monkeypatch.setitem(sys.modules, eo.__name__, eo)
    eo.SearchPredicatesResponse.model_rebuild(force=True)

    async def _search(*a, **k):
        return _hits()
    monkeypatch.setattr(eo, "predicate_hybrid_search", _search)
    req = eo.SearchPredicatesRequest(query="q", entitled_domains=["maintenance"],
                                     user_email="alice@example.invalid", user_id="u-1")
    asyncio.run(eo.search_predicates(req))
    assert len(rows) == 1
    assert rows[0]["endpoint"] == "/search_predicates"
    assert rows[0]["classifier_confidence"] is None
    assert rows[0]["classifier_reasoning"] is None
    assert rows[0]["picked_verb"] == CANDS[0]["verb_iri"]


def test_the_supervisor_sends_its_run_id_and_audit_source(supervisor_mod, monkeypatch):
    class _Ctx(_FakeCtx):
        run_id = "dagster-run-42"

    counter = _CallCounter()
    verb = VerbStub(verb_iri="mesh:verbHigh", input_uri="mro:Thing", domains=["MAINTENANCE"])
    monkeypatch.setattr(
        supervisor_mod.requests, "post",
        _build_dispatcher(ResolveStub(subject_uri="mro:Thing"), [verb],
                          ClassifyStub(verb_iri="UNKNOWN"), counter),
    )
    monkeypatch.setattr(supervisor_mod, "_redeem_caller_token", lambda ctx, who, leg="call": "tok",
                        raising=False)
    supervisor_mod._classify_route(_Ctx(), "what feeds this table", ["MAINTENANCE"], "MAINTENANCE",
                                   user_email="alice@example.invalid")
    assert len(counter.classify_payloads) == 1
    sent = counter.classify_payloads[0]
    assert sent["request_id"] == _Ctx.run_id
    assert sent["audit_source"] == "user_request"
