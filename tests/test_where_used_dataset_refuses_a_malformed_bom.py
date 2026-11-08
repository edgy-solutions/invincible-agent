"""The where-used loader refuses a malformed structure instead of rolling a quantity through it.

Run: uv run pytest tests/test_where_used_dataset_refuses_a_malformed_bom.py -q
"""
from __future__ import annotations

import copy

import pytest

from agent_fleet.ontology_service import where_used as w
from tests.test_where_used_rolls_up_through_every_level import _FIXTURE, ident


def _mutated(edit):
    raw = copy.deepcopy(_FIXTURE)
    edit(raw)
    return raw


def _usage(raw, **over):
    raw["usages"].append({"parent": ident("E1"), "child": ident("P"), "quantity": 1, **over})


CASES = {
    "usage_parent_unknown": lambda r: _usage(r, parent="urn:uuid:nope"),
    "usage_child_unknown": lambda r: _usage(r, child="urn:uuid:nope"),
    "quantity_zero": lambda r: _usage(r, quantity=0),
    "quantity_negative": lambda r: _usage(r, quantity=-2),
    "quantity_not_a_number": lambda r: _usage(r, quantity="3"),
    "cycle": lambda r: _usage(r, parent=ident("P"), child=ident("E1")),
    "end_item_unknown": lambda r: r["end_items"].append({"identity": "urn:uuid:nope", "configurations": []}),
    "sustained_under_unknown": lambda r: r["sustained_under"].append(
        {"end_item": "urn:uuid:nope", "program": "X"}),
    "usage_configuration_outside_vocabulary": lambda r: _usage(r, configuration="as_imagined"),
    "end_item_configuration_outside_vocabulary": lambda r: r["end_items"][0].update(
        configurations=["as_imagined"]),
    "alias_on_two_identities": lambda r: r["identities"][1]["aliases"].append(
        dict(r["identities"][0]["aliases"][0])),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_THE_LOADER_REFUSES(case):
    with pytest.raises(w.DatasetRefused):
        w.build_dataset(_mutated(CASES[case]))


def test_CONTROL_THE_UNMUTATED_FIXTURE_LOADS():
    assert w.build_dataset(copy.deepcopy(_FIXTURE)).identities


def test_AN_UNREADABLE_FILE_IS_REFUSED(tmp_path):
    with pytest.raises(w.DatasetRefused):
        w.load_dataset(tmp_path / "absent.yaml")
