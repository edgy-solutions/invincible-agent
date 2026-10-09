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
        return [dict(r) for r in self.rows]


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


@pytest.mark.parametrize("verb,params", [
    ("what_failed_on_this_part", {"part_number": PART}),
    ("failure_trend_for_this_platform_by_month", {"platform_id": "PLT-ALPHA"}),
])
def test_the_route_refuses_with_source_unavailable_and_the_control_answers(monkeypatch, verb, params):
    _module(monkeypatch, "down_sor", lambda by: _Q(exc=ConnectionError("x")))
    monkeypatch.setenv(fs.CONNECTORS_ENV, "sor-events-a=down_sor:factory")
    r = _post(monkeypatch, verb, params)
    assert r.status_code == 200
    b = r.json()
    assert b["refused"] is True and b["outcome"] == "source_unavailable"
    assert b["connector"] == "sor-events-a" and b["fn"] == verb
    assert "rows" not in b and "failure_count" not in b      # not an empty answer
    # CONTROL: same route, same caller, connector healthy -> an answer. Differs in ONE thing.
    _module(monkeypatch, "down_sor", lambda by: _Q([_hit()]))
    ok = _post(monkeypatch, verb, params).json()
    assert not ok.get("refused") and ok["failure_count"] == 1


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
