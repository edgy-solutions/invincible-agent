"""THE ROUTE'S OWN VERDICT, READ RATHER THAN INFERRED.

Two defects, one shape. `classify_called` used to be set True on any HTTP 200 from
/classify_predicate, overwriting engine-o's own `ClassifyPredicateResponse.classify_called` --
its two short-circuits report False and the supervisor silently disagreed; the INFRA_ERROR
return omitted the key entirely, which a reader cannot tell apart from "ran and returned
True" either. MEASURED 2026-09-08 on artifact-1-1788837904248: `confidence: 0.92,
classify_called: false`, a number only the classifier could have produced, recorded beside a
claim that it never ran.

The second: a MATCHED route's own telemetry carried no code at all (`fallback_reason` is
`None` on every matched route), so a reader reconstructing "why did this route end up here"
had nothing of the route's own to read and fell back to an EXCLUDED CANDIDATE's
`no_verb_in_scope` -- the gate's reason, mistaken for the route's.

Both are now read from the producer and validated against a closed enum
(`iagent_pure.routing_record.ROUTE_REASON_CODES`) rather than restated or left absent. This
file seals both arcs: `classify_called` behaviourally, against the real `_classify_route`;
`reason_code` at every point it is produced (`_classify_route`, `direct_dispatch.py`) and at
the one point both routes converge for rendering (`gateway._project_route_decision`); and the
builder's own validation (`routing_record` raising rather than defaulting).

Run: uv run pytest tests/routing/test_route_reason_is_recorded_not_inferred.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent import direct_dispatch as dd  # noqa: E402
from iagent_pure.routing_record import ROUTE_REASON_CODES, routing_record  # noqa: E402

_SUBJECT = "http://invincible-agent/mesh#Capability"
_VERB = "mesh:planCapabilityPath"
_ENDPOINT = "http://engine-p:8080/plan_capability_path"

_SUP_PATH = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_DD_PATH = _REPO / "src" / "iagent" / "direct_dispatch.py"


# ── the `sup` fixture, the stub harness, copied from test_pre_resolved_route_behaviour.py ──
#
# Reused rather than imported: that file's fixture is module-private (no __all__, not meant
# as a library), and the REUSE-IF-ALREADY-LOADED behaviour is keyed on sys.modules by file
# path regardless of which test file asks first, so two copies of this fixture never load
# the module twice.

@pytest.fixture(scope="session")
def sup():
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if f and Path(f).resolve() == _SUP_PATH.resolve():
            return mod
    spec = importlib.util.spec_from_file_location(
        "dynamic_supervisor_reason_code_test", str(_SUP_PATH),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Log:
    def __init__(self):
        self.lines = []

    def _rec(self, level, msg, *args):
        self.lines.append((level, msg % args if args else msg))

    def info(self, m, *a):
        self._rec("info", m, *a)

    def warning(self, m, *a):
        self._rec("warning", m, *a)

    def error(self, m, *a):
        self._rec("error", m, *a)

    def debug(self, m, *a):
        self._rec("debug", m, *a)


class _Ctx:
    def __init__(self):
        self.log = _Log()


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _dispatcher(calls: list[str], *, verb: str = _VERB, classify_payload: dict | None = None,
                 raise_on: str | None = None):
    """A `requests.post` stub for the FULL path: /resolve -> /find_compatible_verbs ->
    /classify_predicate. `classify_payload` is the literal dict /classify_predicate returns
    (controls `classify_called`); `raise_on` is an endpoint suffix that raises instead of
    responding, to drive the INFRA_ERROR branch.
    """
    def _post(url, *a, **k):
        suffix = url.rsplit("/", 1)[-1]
        calls.append(suffix)
        if raise_on and suffix == raise_on:
            raise RuntimeError("engine-o unreachable (test double)")
        if suffix == "resolve":
            return _Resp({
                "resolved_uri": _SUBJECT,
                "confidence_score": 0.9,
                "reasoning": "test resolve",
                "provenance": {"instance_id": ""},
            })
        if suffix == "find_compatible_verbs":
            return _Resp({"verbs": [{
                "verb_iri": verb,
                "verb_local": "planCapabilityPath",
                "input_uri": _SUBJECT,
                "output_uri": "http://invincible-agent/mesh#CapabilityPath",
                "endpoint_url": _ENDPOINT,
                "owner_persona": "PORTFOLIO_PLANNER",
                "domains": ["PORTFOLIO_PLANNING"],
                "cost_class": "cheap",
                "arity": "set",
                "slots": "[]",
            }]})
        if suffix == "classify_predicate":
            return _Resp(classify_payload if classify_payload is not None else {})
        return _Resp({})
    return _post


def _full_route(sup, monkeypatch, calls, **dispatcher_kwargs):
    """Routes the FULL path (no pre_resolved) so /classify_predicate is actually reached."""
    ctx = _Ctx()
    monkeypatch.setattr(sup.requests, "post", _dispatcher(calls, **dispatcher_kwargs))
    status, predicate, telemetry = sup._classify_route(
        ctx,
        "what is the capability path",
        ["PORTFOLIO_PLANNING"],
        routing_domain="PORTFOLIO_PLANNING",
    )
    return ctx, status, predicate, telemetry


# ── classify_called: read from engine-o, not inferred from the HTTP status ─────────────────

def test_classify_called_FALSE_with_a_resolved_UNKNOWN_is_recorded_not_inferred(sup, monkeypatch):
    """Engine-o classified and declined: HTTP 200, `classify_called: false`, UNKNOWN. The old
    code read the 200 as proof the classifier ran and recorded True regardless -- exactly the
    gap measured on artifact-1-1788837904248.

    MUTATION (run by hand against this arm): restore the literal at
    dynamic_supervisor.py:1396 to `"classify_called": True,`. This test goes RED (asserts
    False, observes True); the control below stays GREEN because it independently asserts
    True on a stub that also says True, which a reverted literal still satisfies by accident
    -- this arm is the one the literal cannot pass.
    """
    calls: list[str] = []
    ctx, status, predicate, telemetry = _full_route(
        sup, monkeypatch, calls,
        classify_payload={
            "resolved_verb_iri": "UNKNOWN", "confidence_score": 0.92,
            "classify_called": False, "candidate_verb_iris": [],
        },
    )
    assert status == sup._ROUTING_NO_MATCH
    assert telemetry["classify_called"] is False, (
        "engine-o said classify_called=False and the supervisor recorded something else"
    )
    assert telemetry["reason_code"] == "no_verb_classified"


def test_classify_called_TRUE_is_recorded_the_control(sup, monkeypatch):
    """THE CONTROL. Without it, a builder that always wrote False would also pass the arm
    above -- this is the case that must come back True."""
    calls: list[str] = []
    ctx, status, predicate, telemetry = _full_route(
        sup, monkeypatch, calls,
        classify_payload={
            "resolved_verb_iri": _VERB, "confidence_score": 0.85,
            "classify_called": True, "candidate_verb_iris": [_VERB],
        },
    )
    assert status == sup._ROUTING_MATCHED
    assert telemetry["classify_called"] is True
    assert telemetry["reason_code"] == "classified_match"


def test_classify_called_ABSENT_KEY_defaults_False_and_warns(sup, monkeypatch):
    """An HTTP 200 with no `classify_called` key at all is not evidence the classifier ran.
    Absence is a THIRD state, distinct from engine-o saying False, and both must read False
    -- with a warning, because an absent field silently defaulting is exactly the shape that
    goes unnoticed until someone reads telemetry that disagrees with a number next to it."""
    calls: list[str] = []
    ctx, status, predicate, telemetry = _full_route(
        sup, monkeypatch, calls,
        classify_payload={
            "resolved_verb_iri": _VERB, "confidence_score": 0.5,
            "candidate_verb_iris": [_VERB],
            # classify_called OMITTED on purpose.
        },
    )
    assert telemetry["classify_called"] is False
    assert any(
        level == "warning" and "omitted classify_called" in msg
        for level, msg in ctx.log.lines
    ), f"no warning logged for the omitted key; log={ctx.log.lines!r}"


def test_INFRA_ERROR_records_classify_called_False_and_reason_code_infra_error(sup, monkeypatch):
    """/classify_predicate unreachable: there is no response to read `classify_called` off
    of, so it must be recorded False explicitly rather than left absent -- an absent key
    here is the other half of the gap this file closes."""
    calls: list[str] = []
    ctx, status, predicate, telemetry = _full_route(
        sup, monkeypatch, calls, raise_on="classify_predicate",
    )
    assert status == sup._ROUTING_INFRA_ERROR
    assert telemetry["classify_called"] is False
    assert telemetry["reason_code"] == "infra_error"


# ── reason_code: the route's own verdict, carried through to the render seam ────────────────

def test_a_matched_classified_route_projects_reason_code_classified_match():
    """The LLM picked the verb via /classify_predicate; the projected `route_decision` must
    carry that verdict rather than leaving a reader to infer it from a neighbour."""
    from iagent.gateway import _project_route_decision

    record = routing_record(
        status="matched", subject_uri=_SUBJECT, subject_confidence=0.9,
        subject_instance_id="", subject_instance_label="",
        verb_iri=_VERB, verb_confidence=0.85, classify_called=True,
        candidate_count=1, subject_candidates=[], fallback_reason="",
        reason_code="classified_match", eligibility_excluded=[],
        acting_persona="PORTFOLIO_PLANNER", acting_domains=["PORTFOLIO_PLANNING"],
        sub_query="what is the capability path",
        predicate={
            "endpoint": _ENDPOINT, "provider": "", "owner_persona": "PORTFOLIO_PLANNER",
            "output_uri": "",
        },
    )
    projected = _project_route_decision(dd.materialization(**record))
    assert projected is not None
    assert projected["reason_code"] == "classified_match"
    assert projected["fallback"] is False


def test_a_pre_resolved_route_projects_reason_code_pre_resolved():
    """Dispatched directly from a prior turn's resolution -- no classifier call at all."""
    from iagent.gateway import _project_route_decision

    record = routing_record(
        status="matched", subject_uri=_SUBJECT, subject_confidence=0.0,
        subject_instance_id="", subject_instance_label="",
        verb_iri=_VERB, verb_confidence=0.0, classify_called=False,
        candidate_count=1, subject_candidates=[], fallback_reason="",
        reason_code="pre_resolved", eligibility_excluded=[],
        acting_persona="PORTFOLIO_PLANNER", acting_domains=["PORTFOLIO_PLANNING"],
        sub_query="what is the capability path",
        predicate={
            "endpoint": _ENDPOINT, "provider": "", "owner_persona": "PORTFOLIO_PLANNER",
            "output_uri": "",
        },
    )
    projected = _project_route_decision(dd.materialization(**record))
    assert projected is not None
    assert projected["reason_code"] == "pre_resolved"
    assert projected["fallback"] is False


