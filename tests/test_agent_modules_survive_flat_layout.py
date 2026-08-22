"""Agent modules must survive the FLATTENED /app layout the container builds them into.

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

TWO WAYS THE FLAT LAYOUT BITES, one test each — both found the hard way, one deploy apart:

  1. a module named after a stdlib module is imported INSTEAD of the stdlib one;
  2. a relative import (`from . import x`) has no parent package to resolve against.

The second produced `ImportError: attempted relative import with no known parent package`
from hypercorn's `load_application`, one restart after the first was fixed.
`agent_fleet/presentation_agent/main.py` already carries the house idiom and says why:
"The Dockerfile flattens the fleet directory differently in image vs dev, so try both
paths" — a flat import first, the packaged path as fallback.
"""

from __future__ import annotations

import ast
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


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """`except ImportError:`, `except (ImportError, X):`, or a bare `except:`."""
    node = handler.type
    if node is None:
        return True
    names = node.elts if isinstance(node, ast.Tuple) else [node]
    return any(isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"}
               for n in names)


def _unrecoverable_relative_imports(source: str) -> list[int]:
    """Relative imports that are NOT inside a try/except ImportError.

    A relative import is not wrong by itself, and WHICH ARM it sits in does not matter —
    the fleet uses both orderings and both work:

      * `agent_fleet/neo4j_expert`      — flat first, relative as the guarded fallback;
      * `agent_fleet/presentation_agent` — relative first, flat as the guarded fallback.

    In the flattened image the relative form raises ImportError and the other arm answers.
    So the discriminant is RECOVERABLE vs bare, not relative-vs-absolute and not which
    branch. Two narrower rules were written before this one and both were wrong: a grep for
    `from .` flagged four working modules in neo4j_expert, and an "only in the except arm"
    rule flagged a working one in presentation_agent. Each false positive pointed at code
    that is deployed and running, which is the cheapest possible way to learn the rule.
    """
    tree = ast.parse(source)
    protected: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
            for inner in ast.walk(node):
                protected.add(id(inner))

    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.level or 0) > 0
        and id(node) not in protected
    )


def test_relative_imports_are_recoverable() -> None:
    """A bare relative import cannot resolve in the flattened image.

    Engine P died on exactly this, one restart after the stdlib-shadow fix:

        File "/app/main.py", line 25, in <module>
          from . import measures
        ImportError: attempted relative import with no known parent package

    The repo layout gives these modules a package, so the import is correct HERE and fails
    only in the image — the same stamp-axis blindness as the shadow, which is why fixing
    that one did not reveal this one.
    """
    offenders = []
    for agent_dir in _flattened_agent_dirs():
        if not agent_dir.is_dir():
            continue
        for path in sorted(agent_dir.glob("*.py")):
            for line_no in _unrecoverable_relative_imports(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{line_no}")

    assert not offenders, (
        "bare relative imports cannot resolve in the flattened image:\n  "
        + "\n  ".join(offenders)
        + "\n\nWrap in a try/except ImportError with the other layout as the fallback; "
        "either ordering is fine, and both are already used in the fleet."
    )
