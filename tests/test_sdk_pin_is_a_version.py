"""The SDK pin is a VERSION, never a floating ref.

WHY THIS IS A TEST AND NOT A CONVENTION. `iagent-mesh` now owns transport auth (the
app-factory dependency every engine inherits) and the ONE general mint. An unpinned
`git+https://...` resolves to the default branch at BUILD time, so a single SDK commit would
change every engine's security behaviour on the next rebuild — with nobody deciding, and no
diff in this repo to review. That is the library-bump outage class with credentials attached.

The precedent is already paid for: doc-tools' floating leaf pin meant a rebuild silently
changed what shipped, and the recovery took git-history archaeology. A pin is cheap; the
class it closes is not.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PINNED = [_ROOT / "pyproject.toml",
           _ROOT / "agent_fleet" / "restate_analyst" / "pyproject.toml"]

_SDK = re.compile(r'"iagent-mesh @ git\+[^"@]+\.git@(?P<ref>[^"]+)"')


@pytest.mark.parametrize("path", _PINNED, ids=lambda p: p.parent.name)
def test_sdk_is_pinned_to_a_tag(path: Path):
    src = path.read_text(encoding="utf-8")
    m = _SDK.search(src)
    assert m, f"{path} does not pin iagent-mesh at all — a floating dep on the auth package"
    ref = m.group("ref")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", ref), (
        f"{path} pins {ref!r} — that is a REF, not a version. Branches move; releases do not."
    )


@pytest.mark.parametrize("path", _PINNED, ids=lambda p: p.parent.name)
def test_no_bare_sdk_dependency_survives(path: Path):
    """A bare `...sdk.git` with no @ref is the floating form this exists to forbid."""
    src = path.read_text(encoding="utf-8")
    assert not re.search(r'"iagent-mesh @ git\+[^"]+sdk\.git"', src), (
        f"{path} carries an UNPINNED iagent-mesh dependency"
    )