def test_a_fallback_route_projects_its_own_reason_code():
    """A route that fell back to the generalist carries ITS code, not a borrowed one."""
    from iagent.gateway import _project_route_decision

    record = routing_record(
        status="no_match", subject_uri="UNKNOWN", subject_confidence=0.0,
        subject_instance_id="", subject_instance_label="",
        verb_iri="UNKNOWN", verb_confidence=0.0, classify_called=False,
        candidate_count=0, subject_candidates=[], fallback_reason="no_predicate_matched",
        reason_code="no_predicate_matched", eligibility_excluded=[],
        acting_persona="", acting_domains=[],
        sub_query="what is the capability path",
    )
    projected = _project_route_decision(dd.materialization(**record))
    assert projected is not None
    assert projected["reason_code"] == "no_predicate_matched"
    assert projected["fallback"] is True


# ── routing_record's own validation ──────────────────────────────────────────────────────

_RECORD_KWARGS_NO_REASON = dict(
    status="matched", subject_uri=_SUBJECT, subject_confidence=0.9,
    subject_instance_id="", subject_instance_label="",
    verb_iri=_VERB, verb_confidence=0.85, classify_called=True,
    candidate_count=1, subject_candidates=[], fallback_reason="",
    eligibility_excluded=[], acting_persona="", acting_domains=[],
    sub_query="q",
)


