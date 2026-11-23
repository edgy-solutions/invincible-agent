"""The notice's parts are in the synthetic BOM, so a notice and where-used join on a part.

PCN26-182 is a synthetic notice OpenDDIL built; its two parts sit in the fixture under SUB-B and,
for E1 only, directly under ASM-A. Each resolves by the number the notice prints and by the
component its graph edge names, and the rows obey the same program gate as every other part.
The part numbers are read from the fixture, never restated here.

Run: uv run pytest tests/test_where_used_joins_the_notice_parts.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_fleet.ontology_service import where_used as w

REPO = Path(__file__).resolve().parents[1]
ALICE, BOB = "alice@example.com", "bob@example.com"

DATASET = w.load_dataset(REPO / w.SHIPPED_LOCATOR)
_FIXTURE = yaml.safe_load((REPO / w.SHIPPED_LOCATOR).read_text(encoding="utf-8"))


def _grants() -> dict:
    programs = yaml.safe_load((REPO / "policy/program_members.yaml").read_text(encoding="utf-8"))["programs"]
    return {k: set(v.get("grant_to") or []) for k, v in programs.items()}


def can_view(program: str, caller_id: str) -> bool:
    return caller_id in _grants().get(program, set())


def _row(label: str) -> dict:
    return next(i for i in _FIXTURE["identities"] if i["label"] == label)


def alias(label: str, scheme: str) -> str:
    return next(a["value"] for a in _row(label)["aliases"] if a["scheme"] == scheme)


def program_of(label: str) -> str:
    return next(r["program"] for r in _FIXTURE["sustained_under"] if r["end_item"] == _row(label)["identity"])


def ask(part: str, caller: str) -> dict:
    return w.where_used(DATASET, part, caller_id=caller, can_view_program=can_view)


def _by_label(answer: dict) -> dict:
    return {DATASET.identities[r["end_item"]]["label"]: r for r in answer["where_used"]}


NOTICE_PARTS = [i["label"] for i in _FIXTURE["identities"]
                if any(a["scheme"] == "notice_part_number" for a in i["aliases"])]


def test_THE_FIXTURE_CARRIES_TWO_NOTICE_PARTS():
    assert NOTICE_PARTS == ["N-182", "N-183"]


@pytest.mark.parametrize("label", NOTICE_PARTS)
@pytest.mark.parametrize("scheme", ["notice_part_number", "graph_component"])
def test_A_NOTICE_PART_RESOLVES_BY_ITS_NUMBER_AND_BY_ITS_COMPONENT(label, scheme):
    assert w.resolve_part(DATASET, alias(label, scheme)) == [_row(label)["identity"]]


def test_ALICE_SEES_THE_FIRST_NOTICE_PART_IN_BOTH_END_ITEMS():
    got = ask(alias("N-182", "notice_part_number"), ALICE)
    assert got["status"] == "ok" and got["count"] == 2
    rows = _by_label(got)
    assert set(rows) == {"E1", "E2"}, "E3 reaches it too but no program sustains E3"
    assert rows["E1"]["qty_per"] == 12 and rows["E2"]["qty_per"] == 6
    assert rows["E1"]["program"] == program_of("E1") and rows["E2"]["program"] == program_of("E2")


def test_BOB_SEES_ONLY_THE_END_ITEM_ON_THEIR_PROGRAM():
    got = ask(alias("N-182", "graph_component"), BOB)
    assert got["status"] == "ok"
    assert set(_by_label(got)) == {"E1"}, "bob is not on E2's program: its row is withheld"


def test_THE_SECOND_NOTICE_PART_IS_USED_IN_E1_ONLY():
    got = ask(alias("N-183", "notice_part_number"), ALICE)
    assert got["status"] == "ok" and got["count"] == 1
    assert _by_label(got)["E1"]["qty_per"] == 2


def test_THE_EXISTING_PART_IS_UNDISTURBED():
    rows = _by_label(ask("0SYN1:PN-1001", ALICE))
    assert (rows["E1"]["qty_per"], rows["E2"]["qty_per"]) == (26, 12)
