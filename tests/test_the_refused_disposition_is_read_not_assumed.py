"""`refused` is a walk-census disposition: the VERB returned a named refusal.

Added 2026-10-09 (architect ruling). A vocabulary word that the sheet can write and the runner can
never produce passes through the loader and never matches, so every arm here fires the classifier
on a payload, not only the loader on a word.

Run: uv run pytest tests/test_the_refused_disposition_is_read_not_assumed.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.engine_abstain import ABSTAINED  # noqa: E402
from iagent_pure.walk_census import (  # noqa: E402
    DISPOSITIONS, FAIL, PASS, REFUSED, CensusRow, judge, load_rows,
)

_CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"


def _row(*dispositions: str) -> CensusRow:
    return CensusRow(
        id="fixture-row", sheet="fixture", sheet_index=1, question="q", user="bob",
        persona="SAFETY_ENGINEER", domains=("SUSTAINMENT",), frontend_id="fixture-frontend",
        expect_verb=None, expect_archetype=None, min_rows=0,
        dispositions=tuple(dispositions),
    )


def _result(final=None, status="matched"):
    return {
        "events": [{"event": "route_decision", "data": {
            "action": {"iri": "mesh:draftRiskAssessment"},
            "handled_by": {"endpoint_url": "http://engine-safety/measure/draft_risk_assessment"},
            "route_status": status, "fallback": False,
        }}],
        "final": final,
    }


_REFUSAL = {"refused": True, "outcome": "hazard_closed", "hazard_id": "HAZ-1005", "reason": "closed"}


def test_REFUSED_is_in_the_vocabulary_and_is_not_abstained():
    assert REFUSED == "refused" and REFUSED in DISPOSITIONS
    assert REFUSED != ABSTAINED and ABSTAINED in DISPOSITIONS


def test_a_named_refusal_is_scored_refused_and_a_row_accepting_it_passes():
    r = _result({"components": [{"archetype": "KNOWLEDGE_DOCUMENT"}], "payload": _REFUSAL})
    assert judge(_row(REFUSED), r)[0] == PASS


def test_a_named_refusal_is_not_scored_drawn_so_a_row_accepting_drawn_fails_by_name():
    r = _result({"components": [{"archetype": "KNOWLEDGE_DOCUMENT"}], "payload": _REFUSAL})
    state, why = judge(_row("drawn"), r)
    assert state == FAIL and any("disposition 'refused'" in w for w in why), why


def test_CONTROL_the_same_answer_without_the_refusal_is_drawn_not_refused():
    """Differs in exactly one thing: the payload no longer says `refused: true`."""
    ok = dict(_REFUSAL, refused=False)
    r = _result({"components": [{"archetype": "KNOWLEDGE_DOCUMENT"}], "payload": ok})
    state, why = judge(_row(REFUSED), r)
    assert state == FAIL and any("disposition 'drawn'" in w for w in why), why


def test_CONTROL_a_refusal_with_no_outcome_word_is_not_a_NAMED_refusal():
    unnamed = {"refused": True, "reason": "which hazard?"}
    r = _result({"components": [{"archetype": "KNOWLEDGE_DOCUMENT"}], "payload": unnamed})
    assert judge(_row(REFUSED), r)[0] == FAIL


def test_a_slot_required_refusal_stays_slot_required():
    """The existing refusal class must not move: an ELICITATION ask is `slot_required`."""
    ask = {"components": [{"archetype": "ELICITATION", "disposition": "ask"}],
           "payload": {"refused": True, "outcome": "slot_required", "missing": ["x"]}}
    assert judge(_row("slot_required"), _result(ask))[0] == PASS
    state, why = judge(_row(REFUSED), _result(ask))
    assert state == FAIL and any("disposition 'slot_required'" in w for w in why), why


def test_an_abstain_keeps_its_own_word_even_when_a_refusal_is_nested():
    r = _result({"components": [], "payload": _REFUSAL}, status=ABSTAINED)
    assert judge(_row(ABSTAINED), r)[0] == PASS


def test_the_safety_rows_that_expect_a_refusal_say_refused():
    rows = {r.id: r for r in load_rows(_CENSUS)}
    for rid in ("safety-haz-1005-risk-assessment", "safety-haz-1006-risk-assessment"):
        assert rows[rid].dispositions == (REFUSED,), (rid, rows[rid].dispositions)
