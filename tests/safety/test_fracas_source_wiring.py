"""The FRACAS source seam, deployment-wired and failing loudly (ADR-0056 Phase 1, backend close).

`failure_source.queries` reads `FAILURE_SOURCE_CONNECTORS` (`name=module:callable`, callable(by) ->
SystemOfRecordQuery). Unset = the sandbox fixture; set = ONLY the named connectors. A connector
that raises, cannot be built, or returns an unusable hit is `SourceUnavailable`, which the route
answers as 200 `refused` / `outcome: source_unavailable` (never an empty answer, never a 5xx the
supervisor would drop unread).
"""
from __future__ import annotations

import sys
import types

import pytest

from agent_fleet.safety_agent import failure_source as fs, main, measures

from . import _program_filter as pf

PART = "PN-8801"


def _hit(**kw):
    h = {"record_id": "E-1", "failure_record_id": "FR-E-1", "part_number": PART,
         "platform": "PLT-ALPHA", "failure_mode": "m", "observed_on": "2026-01-10"}
    h.update(kw)
    return h


def _module(monkeypatch, name, factory):
    m = types.ModuleType(name)
    m.factory = factory
    monkeypatch.setitem(sys.modules, name, m)


class _Q:
    def __init__(self, rows=(), exc=None):
        self.rows, self.exc = list(rows), exc

    def query(self, value):
        if self.exc:
            raise self.exc
        return [dict(r) if isinstance(r, dict) else r for r in self.rows]   # a non-mapping row must REACH the hit check


def test_unset_is_the_sandbox_fixture(monkeypatch):
    monkeypatch.delenv(fs.CONNECTORS_ENV, raising=False)
    assert [n for n, _ in fs.queries(fs.BY_PART)] == ["relyence", "sor-events-a"]


def test_set_serves_ONLY_the_named_connectors_never_the_fixture_beside_them(monkeypatch):
    _module(monkeypatch, "fake_sor", lambda by: _Q([_hit()]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "sor-events-a=fake_sor:factory")
    got = fs.gather(fs.BY_PART, PART)
    assert [r.citation for r in got] == ["sor-events-a:E-1"]   # no FR-6001 from the fixture


def test_the_factory_receives_the_lookup_key(monkeypatch):
    seen = []
    _module(monkeypatch, "fake_sor", lambda by: seen.append(by) or _Q())
    monkeypatch.setenv(fs.CONNECTORS_ENV, "a=fake_sor:factory")
    fs.gather(fs.BY_PLATFORM, "PLT-ALPHA")
    assert seen == [fs.BY_PLATFORM]


@pytest.mark.parametrize("env", ["nonsense", "a=nocolon", "=m:f", "a=no_such_module_xyz:f",
                                 "a=fake_sor:missing_attr"])
def test_a_bad_entry_or_an_unbuildable_connector_is_SourceUnavailable(monkeypatch, env):
    _module(monkeypatch, "fake_sor", lambda by: _Q())
    monkeypatch.setenv(fs.CONNECTORS_ENV, env)
    with pytest.raises(fs.SourceUnavailable):
        fs.gather(fs.BY_PART, PART)


def test_one_connector_down_fails_the_whole_answer_not_half_of_it(monkeypatch):
    _module(monkeypatch, "ok_sor", lambda by: _Q([_hit()]))
    _module(monkeypatch, "down_sor", lambda by: _Q(exc=TimeoutError("slow")))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "a=ok_sor:factory,b=down_sor:factory")
    with pytest.raises(fs.SourceUnavailable) as ei:
        fs.gather(fs.BY_PART, PART)
    assert ei.value.connector == "b" and isinstance(ei.value.__cause__, TimeoutError)


