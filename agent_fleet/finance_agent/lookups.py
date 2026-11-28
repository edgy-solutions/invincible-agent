"""The two built-in lookups: `fin_calendar_periods` and `fin_hierarchy_children`.

Standard terms (ruled 2026-11-25), read from what the deployment declares: the fiscal calendar and
the dataset contract's `status_period` and `hierarchy`. They answer no amount and no verdict. This
module is PURE: it shapes what `asset_inputs` read, as the caller, into the INSTANCES_BY_PROPERTY
payload (`title`, `target`, `columns`, `row_identity`, `rows`) plus the answer's own keys. It reads
nothing and names no column of any contract; the roles come from `asset_inputs.hierarchy_levels`.
"""
from __future__ import annotations

import json
from typing import Any, Optional, Sequence

try:  # flat in the image (/app), packaged in the repo
    from entities import NotInModel
except ImportError:
    from agent_fleet.finance_agent.entities import NotInModel

DOMAIN = "finance"

#: The built-in lookups, and the parameters each takes (the signature's, in `measures`).
LOOKUP_PARAMS = {
    "fin_calendar_periods": ("program_id",),
    "fin_hierarchy_children": ("program_id", "element", "depth"),
}
LOOKUP_FNS = frozenset(LOOKUP_PARAMS)


