"""The suite must be importing the tree it is standing in — not another lane's checkout.

FOUND BY invincible-agent-32, 2026-09-09, hours after the worktree charter was adopted, and
REPRODUCED before this was written:

    cwd       : C:\\Users\\cnogr\\git\\ia-verify        (a fresh worktree)
    iagent    : C:\\Users\\cnogr\\git\\invincible-agent\\src\\iagent\\__init__.py
    SAME TREE?: False

The root venv carries an EDITABLE install (`_editable_impl_iagent.pth`) hard-bound to the
main checkout. So `import iagent` and `import iagent_pure` resolve to the MAIN tree from
inside any worktree that borrows that venv.

**WHAT IT COSTS A LANE.** Edit `src/iagent/gateway.py` in your worktree, run the suite with
the shared venv, and you have tested the main tree's copy of that file. Your change was never
imported. **The suite is green, the change is unverified, and nothing anywhere says so.**

THE FAILURE SCHEDULE IS THE WORST POSSIBLE ONE. A lane's own package files
(`agent_fleet/…`, `policy/…`, its own tests) resolve from CWD and are correct in a worktree;
`iagent_mesh` comes from site-packages and is correct. Only `src/iagent` and `src/iagent_pure`
are captured — so a lane can adopt the charter, work correctly for days, and be silently wrong
the first time they touch `src/`, which is exactly the shared ground the charter was written
to protect.

**THE FIX IS ONE COMMAND** — `uv sync` inside the worktree, giving it its own venv. This file
is the guard that makes forgetting it loud, because a charter line is not a guard: *"a comment
that must be read to be obeyed"* is the same standing objection this repo raised against the
helm-timeout note.

SAME CLASS AS THE IMAGE PIN FIXED THE SAME NIGHT — `global.imageTag` reaching repositories
that never built that sha, and a venv reaching a tree that never had your edit, are both **a
scope that looks local and is not**. The pin produced four ImagePullBackOffs, which are loud.
This produces a green test, which is silent, and silence is the more expensive of the two.

Run: uv run --frozen pytest tests/test_the_suite_is_testing_THIS_tree.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

#: The tree this FILE lives in — the thing whose code the suite is supposed to be exercising.
_TREE = Path(__file__).resolve().parents[1]


def _resolved(mod_name: str) -> Path:
    mod = pytest.importorskip(mod_name)
    f = getattr(mod, "__file__", None)
    assert f, f"{mod_name} has no __file__ to check"
    return Path(f).resolve()


@pytest.mark.parametrize("mod_name", ["iagent", "iagent_pure"])
def test_the_first_party_package_resolves_INSIDE_this_tree(mod_name):
    """`src/iagent` and `src/iagent_pure` are the two packages an editable install captures.

    If this fails you are running a venv bound to a DIFFERENT checkout, and every result in
    this suite is about that checkout's code rather than yours. Fix it, do not skip it:

        cd <this worktree> && uv sync

    Then confirm with the two-line check the charter carries.
    """
    where = _resolved(mod_name)
    assert _TREE in where.parents or where.is_relative_to(_TREE), (
        f"{mod_name} resolved to {where}\n"
        f"but this suite lives in {_TREE}\n\n"
        f"THE SUITE IS TESTING ANOTHER CHECKOUT'S CODE. Your edits under src/ were never "
        f"imported, and a green run here says nothing about them. Run `uv sync` in this "
        f"worktree to give it its own venv."
    )


def test_the_check_can_actually_FAIL():
    """THE CONTROL, and it is not ceremony here.

    The assertion above compares two paths. If `_TREE` were computed from the imported
    module — or if `is_relative_to` were passed something that is trivially true — it would
    pass in every tree including the wrong one, which is precisely the failure being
    guarded. So: a path that is definitely NOT under this tree must be rejected by the same
    comparison.
    """
    foreign = Path(_TREE.anchor) / "definitely" / "not" / "this" / "tree" / "iagent" / "x.py"
    assert not (_TREE in foreign.parents or foreign.is_relative_to(_TREE)), (
        "the containment check accepts a path outside the tree — it cannot detect the "
        "wrong-tree import it exists for"
    )


def test_the_tree_is_a_real_checkout_and_not_a_coincidence():
    """A floor on `_TREE` itself. If `parents[1]` ever stops being the repo root, the test
    above starts comparing against something arbitrary and passes for a new wrong reason."""
    assert (_TREE / "pyproject.toml").is_file(), f"{_TREE} is not the repo root"
    assert (_TREE / "src" / "iagent").is_dir()


def test_the_worktree_hazard_is_NAMED_where_someone_will_meet_it():
    """The charter must carry the `uv sync` step, not just the `worktree add`.

    Adopted 2026-09-09 with the step missing; 32 hit it within hours. A structural fix that
    is one command away from silent failure needs that command written beside it, and this
    asserts it stayed there.
    """
    charter = (_TREE / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    i = charter.find("git worktree add")
    assert i != -1, "the worktree charter is gone from AGENTS.md"
    window = charter[i:i + 1200]
    assert "uv sync" in window, (
        "the worktree instructions do not tell a lane to create its own venv — a lane that "
        "follows them lands on the main tree's src/ and gets a green that means nothing"
    )


# ── the second worktree hazard: a venv that is REAL but INCOMPLETE ───────────

def test_the_agent_fleet_extra_is_installed():
    """`uv sync` alone does not install what this suite needs. It is `--extra agent-fleet`.

    FOUND BY invincible-agent-32, 2026-09-09, following the charter as written. This repo keeps
    the whole fleet's runtime — langgraph, smolagents, restate-sdk, psycopg, litellm and
    fifteen more — in an OPTIONAL extra. A bare `uv sync` installs the 19 core dependencies
    and none of the 22 in `agent-fleet`, so seals that pass in the main tree raise
    `ModuleNotFoundError` in a brand-new worktree.

    **IT BITES IN THE OPPOSITE DIRECTION TO THE EDITABLE-INSTALL HAZARD, AND THAT IS WHY IT
    NEEDS ITS OWN GUARD.** That one produces a GREEN in the wrong tree — silent. This produces
    an ERROR, which is loud and therefore looks safe. Except for what a tired lane does with
    it: an ImportError in a fresh worktree reads as *"my worktree is broken"* rather than
    *"my venv is incomplete"*, and the natural repair is to abandon the worktree and go back
    to the shared tree. **A hazard that pushes people off the safe path costs the same as one
    that silently corrupts** — everyone back in one checkout with `git stash`. 32's framing,
    and it is the reason this is a test and not a footnote.

    `fastapi` is the canary because it is declared IN the extra, its import name matches its
    package name, and nothing in this suite runs without it — so its absence is exactly the
    condition, with no false positives available.
    """
    import importlib.util
    import tomllib

    declared = tomllib.loads((_TREE / "pyproject.toml").read_text(encoding="utf-8"))
    extras = declared.get("project", {}).get("optional-dependencies", {})
    assert "agent-fleet" in extras, (
        "the `agent-fleet` extra is gone from pyproject.toml — this guard, and the charter "
        "line it defends, are both now describing something that does not exist"
    )
    assert any(d.split("[")[0].strip() == "fastapi" for d in extras["agent-fleet"]), (
        "fastapi is no longer in the agent-fleet extra, so it is no longer a canary for it — "
        "pick another dependency that is IN the extra and whose import name matches"
    )

    assert importlib.util.find_spec("fastapi") is not None, (
        "the `agent-fleet` extra is NOT installed in this venv.\n\n"
        "You are probably in a worktree created with a bare `uv sync`. The suite needs:\n\n"
        "    uv sync --extra agent-fleet\n\n"
        "This is a venv that is real but incomplete — not a broken worktree. Do not abandon "
        "the worktree over it."
    )


def test_the_charter_names_the_EXTRA_not_a_bare_sync():
    """The charter said `uv sync` for half a day and 32 followed it into two failing seals.

    Asserted on the instruction a lane will actually copy — the line beside `worktree add` —
    because that is the one that gets run, not the prose around it.
    """
    charter = (_TREE / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    i = charter.find("git worktree add")
    assert i != -1, "the worktree charter is gone from AGENTS.md"
    window = charter[i:i + 1200]
    assert "uv sync --extra agent-fleet" in window, (
        "the worktree instructions still say a bare `uv sync` — a lane following them gets a "
        "venv missing 22 dependencies and reads the resulting ImportError as a broken worktree"
    )
