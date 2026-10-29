"""Produce one CDRL: an export profile's xlsx template, filled with values verbs returned.

Proposal `docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`, Part 2.

THE PRODUCER COMPUTES NOTHING. Each source is run through the engine's one envelope builder (the
function `/measure/{fn}` serves, handed in as `run_source` so this module never imports `main`),
the rows are joined on `table.key`, and every number written is the float the envelope carries.
A period a source marks `undefined` writes `undefined: <reason>` into the cell, never a number.

THE CLAIM IS `cells_sha256`, NOT THE FILE'S BYTES. An xlsx is a zip with write times in it, so the
file is not reproducible; the hash of every cell this module WROTE (sheet, coordinate, value) in
canonical JSON is. The `_manifest` sheet carries the envelope, which carries that hash, so the
manifest is not itself one of the hashed cells.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

try:  # flat in the image (/app), packaged in the repo -- see `measures.py`
    from export import MANIFEST_SCHEMA
    from export_profiles import ExportProfile
except ImportError:
    from agent_fleet.finance_agent.export import MANIFEST_SCHEMA
    from agent_fleet.finance_agent.export_profiles import ExportProfile

#: What `run_source` returns for one source: the served envelope and the method identity.
Source = tuple[dict[str, Any], dict[str, Any]]
RunSource = Callable[[str, dict[str, Any]], Source]

_METHODS_HEADER = ("fn", "measure_id", "name", "version", "module_sha256")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def artifact_filename(profile_name: str, program_id: str) -> str:
    """THE ONE PLACE the file is named: the engine's `/artifact` allow-list is derived from it."""
    return f"fin-cdrl-{profile_name}-{program_id}.xlsx"


def _fact(profile: ExportProfile, name: str, program: Any, as_of: str) -> str:
    if name == "program.name":
        return program.name
    if name == "program.id":
        return program.program_id
    if name == "as_of":
        return as_of
    return profile.cdrl[name.split(".", 1)[1]]


def _cell_value(row: Optional[dict[str, Any]], field: str) -> Any:
    """What one table cell holds: the envelope's value, `undefined: <reason>` where the row says
    the period is undefined, else nothing (a period a source did not return is an empty cell)."""
    if row is None:
        return None
    value = row.get(field)
    if value is None and row.get("undefined"):
        return f"undefined: {row['undefined']}"
    return value


def build_cdrl(
    state: Any,
    profile: ExportProfile,
    *,
    program_id: str,
    as_of: str,
    out_dir: Path,
    run_source: RunSource,
) -> tuple[Path, dict[str, Any]]:
    """Write `fin-cdrl-<name>-<program_id>.xlsx` into `out_dir`; return (path, envelope)."""
    import openpyxl
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

    params = {"program_id": program_id}
    served: dict[str, Source] = {fn: run_source(fn, dict(params)) for fn in profile.sources}
    rows_by_source = {fn: list(env.get("rows") or []) for fn, (env, _m) in served.items()}

    program = next((p for p in state.programs if p.program_id == program_id), None)
    if program is None:  # unreachable behind a source that refused it; named anyway
        raise ValueError(f"program {program_id!r} is not in the model")

    wb = openpyxl.load_workbook(profile.template_path)
    ws = wb[profile.sheet]
    written: list[list[Any]] = []

    def put(sheet: Any, coord: str, value: Any, number_format: Optional[str] = None) -> None:
        if value == "":
            return   # a file has no empty-string cell; it would hash here and read back as nothing
        if isinstance(value, float):
            # openpyxl stores 16 significant digits; hash what the FILE holds, so a reader's
            # recomputation from the cells matches `cells_sha256` (1 ulp from the envelope's float).
            value = float(f"{value:.16g}")
            if value.is_integer() and abs(value) < 1e15:
                value = int(value)   # the file stores `1000`, so a reader gets an int back
        sheet[coord] = value
        if number_format and isinstance(value, (int, float)) and not isinstance(value, bool):
            sheet[coord].number_format = number_format
        written.append([sheet.title, coord, value])

    for coord, fact in profile.cells.items():
        put(ws, coord, _fact(profile, fact, program, as_of))

    # ── the table: join on the key, in order of first appearance across the sources ────────
    keyed = {fn: {r[profile.table_key]: r for r in rows} for fn, rows in rows_by_source.items()}
    order: list[Any] = []
    for fn in profile.sources:
        for r in rows_by_source[fn]:
            if r[profile.table_key] not in order:
                order.append(r[profile.table_key])
    col_letter, first_row = coordinate_from_string(profile.table_start)
    first_col = column_index_from_string(col_letter)
    for i, key in enumerate(order):
        for j, col in enumerate(profile.columns):
            coord = ws.cell(row=first_row + i, column=first_col + j).coordinate
            if col.source == "":
                value: Any = key
            else:
                value = _cell_value(keyed[col.source].get(key), col.field)
            if value is not None:
                put(ws, coord, value, col.format)

    # ── the methods sheet: one row per source, the method that produced its figures ────────
    ms = wb.create_sheet(profile.methods_sheet)
    for j, head in enumerate(_METHODS_HEADER, start=1):
        put(ms, ms.cell(row=1, column=j).coordinate, head)
    methods: dict[str, dict[str, Any]] = {fn: m for fn, (_e, m) in served.items()}
    for i, fn in enumerate(profile.sources, start=2):
        m = methods[fn]
        for j, value in enumerate(
                (fn, m.get("measure_id", ""), m.get("name", ""), m.get("version", ""),
                 m.get("module_sha256", "")), start=1):
            put(ms, ms.cell(row=i, column=j).coordinate, value)

    cells_sha256 = _sha(sorted(written, key=lambda c: (c[0], c[1])))
    envelope = {
        "schema": MANIFEST_SCHEMA,
        "kind": "cdrl",
        "profile": profile.name,
        "template_sha256": profile.template_sha256,
        "program_id": program_id,
        "as_of": as_of,
        "sources": [
            {"fn": fn, "params": dict(params), "method": methods[fn],
             "rows_sha256": _sha(rows_by_source[fn])}
            for fn in profile.sources
        ],
        "cells_sha256": cells_sha256,
    }

    # The manifest is written AFTER the hash and is not part of it.
    mf = wb.create_sheet(profile.manifest_sheet)
    mf["A1"] = _canonical(envelope)
    mf.sheet_state = "hidden"

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / artifact_filename(profile.name, program_id)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".xlsx.tmp")
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, path)   # a reader never sees half a file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path, envelope
