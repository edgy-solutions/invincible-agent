"""THE SUPERVISOR'S RESOLUTION IS PASSED IN, NEVER RE-DERIVED -- architect ruling 2026-10-20.

    "Engine A never re-resolves a subject the supervisor already resolved -- the resolution is
     passed in, not re-derived."
    "Supervisor limit 60s interim, measured against the model's p100, not guessed."

MEASURED 2026-10-20 (sandbox revision 199, Engine O log 03:30-04:16Z): 55 completed
`ClassifyDomainIntent` calls, max 52,553 ms. The supervisor's 30 s `/resolve` budget missed on
two runs (33.6 s, 34.5 s); on those runs Engine A re-resolved the same prompt 4 and 8 times,
each a full model call. Before this, the generalist hop sent a subject only when one grounded;
UNKNOWN and "unreachable" sent nothing, and Engine A re-derived them.

The OUTCOME now travels (`resolution_outcome`: resolved / unknown / unreachable) whenever the
supervisor ran /resolve, and Engine A re-resolves only when no outcome arrived.

Run: uv run --frozen pytest tests/routing/test_a_supervisor_resolution_is_never_re_derived.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_ANALYST = _REPO / "agent_fleet" / "restate_analyst" / "main.py"
_SUPERVISOR = _SRC / "iagent" / "defs" / "dynamic_supervisor.py"

#: The model's measured p100 for ClassifyDomainIntent, in seconds: 52,553 ms on 2026-10-20
#: (55 completed calls, sandbox revision 199, Engine O log 03:30-04:16Z).
MEASURED_P100_S = 52.553

_PORTFOLIO = "http://invincible-agent/idp#Portfolio"


# -- the supervisor side ---------------------------------------------------------------------

@pytest.fixture()
def sup():
    return pytest.importorskip("iagent.defs.dynamic_supervisor")


@pytest.fixture()
def fallback(monkeypatch, sup):
    """The real `_call_engine_a_fallback` with the HTTP hop captured; the body is the artifact."""
    sent: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"final_answer": "ok", "output_uri": "http://x#AgentResponse"}

    def _post(url, json=None, headers=None, timeout=None):  # noqa: A002
        sent.update(url=url, body=json)
        return _Resp()

    monkeypatch.setattr(sup.requests, "post", _post)

    class _Ctx:
        class log:
            @staticmethod
            def info(*a, **k):
                return None

            @staticmethod
            def warning(*a, **k):
                return None

    class _Cfg:
        user_persona = "PORTFOLIO_LEAD"
        entitled_domains = ["PORTFOLIO_PLANNING"]
        user_email = "alice@example.com"
        user_id = "alice"
        trace_id = ""
        session_id = ""

    def _go(telemetry):
        sent.clear()
        sup._call_engine_a_fallback(
            _Ctx(), sub_query="make me a portfolio canvas", config=_Cfg(),
            fallback_reason="no_predicate_matched", fallback_score=None,
            rejected_predicate=None, telemetry=telemetry,
        )
        return sent["body"]

    return _go


def _tele_resolved():
    return {"subject_uri": _PORTFOLIO, "subject_confidence": 0.96}


def _tele_unreachable(sup):
    return {"subject_uri": "UNKNOWN",
            "subject_reasoning": sup._RESOLVE_UNREACHABLE_PREFIX + "Read timed out"}


def _tele_unknown():
    return {"subject_uri": "UNKNOWN", "subject_reasoning": "no class fits"}


def test_a_resolved_subject_sends_the_outcome_and_the_subject(fallback):
    body = fallback(_tele_resolved())
    assert body["resolution_outcome"] == "resolved"
    assert body["resolved_subject_uri"] == _PORTFOLIO


def test_an_unreachable_resolve_sends_the_outcome_and_no_subject(fallback, sup):
    body = fallback(_tele_unreachable(sup))
    assert body["resolution_outcome"] == "unreachable"
    assert "resolved_subject_uri" not in body


def test_an_UNKNOWN_answer_sends_the_outcome_unknown(fallback):
    body = fallback(_tele_unknown())
    assert body["resolution_outcome"] == "unknown"
    assert "resolved_subject_uri" not in body


@pytest.mark.parametrize("telemetry", [{}, None, {"subject_confidence": 0.5}])
def test_control_no_subject_key_means_the_supervisor_never_resolved(fallback, telemetry):
    """The control: with no `subject_uri` key nothing was resolved, so no outcome is claimed and
    Engine A's legacy re-resolve stays legal."""
    body = fallback(telemetry)
    assert "resolution_outcome" not in body


# -- Engine A side ---------------------------------------------------------------------------

