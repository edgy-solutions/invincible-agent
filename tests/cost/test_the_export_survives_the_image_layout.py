"""`package_export` 500'd in every deployed pod, always, and no seal could see it.

MEASURED LIVE 2026-09-12 on `iagent-engine-cost`, calling the verb through its own route:

    File "/app/measures.py", line 757, in package_export
      root = pathlib.Path(__file__).resolve().parents[2]
    IndexError: 2

The image flattens `agent_fleet/cost_agent/` to `/app`, so `/app/measures.py` has exactly two
parents. **In a checkout the identical expression resolves to the repo root and is correct** —
which is why the whole cost suite was green and why this survived from the day the verb
shipped. Nine verbs registered, `/health` green, and one of them had never once been callable
where it was registered.

── THE DAMAGE WAS NOT THE CRASH, IT WAS WHERE THE CRASH LANDED ──────────────────────────────
`package_export` already had TWO `SourceUnavailable` guards that refuse by name when the
builder or the pinned Pyodide runtime is absent — which is exactly the honest answer a pod owes
a caller. **`parents[2]` threw before either could run**, converting a designed refusal into an
untyped 500.

So the fix does not make the artifact buildable in a pod, and these seals do not claim it does.
The builder is 1,266 lines under `scripts/` and the Pyodide runtime is 14 MB and gitignored;
neither is in the image, and shipping them is a deployment decision, not this lane's. **What
the fix buys is that the engine SAYS SO** instead of raising IndexError.

── WHAT STILL WORKS IN THE POD, MEASURED THERE ──────────────────────────────────────────────
`export.build_package` — the GOVERNED half: entitlement scope, manifest, module hashes, five
verification checks, audit line — **runs correctly in the deployed image.** Only the HTML
rendering does not. That is the seam a card action should be built on.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import textwrap
from unittest import mock

import pytest

from agent_fleet.cost_agent import measures as m
from agent_fleet.cost_agent.entities import SourceUnavailable
from agent_fleet.cost_agent.seed import build_state

STATE = build_state()

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DOCKERFILE = _ROOT / ".github" / "docker" / "Dockerfile.agent"


def test_a_flattened_layout_gets_a_NAMED_REFUSAL_and_not_an_IndexError():
    """The defect, reproduced at the seam that decides it.

    `_repo_root()` returning None IS the flattened image, expressed as the one fact the verb
    needs. Asserting on the exception TYPE rather than the message: a caller distinguishes
    refusals by type (ADR-0049 Ruling 4), and an IndexError is indistinguishable from the
    engine being down.
    """
    with mock.patch.object(m, "_repo_root", lambda: None):
        with pytest.raises(SourceUnavailable) as exc:
            m.package_export(STATE, recipient_scope="notional-customer-alpha")

    message = str(exc.value)
    assert "governed" in message.lower(), (
        "the refusal must say which half is still available, or a caller reads it as 'this "
        "verb does not work' and stops asking"
    )


def test_the_root_is_found_by_a_MARKER_and_not_by_counting_levels(tmp_path):
    """Counting is what shipped the defect: `parents[2]` is correct in a checkout, an
    IndexError in `/app`, and the two are indistinguishable by reading the line."""
    # ⛔ THE MARKER MOVED, AND THE REASON IS THE SAME ONE THIS TEST WAS WRITTEN FOR. It asserted
    # the search finds a tree with `scripts/` AND `agent_fleet/` — a fair description of a
    # developer checkout, and the WRONG QUESTION once the runtime began shipping inside an
    # image: a flattened /app carrying the builder and the runtime can build a package and has
    # neither directory. The marker now tests what the caller needs (R-065).
    #
    # AND THIS ARM WAS ALSO A STATEMENT ABOUT A WORKING COPY. `root is not None` held only where
    # the gitignored `.pyodide-cache/` happened to be present — it passed in the checkout that
    # had fetched it and failed in a worktree that had not. Constructed now, so it is about the
    # SEARCH rather than about whose machine runs it.
    built = tmp_path / "somewhere" / "deep" / "nested"
    built.mkdir(parents=True)
    (tmp_path / "somewhere" / "scripts").mkdir()
    (tmp_path / "somewhere" / "scripts" / "build_cost_package.py").write_text("#", encoding="utf-8")
    (tmp_path / "somewhere" / ".pyodide-cache").mkdir()

    found = None
    for candidate in [built, *built.parents]:
        if m._can_build_a_package_here(candidate):
            found = candidate
            break
    assert found == tmp_path / "somewhere", (
        "the upward search did not find the nearest tree that can actually build a package"
    )


def test_the_root_search_RETURNS_NONE_rather_than_raising_when_there_is_no_checkout():
    """None is a first-class answer. "I am not in a checkout" is true and useful in a pod, and
    it is the input to a named refusal rather than an error condition."""
    # THE FLATTENED LAYOUT HAS TWO PARENTS AND NEITHER QUALIFIES. Exercising the search over
    # `/app/measures.py`'s ancestry directly, because that is the input that produced the live
    # IndexError — `parents[2]` on this same path is what the pod raised.
    fake = pathlib.PurePosixPath("/app/measures.py")
    assert len(fake.parents) == 2, [str(p) for p in fake.parents]
    with pytest.raises(IndexError):
        _ = fake.parents[2]        # the expression that shipped, on the layout that broke it

    found = None
    for candidate in pathlib.Path(fake).parents:
        if (candidate / "scripts").is_dir() and (candidate / "agent_fleet").is_dir():
            found = candidate
    assert found is None, f"a flattened layout resolved to {found}"


def test_NO_module_in_this_engine_derives_a_path_by_INDEX_from___file__():
    """THE CENSUS, scoped to this lane's own package.

    A filed defect is a sample. `parents[N]` appears across ten shipped modules in this
    repository; five are inside `try:` blocks and survive, and at least one elsewhere is not —
    reported to its owner rather than edited here.

    THIS SEAL COVERS WHAT THIS LANE SHIPS, so the next module added to `cost_agent/` cannot
    reintroduce it. Comments are excluded because this file's own fix is DOCUMENTED with the
    expression that caused it, and a check that cannot tell a fix from its explanation flags
    the explanation — a defect this repo has four recorded instances of.
    """
    offenders = []
    for path in sorted(pathlib.Path("agent_fleet/cost_agent").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\.parents\[\d+\]", code):
                offenders.append(f"{path.as_posix()}:{lineno}: {code.strip()}")
    assert not offenders, (
        "a path derived by counting directory levels is correct in a checkout and an "
        "IndexError in the flattened image; use a marker search:\n  " + "\n  ".join(offenders)
    )


def test_the_GOVERNED_half_needs_no_checkout_at_all():
    """Measured in the pod and asserted here: the entitlement scope, manifest, module hashes,
    checks and audit line are computed from the engine's own modules.

    THIS IS THE SEAM A CARD ACTION SHOULD USE. It is the half that is deployable today, and
    keeping it provably independent of the checkout is what makes that claim durable rather
    than a fact about this afternoon.
    """
    try:
        from agent_fleet.cost_agent.export import audit_line, build_package
    except ImportError:  # pragma: no cover
        pytest.skip("export module unavailable")

    with mock.patch.object(m, "_repo_root", lambda: None):
        package = build_package(
            STATE, recipient_scope="notional-customer-alpha", algorithm_sha="deadbeef"
        )
    assert package["locator"].startswith("sha256:")
    assert package["manifest"]["modules"], "no module hashes"
    assert len(package["manifest"]["checks"]) == 5
    assert audit_line(package, disclosed_by="seal")["disclosed_to"] == (
        "notional-customer-alpha"
    )


def test_a_baked_sha_is_available_without_git_and_is_NOT_invented():
    """`algorithm_sha()` shells out to git; `git` is not on PATH in the pod, measured.

    The image bakes `IAGENT_GIT_SHA` and the deployed engine returns a real commit for it.
    NONE WHERE ABSENT rather than a placeholder: a package whose `algorithm_sha` is a guess
    names an algorithm the recipient cannot retrieve, which is the exact thing the git path's
    dirty-tree refusal exists to prevent.
    """
    with mock.patch.dict("os.environ", {"IAGENT_GIT_SHA": "abc123"}, clear=False):
        assert m._baked_algorithm_sha() == "abc123"
    for absent in ("", "unknown"):
        with mock.patch.dict("os.environ", {"IAGENT_GIT_SHA": absent}, clear=False):
            assert m._baked_algorithm_sha() is None, (
                f"{absent!r} must not be reported as a real sha"
            )


# ── THE IMAGE LAYOUT, NOT JUST THE SEARCH ─────────────────────────────────────────────────
#
# Every test above runs from the repo checkout, where `agent_fleet` is a real package and
# `scripts.build_cost_dataset` is one `import` away -- so a packaged-only spelling in
# `scripts/build_cost_package.py` is green here and in CI FOREVER, and fails only where
# nobody runs pytest: inside the deployed image. The tests above found `_repo_root()`
# returning None and stopped there -- a real fix for a real crash -- but "a root is found"
# and "the builder at that root is importable" are different claims, and nothing exercised
# the second one.
#
# MEASURED on iagent-engine-cost, built from this Dockerfile with AGENT_DIR=agent_fleet/cost_agent:
#
#     cd /app/scripts && python -c "import build_cost_package"
#     ModuleNotFoundError: No module named 'agent_fleet'
#
# `build_cost_package.py` imports `agent_fleet.cost_agent.export` and `scripts.build_cost_dataset`
# (which imports `agent_fleet.cost_agent.pricing` and `.seed`), and reads
# `agent_fleet/cost_agent/pricing.py` and `page.py` off disk by that same path. The image
# flattens `agent_fleet/cost_agent/` onto `/app` (`COPY ${AGENT_DIR}/ /app/`) and nothing else
# put an `agent_fleet` package there, so every one of those imports failed -- the
# `SourceUnavailable` guards two frames further down in `package_export` never ran.
#
# WHY NO EXISTING TEST COULD SEE IT. `test_a_flattened_layout_gets_a_NAMED_REFUSAL...` above
# patches `_repo_root` to return None and asserts the refusal fires at THAT seam, in-process,
# with `agent_fleet` already imported (packaged) by this very test module. It proves the
# arithmetic no longer throws; it cannot prove the builder loads, because the only process
# that ever ran this test already has the packaged spelling satisfied before the test starts.
# The pattern copied here is `tests/graph_host/test_the_image_layout_can_import_it.py`: stage
# a faithful copy of what the Dockerfile COPYs, with no repo root on sys.path, and run the
# REAL import in a subprocess.
_DOCKERFILE_SRC = _DOCKERFILE.read_text(encoding="utf-8")

#: The exact COPY lines this engine's image layout depends on for the builder to import.
#: Read LIVE from the Dockerfile at stage time (not just asserted by a separate control), so
#: reverting any one of them stages the layout without it -- the same way reverting it in the
#: real Dockerfile ships an image without it.
_COST_COPY_LINES = {
    "agent_dir": "COPY ${AGENT_DIR}/ /app/",
    "builder": "COPY scripts/build_cost_package.py /app/scripts/build_cost_package.py",
    "build_cost_dataset": "COPY scripts/build_cost_dataset.py /app/scripts/build_cost_dataset.py",
    "labor_tab_template": "COPY scripts/labor_tab_template.py /app/scripts/labor_tab_template.py",
    "agent_fleet_init": "COPY agent_fleet/__init__.py /app/agent_fleet/__init__.py",
    "cost_agent_pkg": "COPY agent_fleet/cost_agent/ /app/agent_fleet/cost_agent/",
    "runtime_arg": "ARG PACKAGE_RUNTIME_SRC=.docker-empty",
    "runtime_copy": "COPY ${PACKAGE_RUNTIME_SRC}/ /app/.pyodide-cache/",
}


def test_the_cost_staging_list_still_matches_the_DOCKERFILE():
    """THE SIMULATION'S OWN CONTROL, same reason as graph_host's: without it, the import test
    below could drift into testing a layout the image does not have -- and would keep passing
    while the real one broke, which is strictly worse than not testing it."""
    for name, line in _COST_COPY_LINES.items():
        assert line in _DOCKERFILE_SRC, f"{name}: {line!r} is no longer in the Dockerfile"


def _stage_cost_image(app: pathlib.Path) -> None:
    """Build a tmp tree matching exactly what the Dockerfile COPYs for
    AGENT_DIR=agent_fleet/cost_agent -- reading the Dockerfile LIVE (see above), so a reverted
    COPY line stages a layout without it."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")

    def _copy_dir(src: pathlib.Path, dest: pathlib.Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, dirs_exist_ok=True, ignore=ignore)

    def _copy_file(src: pathlib.Path, dest: pathlib.Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # COPY ${AGENT_DIR}/ /app/ -- unconditional; this is the flatten the defect was found in.
    assert _COST_COPY_LINES["agent_dir"] in _DOCKERFILE_SRC
    _copy_dir(_ROOT / "agent_fleet" / "cost_agent", app)

    # COPY scripts/build_cost_package.py /app/scripts/build_cost_package.py -- unconditional.
    assert _COST_COPY_LINES["builder"] in _DOCKERFILE_SRC
    _copy_file(_ROOT / "scripts" / "build_cost_package.py",
               app / "scripts" / "build_cost_package.py")

    # Everything below is the FIX -- staged only if the Dockerfile still says so.
    if _COST_COPY_LINES["build_cost_dataset"] in _DOCKERFILE_SRC:
        _copy_file(_ROOT / "scripts" / "build_cost_dataset.py",
                   app / "scripts" / "build_cost_dataset.py")
    if _COST_COPY_LINES["labor_tab_template"] in _DOCKERFILE_SRC:
        _copy_file(_ROOT / "scripts" / "labor_tab_template.py",
                   app / "scripts" / "labor_tab_template.py")
    if _COST_COPY_LINES["agent_fleet_init"] in _DOCKERFILE_SRC:
        _copy_file(_ROOT / "agent_fleet" / "__init__.py", app / "agent_fleet" / "__init__.py")
    if _COST_COPY_LINES["cost_agent_pkg"] in _DOCKERFILE_SRC:
        _copy_dir(_ROOT / "agent_fleet" / "cost_agent", app / "agent_fleet" / "cost_agent")

    # ${PACKAGE_RUNTIME_SRC}/ /app/.pyodide-cache/ -- left EMPTY on purpose. CI fetches the
    # runtime only for engine-cost and the fetched files are gitignored, so a checkout (and
    # this stage) can never reproduce them faithfully. Leaving `.pyodide-cache` absent is the
    # FAITHFUL simulation of the `.docker-empty` default and lets the probe below reach the
    # named "runtime missing" refusal instead of silently fabricating a fake one.


def _run_in_staged_layout(app: pathlib.Path, probe: str) -> subprocess.CompletedProcess:
    """A SUBPROCESS, because `agent_fleet` is already imported (packaged) by this test module
    itself -- asserting the flat layout from inside a session that has the packaged one on
    sys.path would prove nothing, which is the shape of a fixture supplying the thing under
    test. cwd and PYTHONPATH match what the Dockerfile's final stage sets
    (`WORKDIR /app` + `PYTHONPATH=/app/src:/app:...`), translated onto the staged tree, with
    NO REPO ROOT anywhere in that path."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(app / "src"), str(app)])}
    return subprocess.run(
        [sys.executable, "-c", probe], cwd=app / "scripts",
        capture_output=True, text=True, env=env,
    )


def test_the_builder_IMPORTS_under_the_flattened_image_layout(tmp_path):
    """The exact command measured live in the pod, reproduced in a staged copy:

        cd /app/scripts && python -c "import build_cost_package"
        ModuleNotFoundError: No module named 'agent_fleet'
    """
    app = tmp_path / "app"
    app.mkdir()
    _stage_cost_image(app)

    assert (app / "agent_fleet" / "cost_agent" / "export.py").exists(), (
        "the fix's own COPY lines did not land in the staged tree -- the control test above "
        "should have caught a Dockerfile drift before this one ran"
    )

    r = _run_in_staged_layout(app, "import build_cost_package\nprint('IMPORTED_OK')")
    assert r.returncode == 0, (
        f"the builder does not import under the image's layout:\n{r.stderr[-1500:]}"
    )
    assert "IMPORTED_OK" in r.stdout, r.stdout


def test_the_builder_REFUSES_BY_NAME_rather_than_crashing_without_the_runtime(tmp_path):
    """The furthest the export can go in this layout without the 14 MB Pyodide runtime
    (gitignored, fetched only in CI): past every import this defect broke, into the GOVERNED
    half (`X.build_package`, entitlement scope and manifest), and only THEN a named refusal
    listing the runtime files that are missing -- never an ImportError and never a crash.
    """
    app = tmp_path / "app"
    app.mkdir()
    _stage_cost_image(app)
    assert not (app / ".pyodide-cache").exists(), (
        "the runtime must be absent for this probe to test the no-runtime path"
    )

    probe = textwrap.dedent("""
        import build_cost_package as builder
        import pathlib
        try:
            builder.build_html("notional-customer-alpha", builder.ROOT / ".pyodide-cache")
        except SystemExit as exc:
            print("REFUSED:", exc)
        else:
            print("DID NOT REFUSE")
        """)
    r = _run_in_staged_layout(app, probe)
    assert r.returncode == 0, (
        f"the builder raised instead of refusing by name:\n{r.stderr[-1500:]}"
    )
    assert "DID NOT REFUSE" not in r.stdout, r.stdout
    assert "REFUSED:" in r.stdout, r.stdout
    assert "missing" in r.stdout.lower(), r.stdout
    for runtime_file in ("pyodide.asm.wasm", "pyodide.asm.js", "python_stdlib.zip",
                         "pyodide-lock.json", "pyodide.js"):
        assert runtime_file in r.stdout, (
            f"the refusal did not name {runtime_file!r} among the missing files:\n{r.stdout}"
        )
