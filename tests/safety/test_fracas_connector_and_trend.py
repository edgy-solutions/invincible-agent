"""FRACAS Phase 1, SystemOfRecordQuery consumer + the second verb (ADR-0056).

PART A -- `what_failed_on_this_part` is served by `SystemOfRecordQuery` connectors, not by a
one-hit lookup and not by a direct read of the fixture. PART B -- `failure_trend_for_this_platform_by_month`.

EVERY CONTROL DIFFERS IN ONE THING: the connector double's content (A), the caller kind or the
membership set (B). The program-filter, NoPerson and Topaz-503 behaviours are sealed in
test_fracas_program_filter.py and are re-proven here for the second verb only.
"""
from __future__ import annotations

import pytest

from agent_fleet.safety_agent import entities, failure_source, instances, main, measures, slots

from . import _program_filter as pf

PART = "PN-8801"
ALPHA = {pf.ALICE: {"SANDBOX_PROGRAM_ALPHA"}}


class Double:
    """A connector that implements the SDK Protocol: `query(value) -> Iterable[dict]`, and nothing
    else. Records every value it is asked for."""

    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    def query(self, value):
        self.asked.append(value)
        return [dict(r) for r in self.rows]


def _row(rid, platform="PLT-ALPHA", observed_on="2026-01-10", part=PART, fr=None):
    return {"record_id": rid, "failure_record_id": fr or ("FR-" + rid), "part_number": part,
            "platform": platform, "failure_mode": "double mode " + rid, "observed_on": observed_on}


def _serve(monkeypatch, **connectors):
    """Replace the engine's connector seam with doubles, one per named system of record."""
    monkeypatch.setattr(failure_source, "queries",
                        lambda by: [(name, d) for name, d in sorted(connectors.items())])


# ───────────────────────── PART A: the consumer path is the one serving the verb ─────────────────

