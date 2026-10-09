"""`FinanceState` <-> plain dict. STDLIB ONLY — this module is embedded into the exported
page verbatim (`page.py` rebuilds `FinanceState` through it inside Pyodide), so an import of
anything outside the standard library would be a dependency the browser cannot resolve.

ONE CODEC, DERIVED FROM THE DATACLASS. `_row_types` reads `FinanceState`'s own field
annotations rather than hand-listing `{"programs": Program, ...}` a second time beside the
model — the same defect class `ratified_template_ids` exists to close for canvases, here for
the one dict shape both `build_fin_package.py` and the embedded `page.py` must agree on.
"""
from __future__ import annotations

import dataclasses
import typing
from typing import Any

try:  # flat in the image (/app) and inside the embedded page's Pyodide FS
    import entities
except ImportError:
    from agent_fleet.finance_agent import entities

FinanceState = entities.FinanceState


def _collection_item_type(field_type: Any, field_name: str) -> type:
    """The row dataclass a `FinanceState` collection field holds — DERIVED from its own
    `list[X]` annotation. Raises `ValueError`, naming the field, on anything else: a field
    this codec cannot map must fail loudly rather than being silently dropped from a package.
    """
    origin = typing.get_origin(field_type)
    if origin is not list:
        raise ValueError(
            f"state_codec has no mapping for FinanceState.{field_name}: not a list field"
        )
    args = typing.get_args(field_type)
    if len(args) != 1 or not dataclasses.is_dataclass(args[0]):
        raise ValueError(
            f"state_codec has no mapping for FinanceState.{field_name}: "
            f"{field_type!r} is not a list of one dataclass"
        )
    return args[0]


def _row_types() -> dict[str, type]:
    hints = typing.get_type_hints(FinanceState)
    return {
        f.name: _collection_item_type(hints[f.name], f.name)
        for f in dataclasses.fields(FinanceState)
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {f.name: getattr(row, f.name) for f in dataclasses.fields(row)}


def _row_from_dict(row_type: type, d: dict[str, Any]) -> Any:
    return row_type(**{f.name: d.get(f.name) for f in dataclasses.fields(row_type)})


def state_to_dict(state: FinanceState) -> dict[str, Any]:
    """`FinanceState` -> a plain dict of lists of dicts — JSON-safe, nothing else.

    What the manifest hashes (`state_sha256`) and what the page embeds. Field order follows
    `FinanceState`'s own declaration, so re-running this on an unchanged state reproduces the
    same dict, which `_canonical`-style hashing depends on.
    """
    row_types = _row_types()
    return {name: [_row_to_dict(row) for row in getattr(state, name)] for name in row_types}


def state_from_dict(d: dict[str, Any]) -> FinanceState:
    """The inverse of `state_to_dict`. Refuses a collection this codec does not map, by name
    (via `_row_types`) — never silently drops it."""
    row_types = _row_types()
    return FinanceState(**{
        name: [_row_from_dict(row_type, r) for r in (d.get(name) or [])]
        for name, row_type in row_types.items()
    })


def narrow(state: FinanceState, program_id: str) -> FinanceState:
    """The state holding only `program_id`'s rows — what a disclosure to one recipient ships.

    Narrows through the model's OWN foreign keys (`program_id`, `ca_id`, `wp_id`), never
    through a second join table kept beside it: a narrowing rule that does not read the same
    keys the model declares is a narrowing rule that can quietly drift from it. Raises
    `NotInModel` (via `FinanceState.program`) when `program_id` names nothing.
    """
    program = state.program(program_id)
    obs = [o for o in state.obs if o.program_id == program_id]
    wbs = [w for w in state.wbs if w.program_id == program_id]
    control_accounts = state.accounts_of(program_id)
    ca_ids = {c.ca_id for c in control_accounts}
    work_packages = [w for w in state.work_packages if w.ca_id in ca_ids]
    wp_ids = {w.wp_id for w in work_packages}
    facts = [f for f in state.facts if f.wp_id in wp_ids]
    funding = [fl for fl in state.funding if fl.program_id == program_id]
    return FinanceState(
        programs=[program], obs=obs, wbs=wbs, control_accounts=control_accounts,
        work_packages=work_packages, facts=facts, funding=funding,
    )
