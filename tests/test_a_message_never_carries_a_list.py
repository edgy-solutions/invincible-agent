"""A message never carries a list; lists are a structured field the card renders.

Ruled 2026-11-19 (architect, item 2d). The where-used and notice-parts answers used to splice end
item labels and MPNs into their `message`. The list now rides in a structured field
(`lists`, `parts`, the table rows), which the card renders.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_fleet.ontology_service import notice_parts as np_mod
from agent_fleet.ontology_service import where_used as w
from tests.planning.test_planning_archetypes_are_projected import _fns
from tests.test_notice_parts_refuses_none_and_pages_many import _read
from tests.test_where_used_rolls_up_through_every_level import ALICE, DATASET, ask, ident

ROOT = Path(__file__).resolve().parent.parent
ENGINE_FILES = [ROOT / "agent_fleet" / "ontology_service" / "where_used.py",
                ROOT / "agent_fleet" / "ontology_service" / "notice_parts.py"]


def _one_short_line(message):
    assert isinstance(message, str)
    assert "\n" not in message and len(message) <= 160, message


def _flat(values):
    for v in values:
        if isinstance(v, (list, tuple)):
            yield from _flat(v)
        elif isinstance(v, str):
            yield v


def _list_values(env):
    out = [v for v in env.values() if isinstance(v, list) and v and all(isinstance(x, str) for x in v)]
    return list(_flat(out))


def _labels(env):
    return [r["end_item"] for r in env.get("rows") or []]


def test_d1_where_used_unknown_configuration():
    got = ask(ident("P"), ALICE, "as_imagined")
    assert got["reason"] == "unknown_configuration"
    _one_short_line(got["message"])
    assert got["lists"][0]["items"] == list(w.CONFIGURATIONS)
    assert got["lists"][0]["total"] == len(w.CONFIGURATIONS)
    assert got["lists"][0]["label"] == "Configurations held here"
    assert "as_imagined" not in got["message"]
    for v in _list_values(got):
        assert v not in got["message"]


def test_d1_where_used_configuration_not_available():
    got = ask(ident("P"), ALICE, "as_built")
    assert got["reason"] == "configuration_not_available"
    _one_short_line(got["message"])
    expected = sorted(DATASET.identities[e]["label"] for e, confs in DATASET.end_items.items()
                      if "as_built" not in confs and DATASET.sustained_under.get(e))
    items = got["lists"][0]["items"]
    assert items == sorted(items) and items
    assert got["lists"][0]["total"] == len(items)
    assert "as_built" in got["lists"][0]["label"]
    assert set(items) <= set(expected)
    assert got["configuration"] == "as_built"
    assert "end_items" not in got and "configurations" not in got
    for v in items:
        assert v not in got["message"]


def test_d1_where_used_success_with_two_rows():
    got = ask(ident("P"), ALICE, w.DEFAULT_CONFIGURATION)
    assert got["status"] == "ok" and len(got["rows"]) >= 2
    _one_short_line(got["message"])
    for label in _labels(got):
        assert label not in got["message"]
    assert str(len(got["rows"])) in got["message"]


@pytest.mark.parametrize("n,offset", [(3, 0), (250, 0), (250, 100)])
def test_d2_notice_parts_complete_and_truncated_pages(n, offset):
    _, got = _read(n, offset)
    assert got["status"] == "ok" and len(got["parts"]) >= 2
    _one_short_line(got["message"])
    mpns = [p["mpn"] for p in got["parts"]]
    assert mpns == sorted(mpns)
    for m in mpns:
        assert m not in got["message"]
    assert got["data"] == got["message"]


def _refusal_env():
    return _fns()["_refusal_envelope"]


def test_d3_the_card_envelope_carries_the_structured_lists():
    env = _refusal_env()
    lacking = ask(ident("P"), ALICE, "as_built")
    assert env(lacking)["lists"] == lacking["lists"]
    unknown = ask(ident("P"), ALICE, "as_imagined")
    assert env(unknown)["lists"] == unknown["lists"]
    assert env(lacking)["message"] == lacking["message"]


def _both_refusals():
    return [ask(ident("P"), ALICE, "as_imagined"), ask(ident("P"), ALICE, "as_built")]


def _one_line_str(v):
    return isinstance(v, str) and "\n" not in v and "\r" not in v and len(v) <= 160


def test_d5_every_lists_the_producers_emit_has_the_proposed_shape():
    for got in _both_refusals():
        lists = got["lists"]
        assert isinstance(lists, list) and lists, got
        for entry in lists:
            assert isinstance(entry, dict) and set(entry) == {"label", "items", "total"}, entry
            assert _one_line_str(entry["label"]), entry["label"]
            assert isinstance(entry["items"], list) and entry["items"]
            assert all(_one_line_str(i) for i in entry["items"]), entry["items"]
            assert isinstance(entry["total"], int) and entry["total"] >= len(entry["items"])


def test_d6_the_presentation_envelope_carries_lists_unchanged_and_no_named_keys():
    env = _refusal_env()
    for got in _both_refusals():
        out = env(got)
        assert out["lists"] == got["lists"]
        assert "end_items" not in out and "configurations" not in out


def _join_in_message_position(source: str) -> list[int]:
    """Line numbers of an `<expr>.join(...)` inside a `message` assignment, the 2nd positional
    argument of `_refused(...)`, or the value of a "message" dict key."""
    def has_join(node):
        return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "join" for n in ast.walk(node))

    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "message" for t in targets) \
                    and node.value is not None and has_join(node.value):
                found.append(node.lineno)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "message" and has_join(node.value):
                found.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_refused":
            if len(node.args) >= 2 and has_join(node.args[1]):
                found.append(node.lineno)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "message" and has_join(v):
                    found.append(node.lineno)
    return found


def test_d4_positive_control_the_scanner_finds_a_join():
    assert _join_in_message_position('message = ", ".join(x)\n')
    assert _join_in_message_position('message = "a" + ", ".join(x)\n')
    assert _join_in_message_position('return _refused("r", f"a {\', \'.join(x)}")\n')
    assert _join_in_message_position('d = {"message": ", ".join(x)}\n')
    assert not _join_in_message_position('names = ", ".join(x)\nmessage = "ok"\n')


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_d4_no_join_feeds_a_message(path):
    assert _join_in_message_position(path.read_text(encoding="utf-8")) == []
