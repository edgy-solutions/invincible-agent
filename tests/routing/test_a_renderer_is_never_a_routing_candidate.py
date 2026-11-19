"""A renderer is never a routing candidate, and dispatch abstains if one arrives.

RULED 2026-11-19 (architect): "a renderer is not a routable verb. Routing's candidate set excludes
any row with no endpoint, and dispatch refuses with a clear abstention if one ever arrives."

A renderer is a `mesh:rendersAs` edge: it has an `iri` and NO `endpoint_url`. Every arm here keys on
the ABSENT ENDPOINT (null and "" alike), never on a verb name, so the class is sealed rather than
the one verb that surfaced it.

  A  the Cypher: every statement that decides "is there a verb here" carries the endpoint
     predicate, in BOTH copies (main.py and mesh_graph.py). The statements are derived from the
     module attributes, not retyped. A real Neo4j is needed to RUN the filter; the stub driver
     returns whatever rows it is handed whatever the text says, so this text arm is the only
     coverage the Cypher filter has offline. That limit covers arm C too (served classes).
  B  the classifier's candidates: both call sites of `_predicate_row` drop a row with no endpoint;
     a routable row on the same store is the control.
  D  dispatch: `execute_subtask` abstains on a matched predicate with no endpoint, makes no HTTP
     call and no generalist fallback; the same predicate with an endpoint is the control.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402
from agent_fleet.ontology_service import mesh_graph  # noqa: E402

# The endpoint predicate, whitespace-tolerant, in the form the ruling's precedent uses.
_PREDICATE = re.compile(r"coalesce\(\s*r\.endpoint_url\s*,\s*''\s*\)\s*<>\s*''")


def _strip_comments(cypher: str) -> str:
    return "\n".join(ln.split("//", 1)[0] for ln in cypher.splitlines())


# ── the engine-o module and its existing store doubles, REUSED not retyped ───────────────────

_HARNESS_PATH = _REPO / "tests" / "test_the_migrated_predicate_route_returns_the_same_rows.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("_renderer_seal_harness", str(_HARNESS_PATH))
    mod = importlib.util.module_from_spec(spec)
    try:
        sys.modules["_renderer_seal_harness"] = mod
        spec.loader.exec_module(mod)
        mod.MAIN = mod._load_main()
    finally:
        sys.modules.pop("_renderer_seal_harness", None)
    return mod


# ── arm A: the Cypher, both copies ───────────────────────────────────────────────────────────


def _statements(harness):
    m = harness.MAIN
    legs = m._FIND_COMPAT_VERBS_CYPHER.split("\nUNION ALL\n")
    out = {f"main._FIND_COMPAT_VERBS_CYPHER leg {i + 1}": leg for i, leg in enumerate(legs)}
    # The served-classes statement has a second, referent-root UNION arm that matches no verb edge.
    out["main._SERVED_CLASSES_CYPHER"] = m._SERVED_CLASSES_CYPHER.split("\nUNION\n")[0]
    out["main._OPERABLE_SUBJECTS_CYPHER"] = m._OPERABLE_SUBJECTS_CYPHER
    out["mesh_graph.VERBS_FOR_CYPHER"] = mesh_graph.VERBS_FOR_CYPHER
    out["mesh_graph.CLASSES_WITH_A_VERB_CYPHER"] = mesh_graph.CLASSES_WITH_A_VERB_CYPHER.split(
        "\nUNION\n"
    )[0]
    out["mesh_graph.OPERABLE_SUBJECTS_CYPHER"] = mesh_graph.OPERABLE_SUBJECTS_CYPHER
    return out


def test_a1_the_derived_statement_list_is_not_empty_and_covers_both_copies(harness):
    names = list(_statements(harness))
    assert len([n for n in names if n.startswith("main._FIND_COMPAT_VERBS_CYPHER")]) == 3
    assert any(n.startswith("mesh_graph.") for n in names)
    assert any(n.startswith("main._") and "COMPAT" not in n for n in names)


def test_a2_every_statement_that_matches_a_verb_edge_requires_an_endpoint(harness):
    missing = [
        name
        for name, text in _statements(harness).items()
        if not _PREDICATE.search(_strip_comments(text))
    ]
    assert not missing, f"a renderer (no endpoint) can pass through: {missing}"


def test_a3_the_predicate_is_a_conjunct_not_a_comment_or_a_return_column(harness):
    # The predicate must sit in a WHERE, ahead of the RETURN, in each statement.
    for name, text in _statements(harness).items():
        body = _strip_comments(text)
        hit = _PREDICATE.search(body)
        assert hit, name
        before = body[: hit.start()]
        assert "WHERE" in before, name
        assert "RETURN" not in before.split("WHERE")[-1], name


def test_a4_the_predicate_detector_fires_on_the_unfiltered_text():
    # Positive control: the detector must be able to say "absent".
    assert not _PREDICATE.search("MATCH (a)-[r]->(b) WHERE r.iri IS NOT NULL RETURN a")
    assert _PREDICATE.search("WHERE r.iri IS NOT NULL AND coalesce(r.endpoint_url, '') <> ''")


# ── arm B: the classifier's candidates, both call sites ──────────────────────────────────────

_ROUTABLE = {
    "verb_iri": "mesh:routableVerb", "verb_local": "routableVerb", "endpoint_url": "http://e/x",
    "domains": ["MAINTENANCE"], "description": "routable",
}


def _renderer(**over):
    return dict({"verb_iri": "mesh:aRenderer", "verb_local": "aRenderer",
                 "domains": ["MAINTENANCE"], "description": "renders"}, **over)


_ABSENT = {"null": {"endpoint_url": None}, "empty": {"endpoint_url": ""}, "missing": {}}


@pytest.mark.parametrize("on", [False, True], ids=["incumbent_arm", "mesh_arm"])
@pytest.mark.parametrize("shape", list(_ABSENT))
def test_b1_a_row_with_no_endpoint_is_not_a_candidate(harness, monkeypatch, on, shape):
    objs = [harness._Obj(_renderer(**_ABSENT[shape]), 0.95), harness._Obj(_ROUTABLE, 0.60)]
    rows, _, _ = harness._pool(harness.MAIN, monkeypatch, on=on, objs=objs)
    iris = [r["verb_iri"] for r in rows]
    assert "mesh:aRenderer" not in iris
    assert all(r["endpoint"] for r in rows)
    # THE CONTROL: the routable row on the same store, scored LOWER, still arrives.
    assert "mesh:routableVerb" in iris


@pytest.mark.parametrize("on", [False, True], ids=["incumbent_arm", "mesh_arm"])
def test_b2_the_control_alone_is_returned_unchanged(harness, monkeypatch, on):
    rows, _, _ = harness._pool(
        harness.MAIN, monkeypatch, on=on, objs=[harness._Obj(_ROUTABLE, 0.60)]
    )
    assert [r["verb_iri"] for r in rows] == ["mesh:routableVerb"]


# ── arm D: dispatch abstains ─────────────────────────────────────────────────────────────────


class _Resp:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"token": "CALLER-TOKEN-x"}


class _Stop(BaseException):
    """Ends the routed path at its first HTTP call (the control)."""


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Ctx:
    run_id = "run-1"
    log = _Log()

    def __init__(self):
        self.events = []

    def get_mapping_key(self):
        return "task_0"

    def log_event(self, ev):
        self.events.append(
            (list(ev.asset_key.path), {k: v.value for k, v in ev.metadata.items()})
        )


class _Cfg:
    user_query = "show it as a table"
    user_persona = "PORTFOLIO_LEAD"
    user_email = "alice@example.com"
    user_id = "alice"
    trace_id = "t"
    session_id = "s"
    thread_id = "th"
    entitled_domains = ["MAINTENANCE"]
    entity_refs = None
    pre_resolved = None
    predicate_fallback_score_threshold = 0.5
    slots = None
    spoken_slot = ""
    spoken_answer = ""
    bound_slots = None


_TASK = {"sub_query": "show it as a table"}
_TEL = {"fallback_reason": "", "subject_uri": "mesh:Thing"}


@pytest.fixture
def drive(monkeypatch):
    record = {"http": [], "fallbacks": []}

    class _Requests:
        class exceptions:  # noqa: N801
            RequestException = ValueError

        @staticmethod
        def post(url, *a, **k):
            record["http"].append(url)
            if str(url).endswith("/internal/identity/redeem"):
                return _Resp()
            raise _Stop()

    def _run(predicate):
        ctx = _Ctx()
        monkeypatch.setattr(ds, "_classify_route",
                            lambda *a, **k: (ds._ROUTING_MATCHED, predicate, dict(_TEL)))
        monkeypatch.setattr(ds, "_log_subtask_route_assets", lambda *a, **k: None)
        monkeypatch.setattr(
            ds, "_call_engine_a_fallback",
            lambda *a, **k: record["fallbacks"].append(k) or {"route_status": "fallback"},
        )
        monkeypatch.setattr(ds, "requests", _Requests)
        monkeypatch.setattr(
            "agent_fleet.utils.service_identity.mint_supervisor_token",
            lambda *a, **k: "svc.token.sig", raising=False,
        )
        try:
            out = ds.execute_subtask.compute_fn.decorated_fn(ctx, _Cfg(), dict(_TASK))
        except _Stop:
            out = None
        except Exception as exc:  # noqa: BLE001  the control may fail AFTER its HTTP call
            out = exc
        return ctx, out

    _run.record = record
    return _run


_VERB = "mesh:aRenderer"


@pytest.mark.parametrize("endpoint", ["", None, "   ", "<missing>"], ids=["empty", "none", "blank", "missing"])
def test_d1_a_matched_predicate_with_no_endpoint_abstains(drive, endpoint):
    pred = {"verb_iri": _VERB, "score": 0.99, "owner_persona": "ANALYST"}
    if endpoint != "<missing>":
        pred["endpoint"] = endpoint
    ctx, out = drive(pred)
    assert isinstance(out, dict), out
    assert out["route_status"] == "abstained"
    assert out["fallback_reason"] == "no_endpoint"
    assert out["predicate_verb_iri"] == _VERB
    er = out["expert_response"]
    assert er["status"] == "no_endpoint" and er["reason"] == "no_endpoint"
    assert er["message"].strip() and _VERB in er["message"]
    assert er["candidates"] == [] and er["data"] == "" and er["sources"] == []
    assert drive.record["http"] == []
    assert drive.record["fallbacks"] == []
    decisions = [m for k, m in ctx.events if k == ["subtask_slots_decision"]]
    assert len(decisions) == 1
    assert decisions[0]["disposition"] == "abstain"
    assert decisions[0]["no_verb_reason"] == "no_endpoint"
    assert decisions[0]["rejected_verb_iri"] == _VERB
    assert decisions[0]["verb_iri"] == ""


def test_d2_the_control_a_real_endpoint_reaches_the_http_double(drive):
    pred = {"verb_iri": "mesh:aRoutableVerb", "score": 0.99, "owner_persona": "ANALYST",
            "endpoint": "http://engine.example/run"}
    _, out = drive(pred)
    assert "http://engine.example/run" in drive.record["http"], out
    assert drive.record["fallbacks"] == []
