"""NO git dependency floats — enforced over EVERY pyproject, not a hand-listed pair.

WHY THIS EXISTS AS A GENERAL GUARD. `test_sdk_pin_is_a_version.py` already forbade a floating
`iagent-mesh`, but it read TWO hand-listed paths and matched ONE package name. So a floating
`dag-tools @ ...@master` sat in the very same root pyproject that test opened, and the guard
could not see it. The rule was followed where someone remembered and unenforced everywhere
else — the same defect shape as an engine set typed out by hand instead of derived by glob.

WHAT IT COST. Upstream renamed the dag-tools DISTRIBUTION (not its module) from `dag_tools` to
`edgy-dag-tools` between v0.1.0 and v0.1.1. `@master` followed the rename, and the requirement
name stopped matching the package metadata. uv REFUSES that mismatch; pip tolerates it. A venv
installed before the rename kept working, so the repo looked healthy from any machine that had
already installed it, and broke only on a FRESH resolve — i.e. exactly on a new contributor's
first setup, or in CI on a cold cache. A floating ref does not fail when it changes; it fails
later, somewhere else, for someone else.

THE DISCRIMINATING FACT for `@master` vs a tag is not "branches are risky" in the abstract: a
build input nobody pinned is a build input nobody DECIDED. The diff that changes behaviour then
lives in another repo, with no review in this one.

A pin may be a semver TAG or a full 40-hex SHA. Both are immutable; that is the whole property
being asserted. A branch, a bare `.git`, `HEAD`, or a short SHA are all rejected.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Every git dependency in the repo, discovered — never enumerated by hand.
_GIT_DEP = re.compile(r'"(?P<name>[A-Za-z0-9._-]+)\s*@\s*git\+(?P<url>[^"]+)"')
_IMMUTABLE = re.compile(r"^(?:v\d+\.\d+\.\d+[\w.-]*|[0-9a-f]{40})$")

# CLOSED 2026-08-08 — was {"provenance-telemetry"}. That package published no tags, so seven
# pyprojects carried it as a BARE git URL. It is now on PyPI at 0.1.0 and all seven declare
# `provenance-telemetry==0.1.0`. Empty is the correct state; an entry here is open debt.
_KNOWN_UNPINNED: set[str] = set()

# THE OBLIGATION MOVED — it did not vanish, and that distinction is the whole point of this
# block. Once a dependency is declared from an INDEX rather than from git, every test above
# stops seeing it: they match on `git+`. So emptying the allowlist above would have read as
# "resolved" when the check had merely lost jurisdiction — a guard going quiet and a guard
# going green look identical in a summary line.
#
# The floating form on an index is a BARE NAME: `"provenance-telemetry"` with no specifier
# resolves to whatever is newest at build time, which is the same "build input nobody decided"
# the git rule exists to forbid, wearing different syntax.
#
# Scoped to the distributions WE publish, because these are the ones where an upstream commit
# and a local rebuild are the same team's decision minutes apart — the case where drift is both
# most likely and least noticed. Third-party ranges are a different risk conversation.
_INTERNAL_DISTRIBUTIONS = {"provenance-telemetry", "iagent-mesh", "edgy-dag-tools", "dag-tools"}
_HAS_SPECIFIER = re.compile(r"[=<>~!]")


def _pyprojects() -> list[Path]:
    found = sorted(p for p in _ROOT.rglob("pyproject.toml")
                   if not any(part in {".venv", ".venv.wsl", "node_modules", ".git"}
                              for part in p.parts))
    assert found, "positive control: no pyproject.toml found at all — the glob is broken"
    return found


def _deps(path: Path) -> list[tuple[str, str]]:
    return [(m.group("name"), m.group("url")) for m in _GIT_DEP.finditer(
        path.read_text(encoding="utf-8"))]


@pytest.mark.parametrize("path", _pyprojects(),
                         ids=lambda p: str(p.relative_to(_ROOT)).replace("\\", "/"))
def test_every_git_dependency_is_pinned_to_an_immutable_ref(path: Path):
    for name, url in _deps(path):
        if name in _KNOWN_UNPINNED:
            continue
        assert "@" in url.split(".git")[-1] or ".git@" in url, (
            f"{path.relative_to(_ROOT)}: dependency {name!r} is a BARE git URL with no @ref — "
            f"it resolves to the default branch at BUILD time, so the shipped code is whatever "
            f"upstream merged last."
        )
        ref = url.split(".git@", 1)[1]
        assert _IMMUTABLE.fullmatch(ref), (
            f"{path.relative_to(_ROOT)}: dependency {name!r} pins {ref!r} — that is a MOVING "
            f"ref, not a version. Use a semver tag or a full 40-hex SHA. (This is the check "
            f"that `dag-tools @ ...@master` evaded by living outside the SDK-only guard.)"
        )


def test_the_known_unpinned_set_does_not_grow():
    """The allowlist is a ledger of open debt, not a place to put new exemptions."""
    floating = {name for path in _pyprojects() for name, url in _deps(path)
                if not _IMMUTABLE.fullmatch(url.split(".git@")[-1] if ".git@" in url else "")}
    unexpected = floating - _KNOWN_UNPINNED
    assert not unexpected, (
        f"new floating git dependencies appeared: {sorted(unexpected)}. Pin them to a tag or a "
        f"full SHA rather than adding them to _KNOWN_UNPINNED."
    )


@pytest.mark.parametrize("path", _pyprojects(),
                         ids=lambda p: str(p.relative_to(_ROOT)).replace("\\", "/"))
def test_internal_index_dependencies_carry_a_version(path: Path):
    """An internal package declared from an index must carry a VERSION SPECIFIER.

    This is the git rule's index-side twin, and it exists because the git-side tests cannot
    see these declarations at all. `"provenance-telemetry"` bare resolves to whatever is
    newest when the image builds; `"provenance-telemetry==0.1.0"` is a decision someone made
    and someone can review in a diff.
    """
    src = path.read_text(encoding="utf-8")
    # Only plain (non-git, non-path) requirement strings — git deps are covered above.
    for m in re.finditer(r'"(?P<req>[A-Za-z0-9._-]+(?:\[[^\]]*\])?[^"]*)"', src):
        req = m.group("req")
        if "@" in req or "/" in req:
            continue
        name = re.split(r"[\[=<>~! ]", req, 1)[0].strip().lower()
        if name not in _INTERNAL_DISTRIBUTIONS:
            continue
        assert _HAS_SPECIFIER.search(req), (
            f"{path.relative_to(_ROOT)}: internal dependency {name!r} is declared as a BARE "
            f"NAME ({req!r}) — it resolves to whatever is newest at BUILD time. That is the "
            f"same undecided build input the git-ref rule forbids, in index syntax. Pin it."
        )


def test_the_internal_pin_guard_is_not_vacuous():
    """Positive control: this guard is worthless if no internal dependency is declared anywhere.

    A rule that matches nothing passes forever. When `provenance-telemetry` moved from a git
    URL to an index requirement, every git-side test silently stopped covering it — so this
    asserts the new guard actually has subjects, which is the specific failure that motivated
    writing it.
    """
    found = set()
    for path in _pyprojects():
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"(?P<req>[A-Za-z0-9._-]+(?:\[[^\]]*\])?[^"]*)"', src):
            req = m.group("req")
            if "@" in req or "/" in req:
                continue
            name = re.split(r"[\[=<>~! ]", req, 1)[0].strip().lower()
            if name in _INTERNAL_DISTRIBUTIONS:
                found.add(name)
    assert found, (
        "no internal index dependency found in any pyproject — either they all moved back to "
        "git URLs (fine, the git tests cover them) or this guard's name set is stale. Either "
        "way it is currently asserting nothing."
    )


def test_dag_tools_name_matches_upstream_metadata():
    """The rename regression, pinned as a fact.

    Upstream's distribution is `edgy-dag-tools` from v0.1.1 on. A requirement still NAMED
    `dag-tools` at a >=v0.1.1 ref is the exact mismatch uv rejects, and pip hides.
    """
    for path in _pyprojects():
        for name, url in _deps(path):
            if "dag-tools.git" not in url:
                continue
            ref = url.split(".git@", 1)[1] if ".git@" in url else ""
            if re.fullmatch(r"v\d+\.\d+\.\d+", ref) and ref >= "v0.1.1":
                assert name == "edgy-dag-tools", (
                    f"{path.relative_to(_ROOT)}: pins dag-tools at {ref} but names it {name!r}; "
                    f"upstream renamed the distribution to `edgy-dag-tools` at v0.1.1 (the "
                    f"module is still `dag_tools`). uv refuses this mismatch."
                )
