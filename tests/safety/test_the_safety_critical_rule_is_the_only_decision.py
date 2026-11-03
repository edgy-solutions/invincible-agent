"""THE RULE (agent_fleet/safety_agent/safety_critical.py) is the one place "safety-critical" is decided.

Ruled 2026-10-28: the seed (existing nodes, prime hook) and promotion (new nodes, cortex-bff) both
call it. These arms seal (a) the seed and the rule agree for every record, (b) no second
implementation exists, with a positive control for the detector, (c) both callers' images ship the
module's tree, (d) the rule's domain is the one Engine S registers, and (e) the census reads the
seed's unmatched list (a strict xfail: scripts/version_census.py is Lane 1's file).
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from agent_fleet.safety_agent import entities  # noqa: E402
from agent_fleet.safety_agent import safety_critical as rule  # noqa: E402

_spec = importlib.util.spec_from_file_location("safety_critical_seed_t", _REPO / "setup" / "safety_critical_seed.py")
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def _records():
    return list(dict.fromkeys(c.part_number for c in entities.SAFETY_ITEMS))


# -- (a) the seed and the rule agree for every record -----------------------------------------
def test_the_rule_says_yes_for_every_record_in_the_engines_domain_and_no_elsewhere():
    assert _records()
    for pn in _records():
        assert rule.safety_critical(pn, rule.DOMAIN) is True, pn
        assert rule.safety_critical(pn, "PRODUCTION_COST") is False, pn


def test_the_rule_says_no_for_a_part_that_is_not_a_record_and_for_a_non_string():
    assert rule.safety_critical("ZZ-NOT-IN-SEED", rule.DOMAIN) is False
    assert rule.safety_critical(None, rule.DOMAIN) is False
    assert rule.safety_critical(" " + _records()[0], rule.DOMAIN) is False, "exact match, as the graph's"


def test_the_seed_writes_exactly_the_parts_for_which_the_rule_says_yes():
    class S:
        calls = []

        def run(self, st, **p):
            self.calls.append(p["mpn"])

            class R:
                def single(self_inner):
                    return {"matched": 1}
            return R()

    s = S()
    seed.seed(s)
    assert s.calls == [pn for pn in s.calls if rule.safety_critical(pn, rule.DOMAIN)]
    assert sorted(s.calls) == sorted(_records())


# -- (b) one implementation ---------------------------------------------------------------------
_DECISION_TOKENS = re.compile(r"\bSAFETY_ITEMS\b|\bCRITICAL_ITEMS\b|\bCRITICAL_PART_NUMBERS\b")
_SETTER = re.compile(r"\bsafety_critical\s*=\s*(?:true|True)\b|\.safety_critical\s*=")
#: entity-data users of the records; none decides criticality for a graph write. measures.py:248 is
#: the interim per-request read, replaced by the mesh read (queued, ADR-0060).
_RECORD_USERS = {
    "agent_fleet/safety_agent/entities.py", "agent_fleet/safety_agent/safety_critical.py",
    "agent_fleet/safety_agent/measures.py", "agent_fleet/safety_agent/instances.py",
}


def _scan(root_rel, pattern, allow=()):
    hits = []
    for p in sorted((_REPO / root_rel).rglob("*.py")):
        rel = p.relative_to(_REPO).as_posix()
        if "/.venv" in rel or "__pycache__" in rel or rel in allow:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                hits.append(f"{rel}:{i}")
    return hits


def test_CONTROL_the_detector_finds_the_decision_in_the_rule_and_the_setter_in_the_seed():
    assert _scan("agent_fleet/safety_agent", _DECISION_TOKENS), "detector is blind to the rule's own read"
    assert _scan("setup", re.compile(r"SET c\.safety_critical = true")) or \
        "SET c.safety_critical = true" in (_REPO / "setup/safety_critical_seed.py").read_text(encoding="utf-8")
    assert _DECISION_TOKENS.search("x = SAFETY_ITEMS") and _SETTER.search("n.safety_critical = true")


def test_nothing_outside_the_engine_reads_the_records_to_decide_criticality():
    assert _scan("setup", _DECISION_TOKENS) == []
    assert _scan("src", _DECISION_TOKENS) == []
    assert _scan("scripts", _DECISION_TOKENS) == []
    others = [h for h in _scan("agent_fleet", _DECISION_TOKENS, allow=_RECORD_USERS)
              if not h.startswith("agent_fleet/safety_agent/")]
    assert others == [], others


def test_the_seed_asks_the_rule_and_does_not_read_the_records_itself():
    text = (_REPO / "setup" / "safety_critical_seed.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "rule.mpns(" in code and not _DECISION_TOKENS.search(code) and "part_number" not in code


def test_no_other_file_sets_safety_critical_on_a_node():
    hits = _scan("src", _SETTER) + _scan("setup", _SETTER, allow={"setup/safety_critical_seed.py"})
    assert hits == [], f"a second place decides/sets safety_critical (call the rule): {hits}"


# -- (c) both callers' images ship the module's tree -------------------------------------------
def test_both_callers_images_ship_the_whole_repo_so_the_rules_import_path_resolves():
    dagster = (_REPO / ".github/docker/Dockerfile.dagster").read_text(encoding="utf-8")
    assert re.search(r"^COPY \. /app\s*$", dagster, re.M), "prime-substrate image no longer copies the repo"
    wf = (_REPO / ".github/workflows/build-containers.yml").read_text(encoding="utf-8")
    m = re.search(r"- service: cortex-bff\s*\n\s*path: (\S+)", wf)
    assert m and m.group(1) == ".", "cortex-bff no longer builds from the repo root"
    agent = (_REPO / ".github/docker/Dockerfile.agent").read_text(encoding="utf-8")
    assert "COPY ${AGENT_DIR}/ /app/" in agent
    assert (_REPO / "agent_fleet/safety_agent/__init__.py").exists()


# -- (d) the rule's domain is the one Engine S registers ----------------------------------------
def test_the_rules_domain_is_the_domain_engine_s_registers():
    tree = ast.parse((_REPO / "agent_fleet/safety_agent/main.py").read_text(encoding="utf-8"))
    declared = [ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DOMAINS" for t in n.targets)]
    assert declared == [[rule.DOMAIN]], declared


# -- (e) the census reads the seed's unmatched list: Lane 1's file ---------------------------------
_CENSUS = _REPO / "scripts" / "version_census.py"


def test_CONTROL_the_census_already_reads_the_PrimeRun_row():
    assert "MATCH (p:PrimeRun)" in _CENSUS.read_text(encoding="utf-8")


@pytest.mark.xfail(strict=True, reason="scripts/version_census.py (lane/01) does not yet read "
                   "PrimeRun.safety_seed_unmatched_count or print `safety_seed_unmatched: N`")
def test_the_census_reports_safety_seed_unmatched():
    text = _CENSUS.read_text(encoding="utf-8")
    assert "safety_seed_unmatched_count" in text
    assert "safety_seed_unmatched:" in text
