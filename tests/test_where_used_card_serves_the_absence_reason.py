"""The where-used card serves the reason a null cell is null.

Cortex draws a null cell as "-" because the reason ("no source") lived only at
`where_used[].data_provenance.absent`. Chris ruled 11-19: the producer serves the reason on the
card and cortex shows the served words. `absent_reason` is `{column key: short phrase}`, derived
from each row's own `absent_reason` (the SDK v0.9.26 row field), never restated; a column that
differs by row carries it per row instead.

Run: uv run pytest tests/test_where_used_card_serves_the_absence_reason.py -q
"""
from __future__ import annotations

from types import SimpleNamespace

from agent_fleet.ontology_service import where_used as w
from tests.test_where_used_rolls_up_through_every_level import ALICE, ask, ident


def _ok():
    got = ask(ident("P"), ALICE)
    assert got["status"] == "ok"
    return got


def _null_everywhere(got):
    return [c["key"] for c in got["columns"] if all(r[c["key"]] is None for r in got["rows"])]


def test_THE_OK_ENVELOPE_CARRIES_THE_NO_SOURCE_REASON():
    assert _ok()["absent_reason"] == {"population": "no source", "stock": "no source"}


def test_EVERY_KEY_IS_A_NULL_COLUMN_AND_THE_PHRASE_IS_THE_PROVENANCES():
    got = _ok()
    assert got["absent_reason"]
    for key, phrase in got["absent_reason"].items():
        assert key in _null_everywhere(got), key
        for r in got["where_used"]:
            assert r["absent_reason"][key] == phrase


def test_EVERY_NULL_COLUMN_WITH_A_PHRASE_IS_IN_THE_MAP():
    got = _ok()
    for key in _null_everywhere(got):
        phrases = {(r["absent_reason"] or {}).get(key) for r in got["where_used"]}
        if len(phrases) == 1 and None not in phrases:
            assert got["absent_reason"][key] == phrases.pop(), key


def test_A_COLUMN_WITH_A_VALUE_IS_NEVER_IN_THE_MAP():
    got = _ok()
    assert "qty_per" not in got["absent_reason"] and "program" not in got["absent_reason"]
    for c in got["columns"]:
        if any(r[c["key"]] is not None for r in got["rows"]):
            assert c["key"] not in got["absent_reason"], c["key"]


def test_EACH_PHRASE_IS_SHORT_AND_BOUNDED():
    for phrase in _ok()["absent_reason"].values():
        assert isinstance(phrase, str) and "\n" not in phrase and 0 < len(phrase) <= 40


def test_PHRASES_THAT_DIFFER_BY_ROW_LAND_PER_ROW_NOT_ON_THE_CARD():
    columns = [{"key": "population"}, {"key": "stock"}, {"key": "qty_per"}]
    table = [{"population": None, "stock": None, "qty_per": 1},
             {"population": None, "stock": None, "qty_per": 2}]
    rows = [SimpleNamespace(absent_reason={"population": "no source", "stock": "held back"}),
            SimpleNamespace(absent_reason={"population": "no source", "stock": "not read"})]
    card, per_row = w._absent_reason(columns, table, rows)
    assert card == {"population": "no source"}
    assert per_row == [{"stock": "held back"}, {"stock": "not read"}]
    table[0]["stock"] = 5
    card, per_row = w._absent_reason(columns, table, rows)
    assert "stock" not in card and all("stock" not in p for p in per_row)


def test_THE_PROJECTOR_PASSTHROUGH_CARRIES_ABSENT_REASON():
    from tests.finance.test_the_wire_carries_what_the_engine_declares import _projector_passthrough

    key, carried = _projector_passthrough()["INSTANCES_BY_PROPERTY"]
    assert key == "rows" and "absent_reason" in carried
    assert "absent_reason" in _ok()


def test_A_REFUSAL_CARRIES_NO_ABSENT_REASON():
    got = ask("no such part anywhere", ALICE)
    assert got["status"] != "ok"
    assert "absent_reason" not in got and "rows" not in got
