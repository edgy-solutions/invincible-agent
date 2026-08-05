"""Tests for the ADR-0008 routing-fallback logic in
``src/iagent/defs/dynamic_supervisor.py``.

The decision points the ADR locks down:

* ``infra_error`` from Engine O → abort the subtask. **Do not** mask
  with the LLM fallback (would hide the outage signal).
* ``no_match`` → fall back to Engine A with reason="no_predicate_matched".
* ``matched`` with top score >= threshold → route to the matched specialist.
* ``matched`` with top score <  threshold → fall back to Engine A with
  reason="low_confidence" and the rejected predicate's verb_iri.

We exercise ``_resolve_predicate_endpoint`` (4-way status disambiguation)
and ``_call_engine_a_fallback`` (payload + structured-log emit) directly,
with stubbed ``requests``. The Dagster ``@op`` wrapper around
``execute_subtask`` itself is integration-tested in the cluster — here we
focus on the policy decisions the ADR makes load-bearing.
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
# Stubs — keep heavy deps out of the import chain
# ---------------------------------------------------------------------------
def _install_stubs():
    if "baml_client" not in sys.modules:
        bc = types.ModuleType("baml_client")
        bc.b = object()
        sys.modules["baml_client"] = bc
    if "dagster" not in sys.modules:
        d = types.ModuleType("dagster")
        # Minimal surface so import-time decorators don't NameError.
        class _Cfg:
            """Stand-in for ``dagster.Config``. Accepts arbitrary kwargs and
            exposes them as attributes — close enough for testing the
            supervisor's *use* of config fields without booting Dagster's
            pydantic stack."""
            def __init__(self, **kwargs):
                # Honor class-level annotations as defaults
                for name, default in self.__class__.__dict__.items():
                    if name.startswith("_") or callable(default):
                        continue
                    setattr(self, name, default)
                for k, v in kwargs.items():
                    setattr(self, k, v)
        d.Config = _Cfg
        d.In = lambda *a, **k: None
        d.Out = lambda *a, **k: None
        d.DynamicOut = lambda *a, **k: None
        d.DynamicOutput = lambda *a, **k: None
        d.Output = lambda *a, **k: None
        d.MetadataValue = type("MetadataValue", (), {
            "text": staticmethod(lambda s: s),
            "json": staticmethod(lambda j: j),
        })
        d.AssetMaterialization = lambda *a, **k: None
        d.op = lambda *a, **k: (lambda f: f)
        d.job = lambda *a, **k: (lambda f: f)
        d.in_process_executor = object()
        class _Cfg2:
            @staticmethod
            def configured(_cfg): return object()
        d.multiprocess_executor = _Cfg2()
        sys.modules["dagster"] = d


@pytest.fixture(scope="module")
def supervisor_mod():
    _install_stubs()
    spec = importlib.util.spec_from_file_location(
        "dynamic_supervisor_fallback_test",
        str(_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fake context / requests
# ---------------------------------------------------------------------------
class _FakeLog:
    def __init__(self):
        self.lines: list[tuple[str, str]] = []
    def info(self, msg, *args):
        self.lines.append(("info", msg % args if args else msg))
    def warning(self, msg, *args):
        self.lines.append(("warning", msg % args if args else msg))
    def error(self, msg, *args):
        self.lines.append(("error", msg % args if args else msg))


class _FakeCtx:
    def __init__(self):
        self.log = _FakeLog()


class _FakeResp:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


# ---------------------------------------------------------------------------
# _classify_route — three-stage SPO disambiguation (ADR-0018 + addendum)
# ---------------------------------------------------------------------------
#
# The original tests here exercised _resolve_predicate_endpoint, which
# was removed in ADR-0018 (5ed222a) and supplanted by _classify_route.
# Same 4-way status outcomes (matched / no_match / infra_error / and
# the new compatibility-empty branch); same fallback policy; different
# orchestrator. The tests below mock the three HTTP endpoints
# (/resolve, /find_compatible_verbs, /classify_predicate) so the
# routing decision graph is exercised end-to-end without requiring
# a live Engine O.
#
# Endpoint shape recap (matches ontology_service/main.py):
#   /resolve  ⇒ {resolved_uri, confidence_score, reasoning}
#   /find_compatible_verbs ⇒ {subject_uri, verbs: [{verb_iri, ...}]}
#   /classify_predicate ⇒ {resolved_verb_iri, confidence_score,
#                          reasoning, predicate?, candidate_verb_iris}

def _route_with_endpoints(supervisor_mod, monkeypatch, responses: dict):
    """Helper: monkeypatch requests.post to route by URL substring.

    ``responses`` maps endpoint name → either a _FakeResp/value, or a
    callable that raises (for infra-error tests). Endpoints we don't
    set explicitly default to a safe empty response.
    """
    def _dispatch(url, *args, **kwargs):
        for key, value in responses.items():
            if key in url:
                if callable(value) and not isinstance(value, _FakeResp):
                    return value(url, *args, **kwargs)
                return value
        return _FakeResp({})
    monkeypatch.setattr(supervisor_mod.requests, "post", _dispatch)
    return _FakeCtx()


def test_matched_returns_predicate_dict(supervisor_mod, monkeypatch):
    """End-to-end happy path. /resolve picks subject, /find_compatible_verbs
    returns one verb (Neo4j decisive at N=1), /classify_predicate returns
    matched. _classify_route plumbs the full predicate dict through with
    the LLM's confidence as ``score``."""
    ctx = _route_with_endpoints(supervisor_mod, monkeypatch, {
        "/resolve": _FakeResp({
            "resolved_uri": "mro:WorkInstruction",
            "confidence_score": 0.95,
            "reasoning": "WI",
        }),
        "/find_compatible_verbs": _FakeResp({
            "subject_uri": "mro:WorkInstruction",
            "verbs": [{
                "verb_iri": "mesh:queryKnowledgeGraph",
                "verb_local": "queryKnowledgeGraph",
                "input_uri": "mesh:GraphQuery",
                "output_uri": "mesh:GraphExpertResponse",
                "endpoint_url": "http://engine-e/query_graph",
                "owner_persona": "AUDITOR",
                "domains": ["MAINTENANCE"],
            }],
        }),
        "/classify_predicate": _FakeResp({
            "resolved_verb_iri": "mesh:queryKnowledgeGraph",
            "confidence_score": 0.82,
            "reasoning": "graph match",
            "predicate": {
                "verb_iri": "mesh:queryKnowledgeGraph",
                "endpoint": "http://engine-e/query_graph",
                "owner_persona": "AUDITOR",
                "domains": ["MAINTENANCE"],
            },
            "candidate_verb_iris": ["mesh:queryKnowledgeGraph"],
        }),
    })

    status, pred, telemetry = supervisor_mod._classify_route(
        ctx, "find vibration symptoms", ["MAINTENANCE"], "MAINTENANCE",
    )
    assert status == supervisor_mod._ROUTING_MATCHED
    assert pred["verb_iri"] == "mesh:queryKnowledgeGraph"
    # LLM confidence replaces BM25 score on the predicate dict.
    assert pred["score"] == 0.82
    assert telemetry["subject_uri"] == "mro:WorkInstruction"
    assert telemetry["verb_iri"] == "mesh:queryKnowledgeGraph"


