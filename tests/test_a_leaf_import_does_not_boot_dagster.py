"""Importing a LEAF of ``iagent`` must not boot Dagster.

THE DEFECT THIS SEALS, 2026-09-11. ``src/iagent/__init__.py`` was one line —
``from .definitions import defs`` — so every import of every submodule executed
the whole Dagster definitions graph. ``iagent.service_urls`` imports ``logging``
and ``os`` and nothing else, and it still cost a full Dagster boot.

HOW IT SURFACED, and why it took three wrong diagnoses to find: the standalone
CI job ran ``tests/test_routing_fallback.py`` by itself. That file stubs
``dagster`` into ``sys.modules`` (a bare ``types.ModuleType``), then loads
``dynamic_supervisor.py``, whose line 1403 reaches for a cheap helper::

    from iagent.service_urls import cortex_bff_base_url

which ran ``iagent/__init__.py`` → ``iagent.definitions`` → ``from dagster
import Definitions`` → and got THE TEST'S OWN STUB::

    ImportError: cannot import name 'Definitions' from 'dagster' (unknown location)

``(unknown location)`` means the module object has no ``__file__``: a stub, not
a missing distribution. It was read as a packaging failure and dagster was
declared in ``pyproject.toml`` to fix it. THE RELOCK MOVED NOTHING — 262
packages before and after, because dagster core was already in ``uv.lock``
(and still is). The declaration was harmless and irrelevant; the diagnosis was
wrong.

WHY THE FULL SUITE STAYED GREEN: the stub installs only ``if "dagster" not in
sys.modules``. In an ordered run some earlier test had already imported the real
dagster, the guard skipped, and the real ``Definitions`` satisfied the import.
The bug was reachable only in the run that isolates the file — which is exactly
the run the order-independence workflow exists to perform. This is the SECOND
instance of that generator in that one file; the first (``Failure``/``Nothing``,
9d57a23) is recorded in its own comment block.

Run: uv run --frozen pytest tests/test_a_leaf_import_does_not_boot_dagster.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

#: Leaves that have no business needing Dagster. Each is imported in its OWN
#: interpreter, because ``sys.modules`` in this one is already polluted by every
#: test that ran before — the state that hid this bug in the first place.
_LEAVES = ("iagent.service_urls",)


def _import_in_a_clean_interpreter(module: str) -> tuple[int, bool, str]:
    """Import `module` in a fresh interpreter; report whether dagster came with it."""
    proc = subprocess.run(
        [sys.executable, "-c",
         f"import sys; import {module}; "
         f"print('DAGSTER' if 'dagster' in sys.modules else 'CLEAN')"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=180,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, "DAGSTER" in (proc.stdout or ""), out


@pytest.mark.parametrize("module", _LEAVES)
def test_THE_LEAF_IMPORT_DOES_NOT_BOOT_DAGSTER(module):
    """THE SEAL."""
    rc, pulled_dagster, out = _import_in_a_clean_interpreter(module)
    assert rc == 0, f"`import {module}` failed outright in a clean interpreter:\n{out}"
    assert not pulled_dagster, (
        f"`import {module}` dragged dagster into sys.modules. Something in the "
        f"import chain — most likely an eager import in `iagent/__init__.py` — "
        f"has re-coupled a leaf helper to the Dagster definitions graph. That "
        f"coupling hands any test's `dagster` stub to the real "
        f"`iagent.definitions`, and it only shows up when the file is run alone."
    )


def test_THE_POSITIVE_CONTROL_definitions_still_DOES_boot_dagster():
    """THE CONTROL, and it shares the seal's gate on purpose.

    The seal above proves an ABSENCE, and an absence is vacuously satisfied by a
    broken producer: if the subprocess could not import anything at all, or if
    dagster were uninstallable here, 'dagster not in sys.modules' would pass
    while measuring nothing. This asserts the same instrument, same interpreter,
    same mechanism, reports the POSITIVE case — so a green above means the leaf
    is clean rather than that nothing was looked at.
    """
    rc, pulled_dagster, out = _import_in_a_clean_interpreter("iagent.definitions")
    assert rc == 0, f"`import iagent.definitions` failed in a clean interpreter:\n{out}"
    assert pulled_dagster, (
        "CONTROL FAILED: importing `iagent.definitions` did not put dagster in "
        "sys.modules. The instrument is not measuring what it claims, so the "
        "absence asserted by the seal above proves nothing."
    )


def test_THE_DEFINITIONS_GRAPH_IS_REACHABLE_BY_ITS_DOCUMENTED_NAME():
    """The coupling was removed; the graph still has to be loadable.

    THIS TEST REPLACES ONE THAT PASSED WHILE MISSING A REGRESSION I HAD JUST
    INTRODUCED. The first cut of this file asserted `defs is not None` after
    `from iagent import defs`, and it went green — because `defs` resolved to the
    `iagent.defs` SUBPACKAGE, and a module is not None. The assertion was on a
    neighbour of the claim (existence) instead of the claim (it is a Definitions),
    so it could not tell the two apart.

    `iagent.defs` is the subpackage and always wins attribute lookup once anything
    imports `iagent.defs.*`. The Definitions object has one true name, asserted here
    BY TYPE:
    """
    proc = subprocess.run(
        [sys.executable, "-c",
         "import iagent.definitions as d, iagent;"
         "print(type(d.defs).__name__, type(iagent.defs).__name__)"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, (
        "`import iagent.definitions` failed outright:" + chr(10)
        + (proc.stdout or "") + (proc.stderr or "")
    )
    got = proc.stdout.split()
    assert got[:1] == ["Definitions"], (
        f"iagent.definitions.defs is {got[:1]}, not a Definitions — the graph no "
        f"longer builds, or the export moved."
    )
    assert got[1:] == ["module"], (
        f"iagent.defs is {got[1:]}, not the subpackage. If something rebound this "
        f"attribute to a Definitions, it did so by import-ordering luck — the "
        f"exact collision this package's docstring exists to rule out."
    )
