"""ADR-0039's decision half, generic: evaluate ANY composed decision table against a set of facts.

`acceptance_selection` was the first consumer and hard-wired `matches == ["level"]`. The workflow
runner selects at trigger and chains at termination over tables it has never seen, so the
evaluation lives here, once, and every consumer -- acceptance included -- goes through it.

THE SEMANTICS ARE THE BUILD SEAL'S, AND A SEAL HOLDS THEM TOGETHER.
`tests/test_a_decision_table_is_total_and_unique.py` proves totality and uniqueness with its own
matcher: equality on each `when` key, an omitted attribute is a wildcard. If the runtime matched
differently -- normalised case, read a list as membership, treated a missing fact as a wildcard --
the seal would prove a property of a table the running system does not evaluate.
`tests/test_the_runtime_decides_as_the_seal_proves.py` walks every committed table's whole
declared input space through both and requires the same row.

FACTS MAY CARRY MORE THAN THE TABLE READS. A chaining table sees the trigger, the outcome and the
chosen option's attributes together; it reads only what `matches` declares. A fact the table
DOES declare must be present and inside its declared domain -- a missing one is refused rather
than wildcarded, because "the producer did not say" and "any value" are different facts.

EVERY FAILURE RAISES. `policy/decisions/README.md`: a fall-through in a selection table means no
definition was chosen at the moment a human decision was due. There is no default row.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping, NamedTuple


class DecisionError(Exception):
    """A table could not decide. ALWAYS terminal -- see the module docstring."""


class Decision(NamedTuple):
    then: str          # a definition id, an audience, or one of the table's declared terminals
    terminal: bool     # True when `then` is in the table's `terminals:` -- a state, not a process
    row: int           # the index of the one matching row, for the transition record
    #: the row's ``refresh_input``: re-read the case's input before the next instance runs
    refresh_input: bool = False


#: Every key a row may carry. A row is read by key, so a misspelled one -- ``refresh_inputs`` --
#: would load, decide, and never refresh: a field the runner cannot see.
ROW_KEYS = frozenset({"when", "then", "refresh_input"})


# ---------------------------------------------------------------------------------------
# WHERE TABLES LIVE -- moved here from acceptance_selection, unchanged in behaviour
# ---------------------------------------------------------------------------------------

def candidate_decision_dirs(module_path: Path) -> list[Path]:
    """The ordered places a `policy/` root can live, given this module's path.

    MIRRORS ``workflow_definition.candidate_definition_dirs`` deliberately, including its depth
    guard: the image FLATTENS this service directory into ``/app``, so in the container this
    module is ``/app/decision_table.py`` and ``parents[2]`` would raise IndexError before any
    honest error could be raised.
    """
    here = module_path.resolve()
    out: list[Path] = []
    if len(here.parents) >= 3:  # repo layout only; guarded, see docstring
        out.append(here.parents[2] / "policy")
    out.append(here.parent / "policy")  # flattened container layout
    return out


def decision_dirs() -> tuple[Path, list[Path]]:
    """``(seed_dir, overlay_dirs)`` for the composer, lowest precedence first.

    ``DECISION_TABLE_DIR`` is an ``os.pathsep``-separated LIST with the same shape and the same
    later-wins rule as ``WORKFLOW_DEFINITIONS_DIR`` -- one mechanism, not a fourth one. Without it
    every overlay on disk composes in NAME order, which is why no two overlays may declare the
    same table (sealed): name order is not a precedence anyone chose.
    """
    env = os.environ.get("DECISION_TABLE_DIR")
    if env:
        parts = [Path(p.strip()) for p in env.split(os.pathsep) if p.strip()]
        if parts:
            return parts[0], parts[1:]
    for root in candidate_decision_dirs(Path(__file__)):
        seed = root / "decisions"
        if seed.is_dir():
            overlays = sorted(
                p for p in (root / "overlays").glob("*/decisions") if p.is_dir()
            )
            return seed, list(overlays)
    root = candidate_decision_dirs(Path(__file__))[0]
    return root / "decisions", []


def load_tables() -> Dict[str, Dict[str, Any]]:
    """Every composed table, keyed by `decision`. COMPOSED BY THE SHARED COMPOSER (ADR-0039
    refuses a fourth): an overlay row REPLACES a seed row wholesale, keyed on `decision`."""
    try:
        from iagent_mesh.declarations import compose_rows, read_rows
    except ImportError as exc:  # pragma: no cover -- the SDK is a hard dependency of the runtime
        raise DecisionError(
            "iagent-mesh SDK is not importable, so the decision layer cannot compose. This is a "
            f"packaging failure, not an empty table: {exc}"
        ) from exc

    seed, overlays = decision_dirs()
    # NO TWO OVERLAYS MAY DECLARE ONE TABLE -- `decision_dirs` said so, and said "(sealed)", and
    # nothing refused it: the composer lets a later overlay replace an earlier one, so the second
    # overlay's rows silently decided every case. Refused HERE, at load, because a deployment's own
    # overlays are never in this repo's tree for a static seal to see. The triggers' rule.
    seen: Dict[str, Path] = {}
    for od in overlays:
        if not od.is_dir():
            continue
        try:
            found = read_rows(od, key_field="decision")
        except Exception as exc:  # noqa: BLE001 -- the composer below names it with the paths
            raise DecisionError(f"could not read decision tables in {str(od)!r}: {exc}") from exc
        for key, (f, _raw) in found.items():
            if key in seen:
                raise DecisionError(
                    f"decision table {key!r} is declared by two overlays ({seen[key]} and {f}); "
                    "name order is not a precedence anyone chose")
            seen[key] = f
    try:
        rows = compose_rows(seed, overlays, key_field="decision",
                            builder=lambda raw: raw, label="decision table")
    except Exception as exc:  # noqa: BLE001 -- re-raised as terminal, with the paths named
        raise DecisionError(
            f"could not compose decision tables from seed {str(seed)!r} "
            f"overlays {[str(o) for o in overlays]}: {exc}"
        ) from exc
    return {str(r.get("decision")): r for r in rows}


def load_table(decision: str) -> Dict[str, Any]:
    """One composed table. AN ABSENT TABLE IS NOT AN EMPTY TABLE: a missing file must not read as
    "no rows matched", so this names every directory it looked in and what it did find."""
    tables = load_tables()
    if decision in tables:
        return tables[decision]
    seed, overlays = decision_dirs()
    raise DecisionError(
        f"no decision table {decision!r} in seed {str(seed)!r} or overlays "
        f"{[str(o) for o in overlays]} (have: {sorted(tables)}). "
        "Presence in the repo is not presence in the running system -- check that "
        "policy/decisions/ and policy/overlays/ are both baked into this image."
    )


# ---------------------------------------------------------------------------------------
# EVALUATION
# ---------------------------------------------------------------------------------------

def decide(table: Mapping[str, Any], facts: Mapping[str, Any]) -> Decision:
    """The one row `table` selects for `facts`. Raises rather than defaulting.

    FIVE REFUSALS, EACH A DIFFERENT FACT:

    * the table declares no `matches`, or an attribute with no `domain` -- totality is then over
      itself by construction and its seal asserts nothing (R-026);
    * a declared attribute is absent from `facts` -- the producer did not say, which is not "any";
    * a fact is outside its declared domain -- a value nobody tailored a row for, a policy gap;
    * no row matches -- the table is not total, and the build seal did not run on this table;
    * more than one row matches -- the outcome would depend on YAML list order (R-035).

    And `then` must be a non-empty string. THE MATCH IS EXACT AND CASE-SENSITIVE.
    """
    name = table.get("decision", "<unnamed>")
    matches = list(table.get("matches") or [])
    if not matches:
        raise DecisionError(f"{name} declares no `matches` -- nothing to decide on")
    domain = table.get("domain") or {}
    inp: dict = {}
    for attr in matches:
        declared = list(domain.get(attr) or [])
        if not declared:
            raise DecisionError(
                f"{name} declares no domain for {attr!r}. Without it the table is total over "
                "itself by construction and its totality seal asserts nothing (R-026).")
        if attr not in facts:
            raise DecisionError(
                f"{name} reads {attr!r} and the facts carry none (have: {sorted(facts)}). An "
                "absent fact is not a wildcard -- the producer did not say.")
        if facts[attr] not in declared:
            raise DecisionError(
                f"{name}: {attr}={facts[attr]!r} is not in the declared domain {declared}. No "
                "row is chosen -- a value with no row is a policy gap and must not take a default.")
        inp[attr] = facts[attr]

    hits = [
        i for i, row in enumerate(table.get("rows") or [])
        if all(inp.get(k) == v for k, v in (row.get("when") or {}).items())
    ]
    if not hits:
        raise DecisionError(
            f"{name} has NO ROW for {inp}. A fall-through here means nothing was chosen at the "
            "moment a decision was due.")
    if len(hits) > 1:
        raise DecisionError(
            f"{name} has {len(hits)} rows matching {inp}: "
            f"{[table['rows'][i].get('then') for i in hits]}. Two matching rows make the outcome "
            "depend on row order, which a YAML list does not declare (R-035).")

    then = table["rows"][hits[0]].get("then")
    if not then or not isinstance(then, str):
        raise DecisionError(f"{name} row {hits[0]} for {inp} has no `then`: {then!r}")
    return Decision(then, then in (table.get("terminals") or []), hits[0],
                    row_refreshes(table, hits[0]))


def row_refreshes(table: Mapping[str, Any], i: int) -> bool:
    """Row ``i``'s ``refresh_input``, refused unless it is a bool on a row that opens an instance.

    A CHAINING ROW MAY RE-READ THE CASE'S INPUT before the definition it opens runs: a case that
    returns to a proposal days later proposes against the picture as it is now, not as it was.
    Refused on a terminal -- a terminal opens nothing, so nothing would read what was refreshed --
    and on anything but a bool, since ``"no"`` is truthy. Read on the decided row at run time and
    on every shipped row at build time, by this one function."""
    name = table.get("decision", "<unnamed>")
    row = (table.get("rows") or [])[i]
    unknown = sorted(set(row) - ROW_KEYS)
    if unknown:
        raise DecisionError(
            f"{name} row {i} carries {unknown}; a row may carry only {sorted(ROW_KEYS)}. A key "
            "nothing reads would load and never act.")
    refresh = row.get("refresh_input", False)
    if not isinstance(refresh, bool):
        raise DecisionError(f"{name} row {i}: `refresh_input` must be true or false, not {refresh!r}")
    if refresh and row.get("then") in (table.get("terminals") or []):
        raise DecisionError(
            f"{name} row {i}: `refresh_input` on the terminal {row.get('then')!r} -- a terminal "
            "opens no instance, so nothing would read the refreshed input")
    return refresh


def targets(table: Mapping[str, Any]) -> tuple[str, ...]:
    """Every NON-terminal `then` the table can produce -- the definitions it may open. Derived from
    the rows, never typed beside them (the boot invariant's input; see acceptance_selection)."""
    terminals = set(table.get("terminals") or [])
    return tuple(sorted({
        str(r.get("then")) for r in (table.get("rows") or [])
        if r.get("then") and str(r.get("then")) not in terminals
    }))
