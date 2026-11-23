"""Where-used takes a declared configuration and refuses one it holds no data for (ruling 2).

The vocabulary and the default are READ from ADR-0065's ruling 2 text, not restated.

Run: uv run pytest tests/test_where_used_configuration_is_declared.py -q
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from agent_fleet.ontology_service import where_used as w
from tests.test_where_used_rolls_up_through_every_level import (
    _FIXTURE, ALICE, ask, can_view, ident,
)

ADR = next((Path(__file__).resolve().parents[1] / "docs/adr").glob("ADR-0065-*.md"))


def _ruling_two() -> tuple[tuple[str, ...], str]:
    text = re.sub(r"\s+", " ", ADR.read_text(encoding="utf-8"))
    m = re.search(r"`configuration` is an argument of the verb \(`([a-z_ |]+)`, default `([a-z_]+)`\)", text)
    assert m, "ruling 2's vocabulary line moved; update this reader, do not restate the list"
    return tuple(v.strip() for v in m.group(1).split("|")), m.group(2)


def test_THE_SHIPPED_VOCABULARY_AND_DEFAULT_ARE_RULING_TWOS():
    vocabulary, default = _ruling_two()
    assert w.CONFIGURATIONS == vocabulary
    assert w.DEFAULT_CONFIGURATION == default


def test_THE_DECLARED_SLOT_CARRIES_THE_VOCABULARY_AND_THE_DEFAULT():
    vocabulary, default = _ruling_two()
    slot = next(s for s in w.slots() if s["name"] == "configuration")
    assert tuple(slot["values"]) == vocabulary and slot["default"] == default


def test_ABSENT_AND_EMPTY_CONFIGURATION_ANSWER_THE_DEFAULT():
    _, default = _ruling_two()
    for value in (None, ""):
        got = ask(ident("P"), ALICE, value)
        assert got["configuration"] == default
        assert got["where_used"] and all(r["configuration"] == default for r in got["where_used"])


def test_A_CONFIGURATION_WITH_NO_DATA_IS_REFUSED_NAMING_THE_END_ITEMS_NEVER_AN_EMPTY_TABLE():
    got = ask(ident("P"), ALICE, "as_built")
    assert got["refused"] is True and got["reason"] == "configuration_not_available"
    assert "where_used" not in got and "rows" not in got
    assert "E1" in got["message"] and "E2" in got["message"]


def test_AN_UNKNOWN_CONFIGURATION_LISTS_THE_VOCABULARY():
    vocabulary, _ = _ruling_two()
    got = ask(ident("P"), ALICE, "as_imagined")
    assert got["reason"] == "unknown_configuration"
    assert all(v in got["message"] for v in vocabulary)


def test_WHEN_ONLY_ONE_END_ITEM_LACKS_THE_CONFIGURATION_ONLY_THAT_ONE_IS_NAMED():
    raw = copy.deepcopy(_FIXTURE)
    e2 = ident("E2")
    for row in raw["end_items"]:
        if row["identity"] == e2:
            row["configurations"] = ["as_designed", "as_built"]
    raw["usages"].append({"parent": e2, "child": ident("P"), "quantity": 7,
                          "configuration": "as_built"})
    ds = w.build_dataset(raw)
    got = w.where_used(ds, ident("P"), "as_built", caller_id=ALICE, can_view_program=can_view)
    assert got["reason"] == "configuration_not_available"
    assert "E1" in got["message"] and "E2" not in got["message"]
