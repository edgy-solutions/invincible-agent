"""No agent module may take the name of a stdlib top-level module.

WHY THIS EXISTS. `agent_fleet/planning_agent/types.py` shipped, and the container could
not start the Python interpreter at all:

    File "/usr/local/lib/python3.12/functools.py", line 22, in <module>
      from types import GenericAlias
    File "/app/types.py", line 22, in <module>
      from dataclasses import dataclass, field
    ImportError: cannot import name 'MappingProxyType' from partially initialized
    module 'types' (most likely due to a circular import) (/app/types.py)

`.github/workflows/build-containers.yml` builds every agent with
`COPY ${AGENT_DIR}/ /app/` under `WORKDIR /app`, so each agent's modules land FLAT at
the top of the interpreter's search path. CPython's own bootstrap then imports our file
instead of its own and dies before any application code runs.

THE REASON THIS SURVIVED EVERY LOCAL CHECK. In the repo the module is
`agent_fleet.planning_agent.types` — properly namespaced, unambiguous, and correct.
1673 tests passed over it. The defect exists only in the flattened container layout, so
it is a stamp-axis fact: a property of WHERE the code runs, not of what it says. The
unit suite cannot see it by construction, which is exactly why it needs its own seal.

Scoped to the agent build paths declared in the workflow matrix, so an agent added later
is covered without anyone remembering this file exists.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "build-containers.yml"

# `.` means "whole repo copied to /app" — a different layout with its own conventions
# (the workflow comments call it out separately), so it is not this seal's business.
_MATRIX_PATH = re.compile(r"^\s*path:\s*(agent_fleet/\S+)\s*$", re.MULTILINE)


def _flattened_agent_dirs() -> list[pathlib.Path]:
    text = WORKFLOW.read_text(encoding="utf-8")
    return [REPO / m for m in sorted(set(_MATRIX_PATH.findall(text)))]


def test_workflow_matrix_still_parses() -> None:
    """A seal that silently matches nothing passes forever and proves nothing."""
    dirs = _flattened_agent_dirs()
    assert len(dirs) >= 8, f"expected the agent build matrix, parsed only {dirs}"


def test_no_agent_module_shadows_a_stdlib_module() -> None:
    stdlib = sys.stdlib_module_names
    offenders = []

    for agent_dir in _flattened_agent_dirs():
        if not agent_dir.is_dir():
            continue  # matrix entry for a path not yet created; not this seal's failure
        for path in sorted(agent_dir.glob("*.py")):
            if path.stem in stdlib:
                offenders.append(f"{path.relative_to(REPO).as_posix()} shadows stdlib '{path.stem}'")

    assert not offenders, (
        "agent modules shadow stdlib modules and will break the container:\n  "
        + "\n  ".join(offenders)
        + "\n\nThese agents are built with `COPY ${AGENT_DIR}/ /app/` and `WORKDIR /app`, "
        "so the file sits at the top of sys.path and CPython's own bootstrap imports it "
        "instead of the stdlib module. The interpreter fails before main.py runs. "
        "Rename to something domain-specific (entities.py, capabilities.py, ...)."
    )
