"""No tracked lock resolves the langfuse client to 5.x, and every project caps it below 5.

Why: langfuse client 5 needs a Langfuse server on v4.59.0 or later. Work's Langfuse is
self-hosted, on 3.165.0, and client 4 works against servers from 3.63.0. So the fleet is
capped below 5 (ruled 2026-11-16).

Lift condition: Chris confirms that work's server is on v4.59 or later. Then delete this
file and the `<5` caps together.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[2]


def _tracked_locks() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*uv.lock"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line]


def langfuse_versions(lock_text: str) -> list[str]:
    data = tomllib.loads(lock_text)
    return [p["version"] for p in data.get("package", []) if p.get("name") == "langfuse"]


def lock_violations(lock_text: str) -> list[str]:
    """Resolved langfuse versions in this lock whose major is 5 or more."""
    return [v for v in langfuse_versions(lock_text) if int(v.split(".")[0]) >= 5]


def _caps_below_5(pyproject_text: str) -> bool:
    data = tomllib.loads(pyproject_text)
    reqs = list(data.get("project", {}).get("dependencies", []))
    for extra in data.get("project", {}).get("optional-dependencies", {}).values():
        reqs.extend(extra)
    reqs.extend(data.get("tool", {}).get("uv", {}).get("constraint-dependencies", []))
    for r in reqs:
        req = Requirement(r)
        if req.name.lower() == "langfuse" and not req.specifier.contains("5.0.0"):
            return True
    return False


def _locks_with_langfuse() -> list[str]:
    return [
        lock for lock in _tracked_locks()
        if langfuse_versions((ROOT / lock).read_text(encoding="utf-8"))
    ]


def test_enumeration_is_not_vacuous():
    locks = _tracked_locks()
    assert locks, "git ls-files found no uv.lock"
    assert "uv.lock" in locks, "the root uv.lock is not among the tracked locks"
    assert _locks_with_langfuse(), "no tracked lock carries langfuse"


def test_every_lock_resolves_langfuse_below_5():
    bad = {
        lock: lock_violations((ROOT / lock).read_text(encoding="utf-8"))
        for lock in _locks_with_langfuse()
    }
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"locks resolving langfuse 5.x: {bad}"


def test_every_such_project_caps_langfuse_below_5():
    uncapped = []
    for lock in _locks_with_langfuse():
        pyproject = ROOT / Path(lock).parent / "pyproject.toml"
        if not _caps_below_5(pyproject.read_text(encoding="utf-8")):
            uncapped.append(str(pyproject.relative_to(ROOT)))
    assert not uncapped, f"pyproject.toml without a langfuse<5 cap: {uncapped}"


def test_detector_control():
    synth = '[[package]]\nname = "langfuse"\nversion = "{}"\n'
    assert lock_violations(synth.format("5.2.0")) == ["5.2.0"]
    assert lock_violations(synth.format("4.15.6")) == []
    assert _caps_below_5('[project]\ndependencies = ["langfuse>=3.0.0,<5"]\n')
    assert not _caps_below_5('[project]\ndependencies = ["langfuse>=3.0.0,<6"]\n')
    assert not _caps_below_5('[project]\ndependencies = ["langfuse"]\n')
    assert _caps_below_5('[tool.uv]\nconstraint-dependencies = ["langfuse<5"]\n')
    assert SpecifierSet("<5").contains("4.99.0")
