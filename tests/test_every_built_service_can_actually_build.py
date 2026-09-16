"""Every service in the build matrix has the two files its image build requires.

THE GAP THIS CLOSES, AND IT IS A GAP IN A SEAL RATHER THAN IN THE CODE. `test_lock_coherence.py`
checks that every `uv.lock` agrees with its `pyproject.toml` — derived from *directories that
have a lock*. That population cannot contain a service with NO lock, so the one failure it cannot
see is the one that stops an image existing at all.

WHAT HAPPENS WITHOUT THEM, both measured rather than imagined:

    no pyproject.toml   `Dockerfile.agent` COPYs `${AGENT_DIR}/pyproject.toml*` — a GLOB, which
                        matches zero files WITHOUT erroring — and runs `uv sync` only
                        `if [ -f "pyproject.toml" ]`. The build does nothing, REPORTS SUCCESS,
                        and ships an image with no `/app/.venv`. The CMD then fails with
                        `/app/.venv/bin/python: not found` and the engine crash-loops: 8 restarts
                        in 17 minutes, the only service down in an otherwise green roll.
    no uv.lock          `uv sync --locked` has nothing to check against. `--locked` (not
                        `--frozen`, changed 2026-08-08 after that exact defect shipped) is there
                        to fail the build when the lock disagrees with the pyproject — and a
                        missing lock is a disagreement it was never asked about.

Both failures are in the BUILD, so nothing in this repo's suite notices, and the first symptom is
a deploy asking for a tag that was never produced or a pod that will not start.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-containers.yml"


def _matrix_services() -> list[tuple[str, str]]:
    """-> (service, path) for every entry in the build matrix. DERIVED from the workflow.

    Hand-listing the fleet here would reproduce the defect one layer up: a list that has to be
    maintained alongside the one it is checking, which is the shape the mirror script's own
    comment calls out — *a lesson written beside a list does not maintain the list*.
    """
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            if "service" in node and "path" in node:
                found.append((str(node["service"]), str(node["path"])))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return found


def test_the_matrix_is_readable_and_not_empty():
    """THE FLOOR. Every assertion below passes on an empty matrix, and the matrix is parsed out
    of a YAML file whose shape can change under a workflow edit."""
    services = _matrix_services()
    assert len(services) >= 10, (
        f"found {len(services)} services in the build matrix — the walk has stopped seeing "
        f"entries, and the checks below now pass on whatever is left: {services}")
    names = [s for s, _ in services]
    assert len(names) == len(set(names)), f"a service is listed twice: {names}"


def test_every_built_service_has_the_two_files_its_build_requires():
    missing = []
    for service, rel in _matrix_services():
        d = ROOT / rel
        if not d.is_dir():
            missing.append(f"  {service}: {rel} is not a directory in this repo")
            continue
        if not (d / "pyproject.toml").is_file():
            missing.append(
                f"  {service}: {rel}/pyproject.toml is absent. The COPY glob matches nothing "
                f"without erroring and `uv sync` is skipped, so the build SUCCEEDS and ships an "
                f"image with no /app/.venv.")
        if not (d / "uv.lock").is_file():
            missing.append(
                f"  {service}: {rel}/uv.lock is absent. `uv sync --locked` has nothing to check "
                f"against, and test_lock_coherence.py cannot see this because it derives its "
                f"population from directories that HAVE a lock.")
    if missing:
        pytest.fail(
            "services whose image build cannot produce a working venv:\n" + "\n".join(missing))


def test_the_check_can_say_no():
    """THE CONTROL. The predicate is `is_file()` over a path built from the matrix, so the way it
    goes quiet is by being pointed somewhere that cannot fail — a directory that does not exist
    is reported, and an absent file inside a real directory is reported differently."""
    real = ROOT / "agent_fleet" / "docs_agent"
    assert (real / "pyproject.toml").is_file(), "the reference point for this control has moved"
    assert not (real / "requirements.txt").is_file(), (
        "the control's negative case now exists; pick another absent file or this asserts nothing")
    assert not (ROOT / "agent_fleet" / "no_such_agent").is_dir(), (
        "the missing-directory branch has a real directory under it")