def _load_analyst():
    """`SUPERVISOR_RESOLUTION_OUTCOMES` and `_supplied_resolution` by AST path (the package
    drags Restate and smolagents in)."""
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_supplied_resolution":
            nodes.append(n)
        elif (isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SUPERVISOR_RESOLUTION_OUTCOMES"
                for t in n.targets)):
            nodes.append(n)
    assert len(nodes) == 2, "Engine A must define the outcome set and _supplied_resolution"
    ns: dict = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<analyst>", "exec"), ns)
    return ns


def test_engine_a_uses_a_resolved_subject():
    ns = _load_analyst()
    ctx = ns["_supplied_resolution"](
        {"resolved_subject_uri": f" {_PORTFOLIO} ", "resolved_instance_id": " i ",
         "resolution_outcome": "resolved"})
    assert ctx is not None and ctx["from_supervisor"] is True
    assert ctx["resolved_uri"] == _PORTFOLIO and ctx["instance_id"] == "i"


@pytest.mark.parametrize("outcome", ["unknown", "unreachable"])
def test_engine_a_does_not_re_derive_an_unknown_or_unreachable_outcome(outcome):
    ctx = _load_analyst()["_supplied_resolution"]({"resolution_outcome": outcome})
    assert ctx is not None, "the supervisor ran /resolve; Engine A must not run it again"
    assert ctx["from_supervisor"] is True
    assert ctx["resolved_uri"] == "UNKNOWN"
    assert ctx["resolution_outcome"] == outcome


def test_an_unrecognized_outcome_fails_closed():
    ctx = _load_analyst()["_supplied_resolution"]({"resolution_outcome": "garbage"})
    assert ctx is not None, "an unrecognized outcome re-opened the re-resolve"
    assert ctx["resolution_outcome"] == "unknown"


@pytest.mark.parametrize("request_", [{}, {"resolved_subject_uri": "   "}])
def test_control_no_supplied_resolution_leaves_the_legacy_re_resolve_legal(request_):
    assert _load_analyst()["_supplied_resolution"](request_) is None


def _analyze_fn():
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "analyze"]
    assert fns, "Engine A has no analyze handler"
    return fns[0]


def _is_resolve_ontology_run(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run" and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ctx" and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "resolve_ontology")


def test_wiring_the_re_resolve_is_reachable_only_when_nothing_was_supplied():
    fn = _analyze_fn()
    assign = next(
        (n for n in ast.walk(fn)
         if isinstance(n, ast.Assign)
         and any(isinstance(t, ast.Name) and t.id == "semantic_ctx" for t in n.targets)
         and isinstance(n.value, ast.Call)
         and isinstance(n.value.func, ast.Name)
         and n.value.func.id == "_supplied_resolution"),
        None)
    assert assign is not None, "semantic_ctx is not assigned from _supplied_resolution(...)"
    guard = next(
        (n for n in ast.walk(fn)
         if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
         and isinstance(n.test.left, ast.Name) and n.test.left.id == "semantic_ctx"
         and len(n.test.ops) == 1 and isinstance(n.test.ops[0], ast.Is)
         and isinstance(n.test.comparators[0], ast.Constant)
         and n.test.comparators[0].value is None),
        None)
    assert guard is not None, "no `if semantic_ctx is None:` guards the re-resolve"
    assert assign.lineno < guard.lineno
    runs = [n for n in ast.walk(fn) if _is_resolve_ontology_run(n)]
    assert len(runs) == 1
    inside = {id(x) for stmt in guard.body for x in ast.walk(stmt)}
    assert id(runs[0]) in inside, "ctx.run('resolve_ontology') is reachable outside the guard"


def _engine_a_outcomes():
    for n in ast.parse(_ANALYST.read_text(encoding="utf-8")).body:
        if (isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SUPERVISOR_RESOLUTION_OUTCOMES"
                for t in n.targets)):
            return set(ast.literal_eval(
                n.value.args[0] if isinstance(n.value, ast.Call) else n.value))
    raise AssertionError("SUPERVISOR_RESOLUTION_OUTCOMES not found")


def test_join_the_outcomes_the_supervisor_emits_are_the_ones_engine_a_knows(fallback, sup):
    emitted = {
        fallback(t)["resolution_outcome"]
        for t in (_tele_resolved(), _tele_unreachable(sup), _tele_unknown())
    }
    assert emitted == _engine_a_outcomes()


# -- the budget ------------------------------------------------------------------------------

def test_the_resolve_budget_covers_the_measured_p100(sup):
    assert sup.RESOLVE_SUBJECT_TIMEOUT_S >= MEASURED_P100_S


def test_the_resolve_post_uses_the_named_budget():
    tree = ast.parse(_SUPERVISOR.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve_subject")
    posts = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "post" and n.args and "/resolve" in ast.unparse(n.args[0])
    ]
    assert len(posts) == 1
    kw = {k.arg: k.value for k in posts[0].keywords}
    assert isinstance(kw.get("timeout"), ast.Name)
    assert kw["timeout"].id == "RESOLVE_SUBJECT_TIMEOUT_S"
