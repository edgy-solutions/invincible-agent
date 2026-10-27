"""The safety_critical seed (setup/safety_critical_seed.py) migrates the fixture's answer onto the graph.

Ruled 2026-10-27 (P1): `MATCH (c:Component {mpn: $mpn}) SET c.safety_critical = true`, never MERGE,
never CREATE, never unset, no other property. These arms are OFFLINE: a double that records the
REQUEST (statement text + parameters) and keeps a tiny in-memory node set so idempotence and "a part
not in the seed is untouched" are observable. Nothing here touches a live graph.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from agent_fleet.safety_agent import entities  # noqa: E402


def _load_seed():
    spec = importlib.util.spec_from_file_location(
        "safety_critical_seed", _REPO / "setup" / "safety_critical_seed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = _load_seed()


class _Result:
    def __init__(self, n):
        self._n = n

    def single(self):
        return {"matched": self._n}


class _Session:
    """Records every request; models Component nodes by mpn and applies MATCH ... SET only."""

    def __init__(self, nodes):
        self.nodes = {mpn: dict(props) for mpn, props in nodes.items()}
        self.calls = []

    def run(self, statement, **params):
        self.calls.append((statement, dict(params)))
        node = self.nodes.get(params["mpn"])
        if node is None:
            return _Result(0)          # MATCH finds nothing: nothing is created
        node["safety_critical"] = True  # the only write the statement text names
        return _Result(1)


def _records():
    return [c.part_number for c in entities.SAFETY_ITEMS]


def test_CONTROL_the_records_exist_and_the_old_names_do_not():
    assert _records(), "the control needs a non-empty record set"
    assert not hasattr(entities, "CRITICAL_ITEMS")
    assert not hasattr(entities, "CRITICAL_PART_NUMBERS")


def test_the_statement_is_match_and_sets_exactly_safety_critical():
    s = seed.STATEMENT
    assert re.search(r"\bMATCH\s*\(c:Component\s*\{mpn:\s*\$mpn\}\)", s), s
    assert not re.search(r"\b(MERGE|CREATE|REMOVE|DELETE)\b", s, re.I), s
    sets = re.findall(r"\bSET\b(.*?)(?=\bRETURN\b|$)", s, re.I | re.S)
    assert len(sets) == 1 and re.fullmatch(r"\s*c\.safety_critical\s*=\s*true\s*", sets[0]), sets
    assert "false" not in s.lower() and "null" not in s.lower()


def test_CONTROL_the_statement_detector_fires_on_a_merge():
    bad = "MERGE (c:Component {mpn: $mpn}) SET c.safety_critical = true"
    assert re.search(r"\b(MERGE|CREATE|REMOVE|DELETE)\b", bad, re.I)


def test_the_parameter_set_is_the_records_part_numbers_read_not_restated():
    sess = _Session({pn: {} for pn in _records()})
    seed.seed(sess)
    assert [p["mpn"] for _, p in sess.calls] == list(dict.fromkeys(_records()))
    assert all(set(p) == {"mpn"} and st == seed.STATEMENT for st, p in sess.calls)


def test_running_it_twice_issues_the_same_writes_and_changes_nothing_more():
    sess = _Session({pn: {"mpn": pn} for pn in _records()})
    first = seed.seed(sess)
    after_first = {k: dict(v) for k, v in sess.nodes.items()}
    n1 = list(sess.calls)
    second = seed.seed(sess)
    assert first == second
    assert sess.calls[len(n1):] == n1
    assert sess.nodes == after_first
    assert all(v == {"mpn": k, "safety_critical": True} for k, v in sess.nodes.items())


def test_a_part_not_in_the_seed_is_untouched_and_a_missing_part_is_not_created():
    other = "ZZ-NOT-IN-SEED"
    absent = _records()[0]
    nodes = {pn: {} for pn in _records()[1:]}
    nodes[other] = {"mpn": other, "note": "keep"}
    sess = _Session(nodes)
    matched = seed.seed(sess)
    assert sess.nodes[other] == {"mpn": other, "note": "keep"}
    assert absent not in sess.nodes, "MATCH must never create the missing Component"
    assert matched[absent] == 0


def test_the_mpn_form_the_graph_stores_is_the_records_form():
    """promotion_stores writes `mpn=target` (steward/extracted text, stripped, NOT normalised) and
    doc-tools writes `affected_mpn` verbatim from the cell. The records' part numbers are the
    canonical spelling the sandbox uses (live PN-8801 resolves with matched_on "PN-8801"), so the
    MATCH is an exact-string match. This arm pins the records' form so a drift to a form the graph
    would not store (lowercase, padded, trailing punctuation) is red here, not a silent 0-node match."""
    for pn in _records():
        assert pn == pn.strip() and pn == pn.upper(), pn
        assert re.fullmatch(r"[A-Z0-9][A-Z0-9-]*[A-Z0-9]", pn), pn


def test_prime_neo4j_calls_the_seed_inside_the_session():
    text = (_REPO / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    body = text[text.index("def prime_neo4j"):]
    assert "safety_critical_seed.seed(session)" in body