def test_no_match_returns_none(supervisor_mod, monkeypatch):
    """/resolve UNKNOWN + /classify_predicate UNKNOWN → no_match.
    The addendum's compatibility-empty shortcut doesn't fire when
    subject_uri itself is UNKNOWN — we fall through unconstrained."""
    ctx = _route_with_endpoints(supervisor_mod, monkeypatch, {
        "/resolve": _FakeResp({
            "resolved_uri": "UNKNOWN",
            "confidence_score": 0.0,
            "reasoning": "no match",
        }),
        "/classify_predicate": _FakeResp({
            "resolved_verb_iri": "UNKNOWN",
            "confidence_score": 0.0,
            "reasoning": "no fit",
            "predicate": None,
            "candidate_verb_iris": [],
        }),
    })
    status, pred, telemetry = supervisor_mod._classify_route(
        ctx, "do something weird", [], "MAINTENANCE",
    )
    assert status == supervisor_mod._ROUTING_NO_MATCH
    assert pred is None
    assert telemetry["subject_uri"] == "UNKNOWN"


def test_zero_compatible_verbs_is_no_match_without_llm(supervisor_mod, monkeypatch):
    """ADR-0018 addendum: subject resolves, but Neo4j marks zero verbs
    compatible → hard NO_MATCH without burning an LLM call on
    /classify_predicate. This is the Neo4j-as-reasoner contract: when
    the graph says no edge exists, route to the generalist fallback
    immediately."""
    classify_called = {"count": 0}
    def _count_classify(url, *a, **k):
        classify_called["count"] += 1
        return _FakeResp({
            "resolved_verb_iri": "UNKNOWN",
            "confidence_score": 0.0,
            "predicate": None,
            "candidate_verb_iris": [],
        })
    ctx = _route_with_endpoints(supervisor_mod, monkeypatch, {
        "/resolve": _FakeResp({
            "resolved_uri": "mro:WorkInstruction",
            "confidence_score": 0.99,
            "reasoning": "WI",
        }),
        "/find_compatible_verbs": _FakeResp({
            "subject_uri": "mro:WorkInstruction",
            "verbs": [],
        }),
        "/classify_predicate": _count_classify,
    })
    status, pred, telemetry = supervisor_mod._classify_route(
        ctx, "do something the graph rejects", [], "MAINTENANCE",
    )
    assert status == supervisor_mod._ROUTING_NO_MATCH
    assert pred is None
    # Critical: we did NOT call /classify_predicate. Neo4j's "no edge"
    # answer is decisive; an LLM call would be pure overhead.
    assert classify_called["count"] == 0


