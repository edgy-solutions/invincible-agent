"""Where-used rolls a part's quantity up through every level of the structure (ADR-0065 s4).

The synthetic fixture has P at the third level (E1 -> ASM-A -> SUB-B -> P) and at the second
(ASM-A -> P, applicable to E1 only), in two end items on different programs, and in a third end
item (E3) that no program sustains. qty_per(E1, P) = 2 * (3*4 + 1) = 26; qty_per(E2, P) = 12.

Run: uv run pytest tests/test_where_used_rolls_up_through_every_level.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from agent_fleet.ontology_service import where_used as w

REPO = Path(__file__).resolve().parents[1]
ALICE, BOB, CAROL = "alice@example.com", "bob@example.com", "carol@example.com"

DATASET = w.load_dataset(REPO / w.SHIPPED_LOCATOR)
_FIXTURE = yaml.safe_load((REPO / w.SHIPPED_LOCATOR).read_text(encoding="utf-8"))


def _grants() -> dict:
    programs = yaml.safe_load((REPO / "policy/program_members.yaml").read_text(encoding="utf-8"))["programs"]
    return {k: set(v.get("grant_to") or []) for k, v in programs.items()}


def can_view(program: str, caller_id: str) -> bool:
    return caller_id in _grants().get(program, set())


def ident(label: str) -> str:
    return next(i["identity"] for i in _FIXTURE["identities"] if i["label"] == label)


def program_of(label: str) -> str:
    """The program the fixture declares the end item sustained under: read, never restated."""
    return next(r["program"] for r in _FIXTURE["sustained_under"] if r["end_item"] == ident(label))


def ask(part: str, caller: str, configuration=None) -> dict:
    return w.where_used(DATASET, part, configuration, caller_id=caller, can_view_program=can_view)


def _by_label(answer: dict) -> dict:
    return {DATASET.identities[r["end_item"]]["label"]: r for r in answer["where_used"]}


def test_ALICE_SEES_BOTH_END_ITEMS_WITH_THE_QUANTITY_ROLLED_UP_THROUGH_EVERY_LEVEL():
    got = ask(ident("P"), ALICE)
    assert got["status"] == "ok" and got["count"] == 2
    rows = _by_label(got)
    assert set(rows) == {"E1", "E2"}, "E3 has no sustained-under row and is never served"
    assert rows["E1"]["qty_per"] == 26
    assert rows["E2"]["qty_per"] == 12
    assert rows["E1"]["program"] == program_of("E1")
    assert rows["E2"]["program"] == program_of("E2")
    assert program_of("E1") != program_of("E2"), "the fixture's two end items are on different programs"
    assert [r["end_item"] for r in got["where_used"]] == [ident("E1"), ident("E2")]


def test_BOB_SEES_ONLY_THE_END_ITEM_ON_A_PROGRAM_BOB_MAY_VIEW():
    got = ask(ident("P"), BOB)
    assert [DATASET.identities[r["end_item"]]["label"] for r in got["where_used"]] == ["E1"]


def test_CAROL_GETS_THE_UNKNOWN_PART_ENVELOPE_BYTE_EQUAL_TO_A_PART_THAT_DOES_NOT_EXIST():
    withheld = ask(ident("P"), CAROL)
    missing = ask("urn:uuid:00000000-0000-7000-8000-00000000ffff", CAROL)
    assert withheld["reason"] == "unknown_part"
    assert json.dumps(withheld, sort_keys=True) == json.dumps(missing, sort_keys=True)


def test_AN_END_ITEM_NO_PROGRAM_SUSTAINS_IS_NEVER_SERVED_TO_ANYONE():
    for caller in (ALICE, BOB, CAROL):
        got = ask(ident("P"), caller)
        assert ident("E3") not in json.dumps(got), caller


def test_ASKING_BY_ALIAS_AND_BY_IDENTITY_GIVE_THE_SAME_ANSWER():
    alias = next(i for i in _FIXTURE["identities"] if i["label"] == "P")["aliases"][0]
    by_identity = ask(ident("P"), ALICE)
    for text in (alias["value"], f"{alias['scheme']}:{alias['value']}"):
        assert ask(text, ALICE) == by_identity, text


def test_A_PART_USED_NOWHERE_IS_REFUSED_NOT_AN_EMPTY_TABLE():
    got = ask(ident("P-UNUSED"), ALICE)
    assert got["refused"] is True and got["reason"] == "no_usage"
    assert "where_used" not in got


def test_APPLICABILITY_AND_EVERY_PATH_BOTH_MATTER():
    # P under ASM-A applies to E1 only (E2 reads 12, not 13), and E1 has two paths (not one).
    rows = _by_label(ask(ident("P"), ALICE))
    assert rows["E2"]["qty_per"] != 13
    assert rows["E1"]["qty_per"] != 24
