"""No automated path sets `safety_critical` to false or removes it.

Ruled 2026-10-28: promotion writes `safety_critical = true` when the rule says so and never writes
false. Clearing the property is a human action under the second-approver rule, never automation.
This censuses the FORM of every write to the property across setup, src, agent_fleet and scripts:

  * `SET x.safety_critical = false` (or null/None)
  * `REMOVE x.safety_critical`
  * a parameterised SET whose value can be false: `SET x.safety_critical = $param`, and the map
    forms `safety_critical: false|$param` after a `SET x += {` / `SET x = {`.

The only permitted write is the literal `= true`; a conditional is expressed around it (WHERE or
FOREACH), never by passing a boolean in. Positive controls prove each detector fires.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ROOTS = ("setup", "src", "agent_fleet", "scripts")
_SUFFIXES = {".py", ".cypher", ".cql", ".sql", ".sh", ".yaml", ".yml"}

_FORMS = {
    "set-false": re.compile(r"safety_critical\s*=\s*(?:false|False|null|None)\b"),
    "remove": re.compile(r"\bREMOVE\b[^\n]*\bsafety_critical\b", re.I),
    "set-param": re.compile(r"safety_critical\s*=\s*\$\w+"),
    "map-false-or-param": re.compile(r"safety_critical['\"]?\s*:\s*(?:false|False|null|None|\$\w+)"),
}


def _census():
    hits = []
    for root in _ROOTS:
        for p in sorted((_REPO / root).rglob("*")):
            rel = p.relative_to(_REPO).as_posix()
            if (p.suffix not in _SUFFIXES or not p.is_file() or "/.venv" in rel
                    or "__pycache__" in rel or "node_modules" in rel):
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for name, rx in _FORMS.items():
                    if rx.search(line):
                        hits.append(f"{rel}:{i} [{name}]")
    return hits


def test_CONTROL_each_detector_fires_on_its_form():
    samples = {
        "set-false": "SET c.safety_critical = false",
        "remove": "REMOVE c.safety_critical",
        "set-param": "SET c.safety_critical = $flag",
        "map-false-or-param": "SET c += {safety_critical: $flag}",
    }
    for name, text in samples.items():
        assert _FORMS[name].search(text), name
    assert not any(rx.search("SET c.safety_critical = true") for rx in _FORMS.values())


def test_CONTROL_the_census_sees_the_one_permitted_write():
    seed = (_REPO / "setup" / "safety_critical_seed.py").read_text(encoding="utf-8")
    assert "SET c.safety_critical = true" in seed, "the census population no longer includes the seed"


def test_no_automated_path_sets_safety_critical_false_or_removes_it():
    assert _census() == [], "an automated path clears or may clear safety_critical (human action only)"
