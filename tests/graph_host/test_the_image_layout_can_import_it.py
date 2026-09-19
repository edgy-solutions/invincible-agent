"""engine-lg loads under the IMAGE's layout, where `agent_fleet` does not exist.

THIS IS THE DEFECT THIS LANE SHIPPED TWICE, and the second time crash-looped every pod.

    RuntimeError: cost_lot_costing_review: cannot import 'build' ... No module named 'agent_fleet'

The image is `COPY ${AGENT_DIR}/ /app/` with `AGENT_DIR=agent_fleet/graph_host`
(`.github/docker/Dockerfile.agent`), so **`agent_fleet` is not in the image at all**: the
builders are `graphs.*` and anything else this engine ships is at the root. A repo-relative
import like `agent_fleet.graph_host.rows` is correct in the tree and unimportable in the pod.

── WHY NO EXISTING TEST COULD SEE IT, WHICH IS WHY THIS ONE EXISTS ─────────────────────────
**The suite imports the packaged layout by construction.** It runs from the repo root, where
`agent_fleet` is a real package, so a packaged-only spelling is green locally and green in CI
**forever**, and fails only where nobody runs pytest. Vigilance is not the fix for a class the
instrument cannot express; a different instrument is.

The first instance was the same engine and the same blindness — a missing `COPY policy/graphs/`
shipped a host serving ZERO graphs behind a green probe. I wrote the boot floor that catches
that one while walking into this one.

── WHAT THIS ASSERTS, AND WHAT IT DELIBERATELY DOES NOT ────────────────────────────────────
It stages a faithful copy of what the Dockerfile COPYs, with **no `agent_fleet` anywhere**, and
runs the host's REAL `load_graphs()` — the exact call that raised in the pod. It does not build
a container: the failure is an import-resolution failure, and import resolution is decided by
`sys.path` and the directory tree, both of which a staged copy reproduces exactly.

SUPERSEDED, NOT DUPLICATED, when the fleet-wide image-import seal lands in CI (`python -c
"import main"` in the BUILT image, every engine — ruled 2026-09-15, and twice on this one engine
is the argument that it is overdue). That seal is stronger because it runs the real artefact.
Until it exists, this covers the engine that has paid for the gap, and **the staging list below
must be kept honest against the Dockerfile** — a stale copy here would test a layout the image
does not have, which is the failure mode of every simulation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.graph_host._engine_deps import needs_langgraph

_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _ROOT / ".github" / "docker" / "Dockerfile.agent"

#: What the image stages, read as (source, destination-under-/app). Kept beside the assertion
#: that the Dockerfile still says so, because a simulation that drifts from its subject reports
#: on a layout nobody deploys.
_STAGED = [
    ("agent_fleet/graph_host", "."),          # COPY ${AGENT_DIR}/ /app/
    ("agent_fleet/utils", "utils"),           # COPY agent_fleet/utils/ /app/utils/
    ("policy/graphs", "policy/graphs"),       # COPY policy/graphs/ /app/policy/graphs/
]


def test_the_staging_list_still_matches_the_DOCKERFILE():
    """THE SIMULATION'S OWN CONTROL. Without it, the flat-layout test below drifts into testing
    a layout the image does not have — and would keep passing while the real one broke, which is
    strictly worse than not testing it."""
    src = _DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY ${AGENT_DIR}/ /app/" in src, "the engine's own COPY changed shape"
    assert "COPY agent_fleet/utils/ /app/utils/" in src, "utils is no longer staged as `utils`"
    assert "COPY policy/graphs/ /app/policy/graphs/" in src, "the ratified rows moved"


@needs_langgraph
def test_the_host_LOADS_with_no_agent_fleet_in_the_image(tmp_path):
    """The call that crash-looped, run in the layout that crash-looped it."""
    app = tmp_path / "app"
    app.mkdir()
    for src, dest in _STAGED:
        target = app / dest if dest != "." else app
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_ROOT / src, target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    assert not (app / "agent_fleet").exists(), (
        "the staged image contains `agent_fleet`, so this test cannot fail the way the pod did"
    )

    probe = textwrap.dedent(
        """
        import os, sys
        sys.path.insert(0, '.')
        os.environ['GRAPH_POLICY_DIR'] = 'policy/graphs'
        import iagent_mesh
        # WHERE IT IMPORTED FROM, not just that it did. ca's wheel check passed while
        # importing their working tree because cwd was on sys.path and the DISTRIBUTION
        # reported the installed version — module from the checkout, version from the
        # metadata. Here the staged /app is first on sys.path, so the same shadowing is
        # available: a stray iagent_mesh in the image would satisfy every assertion below
        # while the installed dependency went untested.
        assert 'site-packages' in iagent_mesh.__file__.replace(chr(92), '/'), (
            'iagent_mesh did not resolve from site-packages: ' + iagent_mesh.__file__
        )
        import main
        loaded = main.load_graphs()
        assert loaded, 'the loader admitted nothing'
        print('LOADED', len(loaded), ','.join(sorted(loaded)))
        print('SDK_FROM', iagent_mesh.__file__)
        """
    )
    # A CHILD PROCESS, because `agent_fleet` is already imported in this one — asserting the
    # flat layout from inside a session that has the packaged one on sys.path would prove
    # nothing, which is the shape of a fixture supplying the thing under test.
    r = subprocess.run([sys.executable, "-c", probe], cwd=app, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": ""})
    assert r.returncode == 0, (
        f"engine-lg does not load under the image's layout:\n{r.stderr[-1500:]}"
    )
    assert "LOADED" in r.stdout, r.stdout


@needs_langgraph
def test_no_module_imports_agent_fleet_OUTSIDE_a_flat_first_fallback():
    """The rule behind the boot test, stated where a reader will meet it.

    An `agent_fleet.` import that is NOT the packaged half of a flat-first `try/except` is
    unimportable in the pod. This catches it at the spelling rather than at the boot, because
    the boot test needs the module to be REACHED — a lazily-imported one inside a rarely-taken
    branch would sail past it.

    ── THE EXEMPTION IS STRUCTURAL, AND THE FIRST VERSION'S WAS NOT ─────────────────────────
    It first exempted lines carrying `# type: ignore[no-redef]`, and went red on a perfectly
    correct fallback whose comment was a bare `# type: ignore`. **That matched a MARKER where
    the property is a POSITION** — the same defect as a check that reads a docstring to decide
    what code does. The legitimacy of an `agent_fleet.` import is entirely "is it inside an
    `except ImportError` handler", which is a fact about the tree, so the tree is what is read.
    """
    import ast

    offenders = []
    for py in (_ROOT / "agent_fleet" / "graph_host").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))

        # every import that sits inside an ImportError handler, by position
        excused: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                names = []
                if isinstance(handler.type, ast.Name):
                    names = [handler.type.id]
                elif isinstance(handler.type, ast.Tuple):
                    names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
                if "ImportError" not in names and "ModuleNotFoundError" not in names:
                    continue
                for sub in ast.walk(handler):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        excused.add(sub.lineno)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("agent_fleet"):
                continue
            if node.lineno in excused:
                continue
            offenders.append(f"{py.relative_to(_ROOT)}:{node.lineno}: from {node.module} import ...")

    assert not offenders, (
        "these imports name `agent_fleet` OUTSIDE a flat-first fallback, and `agent_fleet` "
        "DOES NOT EXIST in the image:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse the flat spelling first with a packaged fallback in an `except ImportError`,"
          " or — better — depend on an INSTALLED package, which removes the fork instead of"
          " handling it."
    )
