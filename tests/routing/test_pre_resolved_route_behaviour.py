"""THE PRE-RESOLVED ROUTE, EXERCISED RATHER THAN INSPECTED.

Its sibling `test_a_pick_is_not_a_new_question.py` asserts on the AST: that the branch exists,
returns, calls the verifier and carries the subject unchanged. Those are real properties and
structure is the right way to pin them.

BUT THE DEFECT THAT ACTUALLY GOT THROUGH WAS NOT STRUCTURAL. The branch read
`_pre_truth.get("needs_instance")` without running `_filter_verbs_by_arity` -- so the flag was
never set, and a single-asset verb would have dispatched against a set query on this path
while the full path correctly asked. Every structural assertion passed: the carry was present,
in the right block, reading the right key. It read a key nothing had written.

It was found by reading the code, not by a test, and that is exactly the class the ruling
asked to be sealed behaviourally. So this file CALLS the router and looks at what comes back.

WHY THIS CASE AND NOT ANOTHER. `planCapabilityPath` is `arity: single`; "what is the
capability path" grounds to `Capability` with no instance; that combination is why an ask
fires at all (see `_filter_verbs_by_arity`, the H06 ruling). It is therefore the exact shape
of the walk that prompted this work -- the ask, then the pick that answers it -- and the pick
re-enters with the same subject and still no instance.

Run: uv run --frozen pytest tests/routing/test_pre_resolved_route_behaviour.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SUBJECT = "http://invincible-agent/mesh#Capability"
_VERB = "mesh:planCapabilityPath"


_SUP_PATH = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"


@pytest.fixture(scope="session")
def sup():
    """The real module — REUSED if anything already loaded it.

    THE FIRST VERSION LOADED IT UNCONDITIONALLY AND WAS ORDER-DEPENDENT. Executing
    `dynamic_supervisor.py` a second time under a different module name re-runs its Dagster
    registrations, and dagster's serdes registry refuses:

        SerdesUsageError: Multiple deserializers registered for storage name
        `ConfigurableClassData`

    Alone it passed. In the routing suite's file order it passed. Run after
    `test_ask_to_answer_lineage.py` it errored at fixture setup — every test in this file, on
    an ordering nobody chose. That is the flaky-seal shape that gets a file deleted six weeks
    later rather than fixed, and the docstring here previously ARGUED for the broken version:
    it said a stub installer was a stale second copy of the import graph. That reasoning was
    wrong about the thing it was defending — `test_adr0019_contracts.py` stubs dagster for
    exactly this reason, and I read its stub set as duplication rather than as the fix.

    So: reuse whatever copy exists, keyed on the FILE rather than on a module name, because
    the collision is between two different names for one file.
    """
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if f and Path(f).resolve() == _SUP_PATH.resolve():
            return mod
    spec = importlib.util.spec_from_file_location(
        "dynamic_supervisor_pre_resolved_test", str(_SUP_PATH),
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


def _dispatcher(calls: list[str], *, arity: str = "single", verb: str = _VERB):
    """A `requests.post` that records which engine endpoints were hit."""
    def _post(url, *a, **k):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("/find_compatible_verbs"):
            return _Resp({"verbs": [{
                "verb_iri": verb,
                "verb_local": "planCapabilityPath",
                "input_uri": _SUBJECT,
                "output_uri": "http://invincible-agent/mesh#CapabilityPath",
                "endpoint_url": "http://engine-p:8080/plan_capability_path",
                "owner_persona": "PORTFOLIO_PLANNER",
                "domains": ["PORTFOLIO_PLANNING"],
                "cost_class": "cheap",
                "arity": arity,
                "slots": "[]",
            }]})
        if url.endswith("/resolve"):
            return _Resp({"class_uri": "UNKNOWN", "confidence": 0.0})
        return _Resp({})
    return _post


def _route(sup, monkeypatch, calls, *, instance_id="", arity="single", verb=_VERB,
           pre_verb=_VERB):
    monkeypatch.setattr(sup.requests, "post", _dispatcher(calls, arity=arity, verb=verb))
    return sup._classify_route(
        _Ctx(),
        "what is the capability path",
        ["PORTFOLIO_PLANNING"],
        routing_domain="PORTFOLIO_PLANNING",
        pre_resolved={
            "subject_uri": _SUBJECT,
            "subject_instance_id": instance_id,
            "subject_instance_label": "",
            "verb_iri": pre_verb,
        },
    )


# ── the defect that structure could not see ─────────────────────────────────

def test_a_single_asset_verb_on_the_SKIP_path_is_flagged_needs_instance(sup, monkeypatch):
    """THE ONE THE RULING ASKED FOR. Set-shaped subject, no instance, answered ask.

    `needs_instance` is what makes the disposition ask instead of dispatching. If the arity
    gate does not run on this path the flag is absent, the predicate looks ordinary, and the
    verb dispatches against a subject with no instance — the failure is a wrong answer, not
    an error, which is the kind nobody reports.
    """
    calls: list[str] = []
    status, predicate, telemetry = _route(sup, monkeypatch, calls)
    assert status == sup._ROUTING_MATCHED, f"expected a route, got {status}"
    assert predicate is not None
    assert predicate.get("needs_instance") is True, (
        "the arity gate did not run on the pre-resolved path — a single-asset verb would "
        "dispatch against a set query here while the full path asks"
    )


def test_the_flag_is_NOT_set_when_the_ask_carried_an_instance(sup, monkeypatch):
    """THE CONTROL. A flag that is always on is not a gate — it would make every
    pre-resolved route ask, forever, which is the opposite failure and just as silent."""
    calls: list[str] = []
    _, predicate, _ = _route(sup, monkeypatch, calls, instance_id="urn:instance:C8")
    assert not predicate.get("needs_instance"), (
        "needs_instance is set even though the ask resolved a specific instance"
    )


def test_a_multi_arity_verb_is_never_flagged(sup, monkeypatch):
    """The second control, on the other axis: the gate must key on arity, not on absence of
    an instance alone."""
    calls: list[str] = []
    _, predicate, _ = _route(sup, monkeypatch, calls, arity="set")
    assert not predicate.get("needs_instance")


# ── the skip is real, measured by what was called ───────────────────────────

def test_NO_MODEL_CALL_IS_MADE_ON_THE_SKIP(sup, monkeypatch):
    """The latency claim, asserted on behaviour rather than on the shape of a branch.

    /resolve and /classify_predicate are the two model calls inside the router. Neither may
    be hit when the route was already established. The verifier must be, and asserting that
    is what stops this test passing on a branch that returned early and did nothing.
    """
    calls: list[str] = []
    status, predicate, _ = _route(sup, monkeypatch, calls)
    assert status == sup._ROUTING_MATCHED
    assert "resolve" not in calls, f"the subject was resolved again: {calls}"
    assert "classify_predicate" not in calls, f"the predicate was classified again: {calls}"
    assert "find_compatible_verbs" in calls, (
        f"the eligibility verifier never ran — nothing was checked: {calls}"
    )


def test_the_route_carried_is_the_route_returned(sup, monkeypatch):
    """Byte-equality, observed on the way out rather than read off the source."""
    calls: list[str] = []
    _, predicate, telemetry = _route(sup, monkeypatch, calls)
    assert telemetry["subject_uri"] == _SUBJECT
    assert telemetry["verb_iri"] == _VERB
    assert predicate["verb_iri"] == _VERB
    assert telemetry.get("pre_resolved") is True


# ── and it invalidates ──────────────────────────────────────────────────────

def test_a_verb_that_is_no_longer_compatible_ROUTES_THE_FULL_PATH(sup, monkeypatch):
    """THE INVALIDATION, which is the reason /find_compatible_verbs was kept.

    The ask chose a verb; entitlements are revoked, an engine is retired, the TTL is
    re-primed, or the person picking is not the person who asked. The compat-walk no longer
    returns it. The route must be recomputed, not remembered — and recomputing means /resolve
    is called, which is the observable.
    """
    calls: list[str] = []
    _route(sup, monkeypatch, calls, verb="mesh:somethingElse")
    assert "resolve" in calls, (
        f"a stale verb was accepted without re-resolving — the ask's route is a cache with "
        f"no invalidation: {calls}"
    )
