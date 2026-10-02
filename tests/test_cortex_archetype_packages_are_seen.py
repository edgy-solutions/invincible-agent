"""Population ratchet: every cortex archetype PACKAGE (ADR-0055, `src/archetypes/<pkg>/`) must
be seen by both archetype registries this repo already keeps -- derived from cortex's own
package list, never a hand-written name list, so a new package is covered the day it lands and
nobody has to remember to add it here.

Two places already parse cortex's contract files into an archetype-name population:
`_cortex_declared_archetypes()` (tests/finance/test_the_wire_carries_what_the_engine_declares.py)
and `_contract_archetypes()` (tests/planning/test_archetype_registries_agree.py). This file does
not re-derive a third copy of rule A's union glob -- it imports those two functions (and rule
A's own helper, to check the contract file is actually reachable by it) directly, rather than
re-deriving a third copy of the same union that could drift from either.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CORTEX_DIR = _ROOT.parent / "cortex-ui"

if not _CORTEX_DIR.is_dir():
    pytest.skip("cortex-ui is not checked out beside this repo", allow_module_level=True)

# `tests/` and `tests/planning/` both carry `__init__.py`, so this imports as a package member
# with the repo root on sys.path -- no path surgery needed.
import tests.planning.test_archetype_registries_agree as _registries  # noqa: E402

# `tests/finance/` has NO `__init__.py`, so pytest's rootdir-insertion imports that file as a
# bare top-level module and puts `tests/finance/` itself (not the repo root) on sys.path. To
# import its functions here we put that directory on sys.path first, matching this repo's
# existing manual sys.path.insert pattern rather than inventing a shared import module.
_FINANCE_DIR = _ROOT / "tests" / "finance"
if str(_FINANCE_DIR) not in sys.path:
    sys.path.insert(0, str(_FINANCE_DIR))
import test_the_wire_carries_what_the_engine_declares as _wire  # noqa: E402

_ARCHETYPE_LINE = re.compile(r'archetype:\s*"([A-Z_]+)"')


def _archetype_packages() -> list[Path]:
    """Every `src/archetypes/<pkg>/` directory cortex ships, derived from its own `index.ts`
    files -- not a list kept here that could fall behind a new package landing in cortex-ui."""
    return sorted((_CORTEX_DIR / "src" / "archetypes").glob("*/index.ts"))


def test_the_archetype_package_population_is_inhabited():
    """Positive control. An empty population makes every assertion below pass vacuously -- this
    ratchet's own subject, applied to itself, the same shape as this repo's other positive
    controls (e.g. test_archetype_registries_agree.test_the_populations_are_inhabited)."""
    assert len(_archetype_packages()) >= 1, (
        "no src/archetypes/*/index.ts found under cortex-ui -- either the archetype-package "
        "convention (ADR-0055) was abandoned, or this derivation is looking in the wrong "
        "place, and either way every check below would pass over nothing"
    )


def test_every_archetype_package_is_seen_by_BOTH_registries():
    """For each package cortex ships: its contract.ts exists, rule A's own helper actually finds
    it (not just `.is_file()` -- the point of this ratchet is catching a helper that silently
    stops matching the package convention), it declares exactly one archetype, and that
    archetype's ID appears in both of this repo's independently-parsed archetype populations.
    """
    packages = _archetype_packages()
    declared_by_wire = _wire._cortex_declared_archetypes()
    declared_by_registries = _registries._contract_archetypes()
    rule_a_files = set(_registries._cortex_contract_files(_CORTEX_DIR))

    failures: list[str] = []
    for index_ts in packages:
        pkg_dir = index_ts.parent
        contract = pkg_dir / "contract.ts"
        if not contract.is_file():
            failures.append(f"{pkg_dir.name}: no contract.ts beside its index.ts")
            continue
        if contract not in rule_a_files:
            failures.append(
                f"{pkg_dir.name}: contract.ts exists but rule A's own contract-file helper "
                f"did not return it"
            )
            continue
        text = contract.read_text(encoding="utf-8", errors="replace")
        ids = _ARCHETYPE_LINE.findall(text)
        if len(ids) != 1:
            failures.append(
                f"{pkg_dir.name}: expected exactly one `archetype: \"...\"` declaration, "
                f"found {ids}"
            )
            continue
        archetype_id = ids[0]
        if archetype_id not in declared_by_wire:
            failures.append(
                f"{pkg_dir.name} ({archetype_id}): absent from the wire file's "
                f"_cortex_declared_archetypes()"
            )
        if archetype_id not in declared_by_registries:
            failures.append(
                f"{pkg_dir.name} ({archetype_id}): absent from the registries-agree file's "
                f"_contract_archetypes()"
            )

    assert not failures, (
        "archetype package(s) cortex ships that at least one registry does not see:\n  "
        + "\n  ".join(failures)
    )