def test_http_503_returns_infra_error(supervisor_mod, monkeypatch):
    """/classify_predicate returns 503 → infra_error. Must NOT be
    conflated with no_match — different ADR-0008 branches."""
    ctx = _route_with_endpoints(supervisor_mod, monkeypatch, {
        "/resolve": _FakeResp({
            "resolved_uri": "mro:WorkInstruction",
            "confidence_score": 0.9,
            "reasoning": "WI",
        }),
        "/find_compatible_verbs": _FakeResp({
            "subject_uri": "mro:WorkInstruction",
            "verbs": [{
                "verb_iri": "mesh:queryKnowledgeGraph",
                "input_uri": "mesh:GraphQuery",
                "output_uri": "mesh:GraphExpertResponse",
            }],
        }),
        "/classify_predicate": _FakeResp(
            {"detail": "baml down"}, status_code=503,
        ),
    })
    status, pred, telemetry = supervisor_mod._classify_route(
        ctx, "q", [], "MAINTENANCE",
    )
    assert status == supervisor_mod._ROUTING_INFRA_ERROR
    assert pred is None
    assert "error" in telemetry


def test_network_exception_returns_infra_error(supervisor_mod, monkeypatch):
    """Connection refused / DNS / timeout on /classify_predicate →
    infra_error. /find_compatible_verbs network errors are non-fatal
    (we degrade to unconstrained classification), but a downed
    /classify_predicate IS fatal — the router cannot pick a verb."""
    def _resolve_ok(*a, **k):
        return _FakeResp({
            "resolved_uri": "mro:WorkInstruction",
            "confidence_score": 0.9,
            "reasoning": "WI",
        })
    def _compat_ok(*a, **k):
        return _FakeResp({
            "subject_uri": "mro:WorkInstruction",
            "verbs": [{
                "verb_iri": "mesh:queryKnowledgeGraph",
                "input_uri": "mesh:GraphQuery",
                "output_uri": "mesh:GraphExpertResponse",
            }],
        })
    def _classify_boom(*a, **k):
        raise ConnectionError("connection refused")
    ctx = _route_with_endpoints(supervisor_mod, monkeypatch, {
        "/resolve": _resolve_ok,
        "/find_compatible_verbs": _compat_ok,
        "/classify_predicate": _classify_boom,
    })
    status, pred, telemetry = supervisor_mod._classify_route(
        ctx, "q", [], "MAINTENANCE",
    )
    assert status == supervisor_mod._ROUTING_INFRA_ERROR
    assert pred is None


# ---------------------------------------------------------------------------
# _call_engine_a_fallback — payload shape + telemetry log line
# ---------------------------------------------------------------------------
def _make_config(supervisor_mod, **overrides):
    """Build a SupervisorQueryConfig with sensible defaults."""
    defaults = dict(
        user_query="find vibration",
        thread_id="thread-1",
        user_persona="MECHANIC",
        entitled_domains=["MAINTENANCE"],
        entity_refs=[],
        user_id="user-1",
        predicate_fallback_score_threshold=0.40,
    )
    defaults.update(overrides)
    return supervisor_mod.SupervisorQueryConfig(**defaults)