def test_routing_record_with_no_reason_code_raises_TypeError():
    """`reason_code` is required with no default -- a caller that forgets it fails loudly at
    the call, which is the whole point of making it a required keyword rather than a field
    that defaults to something plausible."""
    with pytest.raises(TypeError):
        routing_record(**_RECORD_KWARGS_NO_REASON)  # type: ignore[call-arg]


def test_routing_record_with_an_unknown_reason_code_raises_ValueError():
    with pytest.raises(ValueError):
        routing_record(**_RECORD_KWARGS_NO_REASON, reason_code="not_a_real_code")


# ── census: every fallback_reason literal either producer module can emit ──────────────────

def _literal_fallback_reasons(path: Path) -> tuple[set[str], set[str]]:
    """Every string literal `path`'s AST shows reaching a `fallback_reason` dict key or call
    keyword, plus every Name this walk gave up tracing (returned for diagnostic use, not
    asserted on here).

    WHAT THIS WALK CANNOT SEE: a value that reaches `fallback_reason` only through a
    TUPLE-UNPACKING assignment (`a, b, c = f()`), and a value that is a member of a frozenset
    consulted by membership test rather than ever assigned to the traced name itself.
    `instance_not_found` is exactly this shape in dynamic_supervisor.py -- it reaches
    `_fb_reason` only through the tuple-unpacked local `subject_abstention_reason`
    (`_resolve_subject`'s 8-tuple return), never as a literal assigned to `_fb_reason`, so
    the walk cannot find it. `test_every_fallback_reason_the_producers_can_emit_is_in_
    ROUTE_REASON_CODES` below asserts this gap by name rather than silently reporting a
    narrower census than it claims to.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    assigns: dict[str, list[ast.expr]] = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)):
            assigns.setdefault(n.targets[0].id, []).append(n.value)

    found: set[str] = set()
    unresolved: set[str] = set()

    def _resolve(node: ast.expr, seen: frozenset) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
            found.add(node.value)
        elif isinstance(node, ast.IfExp):
            _resolve(node.body, seen)
            _resolve(node.orelse, seen)
        elif isinstance(node, ast.Name):
            if node.id in seen:
                return
            rhs_list = assigns.get(node.id)
            if not rhs_list:
                unresolved.add(node.id)
                return
            for rhs in rhs_list:
                _resolve(rhs, seen | {node.id})
        # else: a Call, Attribute, BinOp, ... — untraceable without executing the code;
        # silently skipped rather than guessed at.

    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "fallback_reason":
                    _resolve(v, frozenset())
        elif isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "fallback_reason":
                    _resolve(kw.value, frozenset())

    return found, unresolved


def test_every_fallback_reason_the_producers_can_emit_is_in_ROUTE_REASON_CODES():
    """CENSUS, not a sample: the union, over both producer modules, of every string constant
    this walk can trace into a `fallback_reason` dict key or call keyword, asserted inside
    the closed enum `routing_record` now validates against. A ninth negative code added to a
    producer without a matching ROUTE_REASON_CODES entry fails HERE, at the vocabulary,
    instead of downstream as a reader silently trusting an unvalidated string.

    POSITIVE CONTROL: the walk must find `infra_error` (a direct literal in the INFRA_ERROR
    except-block's telemetry dict) and `no_verb_classified` (the inline ternary on the final
    MATCHED/NO_MATCH telemetry dict). A walk that finds neither is walking the wrong shape of
    the AST, not reporting a clean census. `no_predicate_matched` / `low_confidence` corroborate
    the walk's Call-keyword scan specifically (they reach `fallback_reason` only as keyword
    arguments to `_call_engine_a_fallback`, never as a dict literal).
    """
    sup_found, _sup_unresolved = _literal_fallback_reasons(_SUP_PATH)
    dd_found, _dd_unresolved = _literal_fallback_reasons(_DD_PATH)
    found = sup_found | dd_found

    assert {"infra_error", "no_verb_classified"} <= found, (
        f"positive control failed -- walk found {sorted(found)}"
    )
    assert {"no_predicate_matched", "low_confidence"} <= found, (
        f"the Call-keyword scan missed the ADR-0008 codes -- walk found {sorted(found)}"
    )

    unknown = found - ROUTE_REASON_CODES
    assert not unknown, (
        f"producer(s) can emit {sorted(unknown)}, which ROUTE_REASON_CODES does not cover"
    )

    assert "instance_not_found" not in sup_found, (
        "the walk found instance_not_found directly — dynamic_supervisor.py changed shape "
        "and this test's documented blind spot is now stale; update the docstring above"
    )


def test_a_classified_verb_with_NO_PREDICATE_is_not_a_classified_match(sup, monkeypatch):
    """The NO_MATCH return fires on `verb_iri == "UNKNOWN" or not predicate`, so `reason_code`
    must key on the same pair. Here the classifier names a verb the compat walk never offered:
    there is no predicate to dispatch to, the route does not match, and the record must not
    say `classified_match` beside a no_match status."""
    calls: list[str] = []
    ctx, status, predicate, telemetry = _full_route(
        sup, monkeypatch, calls,
        classify_payload={
            "resolved_verb_iri": "http://invincible-agent/mesh#notOffered",
            "confidence_score": 0.85, "classify_called": True,
            "candidate_verb_iris": ["http://invincible-agent/mesh#notOffered"],
        },
    )
    assert status == sup._ROUTING_NO_MATCH
    assert telemetry["reason_code"] != "classified_match", (
        f"a no_match route recorded classified_match (verb_iri={telemetry.get('verb_iri')!r})"
    )
