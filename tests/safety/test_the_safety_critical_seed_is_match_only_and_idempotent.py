"""The safety_critical seed (setup/safety_critical_seed.py) applies the RULE to existing Components.

Ruled 2026-10-27/28: `MATCH (c:Component:{DOMAIN} {mpn: $mpn}) SET c.safety_critical = true`, never
MERGE, never CREATE, never unset, no other property; scoped to the engine's domain label; a 0-match
is never silent and never fails setup. OFFLINE: a double that records the REQUEST and keeps a tiny
in-memory node set keyed (domain label, mpn). Nothing here touches a live graph.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from agent_fleet.safety_agent import entities  # noqa: E402
from agent_fleet.safety_agent import safety_critical as rule  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = _load("safety_critical_seed", "setup/safety_critical_seed.py")
prime = _load("prime_databases_under_test", "setup/prime_databases.py")

_LABEL = re.compile(r"MATCH \(c:Component(?::(\w+))? \{mpn: \$mpn\}\)")


class _Result:
    def __init__(self, n):
        self._n = n

    def single(self):
        return {"matched": self._n}

    def consume(self):
        return None


class _Session:
    """Records every request; nodes are {(label, mpn): props}. Applies MATCH ... SET only.

    The MATCH's domain label is READ FROM THE STATEMENT, so a statement with the label removed
    really does reach every domain -- that is what the control below relies on.
    """

    def __init__(self, nodes):
        self.nodes = {k: dict(v) for k, v in nodes.items()}
        self.calls = []

    def run(self, statement, **params):
        self.calls.append((statement, dict(params)))
        if "MATCH (c:Component" not in statement:
            return _Result(0)
        label = _LABEL.search(statement).group(1)
        n = 0
        for (lab, mpn), props in self.nodes.items():
            if mpn == params["mpn"] and (label is None or lab == label):
                props["safety_critical"] = True
                n += 1
        return _Result(n)


def _listed():
    return list(dict.fromkeys(c.part_number for c in entities.SAFETY_ITEMS))


def _graph(domains=("SUSTAINMENT",), parts=None):
    return {(d, pn): {"mpn": pn} for d in domains for pn in (parts if parts is not None else _listed())}


def test_CONTROL_the_records_exist_and_the_old_names_do_not():
    assert _listed(), "the control needs a non-empty record set"
    assert not hasattr(entities, "CRITICAL_ITEMS")
    assert not hasattr(entities, "CRITICAL_PART_NUMBERS")


def test_the_statement_is_match_scoped_to_the_domain_and_sets_exactly_safety_critical():
    s = seed.STATEMENT
    assert f"MATCH (c:Component:{rule.DOMAIN} {{mpn: $mpn}})" in s, s
    assert not re.search(r"\b(MERGE|CREATE|REMOVE|DELETE)\b", s, re.I), s
    sets = re.findall(r"\bSET\b(.*?)(?=\bRETURN\b|$)", s, re.I | re.S)
    assert len(sets) == 1 and re.fullmatch(r"\s*c\.safety_critical\s*=\s*true\s*", sets[0]), sets


def test_CONTROL_the_statement_detector_fires_on_a_merge():
    bad = "MERGE (c:Component {mpn: $mpn}) SET c.safety_critical = true"
    assert re.search(r"\b(MERGE|CREATE|REMOVE|DELETE)\b", bad, re.I)


def test_the_label_is_validated_before_it_is_interpolated():
    for bad in ("sustainment", "SUS TAINMENT", "X}) DETACH DELETE (c", ""):
        with pytest.raises(ValueError):
            seed.statement(bad)


def test_the_parameter_set_is_what_the_rule_lists_read_not_restated():
    sess = _Session(_graph())
    seed.seed(sess)
    assert [p["mpn"] for _, p in sess.calls] == rule.mpns(rule.DOMAIN)
    assert all(set(p) == {"mpn"} and st == seed.STATEMENT for st, p in sess.calls)


def test_running_it_twice_issues_the_same_writes_and_changes_nothing_more():
    sess = _Session(_graph())
    first = seed.seed(sess)
    after_first = {k: dict(v) for k, v in sess.nodes.items()}
    n1 = list(sess.calls)
    assert seed.seed(sess) == first
    assert sess.calls[len(n1):] == n1
    assert sess.nodes == after_first
    assert all(v == {"mpn": k[1], "safety_critical": True} for k, v in sess.nodes.items())


def test_a_part_not_in_the_seed_is_untouched_and_a_missing_part_is_not_created():
    other = "ZZ-NOT-IN-SEED"
    absent = _listed()[0]
    nodes = _graph(parts=_listed()[1:])
    nodes[("SUSTAINMENT", other)] = {"mpn": other, "note": "keep"}
    sess = _Session(nodes)
    out = seed.seed(sess)
    assert sess.nodes[("SUSTAINMENT", other)] == {"mpn": other, "note": "keep"}
    assert ("SUSTAINMENT", absent) not in sess.nodes, "MATCH must never create the missing Component"
    assert out["matched"][absent] == 0 and out["unmatched"] == [absent]


def _other_domain_is_untouched(statement_for):
    """Same mpn under two domain labels: only the engine's domain may be marked."""
    sess = _Session(_graph(domains=("SUSTAINMENT", "PRODUCTION_COST")))
    for pn in _listed():
        sess.run(statement_for(rule.DOMAIN), mpn=pn)
    assert all(v.get("safety_critical") for (d, _), v in sess.nodes.items() if d == "SUSTAINMENT")
    assert not any("safety_critical" in v for (d, _), v in sess.nodes.items() if d == "PRODUCTION_COST"), \
        "a Component in ANOTHER domain was marked"