class LookupRefused(Exception):
    """A lookup refused before or at the answer. `code` is the wire's `error`; `message` names the
    rule and the declaration, never a row's value."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def check_depth(depth: Any) -> int:
    """`depth` as an integer of at least 1, or `bad_depth`. Checked BEFORE any read; a bool is not
    an integer here."""
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
        raise LookupRefused("bad_depth", "depth must be an integer of at least 1")
    return depth


def calendar_answer(calendar: Any, status: Optional[str], status_column: Optional[str]) -> dict[str, Any]:
    """The periods of the declared calendar IN THE CALENDAR'S OWN ORDER (never sorted by label),
    the one named by the data's status value marked. With no status column declared nothing is
    marked and the answer says so."""
    periods = [{
        "label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(),
        "fiscal_year": p.fiscal_year, "quarter": p.quarter, "half": p.half,
        "status": status is not None and p.label == status,
    } for p in calendar.periods]
    return {
        "calendar_id": calendar.calendar_id,
        "periods": periods,
        "status_period": status,
        "status_column": status_column,
        "title": f"Fiscal calendar {calendar.calendar_id}" + (
            f", reported through {status}" if status is not None
            else " (the contract declares no status period)"),
        # No `class`: no ontology declares a class for a fiscal period, and cortex shows
        # `target.class` as the table's subtitle. A class named here would be one nobody declared.
        "target": {"domain": DOMAIN},
        "columns": [
            {"key": "label", "label": "Period"},
            {"key": "start", "label": "Start"},
            {"key": "end", "label": "End"},
            {"key": "fiscal_year", "label": "Fiscal year"},
            {"key": "quarter", "label": "Quarter"},
            {"key": "half", "label": "Half"},
            {"key": "status", "label": "Status period"},
        ],
        "row_identity": {"key": "label"},
        "rows": [dict(p) for p in periods],
    }


def locate(element: str, program_id: str, levels: Sequence[tuple[str, str]],
           rows: Sequence[tuple[str, ...]]) -> int:
    """The index into `levels` (scope first) at which `element` stands, exactly. `rows` are the
    distinct tuples of the hierarchy columns (the scope level is the program itself). Absent
    everywhere: `NotInModel` naming the element only. At two or more levels: `element_ambiguous`,
    naming each level's role and column, never choosing one. An element below the top hierarchy level
    that stands under more than one parent path: `element_ambiguous` too, naming every parent path
    (sorted) and never choosing one; a name is a node only when its ancestors are one path."""
    found = []
    if element == program_id:
        found.append(0)
    for i in range(1, len(levels)):
        if any(r[i - 1] == element for r in rows):
            found.append(i)
    if not found:
        raise NotInModel(f"the model holds no element {element!r} in program {program_id!r}")
    if len(found) > 1:
        where = ", ".join(f"{levels[i][1]} ({levels[i][0]})" for i in found)
        raise LookupRefused(
            "element_ambiguous",
            f"the element {element!r} stands at more than one level: {where}; name one level")
    at = found[0]
    if at >= 2:  # below the top level: the node's ancestors must be one path
        parents = sorted({tuple(r[:at - 1]) for r in rows if r[at - 1] == element})
        if len(parents) > 1:
            named = ", ".join(" / ".join(p) for p in parents)
            raise LookupRefused(
                "element_ambiguous",
                f"the element {element!r} ({levels[at][1]}, column {levels[at][0]}) stands under more "
                f"than one parent: {named}; ask for it under one of those parents")
    return at


def hierarchy_answer(program_id: str, element: str, depth: int, scope_column: str,
                     levels: Sequence[tuple[str, str]], rows: Sequence[tuple[str, ...]]) -> dict[str, Any]:
    """The children of `element`, down `depth` levels and no further than the work package.

    `levels` is `[(scope, "scope"), *hierarchy_levels(contract)]`, `rows` the distinct tuples of the
    hierarchy columns of the program's rows. An element equal to `program_id` is the scope level.
    ORDER: ascending by string at each level. No amount is read or returned."""
    levels = list(levels)
    if len(levels) < 2:
        raise LookupRefused(
            "hierarchy_not_declared",
            "the dataset contract declares no hierarchy; the lookup needs its level columns")
    depth = check_depth(depth)
    at = locate(element, program_id, levels, rows)
    # a row's tuple is the hierarchy columns; the scope level has no column of its own in it.
    path_index = at - 1  # index into a row's tuple of the located column (-1: the scope)
    scoped = [r for r in rows if at == 0 or r[path_index] == element]

    def descend(level_at: int, within: list[tuple[str, ...]], remaining: int,
                parent_depth: int) -> tuple[list[dict[str, Any]], int]:
        if remaining == 0 or level_at + 1 >= len(levels):
            return [], parent_depth
        child_at = level_at + 1
        names = sorted({r[child_at - 1] for r in within})
        reached = parent_depth
        out = []
        for name in names:
            below = [r for r in within if r[child_at - 1] == name]
            kids, deepest = descend(child_at, below, remaining - 1, parent_depth + 1)
            reached = max(reached, deepest, parent_depth + 1)
            out.append({"name": name, "level": levels[child_at][0], "role": levels[child_at][1],
                        "children": kids})
        return out, reached

    children, returned = descend(at, scoped, depth, 0)
    # the table is a pre-order walk of the nested answer.
    ordered: list[dict[str, Any]] = []

    # A node's identity is its path from the top hierarchy level down; `locate` guarantees the asked
    # element's own ancestors are one path, so two nodes with one name under two parents never share it.
    base: list[str] = []
    if at >= 1:
        base = [str(x) for x in (scoped[0][:at - 1] if scoped else ())] + [element]

    def walk(nodes: list[dict[str, Any]], parent: str, d: int, path: list[str]) -> None:
        for n in nodes:
            here = path + [n["name"]]
            ordered.append({"name": n["name"], "level": n["level"], "role": n["role"],
                            "parent": parent, "depth": d,
                            "identity": json.dumps(here, ensure_ascii=False)})
            walk(n["children"], n["name"], d + 1, here)

    walk(children, element, 1, base)
    table = ordered
    return {
        "element": element,
        "level": levels[at][0],
        "role": levels[at][1],
        "depth_requested": depth,
        "depth_returned": returned,
        "children": children,
        "title": f"Under {element}",
        # `fin:WBSElement` is the declared class of a node of the decomposition (finance_extension.ttl);
        # control accounts and work packages are its lower levels.
        "target": {"domain": DOMAIN, "class": "fin:WBSElement"},
        "columns": [
            {"key": "name", "label": "Element"},
            {"key": "role", "label": "Level"},
            {"key": "parent", "label": "Under"},
            {"key": "depth", "label": "Depth"},
        ],
        "row_identity": {"key": "identity"},
        "rows": table,
    }
