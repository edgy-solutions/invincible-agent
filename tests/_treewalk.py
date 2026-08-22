"""A tree-walk that PRUNES instead of filtering, and survives an unreadable directory.

WHY THIS EXISTS. Two guards derive their populations with `Path.rglob` and then filter the
results:

    sorted({p.parent for p in _ROOT.rglob("uv.lock")
            if not any(x in p.parts for x in (".venv", ".venv.wsl", "node_modules"))})

The filter is correct and it is too late. `rglob` must TRAVERSE a directory to yield anything
from it, so the exclusion runs after the descent it was meant to prevent. On this tree that
descent hits `.venv.wsl/lib64` — a WSL symlink a Windows interpreter cannot traverse — and
raises `OSError: [WinError 1920]` at IMPORT time, during collection, before a single test runs.

The cost of that is worse than it sounds and is the reason this file is worth having: a
collection error REMOVES A TEST FILE FROM THE POPULATION SILENTLY. The run still prints a large
green count, and the two files it removed are the ones that police dependency hygiene.

TWO PROPERTIES, and the second is the one a rewrite would drop:

  PRUNE   excluded directories are never descended into, so nothing inside them can raise.
  ENDURE  a directory that cannot be read is SKIPPED, not fatal. A tree-walk that dies on one
          unreadable entry is a latent defect on any machine that grows a symlink, a permission
          quirk, or a cloud-storage placeholder — and it fails at collection, where the symptom
          points at the test rather than at the tree.

Neither property is available from `rglob`, which offers no pruning hook and no error callback.

THIS CLASS WAS FOUND ON 2026-08-05, NOT BY ME. `docs/plans/suite-signal-session.md` records
`agent_fleet/restate_analyst/.venv.wsl`'s `lib64` symlink "crashing three tree-walking tests
with OSError: [WinError 1920] before they asserted anything" — same symlink, same error, same
walks. That session banked it as an instrument-defect LESSON and did not convert it into a
GUARD, so the walks stayed unfixed and it fired again sixteen days later against a different
reader. Both `.venv.wsl` directories are still in the tree.

That is the reason this file exists rather than a fourth write-up: a banked lesson that is not
converted into a guard recurs on schedule.
"""
from __future__ import annotations

import os
from pathlib import Path

# Directories never worth descending into, anywhere. `.venv.wsl` is named explicitly rather
# than caught by a `.venv*` pattern because it is the one that actually broke, and a reader
# deleting it should have to think about why it is here.
DEFAULT_PRUNE = frozenset({
    ".venv", ".venv.wsl", "node_modules", ".git", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
})


def find_files(
    root: Path,
    filename: str,
    *,
    prune: frozenset[str] = DEFAULT_PRUNE,
) -> list[Path]:
    """Every `filename` under `root`, without descending into pruned directories.

    Unreadable directories are skipped rather than raised — see ENDURE above. `os.walk` is used
    rather than `Path.rglob` for the one reason `rglob` cannot offer: mutating `dirnames`
    in place prunes the walk BEFORE the descent.
    """
    out: list[Path] = []

    def _on_error(_exc: OSError) -> None:
        # Deliberately swallowed. An entry we cannot read contributes nothing to the population,
        # and raising here converts a local filesystem quirk into a collection error that
        # removes whole test files from the run.
        return None

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error, followlinks=False):
        # PRUNE IN PLACE. This is the whole point; a post-hoc filter cannot do it.
        dirnames[:] = [d for d in dirnames if d not in prune]
        if filename in filenames:
            out.append(Path(dirpath) / filename)
    return sorted(out)