@pytest.mark.parametrize("bad", [
    {"record_id": ""}, {"platform": None}, {"observed_on": None}, {"failure_record_id": ""},
])
def test_an_unusable_hit_is_refused_naming_the_field(monkeypatch, bad):
    _module(monkeypatch, "bad_sor", lambda by: _Q([_hit(**bad)]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "a=bad_sor:factory")
    with pytest.raises(fs.SourceUnavailable, match=next(iter(bad))):
        fs.gather(fs.BY_PART, PART)


def test_a_missing_KEY_is_refused_but_a_null_failure_mode_is_a_recorded_answer(monkeypatch):
    h = _hit()
    del h["platform"]
    _module(monkeypatch, "bad_sor", lambda by: _Q([h]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "a=bad_sor:factory")
    with pytest.raises(fs.SourceUnavailable):
        fs.gather(fs.BY_PART, PART)
    _module(monkeypatch, "null_sor", lambda by: _Q([_hit(failure_mode=None)]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "a=null_sor:factory")
    assert fs.gather(fs.BY_PART, PART)[0].failure_mode is None


def test_a_duplicate_citation_is_kept_once(monkeypatch):
    _module(monkeypatch, "dup_sor", lambda by: _Q([_hit(), _hit()]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "a=dup_sor:factory")
    assert len(fs.gather(fs.BY_PART, PART)) == 1


def _post(monkeypatch, verb, params):
    from fastapi.testclient import TestClient

    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    with TestClient(main.app) as c:
        return c.post(f"/measure/{verb}", json={"query": "", "params": params})


# ---------------------------------------------------------------------------
# The refusal paths, ROUTE LEVEL: three failure modes x two verbs, per connector.
#
#   (a) BUILD   - the connector cannot be built (module / callable / constructor fails)
#   (b) RAISES  - it builds, and raises while it is queried
#   (c) BAD REC - it answers, with a hit the engine cannot use
#
# One named test per mode; each is parametrized over BOTH verbs and over BOTH connector names
# the sandbox knows (so a handler that special-cases one name is seen). Each carries its own
# CONTROL: the same connector, same caller, same route, healthy -> a populated answer. The
# control differs from the subject in the fault and nothing else.
# ---------------------------------------------------------------------------

VERBS = [
    pytest.param("what_failed_on_this_part", {"part_number": PART}, id="what_failed"),
    pytest.param("failure_trend_for_this_platform_by_month", {"platform_id": "PLT-ALPHA"},
                 id="trend"),
]
CONNECTORS = ["sor-events-a", "relyence"]


def _assert_refused_naming(r, verb, connector):
    assert r.status_code == 200
    b = r.json()
    assert b["refused"] is True and b["outcome"] == "source_unavailable", b
    assert b["connector"] == connector and b["fn"] == verb, b
    assert connector in b["reason"]
    assert "rows" not in b and "failure_count" not in b      # not an empty answer
    assert "series" not in b and "periods" not in b


def _assert_populated(r):
    b = r.json()
    assert r.status_code == 200 and not b.get("refused"), b
    assert b["failure_count"] == 1, b


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("verb,params", VERBS)
def test_mode_a_BUILD_a_connector_that_cannot_be_built_is_refused_naming_it(
        monkeypatch, verb, params, connector):
    def cannot_build(by):
        raise RuntimeError("constructor failed")

    _module(monkeypatch, "fake_sor", cannot_build)
    monkeypatch.setenv(fs.CONNECTORS_ENV, f"{connector}=fake_sor:factory")
    _assert_refused_naming(_post(monkeypatch, verb, params), verb, connector)
    # CONTROL: the same name, the same module, the factory builds.
    _module(monkeypatch, "fake_sor", lambda by: _Q([_hit()]))
    _assert_populated(_post(monkeypatch, verb, params))


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("verb,params", VERBS)
def test_mode_a_BUILD_an_unimportable_module_or_missing_callable_is_refused_naming_it(
        monkeypatch, verb, params, connector):
    monkeypatch.setenv(fs.CONNECTORS_ENV, f"{connector}=no_such_module_xyz:factory")
    _assert_refused_naming(_post(monkeypatch, verb, params), verb, connector)
    _module(monkeypatch, "fake_sor", lambda by: _Q([_hit()]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, f"{connector}=fake_sor:missing_attr")
    _assert_refused_naming(_post(monkeypatch, verb, params), verb, connector)
    # CONTROL: module and callable both resolve.
    monkeypatch.setenv(fs.CONNECTORS_ENV, f"{connector}=fake_sor:factory")
    _assert_populated(_post(monkeypatch, verb, params))


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("verb,params", VERBS)
def test_mode_b_RAISES_a_connector_that_raises_during_query_is_refused_naming_it(
        monkeypatch, verb, params, connector):
    _module(monkeypatch, "fake_sor", lambda by: _Q(exc=ConnectionError("x")))
    monkeypatch.setenv(fs.CONNECTORS_ENV, f"{connector}=fake_sor:factory")
    _assert_refused_naming(_post(monkeypatch, verb, params), verb, connector)
    # CONTROL: the connector is built the same way and does not raise.
    _module(monkeypatch, "fake_sor", lambda by: _Q([_hit()]))
    _assert_populated(_post(monkeypatch, verb, params))


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("verb,params", VERBS)
@pytest.mark.parametrize("bad", [
    pytest.param(lambda: _hit(record_id=""), id="empty-required-field"),
    pytest.param(lambda: {k: v for k, v in _hit().items() if k != "platform"}, id="missing-key"),
    pytest.param(lambda: "not-a-dict", id="not-a-mapping"),
])
def test_mode_c_BAD_RECORD_an_unusable_hit_is_refused_naming_the_connector(
        monkeypatch, verb, params, connector, bad):
    _module(monkeypatch, "fake_sor", lambda by: _Q([bad()]))
    monkeypatch.setenv(fs.CONNECTORS_ENV, f"{connector}=fake_sor:factory")
    _assert_refused_naming(_post(monkeypatch, verb, params), verb, connector)
    # CONTROL: the same connector returns a well-formed hit.
    _module(monkeypatch, "fake_sor", lambda by: _Q([_hit()]))
    _assert_populated(_post(monkeypatch, verb, params))


@pytest.mark.parametrize("faulty_first", [True, False], ids=["faulty-first", "faulty-second"])
@pytest.mark.parametrize("mode", ["build", "raises", "bad_record"])
@pytest.mark.parametrize("verb,params", VERBS)
def test_multi_connector_one_healthy_one_faulty_refuses_the_WHOLE_answer_naming_the_faulty_one(
        monkeypatch, verb, params, mode, faulty_first):
    def cannot_build(by):
        raise RuntimeError("constructor failed")

    faulty = {"build": cannot_build,
              "raises": lambda by: _Q(exc=TimeoutError("slow")),
              "bad_record": lambda by: _Q([_hit(record_id="")])}[mode]
    _module(monkeypatch, "ok_sor", lambda by: _Q([_hit()]))
    _module(monkeypatch, "faulty_sor", faulty)
    pair = ["sor-events-a=ok_sor:factory", "relyence=faulty_sor:factory"]
    monkeypatch.setenv(fs.CONNECTORS_ENV, ",".join(reversed(pair) if faulty_first else pair))
    _assert_refused_naming(_post(monkeypatch, verb, params), verb, "relyence")
    # CONTROL: both healthy -> the healthy connector's record is served, (half an answer is not
    # what the refusal withheld: the same hit is what the faulty pair would have returned).
    _module(monkeypatch, "faulty_sor", lambda by: _Q([_hit(record_id="E-2", failure_record_id="FR-E-2")]))
    ok = _post(monkeypatch, verb, params).json()
    assert not ok.get("refused") and ok["failure_count"] == 2, ok


def test_the_route_still_answers_engine_fault_for_a_bug_that_is_not_a_source_fault(monkeypatch):
    def boom(part_number):
        raise ValueError("bug")

    monkeypatch.setattr(measures, "what_failed_on_this_part", boom)
    r = _post(monkeypatch, "what_failed_on_this_part", {"part_number": PART})
    assert r.json()["outcome"] == "engine_fault"


def test_PCN26_184_parts_have_no_failure_history_in_the_sandbox_sources(monkeypatch):
    """The two parts the Friday walk's notice names (5530-184, 5530-185; sessions/friday-demo-
    runbook.md section 3, lane 74) are not safety-critical items here and no source holds a
    failure for them. The answer is a DECIDED refusal ('unknown part'), not a card of zeros;
    the notice supplies part numbers only, so no platform or failure mode is asserted for them."""
    monkeypatch.delenv(fs.CONNECTORS_ENV, raising=False)
    for pn in ("5530-184", "5530-185"):
        assert fs.gather(fs.BY_PART, pn) == []
        pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
        r = measures.what_failed_on_this_part(part_number=pn)
        assert r["refused"] is True and r["reason"] == f"unknown part '{pn}'"
