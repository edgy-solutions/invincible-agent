"""The two FRACAS verbs emit what their DECLARED archetype draws (ADR-0056 Phase 1).

THE DEFECT THIS EXISTS FOR cannot be caught on either side alone. The producer's own tests pass -
the failure records are right. The renderer's own tests pass - it refuses a payload with no axes,
exactly as its contract says. Only the PAIR is wrong, and it is assembled in a browser. Before
2026-10-08 these two verbs had NO binding at all, so their success path drew as the
KNOWLEDGE_DOCUMENT fallback ("No content available") while every refusal drew correctly.

THE POPULATION IS DERIVED, never listed: the bound `safety:` subjects whose output class is a
FRACAS verb's `output_uri` in main.VERBS. A FRACAS verb whose class is not bound fails the
partition arm, so a third verb cannot leave the population unseen.

WHAT IS READ, AND FROM WHERE.
  * The REQUIRED ROW KEYS are parsed out of cortex-ui's contract (`ContributionRow`,
    `MultiSeriesRow`) when the sibling is checked out. cortex-ui moved these from
    `src/components/planning/<Name>.contract.ts` to `src/archetypes/<kebab>/contract.ts`; BOTH
    are tried, because an older seal in this repo still looks only at the first and so reads
    nothing. A hand-copied mirror covers the sibling being absent and is asserted EQUAL to the
    parse whenever both exist.
  * The RENDERER'S OWN VALIDATION is restated from `validateContributionRanking` /
    `validateMultiSeries` as behaviours (numeric contribution, non-empty name; a declared series
    that is numeric in some row, one unit). That is a restatement, so it is labelled one.
  * The projector's PASSTHROUGH is imported, not restated: `_PROJECTED_ARCHETYPES`, and the REAL
    `_project_planning_archetype` is run on the engine's payload.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
from agent_fleet.safety_agent import main as safety_main
from agent_fleet.safety_agent import measures

from tests.planning.test_planning_archetypes_are_projected import _envelope, _fns

from . import _program_filter as pf

ROOT = Path(__file__).resolve().parents[2]
_UI = ROOT.parent / "cortex-ui" / "src"

#: archetype -> (new-layout contract, old-layout contract, TS interface of one row)
_CONTRACTS = {
    "CONTRIBUTION_RANKING": ("archetypes/contribution-ranking/contract.ts",
                             "components/planning/ContributionRanking.contract.ts",
                             "ContributionRow"),
    "MULTI_SERIES": ("archetypes/multi-series/contract.ts",
                     "components/planning/MultiSeries.contract.ts", "MultiSeriesRow"),
}
_MIRROR = {"CONTRIBUTION_RANKING": {"entity_id", "entity_name", "contribution"},
           "MULTI_SERIES": {"period"}}

#: One representative call per verb: a populated path for a caller who may see everything.
_CALLS = {"what_failed_on_this_part": {"part_number": "PN-8801"},
          "failure_trend_for_this_platform_by_month": {"platform_id": "PLT-ALPHA"}}

_FRACAS = {v["fn"]: v["output_uri"].rsplit("#", 1)[-1] for v in safety_main.VERBS
           if v["fn"] in _CALLS}
BOUND = {b["subject_uri"].split(":", 1)[1]: b for b in PRESENTATION_CAPABILITIES
         if b["subject_uri"].startswith("safety:")}


def _parse_required(archetype):
    for rel in _CONTRACTS[archetype][:2]:
        path = _UI / rel
        if path.is_file():
            src = path.read_text(encoding="utf-8")
            m = re.search(rf"export interface {_CONTRACTS[archetype][2]} \{{(.*?)^\}}", src,
                          re.S | re.M)
            if m:
                body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
                body = re.sub(r"//.*", "", body)
                return {n for n, opt in re.findall(r"^\s*(\w+)(\??):", body, re.M) if not opt}
    return None


def required_keys(archetype):
    parsed = _parse_required(archetype)
    if parsed is None:
        return set(_MIRROR[archetype])
    # MultiSeriesRow also declares an index signature, which the pattern above does not match.
    assert parsed == _MIRROR[archetype], (
        f"{archetype}: the contract requires {sorted(parsed)}, the mirror says "
        f"{sorted(_MIRROR[archetype])}")
    return parsed


def _payload(fn, monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    return getattr(measures, fn)(**_CALLS[fn])


_FNS = _fns()   # the projector's own helpers, exec'd out of source: main.py needs baml_client


def _project(archetype, payload):
    """Run the REAL projector on the engine's payload, framed the way a measure answers: rows
    under `structured_data`, every other key beside it."""
    extra = {k: v for k, v in payload.items() if k != "rows"}
    return _FNS["_project_planning_archetype"](
        archetype, _envelope(payload.get("rows", []), **extra), "SAFETY_ENGINEER", None)


def test_every_FRACAS_verb_output_class_is_bound_to_an_archetype():
    """THE PARTITION. A FRACAS output class in no binding draws as the fallback."""
    assert set(_FRACAS) == set(_CALLS), "a FRACAS verb in _CALLS is missing from main.VERBS"
    unbound = sorted(c for c in _FRACAS.values() if c not in BOUND)
    assert not unbound, f"FRACAS output classes with no PRESENTATION_CAPABILITIES row: {unbound}"
    assert {BOUND[c]["archetype"] for c in _FRACAS.values()} == {
        "CONTRIBUTION_RANKING", "MULTI_SERIES"}


def test_the_declared_bindings_are_the_ones_the_order_names():
    assert BOUND[_FRACAS["what_failed_on_this_part"]]["archetype"] == "CONTRIBUTION_RANKING"
    assert BOUND[_FRACAS["failure_trend_for_this_platform_by_month"]]["archetype"] == "MULTI_SERIES"


@pytest.mark.parametrize("fn", sorted(_CALLS))
def test_the_rows_carry_the_archetypes_required_keys(fn, monkeypatch):
    arch = BOUND[_FRACAS[fn]]["archetype"]
    rows = _payload(fn, monkeypatch)["rows"]
    assert rows, f"{fn} produced no rows to draw on the populated path"
    for row in rows:
        missing = required_keys(arch) - set(row)
        assert not missing, f"{fn} -> {arch}: a row is missing {sorted(missing)}"


@pytest.mark.parametrize("fn", sorted(_CALLS))
def test_every_expected_field_is_actually_emitted(fn, monkeypatch):
    """A binding advertising a field the producer never emits is a promise to the selector."""
    b = BOUND[_FRACAS[fn]]
    payload = _payload(fn, monkeypatch)
    for field in b["expected_fields"]:
        assert field in payload or field in payload["rows"][0], (
            f"{fn} advertises {field!r} and emits it nowhere")


def test_CONTRIBUTION_RANKING_renderer_validation_holds(monkeypatch):
    rows = _payload("what_failed_on_this_part", monkeypatch)["rows"]
    for r in rows:
        assert isinstance(r["entity_name"], str) and r["entity_name"]
        assert isinstance(r["contribution"], (int, float)) and not isinstance(r["contribution"], bool)
    # order is upstream: descending by contribution, and the share is a share of the total
    assert [r["contribution"] for r in rows] == sorted((r["contribution"] for r in rows), reverse=True)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert abs(sum(r["share_of_total"] for r in rows) - 1) < 0.01
    assert all(r["record_ids"] and r["citations"] for r in rows), "provenance rides in every row"


def test_MULTI_SERIES_renderer_validation_holds(monkeypatch):
    out = _payload("failure_trend_for_this_platform_by_month", monkeypatch)
    series, rows = out["series"], out["rows"]
    assert series, "no declared series: the card refuses 'does not declare which keys are series'"
    assert all(isinstance(s["key"], str) and s["key"] and isinstance(s["label"], str) for s in series)
    assert len({str(s.get("unit") or "") for s in series}) == 1, "one unit per card"
    for s in series:
        assert any(isinstance(r.get(s["key"]), (int, float)) for r in rows)
        for r in rows:
            assert isinstance(r[s["key"]], (int, float)), "a hole in the line"
    periods = [r["period"] for r in rows]
    assert all(isinstance(p, str) and p for p in periods) and periods == sorted(periods)


@pytest.mark.parametrize("fn", sorted(_CALLS))
def test_the_REAL_projector_carries_the_rows_and_the_declared_envelope(fn, monkeypatch):
    arch = BOUND[_FRACAS[fn]]["archetype"]
    payload = _payload(fn, monkeypatch)
    rows_key, envelope = _FNS["_PROJECTED_ARCHETYPES"][arch]
    assert rows_key == "rows"
    card = _project(arch, payload)
    assert card is not None, "the projector degraded a populated payload"
    assert card["rows"] == payload["rows"], "rows pass through VERBATIM"
    for field in envelope:
        if field in payload:
            assert card.get(field) == payload[field], (
                f"{fn}: envelope field {field!r} is on the engine's wire and NOT on the card")


def test_a_caller_who_may_see_nothing_draws_the_renderers_refusal_not_a_zero_row(monkeypatch):
    """The empty answer is `rows: []`, and the projector degrades it: an empty planning card is a
    refusal, not an answer. No fabricated zero-row stands in for it."""
    pf.install(monkeypatch, caller=pf.ALICE, members={})
    for fn in _CALLS:
        out = getattr(measures, fn)(**_CALLS[fn])
        assert out["refused"] is False and out["rows"] == []
        assert _project(BOUND[_FRACAS[fn]]["archetype"], out) is None


# ── controls: each arm above must be able to fail ───────────────────────────────────────────

def test_CONTROL_the_row_key_check_fails_when_a_key_is_dropped(monkeypatch):
    rows = _payload("what_failed_on_this_part", monkeypatch)["rows"]
    broken = {k: v for k, v in rows[0].items() if k != "entity_name"}
    assert required_keys("CONTRIBUTION_RANKING") - set(broken) == {"entity_name"}


def test_CONTROL_the_projector_arm_fails_when_the_series_declaration_is_dropped(monkeypatch):
    """The ONE difference from the real payload: no `series`. The projector then carries a card
    with no declaration, and the envelope comparison names it."""
    out = _payload("failure_trend_for_this_platform_by_month", monkeypatch)
    bare = {k: v for k, v in out.items() if k != "series"}
    card = _project("MULTI_SERIES", bare)
    assert card is None or card.get("series") != out["series"]


def test_CONTROL_a_row_keyed_by_the_old_domain_name_is_what_the_old_payload_was(monkeypatch):
    """The payload before this change had `failures` / `months` and no `rows`; the projector found
    no rows and degraded. That is the blank card the binding exists to end."""
    out = _payload("what_failed_on_this_part", monkeypatch)
    old = {k: v for k, v in out.items() if k not in ("rows", "value_label", "value_unit", "scope_label")}
    assert _project("CONTRIBUTION_RANKING", old) is None