def test_the_verb_is_served_by_the_connectors_query_with_the_part_number(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    d = Double([_row("X-1")])
    _serve(monkeypatch, dbl=d)
    out = measures.what_failed_on_this_part(part_number=PART)
    assert d.asked == [PART], "the connector must be asked for the part number"
    assert [f["record_id"] for f in out["failures"]] == ["FR-X-1"]
    assert out["failures"][0]["citation"] == "dbl:X-1", "citation is <connector>:<record_id>"
    assert out["systems_of_record_cited"] == ["dbl"]


def test_CONTROL_the_fixture_alone_no_longer_serves_the_verb(monkeypatch):
    """Same request, same caller; the ONLY difference is that the connectors hold nothing. The
    fixture still holds two PN-8801 records. If the verb read the fixture directly (the old
    path) this would return them."""
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    assert [r for r in entities.FAILURE_RECORDS if r.part_number == PART], "fixture assumption"
    _serve(monkeypatch, dbl=Double([]))
    out = measures.what_failed_on_this_part(part_number=PART)
    assert out["failures"] == [] and out["failure_count"] == 0 and out["refused"] is False


def test_the_measures_module_no_longer_holds_the_failure_fixture():
    assert not hasattr(measures, "FAILURE_RECORDS"), (
        "measures must reach failure records only through failure_source")


def test_the_default_connectors_reproduce_the_old_answer_citation_for_citation(monkeypatch):
    """The sandbox connectors are the fixture behind the Protocol: same ids, same citations."""
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    out = measures.what_failed_on_this_part(part_number=PART)
    assert [(f["record_id"], f["citation"]) for f in out["failures"]] == [
        ("FR-6001", "sor-events-a:EVT-55101"), ("FR-6002", "relyence:FM-7734")]


def test_both_default_connectors_and_a_double_are_system_of_record_queries():
    sdk = pytest.importorskip("iagent_mesh.systems_of_record")
    if not hasattr(sdk, "SystemOfRecordQuery"):
        pytest.skip("installed iagent-mesh predates 0.9.9 (SystemOfRecordQuery); the engine pins 60e56c9")
    for obj in (failure_source.FixtureFailureQuery("relyence", failure_source.BY_PART), Double([])):
        assert isinstance(obj, sdk.SystemOfRecordQuery)


def test_a_connector_that_cannot_reach_its_source_is_never_an_empty_answer(monkeypatch):
    class Down:
        def query(self, value):
            raise ConnectionError("source unreachable")

    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    _serve(monkeypatch, dbl=Double([_row("X-1")]), down=Down())
    with pytest.raises(ConnectionError):
        measures.what_failed_on_this_part(part_number=PART)


def test_the_program_filter_applies_to_what_a_connector_returns(monkeypatch):
    """CONTROL pair: the same two connector rows, a member of ALPHA only sees the ALPHA one."""
    pf.install(monkeypatch, caller=pf.ALICE, members=ALPHA)
    _serve(monkeypatch, dbl=Double([_row("A-1", "PLT-ALPHA"), _row("B-1", "PLT-BRAVO")]))
    out = measures.what_failed_on_this_part(part_number=PART)
    assert [f["citation"] for f in out["failures"]] == ["dbl:A-1"]
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    out = measures.what_failed_on_this_part(part_number=PART)
    assert sorted(f["citation"] for f in out["failures"]) == ["dbl:A-1", "dbl:B-1"]


# ───────────────────────── PART B: failure_trend_for_this_platform_by_month ───────────────────────

def _trend(platform="PLT-ALPHA"):
    return measures.failure_trend_for_this_platform_by_month(platform_id=platform)


def test_a_member_gets_the_months_with_citations(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    out = _trend("PLT-ALPHA")
    assert out["refused"] is False and out["failure_count"] == 1
    assert out["months"] == [{"month": "2026-03", "failure_count": 1,
                              "failure_record_ids": ["FR-6001"],
                              "citations": ["sor-events-a:EVT-55101"]}]


def test_a_non_member_person_gets_the_empty_series_and_the_member_control_gets_it_populated(monkeypatch):
    pf.install(monkeypatch, caller=pf.CAROL, members={})
    denied = _trend("PLT-BRAVO")
    assert denied["refused"] is False and denied["failure_count"] == 0 and denied["months"] == []
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    assert _trend("PLT-BRAVO")["failure_count"] == 1


def test_the_denied_answer_cannot_be_told_from_a_clean_platform_by_its_shape(monkeypatch):
    pf.install(monkeypatch, caller=pf.CAROL, members={})
    denied = _trend("PLT-BRAVO")
    clean = [p for p in entities.PLATFORM_IDS
             if not any(r.platform == p for r in entities.FAILURE_RECORDS)]
    assert clean, "fixture assumption: a platform with no failure record"
    ref = _trend(clean[0])
    for k in ("refused", "failure_count", "months", "undated", "systems_of_record_cited"):
        assert denied[k] == ref[k], (k, denied[k], ref[k])


def test_a_member_of_one_program_sees_only_that_platform(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=ALPHA)
    assert _trend("PLT-ALPHA")["failure_count"] == 1
    assert _trend("PLT-BRAVO")["failure_count"] == 0


def test_an_unmapped_platform_is_denied_even_for_a_member_of_every_mapped_program(monkeypatch, tmp_path):
    (tmp_path / "platform_programs.yaml").write_text(
        "platform_programs:\n  PLT-ALPHA: SANDBOX_PROGRAM_ALPHA\n", encoding="utf-8")
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, overlay_dirs=str(tmp_path))
    assert _trend("PLT-BRAVO")["failure_count"] == 0, "no mapping row -> denied"
    assert _trend("PLT-ALPHA")["failure_count"] == 1, "control: the mapped platform is served"


@pytest.mark.parametrize("caller", [None, "svc:supervisor"])
def test_no_person_raises_and_topaz_is_not_asked(monkeypatch, caller):
    asked = pf.install(monkeypatch, caller=caller, members=pf.ALL_PROGRAMS)
    with pytest.raises(measures.NoPerson):
        _trend()
    assert asked == []


def _post(monkeypatch, caller, members, **kw):
    from fastapi.testclient import TestClient

    pf.install(monkeypatch, caller=caller, members=members, **kw)
    body = {"query": "", "params": {"platform_id": "PLT-ALPHA"}}
    with TestClient(main.app) as c:
        return c.post("/measure/failure_trend_for_this_platform_by_month", json=body)


def test_the_route_answers_422_no_person_503_and_the_person_control_200(monkeypatch):
    r = _post(monkeypatch, "svc:supervisor", pf.ALL_PROGRAMS)
    assert r.status_code == 422 and r.json() == {
        "error": "no_person", "fn": "failure_trend_for_this_platform_by_month",
        "message": "this verb answers for a person; the caller carries none"}
    r = _post(monkeypatch, pf.ALICE, pf.ALL_PROGRAMS, topaz_down=True)
    assert r.status_code == 503 and r.json()["error"] == "authorization_unavailable"
    assert "months" not in r.json()
    r = _post(monkeypatch, pf.ALICE, pf.ALL_PROGRAMS)
    assert r.status_code == 200 and r.json()["failure_count"] == 1


def test_topaz_down_raises_rather_than_answering_empty(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, topaz_down=True)
    with pytest.raises(measures.ProgramAuthorizationUnavailable):
        _trend()


def test_empty_months_appear_and_the_series_crosses_a_year_boundary(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    _serve(monkeypatch, dbl=Double([_row("N", observed_on="2026-11-30"),
                                    _row("F", observed_on="2027-02-01"),
                                    _row("N2", observed_on="2026-11-02")]))
    out = _trend()
    assert [(m["month"], m["failure_count"]) for m in out["months"]] == [
        ("2026-11", 2), ("2026-12", 0), ("2027-01", 0), ("2027-02", 1)]
    assert out["months"][1]["citations"] == [] and out["failure_count"] == 3


def test_the_month_is_the_observed_on_date_as_written_no_timezone(monkeypatch):
    """A date at a month edge stays in its month: no zone shifts it."""
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    _serve(monkeypatch, dbl=Double([_row("E1", observed_on="2026-05-31"),
                                    _row("E2", observed_on="2026-06-01")]))
    assert [(m["month"], m["failure_record_ids"]) for m in _trend()["months"]] == [
        ("2026-05", ["FR-E1"]), ("2026-06", ["FR-E2"])]


def test_an_unparseable_date_is_counted_undated_not_dropped_or_bucketed(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    _serve(monkeypatch, dbl=Double([_row("G", observed_on="2026-02-03"),
                                    _row("BAD", observed_on="sometime in spring")]))
    out = _trend()
    assert out["undated"] == {"count": 1, "citations": ["dbl:BAD"]}
    assert [m["month"] for m in out["months"]] == ["2026-02"] and out["failure_count"] == 2


def test_the_month_range_comes_from_visible_records_only(monkeypatch):
    """A connector that over-returns a BRAVO record in March 2027 must not stretch an ALPHA-only
    member's range to include it (that would leak that a hidden record exists)."""
    rows = [_row("A", "PLT-ALPHA", "2026-01-05"), _row("B", "PLT-BRAVO", "2027-03-05")]
    pf.install(monkeypatch, caller=pf.ALICE, members=ALPHA)
    _serve(monkeypatch, dbl=Double(rows))
    assert [m["month"] for m in _trend()["months"]] == ["2026-01"]
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    out = measures.failure_trend_for_this_platform_by_month(platform_id="PLT-ALPHA")
    assert out["failure_count"] == 2 and out["months"][-1]["month"] == "2027-03"


def test_the_trend_is_served_by_the_connectors_query_with_the_platform(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    d = Double([])
    _serve(monkeypatch, dbl=d)
    _trend("PLT-BRAVO")
    assert d.asked == ["PLT-BRAVO"]


def test_an_unknown_platform_refuses_and_a_known_clean_platform_does_not(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    assert _trend("PLT-NOPE")["refused"] is True
    assert "unknown platform" in _trend("PLT-NOPE")["reason"]
    assert _trend("PLT-CHARLIE")["refused"] is False and _trend("PLT-CHARLIE")["months"] == []
    assert measures.failure_trend_for_this_platform_by_month(platform_id="")["refused"] is True


# ───────────────────────── registration: every name registry the first verb touched ──────────────

FN = "failure_trend_for_this_platform_by_month"


def test_the_verb_is_registered_everywhere_the_first_verb_is():
    v = main.BY_FN[FN]
    assert v["verb"] == "mesh:failureTrendForThisPlatformByMonth"
    assert v["input_uri"] == main.SAFETY + "Platform" and v["output_uri"] == main.SAFETY + "FailureTrend"
    assert callable(getattr(measures, FN))
    declared = [s["name"] for s in slots.slots_for(FN)]
    assert declared == ["platform_id"], declared
    assert slots._REFERENT_KIND["platform_id"] == main.SAFETY + "Platform"


def test_the_platform_class_is_enumerable_and_resolvable_from_the_fixtures():
    out = instances.enumerate_class(main.SAFETY + "Platform")
    assert out["outcome"] == "members"
    assert [m["identifier"] for m in out["members"]] == list(entities.PLATFORM_IDS)
    assert {"PLT-ALPHA", "PLT-BRAVO", "PLT-CHARLIE"} <= set(entities.PLATFORM_IDS)
