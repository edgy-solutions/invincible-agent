"""Every decision row's `then` names a definition that EXISTS.

THE GAP THIS CLOSES, found writing ADR-0051's chaining rows. `test_a_decision_table_is_total_and_unique.py`
proves a table is total, unique, domain-declared and row-minimal — everything about the table's
SHAPE. It never resolves `then`. So a row reading

    - when: {level: High}
      then: safety_acceptance_with_concurence     # typo, or a definition never written

passes **every existing check**: it matches a declared attribute, uses a declared domain value,
covers its input, overlaps nothing, and is load-bearing for totality. The table is provably total
over a target that does not exist.

**AND THE FAILURE IS THE ONE TOTALITY WAS WRITTEN TO PREVENT, arriving one layer along.** A gap in
the rows means no definition was chosen; a dangling `then` means one was chosen and cannot be
opened. Both surface at the moment a human risk decision was due, and neither says so where the
defect is. Totality closed the first and left the second — which is not a criticism of that seal,
it is the reason a shape check and a reference check are different seals.

**THIS IS THE THIRD TIME THIS CLASS HAS APPEARED IN THIS ARC**, and the recurrence is the argument
for the seal rather than for care:

    a `mesh:` prefix resolving to a class that does not exist — the triple parsed, the file
      loaded, and `subClassOf` bound to nothing
    a docs citation naming a packet that was on another branch — the link read as resolved
      because the file existed SOMEWHERE
    a decision row naming a definition that was never authored — the table reads as total

Each is a reference that LOOKS satisfied because the checker never followed it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_DECISION_DIRS = (
    _REPO / "policy" / "decisions",
    _REPO / "policy" / "overlays" / "sample" / "decisions",
)
_WORKFLOW_DIR = _REPO / "policy" / "workflows"


def _tables() -> list[tuple[str, dict]]:
    """Every decision table, GLOBBED rather than listed — a table added tomorrow is covered on
    arrival, the same rule the registry-sites packet exists to enforce."""
    out: list[tuple[str, dict]] = []
    for d in _DECISION_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if raw.get("rows"):
                out.append((f"{d.name}/{p.name}", raw))
    return out


def _definition_ids() -> set[str]:
    """The `id` of every authored definition — read from the FILES, not from a loader.

    Deliberately not `load_all_workflows`: that resolves `WORKFLOW_DEFINITIONS_DIR`, which is now
    an overlay list and may point somewhere this checkout does not have. A reference check must
    read what is on disk here, or it asserts something about a deployment rather than about the
    repository it is guarding.
    """
    ids: set[str] = set()
    for p in sorted(_WORKFLOW_DIR.glob("*.yaml")):
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if raw.get("id"):
            ids.add(str(raw["id"]))
    return ids


def test_there_are_definitions_and_tables_to_check():
    """Guard against a vacuous pass: both sides of the reference must be non-empty, or every
    assertion below holds over nothing."""
    assert _definition_ids(), "no workflow definitions found — the instrument is broken"
    assert _tables(), (
        "no decision tables found — this seal would pass while checking nothing, which is the "
        "shape it exists to catch"
    )


def test_every_row_selects_a_definition_that_exists():
    """THE SEAL. A `then` is a reference, and a reference nobody follows is a claim."""
    known = _definition_ids()
    dangling: list[str] = []
    for label, table in _tables():
        for i, row in enumerate(table.get("rows") or []):
            target = row.get("then")
            if target and str(target) not in known:
                dangling.append(
                    f"{label} row {i}: `then: {target}` names no definition. Known: {sorted(known)}"
                )
    assert not dangling, (
        "decision row(s) select a definition that does not exist — the table is provably TOTAL "
        "over a target nothing can open, and the symptom appears at the moment a decision was "
        "due:\n  " + "\n  ".join(dangling)
    )


def test_the_reference_checker_can_say_no():
    """THE CONTROL. A resolver that has only ever been handed real ids has not been shown able to
    reject a fabricated one — and an empty `known` set would make the assertion above pass by
    matching nothing rather than by resolving everything."""
    known = _definition_ids()
    assert "safety_acceptance_with_concurrence" in known, (
        "a definition known to be authored is not being read — the resolver is broken, not the data"
    )
    assert "safety_acceptance_with_concurence" not in known, (
        "the resolver accepts a misspelling — it is not discriminating"
    )


def test_every_definition_is_reachable_from_some_table():
    """THE OTHER DIRECTION, reported rather than enforced.

    A definition no row selects is unreachable — authored, valid, and dead. That is legitimate
    while a definition is written ahead of its selection row (both safety ones were, deliberately,
    and their headers say so), so this does NOT fail. It prints, because the state it describes is
    fine for a day and a defect after a month, and nothing else in the suite would ever mention it.
    """
    known = _definition_ids()
    selected = {
        str(row.get("then"))
        for _label, table in _tables()
        for row in (table.get("rows") or [])
        if row.get("then")
    }
    unreachable = sorted(known - selected)
    if unreachable:
        print(
            "\nNOTE — definitions no decision row selects (authored but unreachable): "
            + ", ".join(unreachable)
            + "\n  Expected while a definition precedes its selection row; a defect if it persists."
        )
