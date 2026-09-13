"""Engine S's modules IMPORT in the flattened `/app` layout — the thing the image actually does.

THE DEFECT THIS SEALS ALMOST SHIPPED, and it was not a runtime error. `matrix.py` computed

    _DEFAULT_TTL = Path(__file__).resolve().parents[2] / "setup" / ...

at MODULE SCOPE. In the image `/app` IS the engine directory, so the module is `/app/matrix.py`
whose parents are exactly `['/app', '/']` — `parents[2]` raises **IndexError during import**, and
`measures.py` imports it at load. **The pod could not have come up.** Found by
`invincible-agent-81` before the engine was ever deployed.

**THE ESCAPE HATCH COULD NOT HAVE SAVED IT.** `matrix_path()` honours `SAFETY_RISK_MATRIX_TTL`,
but the constant was evaluated at import — the override was computed after the crash. There was no
deployment-time workaround, which is what made a code fix urgent rather than routine.

── WHY THIS SEAL IMPORTS RATHER THAN READS ─────────────────────────────────────────────────────
**A seal that asserted a string about `parents` would go green the moment someone rewrote the
expression while leaving it unguarded.** The defect is not "this file contains `parents[2]`" — it
is "importing this module under the flat layout raises". So this copies the engine's modules into
a directory with the image's SHAPE and imports them there, in a subprocess with a clean path.

That also makes it survive a rewrite in either direction: a future author who replaces the path
logic entirely still has to satisfy an import.

── WHY IT IS A SUBPROCESS ──────────────────────────────────────────────────────────────────────
`agent_fleet.safety_agent.*` is already imported by the rest of this suite. Re-importing the flat
copies in-process would collide on module names (`matrix`, `measures`, `entities`) and could pick
up the packaged versions instead — a green that proves the repo layout works, which is the layout
that was never in doubt.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ENGINE = Path(__file__).resolve().parents[2] / "agent_fleet" / "safety_agent"
_UTILS = Path(__file__).resolve().parents[2] / "agent_fleet" / "utils"


def _flat_image(tmp_path: Path) -> Path:
    """A directory shaped like `/app`: the engine's modules at the top, `utils/` beside them.

    Mirrors `.github/workflows/build-containers.yml` — `COPY ${AGENT_DIR}/ /app/` plus
    `COPY agent_fleet/utils/ /app/utils/`. The TTLs are NOT copied, deliberately, because the
    image does not carry them either: they are primed. An engine that only starts when a file the
    image never ships is present would pass a laxer seal and fail in the cluster.
    """
    app = tmp_path / "app"
    app.mkdir()
    for py in _ENGINE.glob("*.py"):
        shutil.copy2(py, app / py.name)
    shutil.copytree(_UTILS, app / "utils")
    return app


def _import_in(app: Path, module: str) -> subprocess.CompletedProcess:
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(app)!r})
        import {module}
        print("IMPORTED", {module}.__name__)
        """
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(app), timeout=120
    )


@pytest.mark.parametrize("module", ["matrix", "entities", "measures", "slots"])
def test_each_module_imports_flat(tmp_path, module):
    """THE SEAL. Import the way the image does, one module at a time so a failure names one."""
    app = _flat_image(tmp_path)
    r = _import_in(app, module)
    assert r.returncode == 0, (
        f"`import {module}` FAILS in the flattened /app layout — the pod cannot start.\n"
        f"stderr:\n{r.stderr}"
    )
    assert "IMPORTED" in r.stdout


def test_the_harness_can_actually_fail(tmp_path):
    """THE CONTROL. A harness that has only ever imported working modules has not been shown able
    to report a broken one — and a subprocess that silently succeeded on a missing module would
    make every assertion above vacuous."""
    app = _flat_image(tmp_path)
    r = _import_in(app, "a_module_that_does_not_exist")
    assert r.returncode != 0, "the harness reports success for a module that is not there"
    assert "ModuleNotFoundError" in r.stderr


def test_THE_GUARD_HOLDS_AT_THE_DEPTH_THAT_ACTUALLY_MATTERS():
    """THE SEAL THE IMPORT TEST ABOVE CANNOT BE — and finding that out is the finding.

    The first version of this file copied the engine into a temp directory, called it the flat
    layout, and PASSED WITH THE GUARD REMOVED. `C:/Users/.../Temp/.../app/matrix.py` has plenty
    of parents; `/app` has two only because it sits at the filesystem root. **The fixture could
    not reproduce the property it was named after** — a fixture-that-cannot-fail inside the seal
    written to catch this very bug, which is the fourth instance of that shape in this arc.

    A temp directory cannot be made shallow without writing to the filesystem root, so the
    function takes its module path as an ARGUMENT (the shape `candidate_definition_dirs` already
    used, for this reason) and the seal hands it the real one.
    """
    from agent_fleet.safety_agent.matrix import candidate_matrix_paths

    flat = Path("/app/matrix.py")
    assert len(flat.parents) == 2, "the /app shape this guard exists for has changed"

    out = candidate_matrix_paths(flat)          # must not raise IndexError
    assert out, "no candidate returned under the flat layout"
    # COMPARED BY SHAPE, NOT BY LITERAL, because `.resolve()` is platform-dependent: on Linux
    # `/app/matrix.py` stays `/app/matrix.py` (two parents, which is the real image), and on
    # Windows it becomes `C:\app\matrix.py` (also two parents, so the guard is exercised the same
    # way). Asserting the literal string passed on one OS and failed on the other while the
    # PROPERTY under test held on both — an instrument reporting a platform difference as a defect.
    assert out[-1].name == "safety_risk_matrix.ttl", "the flat candidate is not the matrix file"
    assert out[-1].parent == flat.resolve().parent, (
        "the flat candidate is not beside the module — a deployment override would have nothing "
        "sensible to be compared against"
    )
    assert not any("setup" in str(p) for p in out), (
        "a repo-relative candidate was produced at flat depth — the guard did not hold"
    )


def test_the_repo_layout_still_finds_the_real_file():
    """THE CONTROL for the guard: at repo depth the repo candidate MUST appear, or the guard has
    been \"fixed\" by disabling the path that actually works today."""
    from agent_fleet.safety_agent import matrix as m

    out = m.candidate_matrix_paths(Path(m.__file__))
    assert any(p.name == "safety_risk_matrix.ttl" and "setup" in str(p) for p in out), (
        "the repo candidate is gone — the guard now suppresses the only path that resolves today"
    )
    assert out[0].exists(), "the repo candidate does not point at the shipped TTL"


def test_matrix_path_does_not_raise_under_the_flat_layout(tmp_path):
    """The resolution path is exercised too, not merely the import.

    Importing proves the module loads; this proves the first thing a caller touches does not then
    raise for the same reason one function along. A guard that moved the crash rather than removing
    it would pass the import seal.
    """
    app = _flat_image(tmp_path)
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(app)!r})
        import matrix
        p = matrix.matrix_path()
        print("PATH_OK", p.name)
        """
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(app), timeout=120
    )
    assert r.returncode == 0, f"`matrix_path()` raises under the flat layout:\n{r.stderr}"
    assert "PATH_OK" in r.stdout
