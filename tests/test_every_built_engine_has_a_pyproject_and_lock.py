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


# ── THE RUNTIME-SECRET ARM ──────────────────────────────────────────────────────────────────
#
# TWO ARMS BECAUSE THEY FAIL AT DIFFERENT TIMES. The build-input arm above catches an engine
# whose image cannot be built usefully — that surfaces at pod start. This arm catches an engine
# whose image is fine and whose REGISTRATION cannot mint — and that surfaces ninety seconds
# after a GREEN roll, as four WARNING lines, with the pod 1/1 READY and the mesh empty.
#
# Measured 2026-09-14: engine-safety came up healthy, minted 5/5 failures on
# ENGINE_SAFETY_CLIENT_SECRET, logged "registered 3/3", and held zero verbs in the graph. The
# secret was mentioned in values.yaml COMMENTS and guarded nowhere.

_SECRETS = _ROOT / "helm" / "invincible-agent" / "templates" / "secrets.yaml"
_ENGINES = _ROOT / "helm" / "invincible-agent" / "templates" / "engines.yaml"

#: One chart row per engine: (dict "key" "engineO" "component" "engine-o" ...)
_ENGINE_ROW = re.compile(r'\(dict\s+"key"\s+"(\w+)"\s+"component"\s+"([a-z0-9-]+)"')

#: component -> the env var its mint reads. HAND-KEPT ON PURPOSE, AND THE POPULATION IS NOT.
#:
#: ⛔ THE FIRST VERSION DERIVED THIS AND THAT WAS A GUESS DRESSED AS A DERIVATION. `data-analyst`
#: reads ENGINE_DA_CLIENT_SECRET, not ENGINE_DATA_ANALYST_CLIENT_SECRET -- the var follows the
#: SERVICE's short name, which no rule recovers from the component. Same shape as the census's
#: _COMPONENT_TO_URL_VAR and for the same reason. What IS derived is the set of engines that must
#: appear here: it comes from the chart's $engines, so a new engine cannot be silently absent.
_SECRET_VAR = {
    "engine-a": "ENGINE_A_CLIENT_SECRET",
    "engine-cost": "ENGINE_COST_CLIENT_SECRET",
    "engine-d": "ENGINE_D_CLIENT_SECRET",
    "engine-e": "ENGINE_E_CLIENT_SECRET",
    "engine-fin": "ENGINE_FIN_CLIENT_SECRET",
    "engine-lg": "ENGINE_LG_CLIENT_SECRET",
    "engine-o": "ENGINE_O_CLIENT_SECRET",
    "engine-p": "ENGINE_P_CLIENT_SECRET",
    "engine-safety": "ENGINE_SAFETY_CLIENT_SECRET",
    "engine-w": "ENGINE_W_CLIENT_SECRET",
    "data-analyst": "ENGINE_DA_CLIENT_SECRET",
}

#: Components whose engine needs no Keycloak client secret, each with its REASON.
_NO_CLIENT_SECRET: dict[str, str] = {
    "central-gateway": "not an engine; holds no mint and calls register_engine_to_mesh nowhere",
    # ── UNRESOLVED, NAMED RATHER THAN SILENT. Each of these calls register_engine_to_mesh and
    # has no client-secret guard. NONE is a confirmed defect: data-analyst is deployed, has NO
    # ENGINE_DA_CLIENT_SECRET set, and logs ZERO mint failures — so it is reaching the mesh by
    # some path this seal does not model, or not registering at all. Asserting a guard it may
    # not need would be the over-constrained seal that fails on honest data.
    #
    # They are EXCLUDED WITH A REASON rather than asserted or deleted, which is the partition
    # rule: every member in the basis or in an exclusion list with a reason, never quietly
    # dropped. Each needs one measurement — does it mint, and against what — and that is a
    # ruling, not a guess.
    "data-analyst": "UNRESOLVED: mints, no secret set, no mint failures — needs a measurement",
    "engine-b": "UNRESOLVED: retirement status unconfirmed; see test_engine_b_removal_list",
    "engine-c": "UNRESOLVED: no secret declared; liveness and mint path unmeasured",
    "engine-f": "UNRESOLVED: the presentation agent; announces transport auth, mint path unmeasured",
}


def _chart_components() -> list[str]:
    return sorted({c for _k, c in _ENGINE_ROW.findall(_ENGINES.read_text(encoding="utf-8"))})


def test_the_engines_list_is_readable_and_plural():
    """THE FLOOR for this arm. Its population is the chart's `$engines`, not the build matrix —
    a different independent statement, because a secret is a RUNTIME need and an engine can be
    in one list and not the other."""
    comps = _chart_components()
    assert len(comps) >= 6, f"parsed only {comps} from engines.yaml — the row shape moved"


@pytest.mark.parametrize("component", _chart_components())
def test_every_chart_engine_has_a_rendered_client_secret_guard(component: str):
    """A secret mentioned in a comment is not a secret that renders.

    The env var follows the SERVICE (`ENGINE_SAFETY_CLIENT_SECRET`) while the values key follows
    the IMAGE (`safetyAgentClientSecret`) — so grepping either name alone finds half the wiring,
    which is exactly how this one was missed.
    """
    if component in _NO_CLIENT_SECRET:
        pytest.skip(f"{component}: {_NO_CLIENT_SECRET[component]}")
    var = _SECRET_VAR.get(component)
    assert var, (
        f"{component} has no entry in _SECRET_VAR. The var name is NOT derivable from the "
        f"component -- `data-analyst` is ENGINE_DA, not ENGINE_DATA_ANALYST -- so a mechanical "
        f"rule would be a guess dressed as a derivation. Add the real name or an exclusion."
    )
    body = _SECRETS.read_text(encoding="utf-8")
    assert var in body, (
        f"{component} is in the chart's $engines and {var} is guarded nowhere in secrets.yaml. "
        f"The engine will come up 1/1 READY, fail its mint, log a success count, and hold zero "
        f"verbs in the mesh. Add the guard, or add {component} to _NO_CLIENT_SECRET with a reason."
    )


def test_THE_SECRET_EXCLUSION_LIST_NAMES_A_REASON():
    for c, why in _NO_CLIENT_SECRET.items():
        assert why and why.strip(), f"{c} is excluded with no reason"