def test_fallback_payload_for_no_match(supervisor_mod, monkeypatch):
    """no_predicate_matched fallback → task_description=sub_query,
    fallback_reason set, rejected_verb_iri null."""
    captured: dict = {}
    def _capture_post(url, json, timeout, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResp({"status": "OK"})
    monkeypatch.setattr(supervisor_mod.requests, "post", _capture_post)

    ctx = _FakeCtx()
    config = _make_config(supervisor_mod)
    result = supervisor_mod._call_engine_a_fallback(
        ctx,
        sub_query="find vibration symptoms",
        config=config,
        fallback_reason="no_predicate_matched",
        fallback_score=None,
        rejected_predicate=None,
    )

    assert captured["url"].endswith("/analyze")
    assert captured["json"]["task_description"] == "find vibration symptoms"
    assert captured["json"]["dataset_id"] == "generalist_fallback"
    assert captured["json"]["fallback_reason"] == "no_predicate_matched"
    assert captured["json"]["fallback_score"] is None
    assert captured["json"]["rejected_verb_iri"] is None
    assert captured["json"]["user_persona"] == "MECHANIC"
    assert result["fallback_reason"] == "no_predicate_matched"
    assert result["predicate_verb_iri"] is None


def test_fallback_payload_for_low_confidence(supervisor_mod, monkeypatch):
    """low_confidence fallback → fallback_score plumbed, rejected_verb_iri set."""
    captured: dict = {}
    def _capture_post(url, json, timeout, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResp({"status": "OK"})
    monkeypatch.setattr(supervisor_mod.requests, "post", _capture_post)

    ctx = _FakeCtx()
    config = _make_config(supervisor_mod)
    rejected = {
        "verb_iri": "mesh:retrieveKnowledge",
        "score": 0.22,
    }
    supervisor_mod._call_engine_a_fallback(
        ctx,
        sub_query="ill-defined query",
        config=config,
        fallback_reason="low_confidence",
        fallback_score=0.22,
        rejected_predicate=rejected,
    )

    assert captured["json"]["fallback_reason"] == "low_confidence"
    assert captured["json"]["fallback_score"] == 0.22
    assert captured["json"]["rejected_verb_iri"] == "mesh:retrieveKnowledge"


def test_fallback_emits_telemetry_log_line(supervisor_mod, monkeypatch):
    """ADR-0008 telemetry: structured log scrapable as
    predicate_fallback_total{reason}. Verify the key tokens appear."""
    monkeypatch.setattr(
        supervisor_mod.requests, "post",
        lambda *a, **k: _FakeResp({"status": "OK"}),
    )
    ctx = _FakeCtx()
    config = _make_config(supervisor_mod)
    supervisor_mod._call_engine_a_fallback(
        ctx,
        sub_query="q",
        config=config,
        fallback_reason="low_confidence",
        fallback_score=0.30,
        rejected_predicate={"verb_iri": "x:y", "score": 0.30},
    )

    info_lines = [msg for level, msg in ctx.log.lines if level == "info"]
    assert any(
        "predicate_fallback_total" in line
        and "reason=low_confidence" in line
        for line in info_lines
    ), f"missing fallback counter log; got: {info_lines}"


# ---------------------------------------------------------------------------
# Threshold knob — env-tunable default, per-config override
# ---------------------------------------------------------------------------
def test_threshold_default_loaded_from_env(monkeypatch):
    """PREDICATE_FALLBACK_SCORE_THRESHOLD env reads at module import time.
    We re-import the module under a custom env to confirm the default flows
    through to the supervisor's class default."""
    monkeypatch.setenv("PREDICATE_FALLBACK_SCORE_THRESHOLD", "0.65")
    _install_stubs()
    sys.modules.pop("dynamic_supervisor_env_test", None)
    spec = importlib.util.spec_from_file_location(
        "dynamic_supervisor_env_test",
        str(_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._FALLBACK_SCORE_THRESHOLD_DEFAULT == pytest.approx(0.65)
