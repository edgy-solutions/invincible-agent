"""`refused` is a walk-census disposition: the VERB returned a named refusal.

Added 2026-10-09 (architect ruling). A vocabulary word that the sheet can write and the runner can
never produce passes through the loader and never matches, so every arm here fires the classifier
on a payload, not only the loader on a word.

THE WIRE SHAPE (rewritten 2026-10-10): the client never sees an engine verb body, only the cards
presentation draws. A refusal therefore rides at components[i]["refusal"] (presentation REFUSAL_FIELD),
never at final["payload"], and is read by that NAME.

Run: uv run pytest tests/test_the_refused_disposition_is_read_not_assumed.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.engine_abstain import ABSTAINED  # noqa: E402
from iagent_pure.walk_census import (  # noqa: E402
    DISPOSITIONS, FAIL, PASS, REFUSAL_FIELD, REFUSED, CensusRow, judge, load_rows,
)

_CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"


def _row(*dispositions: str, outcome: str | None = None) -> CensusRow:
    return CensusRow(
        id="fixture-row", sheet="fixture", sheet_index=1, question="q", user="bob",
        persona="SAFETY_ENGINEER", domains=("SUSTAINMENT",), frontend_id="fixture-frontend",
        expect_verb=None, expect_archetype=None, min_rows=0,
        dispositions=tuple(dispositions), expect_refusal_outcome=outcome,
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


_REFUSAL = {"refused": True, "outcome": "hazard_closed", "reason": "closed"}


def _doc(refusal=None):
    c = {"archetype": "KNOWLEDGE_DOCUMENT"}
    if refusal is not None:
        c[REFUSAL_FIELD] = refusal
    return c


def test_REFUSED_is_in_the_vocabulary_and_is_not_abstained():
    assert REFUSED == "refused" and REFUSED in DISPOSITIONS
    assert REFUSED != ABSTAINED and ABSTAINED in DISPOSITIONS


def test_the_two_names_cannot_drift():
    """walk_census may not import agent_fleet, so read the producer's source as TEXT."""
    src = (_REPO / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    found = re.findall(r'^REFUSAL_FIELD = "(\w+)"', src, re.MULTILINE)
    assert len(found) == 1, found
    assert found[0] == REFUSAL_FIELD


def test_a_named_refusal_is_scored_refused_and_a_row_accepting_it_passes():
    r = _result({"components": [_doc(_REFUSAL)]})
    assert judge(_row(REFUSED), r)[0] == PASS


def test_a_named_refusal_is_not_scored_drawn_so_a_row_accepting_drawn_fails_by_name():
    r = _result({"components": [_doc(_REFUSAL)]})
    state, why = judge(_row("drawn"), r)
    assert state == FAIL and any("disposition 'refused'" in w for w in why), why


def test_CONTROL_the_same_answer_without_the_refusal_is_drawn_not_refused():
    """Differs in exactly one thing: the card no longer says `refused: true`."""
    r = _result({"components": [_doc(dict(_REFUSAL, refused=False))]})
    state, why = judge(_row(REFUSED), r)
    assert state == FAIL and any("disposition 'drawn'" in w for w in why), why


def test_CONTROL_a_refusal_with_no_outcome_word_is_not_a_NAMED_refusal():
    r = _result({"components": [_doc({"refused": True, "reason": "which hazard?"})]})
    assert judge(_row(REFUSED), r)[0] == FAIL


def test_CONTROL_a_refusal_planted_only_in_events_or_final_payload_is_not_read():
    """The read is BY NAME: the same envelope anywhere but the card's field scores drawn."""
    planted_payload = _result({"components": [_doc()], "payload": dict(_REFUSAL)})
    planted_events = _result({"components": [_doc()]})
    planted_events["events"].append({"event": "x", "data": dict(_REFUSAL)})
    for r in (planted_payload, planted_events):
        state, why = judge(_row(REFUSED), r)
        assert state == FAIL and any("disposition 'drawn'" in w for w in why), why


def test_a_mixed_board_scores_drawn():
    r = _result({"components": [_doc(), _doc(_REFUSAL)]})
    state, why = judge(_row(REFUSED), r)
    assert state == FAIL and any("disposition 'drawn'" in w for w in why), why
    assert judge(_row("drawn"), r)[0] == PASS


def test_a_slot_required_refusal_stays_slot_required():
    """The existing refusal class must not move: an ELICITATION ask is `slot_required`."""
    ask = {"components": [{"archetype": "ELICITATION", "disposition": "ask",
                           REFUSAL_FIELD: {"refused": True, "outcome": "slot_required"}}]}
    assert judge(_row("slot_required"), _result(ask))[0] == PASS
    state, why = judge(_row(REFUSED), _result(ask))
    assert state == FAIL and any("disposition 'slot_required'" in w for w in why), why


def test_an_abstain_keeps_its_own_word_even_when_a_refusal_is_nested():
    r = _result({"components": [_doc(_REFUSAL)]}, status=ABSTAINED)
    assert judge(_row(ABSTAINED), r)[0] == PASS


def test_the_expected_outcome_word_passes_on_a_match_and_fails_naming_both_on_a_mismatch():
    r = _result({"components": [_doc(_REFUSAL)]})
    assert judge(_row(REFUSED, outcome="hazard_closed"), r)[0] == PASS
    bad = _result({"components": [_doc(dict(_REFUSAL, outcome="source_unavailable"))]})
    state, why = judge(_row(REFUSED, outcome="hazard_closed"), bad)
    assert state == FAIL and any(
        "refusal outcome 'source_unavailable' != expected 'hazard_closed'" in w for w in why), why


def test_the_safety_rows_that_expect_a_refusal_say_refused_and_name_their_outcome():
    rows = {r.id: r for r in load_rows(_CENSUS)}
    want = {"safety-haz-1005-risk-assessment": "hazard_closed",
            "safety-haz-1006-risk-assessment": "not_assessed"}
    for rid, outcome in want.items():
        assert rows[rid].dispositions == (REFUSED,), (rid, rows[rid].dispositions)
        assert rows[rid].expect_refusal_outcome == outcome, (rid, rows[rid].expect_refusal_outcome)


# ── Q13-shaped seals: a refusal that names itself only in `reason` (unknown part) ────────────

_REPRO_ID = "repro-failures-recorded-for-part-5530-184"
_UNKNOWN_PART = {"refused": True, "outcome": "refused", "reason": "unknown part '5530-184'"}


def _fracas(final, status="matched"):
    """`_result` routed to the FRACAS verb the repro row expects."""
    r = _result(final, status)
    d = r["events"][0]["data"]
    d["action"] = {"iri": "mesh:whatFailedOnThisPart"}
    d["handled_by"] = {"endpoint_url": "http://engine-safety/measure/what_failed_on_this_part"}
    return r


def _repro_row() -> CensusRow:
    return {r.id: r for r in load_rows(_CENSUS)}[_REPRO_ID]


def test_the_unknown_part_refusal_passes_the_real_repro_row():
    r = _fracas({"components": [_doc(_UNKNOWN_PART), _doc(_UNKNOWN_PART)]})
    state, why = judge(_repro_row(), r)
    assert state == PASS, why


def test_a_refusal_with_a_different_reason_fails_naming_both_strings():
    bad = _fracas({"components": [_doc(dict(_UNKNOWN_PART, reason="source_unavailable"))]})
    state, why = judge(_repro_row(), bad)
    assert state == FAIL and any(
        "source_unavailable" in w and "lacks 'unknown part'" in w for w in why), why


def test_CONTROL_the_rev_185_abstain_fails_the_repro_row():
    """The 185 result: the supervisor abstained (`no_verb_classified`). Not refused, not drawn."""
    r = _fracas({"components": [_doc()]}, status=ABSTAINED)
    state, why = judge(_repro_row(), r)
    assert state == FAIL and any("disposition 'abstained'" in w for w in why), why


def test_the_repro_row_is_the_hand_repro_on_its_own_sheet():
    row = _repro_row()
    assert row.expect_verb == "what_failed_on_this_part"
    assert row.expect_refusal_reason_contains == "unknown part"
    assert (row.user, row.persona) == ("bob", "SAFETY_ENGINEER")
    assert row.sheet == "docs/measurements/hand-repro-walk-sheet.md"
    assert not row.sheet.endswith("safety-walk-sheet.md")
