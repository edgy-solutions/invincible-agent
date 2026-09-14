"""Every engine the build matrix names has a `pyproject.toml` AND a `uv.lock`.

THE ELEVENTH REGISTRY SITE, and it is a mechanism the packet does not list. `agent_fleet/
safety_agent/` was added to the build matrix correctly — the entry is there, with a comment
explaining that without it no image is ever built — and the directory held only `.py` files.

**So `Dockerfile.agent` built an image with no venv to create, the build reported SUCCESS, and
the failure surfaced at pod start as:**

    /bin/sh: 1: /app/.venv/bin/python: not found

Seventeen minutes and eight restarts into a CrashLoopBackOff, on a roll that otherwise succeeded.

WHY THE EXISTING SEAL COULD NOT SEE IT. `test_lock_coherence.py` walks `agent_fleet/*/
pyproject.toml` and checks each lock against its manifest — **so a directory with NO pyproject is
not a failure, it is not a member.** The population is derived from the very artifact whose
absence is the defect.

> **THE PYPROJECT IS NOT THE IMPORT** (the `utils/` hole), **and here: the pyproject is not the
> MEMBERSHIP.** A check that enumerates by the thing that can be missing cannot report it missing.

So this seal derives its population from **the build matrix** — the independent statement of what
gets packaged — and asserts each named service has the inputs its Dockerfile needs. A service in
the matrix with nothing to build is red **by name, at commit time**, instead of green through CI
and crash-looping in the cluster.

IT IS THE FOURTH MECHANISM OF "REGISTERED IS NOT PARTICIPATING". A payload field; a shadowed
guard; path arithmetic correct in one layout and impossible in another; and now **a missing build
input that produces a GREEN BUILD.**

Run: uv run --frozen pytest tests/test_every_built_engine_has_a_pyproject_and_lock.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "build-containers.yml"

#: A matrix row's `path:`, which is the directory the image is built from. Derived rather than
#: listed: a twelfth engine is covered on arrival, which is the whole point of the packet this
#: seal comes from.
_MATRIX_PATH = re.compile(r'^\s*path:\s*(agent_fleet/\w+)\s*$', re.M)

#: Services whose image legitimately needs no per-engine dependency set, each with its REASON.
#: An exclusion list with reasons is auditable; one without is the list nobody can read.
_NOT_A_UV_PROJECT: dict[str, str] = {}


def _matrix_paths() -> list[str]:
    return sorted(set(_MATRIX_PATH.findall(_WORKFLOW.read_text(encoding="utf-8"))))


def test_the_matrix_is_readable_and_plural():
    """THE FLOOR. A regex that matched nothing would make every assertion below vacuous — and
    this seal exists precisely because an empty population reads like a clean result."""
    paths = _matrix_paths()
    assert len(paths) >= 8, (
        f"parsed only {paths} from the build matrix — the `path:` shape moved, and this seal is "
        f"now quantifying over almost nothing"
    )


@pytest.mark.parametrize("rel", _matrix_paths())
def test_every_matrix_engine_has_a_pyproject(rel: str):
    """Without one, `uv sync` has nothing to install and the image ships with no `.venv`."""
    if rel in _NOT_A_UV_PROJECT:
        pytest.skip(f"{rel}: {_NOT_A_UV_PROJECT[rel]}")
    p = _ROOT / rel / "pyproject.toml"
    assert p.is_file(), (
        f"{rel} is in the build matrix and has NO pyproject.toml. The image builds GREEN and the "
        f"container dies at start with `/app/.venv/bin/python: not found`. Add one, or add {rel} "
        f"to _NOT_A_UV_PROJECT with the reason its image needs no dependency set."
    )


@pytest.mark.parametrize("rel", _matrix_paths())
def test_every_matrix_engine_has_a_lock(rel: str):
    """The image build runs `uv sync --locked`. A pyproject with no lock fails at IMAGE time
    rather than at pod start — louder than the missing-pyproject case, and still avoidable
    here."""
    if rel in _NOT_A_UV_PROJECT:
        pytest.skip(f"{rel}: {_NOT_A_UV_PROJECT[rel]}")
    assert (_ROOT / rel / "uv.lock").is_file(), (
        f"{rel} has a pyproject.toml but no uv.lock, and the image build runs `uv sync --locked`"
    )


def test_THE_EXCLUSION_LIST_NAMES_A_REASON_FOR_EVERY_ENTRY():
    """An exclusion whose reason is empty is a silenced failure wearing a decision's clothes."""
    for rel, why in _NOT_A_UV_PROJECT.items():
        assert why and why.strip(), f"{rel} is excluded with no reason"


def test_THE_POPULATION_COMES_FROM_THE_MATRIX_not_from_the_directories():
    """THE ANTI-VACUUM CHECK, and it is the whole construction.

    Deriving the population by globbing `agent_fleet/*/pyproject.toml` — which is what
    `test_lock_coherence` does, correctly, for its own purpose — makes a missing pyproject a
    NON-MEMBER rather than a failure. The defect becomes invisible to the check by construction.

    So this asserts the two populations DIFFER in the direction that matters: the matrix names at
    least as many engines as have pyprojects, and any excess is exactly what this seal is for.
    """
    matrix = set(_matrix_paths())
    have_pyproject = {
        f"agent_fleet/{p.parent.name}"
        for p in (_ROOT / "agent_fleet").glob("*/pyproject.toml")
    }
    assert matrix, "the matrix parsed to nothing"
    missing = sorted(matrix - have_pyproject - set(_NOT_A_UV_PROJECT))
    assert not missing, (
        f"{len(missing)} matrix engine(s) with no pyproject: {missing}. A glob-derived seal "
        f"cannot see these — they are not members of its population."
    )
