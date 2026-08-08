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

# Known, NAMED debt — `provenance-telemetry` publishes NO TAGS upstream, so there is nothing to
# pin to but a SHA, and freezing seven components' telemetry is a deployment decision, not a
# test's to make. Listed so the guard still blocks NEW floating deps while this one is open.
# Removing an entry here is the fix; adding one requires the same explicit argument.
_KNOWN_UNPINNED = {"provenance-telemetry"}


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