def test_only_the_engines_domain_is_marked_when_the_same_mpn_is_in_two_domains():
    _other_domain_is_untouched(seed.statement)


def test_CONTROL_with_the_domain_removed_from_the_match_the_two_domain_test_fails():
    no_domain = lambda _d: seed.statement(rule.DOMAIN).replace(f":{rule.DOMAIN}", "")  # noqa: E731
    assert f":{rule.DOMAIN}" not in no_domain(rule.DOMAIN)
    with pytest.raises(AssertionError, match="ANOTHER domain"):
        _other_domain_is_untouched(no_domain)


def test_an_empty_graph_gives_every_listed_part_unmatched_and_does_not_raise():
    out = seed.seed(_Session({}))
    assert out["unmatched"] == _listed()
    assert set(out["matched"]) == set(_listed()) and not any(out["matched"].values())


def test_unmatched_and_matched_partition_the_rule_listing():
    out = seed.seed(_Session(_graph(parts=_listed()[:1])))
    hit = {p for p, n in out["matched"].items() if n}
    assert sorted(set(out["unmatched"]) | hit) == sorted(_listed())
    assert not set(out["unmatched"]) & hit


class _Driver:
    def __init__(self, sess):
        self._s = sess

    def session(self):
        return self

    def __enter__(self):
        return self._s

    def __exit__(self, *a):
        return False

    def close(self):
        pass


def test_prime_neo4j_on_an_empty_graph_returns_the_unmatched_list_and_does_not_fail(monkeypatch):
    sess = _Session({})
    monkeypatch.setattr(prime.GraphDatabase, "driver", staticmethod(lambda *a, **k: _Driver(sess)))
    assert prime.prime_neo4j() == _listed()


def test_the_prime_records_the_unmatched_list_and_count_on_its_PrimeRun_row(monkeypatch):
    sess = _Session({})
    monkeypatch.setattr(prime.GraphDatabase, "driver", staticmethod(lambda *a, **k: _Driver(sess)))
    prime.record_prime_run(wiped=False, safety_seed_unmatched=["PN-1", "PN-2"])
    (cypher, params), = [c for c in sess.calls if "PrimeRun" in c[0]]
    assert re.search(r"safety_seed_unmatched:\s+\$unmatched", cypher)
    assert params["unmatched"] == ["PN-1", "PN-2"] and params["unmatched_n"] == 2


def test_the_mpn_form_the_graph_stores_is_the_records_form():
    """promotion_stores writes `mpn=target` (stripped, NOT normalised) and doc-tools writes the cell
    verbatim; the records' part numbers are the canonical spelling. Pin the records' form so a drift
    to one the graph would not store is red here, not a silent 0-node match."""
    for pn in _listed():
        assert pn == pn.strip() and pn == pn.upper(), pn
        assert re.fullmatch(r"[A-Z0-9][A-Z0-9-]*[A-Z0-9]", pn), pn
