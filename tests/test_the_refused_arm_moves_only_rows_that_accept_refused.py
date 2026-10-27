"""MEASURED, NOT ASSERTED IN A COMMENT: the `refused` arm of `judge` moves no existing row.

The hunk's comment said "no existing row's verdict moves" and nothing measured it. This runs every
census row through the CURRENT judge and through the judge as it was before the arm existed (the
arm's only input, `_card_refusals`, forced empty - structurally the pre-arm judge, since the arm
is `elif _card_refusals(...)`), over a battery of answers built from each row's own expectations.

  * Boards with NO refusal on a card: the two judges must agree on every row (the claim).
  * Boards where EVERY card refuses: rows move only in the right direction (see the test).
  * A mixed board (one refusing card, one plain): the two judges agree on every row.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from iagent_pure import walk_census as wc  # noqa: E402

_ROWS = wc.load_rows(_REPO / "docs" / "measurements" / "walk-census.yaml")
_REFUSAL = {"refused": True, "outcome": "hazard_closed", "reason": "closed"}


def _answer(row, cards):
    return {
        "events": [{"event": "route_decision", "data": {
            "action": {"iri": row.expect_verb or "mesh:anything"},
            "handled_by": {"endpoint_url": f"http://engine/measure/{row.expect_verb or 'x'}"},
            "route_status": "matched", "fallback": False,
        }}],
        "final": {"components": cards},
    }


def _card(row, refusal=None):
    c = {"archetype": row.expect_archetype or "KNOWLEDGE_DOCUMENT"}
    if refusal:
        c[wc.REFUSAL_FIELD] = dict(refusal)
    return c


def _refusal_for(row):
    """The refusal this row would be waiting for, so a row that names an outcome or a reason is
    given the one it asks for."""
    return {"refused": True, "outcome": row.expect_refusal_outcome or "hazard_closed",
            "reason": row.expect_refusal_reason_contains or "closed"}


def _old_and_new(row, cards, monkeypatch):
    new = wc.judge(row, _answer(row, cards))
    monkeypatch.setattr(wc, "_card_refusals", lambda comps: [])
    old = wc.judge(row, _answer(row, cards))
    monkeypatch.undo()
    return old, new


def test_the_census_is_not_empty():
    assert len(_ROWS) >= 30


def test_no_refusal_on_any_card_the_two_judges_agree_on_every_row(monkeypatch):
    for row in _ROWS:
        for cards in ([_card(row)], [_card(row), _card(row)], []):
            old, new = _old_and_new(row, cards, monkeypatch)
            assert old == new, (row.id, len(cards))


def test_a_mixed_board_the_two_judges_agree_on_every_row(monkeypatch):
    for row in _ROWS:
        old, new = _old_and_new(row, [_card(row, _REFUSAL), _card(row)], monkeypatch)
        assert old == new, row.id


def test_every_card_refusing_moves_rows_only_in_the_right_direction(monkeypatch):
    """MEASURED: an all-refused board is no longer `drawn`. So a row accepting only `drawn` goes
    PASS -> FAIL on it (correct: a refusal drawn as a card is not a drawn answer), and a row
    accepting `refused` goes FAIL -> PASS. Never the reverse for either."""
    moved = []
    for row in _ROWS:
        old, new = _old_and_new(row, [_card(row, _refusal_for(row))], monkeypatch)
        if old[0] == new[0]:
            continue
        moved.append((row.id, old[0], new[0]))
        if wc.REFUSED in row.dispositions:
            assert (old[0], new[0]) == (wc.FAIL, wc.PASS), row.id
        else:
            assert (old[0], new[0]) == (wc.PASS, wc.FAIL), row.id
    assert any(wc.REFUSED in r.dispositions for r in _ROWS if r.id in {m[0] for m in moved}), (
        "positive control: no refused-accepting row moved, so the arm was never exercised"
    )
