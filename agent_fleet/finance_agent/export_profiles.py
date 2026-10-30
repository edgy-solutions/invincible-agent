"""A finance EXPORT PROFILE as an overlay row. Proposal `docs/proposals/a-measure-is-an-overlay-row-
and-a-cdrl-is-an-export-profile.md`, Part 2: a CDRL is an export profile.

A row declares one deliverable: an xlsx template (kept beside the row), the verbs whose answers fill
it, which cells carry which program fact, and which column carries which field of which verb. The
producer (`cdrl.py`) writes values; this module only decides what a profile may say.

── WHAT A ROW MAY NOT SAY, AND WHERE IT IS REFUSED ──────────────────────────────────────────
Every refusal is at LOAD, names the FILE and the reason, and stops the engine booting (a profile set
that loaded half is a deliverable that exists for some deployments only, with no symptom):

* a key outside the proposal's (a `formula`, `compute` or `expression` key is the same refusal: a
  profile computes NOTHING, every number is a value a verb returned);
* `format` outside `FORMATS`, `scope` other than `program`;
* a key the format does not have (see the table below), or a key it needs and lacks;
* a template that is missing, or whose bytes do not match `template.sha256`;
* a `sheet` the template does not hold; a docx `T<n>!<A1>` outside the template's tables; a `methods_sheet` / `manifest_sheet` colliding with one;
* a json pointer that is empty, has an empty segment, an index or a `~`, or collides with or nests
  under another;
* a docx/csv column `format` outside `TEXT_FORMATS`; a json column `format`;
* a `provenance_sheets` that is not a YAML boolean (default true), or false on a row that also
  names `methods_sheet` / `manifest_sheet`: false delivers exactly the template's sheets;
* a `cells` value outside the closed fact vocabulary `CELL_FACTS`, or a key that is not an A1 cell;
* a source that is neither a built-in verb nor a composed declared measure;
* a column naming a verb not in `sources`, or a field outside that verb's FIELD SET: for a declared
  measure `{period}` plus its series keys, for a built-in the `measures.ROW_FIELDS` table (a
  built-in absent from it cannot be a source at all).

── THE FORMATS (one reading each; the architect confirms in the PR) ───────────────────────────
| key            | xlsx            | docx                   | csv       | json                |
| template       | required        | required               | refused   | refused             |
| sheet          | required        | refused                | refused   | refused             |
| cells keys     | A1              | T<n>!<A1> (1-based)    | refused   | /a/b object pointer |
| table.start    | A1              | T<n>!<A1>              | refused   | refused             |
| table.at       | refused         | refused                | refused   | required (pointer)  |
| column `as`    | refused         | refused                | required  | required            |
| column format  | Excel format    | TEXT_FORMATS keys only | same      | refused             |
| provenance_sheets | optional     | refused                | refused   | refused             |
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from iagent_mesh.declarations import DeclarationError, compose_rows, read_rows

try:  # flat in the image (/app), packaged in the repo -- see `measures.py`
    import measures as _measures
except ImportError:
    from agent_fleet.finance_agent import measures as _measures

_SEED_ENV = "FIN_EXPORT_PROFILE_POLICY_DIR"
_OVERLAY_ENV = "FIN_EXPORT_PROFILE_OVERLAY_DIRS"


def _default_seed_dir() -> Path:
    """`<repo>/policy/fin_export_profiles`, found the way `measure_verbs.py` finds its seed, but
    walking up rather than counting levels: in the flattened image this file is `/app/<module>.py`
    and a fixed `parents[2]` does not exist there."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "policy" / "fin_export_profiles"
        if candidate.is_dir():
            return candidate
    return Path("/app/policy/fin_export_profiles")


FIN_EXPORT_PROFILE_POLICY_DIR_DEFAULT = _default_seed_dir()


def FIN_EXPORT_PROFILE_POLICY_DIR() -> Path:  # noqa: N802 -- named like the constants it parallels
    """The seed directory, read from the environment at CALL time."""
    return Path(os.getenv(_SEED_ENV) or str(FIN_EXPORT_PROFILE_POLICY_DIR_DEFAULT))


def FIN_EXPORT_PROFILE_OVERLAY_DIRS() -> list[Path]:  # noqa: N802
    return [Path(p) for p in os.getenv(_OVERLAY_ENV, "").split(os.pathsep) if p]


#: What a title-block cell may carry. CLOSED: a name outside it is a refusal.
CELL_FACTS = frozenset({
    "program.name", "program.id", "as_of",
    "cdrl.item", "cdrl.title", "cdrl.data_item", "cdrl.frequency",
})

_A1 = re.compile(r"^[A-Z]{1,3}[1-9][0-9]*$")
_TCELL = re.compile(r"^T([1-9][0-9]*)!([A-Z]{1,3}[1-9][0-9]*)$")

#: The formats a profile may name. One producer writer per entry (`cdrl.build_cdrl`).
FORMATS = ("xlsx", "docx", "csv", "json")

#: How a number is rendered as TEXT in a docx or csv cell: CLOSED, keyed by the Excel number format
#: the xlsx profile would use. A docx/csv column whose `format` is not a key is a load refusal.
TEXT_FORMATS: Mapping[str, str] = {
    "#,##0": "{:,.0f}", "#,##0.00": "{:,.2f}", "0": "{:.0f}", "0.0": "{:.1f}",
    "0.00": "{:.2f}", "0.000": "{:.3f}", "0.0%": "{:.1%}",
}

_TOP_KEYS = frozenset({
    "name", "format", "scope", "label", "audience", "cdrl", "template", "sheet", "cells",
    "sources", "table", "methods_sheet", "manifest_sheet", "provenance_sheets",
})
_CDRL_KEYS = frozenset({"item", "title", "data_item", "frequency"})
_TEMPLATE_KEYS = frozenset({"file", "sha256"})
_TABLE_KEYS = frozenset({"start", "at", "key", "columns"})
_COLUMN_KEYS = frozenset({"from", "format", "as"})
_SOURCE_KEYS = frozenset({"fn"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ExportProfileError(DeclarationError):
    """An export-profile row is invalid. Names the FILE."""


@dataclass(frozen=True)
class Column:
    source: str                 # the verb ("period" for the key column)
    field: str
    format: Optional[str]       # the cell's number format (xlsx) / TEXT_FORMATS key (docx, csv)
    as_: Optional[str] = None   # csv header text / json row-object key (YAML `as`)


@dataclass(frozen=True)
class ExportProfile:
    name: str
    format: str
    scope: str
    label: str
    audience: Optional[str]
    cdrl: Mapping[str, str]
    template_path: Optional[Path]   # resolved beside the row's own file; None for csv / json
    template_sha256: Optional[str]
    sheet: Optional[str]            # xlsx only
    cells: Mapping[str, str]    # coordinate -> fact name: A1 (xlsx), T<n>!<A1> (docx), /a/b (json)
    sources: tuple[str, ...]
    table_start: Optional[str]      # xlsx A1 / docx T<n>!<A1>; None for csv / json
    table_key: str
    columns: tuple[Column, ...]
    methods_sheet: str
    manifest_sheet: str
    provenance_sheets: bool = True  # always False outside xlsx: only an xlsx has sheets
    table_at: Optional[str] = None  # json: the pointer of the row array

    def header(self) -> dict[str, str]:
        """The shared header, and nothing else: no template path, no sha, no sources."""
        return {"name": self.name, "format": self.format, "scope": self.scope, "label": self.label}


def _need(raw: Mapping[str, Any], path: str) -> Any:
    cur: Any = raw
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            raise ValueError(f"missing required key {path!r}")
    return cur


def _only(raw: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ValueError(
            f"{where} carries {extra}; a profile names facts and verb fields and computes "
            f"nothing (no formula, compute or expression): the keys are {sorted(allowed)}")


def field_set(source: str, declared: Mapping[str, Any]) -> frozenset[str]:
    """The fields a column may take from `source`: a declared measure's `{period}` plus its series
    keys, else a built-in's `measures.ROW_FIELDS` entry. Raises ValueError naming the source."""
    if source in declared:
        row = declared[source]
        return frozenset({"period"}) | frozenset(s["key"] for s in row.series)
    if source in _measures.OUTPUT_URI:
        if source not in _measures.ROW_FIELDS:
            raise ValueError(
                f"source {source!r} is a built-in verb that declares no row fields "
                f"(measures.ROW_FIELDS), so it cannot be a CDRL source")
        return _measures.ROW_FIELDS[source]
    raise ValueError(
        f"source {source!r} is neither a built-in verb nor a declared measure_id "
        f"(built-ins {sorted(_measures.OUTPUT_URI)}, declared {sorted(declared)})")


def _template_sheets(path: Path) -> list[str]:
    import openpyxl
    wb = openpyxl.load_workbook(path)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _tcell(coord: Any) -> Optional[tuple[int, str]]:
    """`T<n>!<A1>` -> (n, "A1"), else None."""
    m = _TCELL.match(coord) if isinstance(coord, str) else None
    return (int(m.group(1)), m.group(2)) if m else None


def _a1_parts(coord: str) -> tuple[int, int]:
    """`B7` -> (column 2, row 7), both 1-based."""
    m = re.match(r"^([A-Z]{1,3})([1-9][0-9]*)$", coord)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return col, int(m.group(2))


def _docx_grids(path: Path) -> list[tuple[int, int]]:
    """(rows, columns) of each body table of the document, in `document.tables` order."""
    import docx
    return [(len(t.rows), len(t.columns)) for t in docx.Document(str(path)).tables]


def _check_tcell(coord: Any, where: str, grids: list[tuple[int, int]], file: str) -> None:
    parsed = _tcell(coord)
    if parsed is None:
        raise ValueError(f"{where} {coord!r} is not a T<n>!<A1> coordinate (n 1-based, e.g. T1!B2)")
    n, a1 = parsed
    if n > len(grids):
        raise ValueError(
            f"{where} {coord!r} names table {n}, but template {file!r} holds {len(grids)} table(s)")
    col, row = _a1_parts(a1)
    rows, cols = grids[n - 1]
    if row > rows or col > cols:
        raise ValueError(
            f"{where} {coord!r} is outside table {n} of template {file!r}, "
            f"whose grid is {rows} row(s) x {cols} column(s)")


def _pointer_segments(ptr: Any, where: str) -> tuple[str, ...]:
    if not isinstance(ptr, str) or ptr == "":
        raise ValueError(f"{where} pointer {ptr!r} is empty")
    if not ptr.startswith("/"):
        raise ValueError(f"{where} pointer {ptr!r} must start with '/' (a /a/b object path)")
    if "~" in ptr:
        raise ValueError(f"{where} pointer {ptr!r} carries '~'; no escapes are supported")
    segs = tuple(ptr[1:].split("/"))
    if any(s == "" for s in segs):
        raise ValueError(f"{where} pointer {ptr!r} has an empty segment")
    if any(s.isdigit() for s in segs):
        raise ValueError(f"{where} pointer {ptr!r} has an array index; only object keys are supported")
    return segs


def _build(raw: dict, directory: Path, declared: Mapping[str, Any]) -> ExportProfile:
    # Raises ValueError: `compose_rows` re-raises it as ExportProfileError WITH THE FILE NAMED.
    for path in ("name", "format", "scope", "label", "cdrl.item", "sources", "table.key",
                 "table.columns"):
        _need(raw, path)
    _only(raw, _TOP_KEYS, "the profile")
    _only(raw["cdrl"], _CDRL_KEYS, "cdrl")
    _only(raw["table"], _TABLE_KEYS, "table")
    fmt = raw["format"]
    if fmt not in FORMATS:
        raise ValueError(f"format {fmt!r}; the formats are {list(FORMATS)}")
    if raw["scope"] != "program":
        raise ValueError(f"scope {raw['scope']!r}; only 'program' is supported (one file per program)")
    templated = fmt in ("xlsx", "docx")

    # ── per-format keys: required where the format has the thing, refused where it has not ──
    def refuse(key: str, why: str) -> None:
        raise ValueError(f"{key} is not allowed on a {fmt} profile: {why}")

    if not templated:
        if "template" in raw:
            refuse("template", f"a {fmt} profile has no template; the producer writes the whole file")
    else:
        _need(raw, "template.file")
        _need(raw, "template.sha256")
        _only(raw["template"], _TEMPLATE_KEYS, "template")
    if fmt != "xlsx":
        if "sheet" in raw:
            refuse("sheet", "only an xlsx has sheets")
        gone = [k for k in ("provenance_sheets", "methods_sheet", "manifest_sheet") if k in raw]
        if gone:
            raise ValueError(
                f"{' and '.join(gone)} is not allowed on a {fmt} profile: only an xlsx has sheets, "
                f"so the delivered file is exactly the form and the provenance travels in the "
                f"envelope and the X-Cells-Sha256 header")
    else:
        _need(raw, "sheet")
    if fmt == "csv":
        if "cells" in raw:
            refuse("cells", "a CSV has no title block")
    else:
        _need(raw, "cells")
    if fmt in ("xlsx", "docx"):
        _need(raw, "table.start")
        if "at" in raw["table"]:
            refuse("table.at", f"it names the row array of a json file, not a {fmt} table")
    elif "start" in raw["table"]:
        refuse("table.start", f"a {fmt} file has no grid to start in")
    if fmt == "json":
        _need(raw, "table.at")

    # ── the template: present, beside the row, and the bytes the row pins ──────────────────
    template: Optional[Path] = None
    pinned: Optional[str] = None
    sheet: Optional[str] = None
    sheets: list[str] = []
    grids: list[tuple[int, int]] = []
    file = ""
    if templated:
        file = str(raw["template"]["file"])
        if file != Path(file).name or file in (".", ".."):
            raise ValueError(f"template.file {file!r} must be a file beside the row, not a path")
        pinned = str(raw["template"]["sha256"])
        if not _SHA256.match(pinned):
            raise ValueError(f"template.sha256 {pinned!r} is not 64 lowercase hex digits")
        template = directory / file
        if not template.is_file():
            raise ValueError(f"template {file!r} is missing from {directory.name!r}")
        actual = hashlib.sha256(template.read_bytes()).hexdigest()
        if actual != pinned:
            raise ValueError(
                f"template {file!r} has sha256 {actual}, the row pins {pinned}; the bytes the row "
                f"was reviewed against are not the bytes on disk")
        if fmt == "xlsx":
            sheets = _template_sheets(template)
        else:
            grids = _docx_grids(template)
    if fmt == "xlsx":
        sheet = str(raw["sheet"])
        if sheet not in sheets:
            raise ValueError(f"sheet {sheet!r} is not a sheet of template {file!r} ({sheets})")
    prov = raw.get("provenance_sheets", True) if fmt == "xlsx" else False
    methods = str(raw.get("methods_sheet") or "Methods")
    manifest = str(raw.get("manifest_sheet") or "_manifest")
    if fmt == "xlsx":
        if not isinstance(prov, bool):
            raise ValueError(f"provenance_sheets {prov!r} must be a YAML boolean (true or false)")
        if not prov:
            named = [k for k in ("methods_sheet", "manifest_sheet") if k in raw]
            if named:
                raise ValueError(
                    f"{' and '.join(named)} names a provenance sheet but provenance_sheets is false")
        else:
            for label, name in (("methods_sheet", methods), ("manifest_sheet", manifest)):
                if name in sheets:
                    raise ValueError(f"{label} {name!r} collides with a sheet of template {file!r}")
            if methods == manifest:
                raise ValueError(f"methods_sheet and manifest_sheet are both {methods!r}")

    # ── the title block: closed fact vocabulary, coordinates in the format's own addressing ──
    cdrl = {k: str(v) for k, v in raw["cdrl"].items()}
    cells = dict(raw["cells"]) if fmt != "csv" else {}
    pointers: list[tuple[str, tuple[str, ...]]] = []
    for coord, fact in cells.items():
        if fmt == "xlsx":
            if not isinstance(coord, str) or not _A1.match(coord):
                raise ValueError(f"cells key {coord!r} is not an A1 coordinate")
        elif fmt == "docx":
            _check_tcell(coord, "cells key", grids, file)
        else:
            pointers.append((coord, _pointer_segments(coord, "cells key")))
        if fact not in CELL_FACTS:
            raise ValueError(
                f"cells {coord} names {fact!r}, outside the fact vocabulary {sorted(CELL_FACTS)}")
        if fact.startswith("cdrl.") and fact.split(".", 1)[1] not in cdrl:
            raise ValueError(f"cells {coord} names {fact!r}, which the row's cdrl block does not give")
    at: Optional[str] = None
    if fmt == "json":
        at = str(raw["table"]["at"])
        pointers.append((at, _pointer_segments(at, "table.at")))
        for i, (p, ps) in enumerate(pointers):
            for q, qs in pointers[i + 1:]:
                short = min(len(ps), len(qs))
                if ps[:short] == qs[:short]:
                    raise ValueError(f"pointer {p!r} collides with or nests under pointer {q!r}")

    # ── the sources and the columns ────────────────────────────────────────────────────────
    sources: list[str] = []
    for item in raw["sources"]:
        if not isinstance(item, dict) or "fn" not in item:
            raise ValueError(f"sources entry {item!r} is not {{fn: ...}}")
        _only(item, _SOURCE_KEYS, "a sources entry")
        sources.append(str(item["fn"]))
    if not sources:
        raise ValueError("sources is empty")
    fields = {fn: field_set(fn, declared) for fn in sources}

    start: Optional[str] = None
    if fmt == "xlsx":
        start = str(raw["table"]["start"])
        if not _A1.match(start):
            raise ValueError(f"table.start {start!r} is not an A1 coordinate")
    elif fmt == "docx":
        start = str(raw["table"]["start"])
        _check_tcell(start, "table.start", grids, file)
    key = str(raw["table"]["key"])
    for fn in sources:
        if key not in fields[fn]:
            raise ValueError(f"table.key {key!r} is not a field of source {fn!r} ({sorted(fields[fn])})")
    columns: list[Column] = []
    for col in raw["table"]["columns"]:
        if not isinstance(col, dict) or "from" not in col:
            raise ValueError(f"table column {col!r} is not {{from: ...}}")
        _only(col, _COLUMN_KEYS, "a table column")
        ref = str(col["from"])
        cfmt = str(col["format"]) if col.get("format") is not None else None
        as_ = col.get("as")
        if fmt in ("csv", "json"):
            if not (isinstance(as_, str) and as_):
                raise ValueError(
                    f"table column from {ref!r} has no 'as': a {fmt} column needs its "
                    f"{'header text' if fmt == 'csv' else 'row object key'}")
        elif "as" in col:
            raise ValueError(
                f"table column from {ref!r} carries 'as', which only a csv or json column takes")
        if "format" in col:
            if fmt == "json":
                raise ValueError(
                    f"table column from {ref!r} carries 'format': a json number is a number")
            if fmt in ("docx", "csv") and cfmt not in TEXT_FORMATS:
                raise ValueError(
                    f"table column from {ref!r} has format {cfmt!r}, outside the text formats "
                    f"{list(TEXT_FORMATS)} a {fmt} cell may use")
        if ref == key:
            columns.append(Column("", key, cfmt, as_))
            continue
        fn, dot, fld = ref.rpartition(".")
        if not dot:
            raise ValueError(
                f"column from {ref!r} is neither {key!r} nor <source>.<field>; the sources are {sources}")
        if fn not in sources:
            raise ValueError(f"column from {ref!r} names verb {fn!r}, which is not in sources {sources}")
        if fld not in fields[fn]:
            raise ValueError(
                f"column from {ref!r}: {fn!r} does not return a field {fld!r} "
                f"(it returns {sorted(fields[fn])})")
        columns.append(Column(fn, fld, cfmt, as_))
    if not columns:
        raise ValueError("table.columns is empty")
    if fmt in ("csv", "json"):
        names = [c.as_ for c in columns]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"table columns repeat 'as' {dup}")
    if fmt == "docx":
        n, a1 = _tcell(start)  # type: ignore[misc]
        col0, _row0 = _a1_parts(a1)
        if col0 + len(columns) - 1 > grids[n - 1][1]:
            raise ValueError(
                f"table.start {start!r} with {len(columns)} column(s) runs past table {n} of "
                f"template {file!r}, whose grid is {grids[n - 1][0]} row(s) x {grids[n - 1][1]} column(s)")

    return ExportProfile(
        name=str(raw["name"]), format=fmt, scope="program", label=str(raw["label"]),
        audience=str(raw["audience"]) if raw.get("audience") is not None else None,
        cdrl=cdrl, template_path=template, template_sha256=pinned, sheet=sheet, cells=cells,
        sources=tuple(sources), table_start=start, table_key=key, columns=tuple(columns),
        methods_sheet=methods, manifest_sheet=manifest, provenance_sheets=prov, table_at=at,
    )


def _origin_dirs(directories: Iterable[Path]) -> dict[str, Path]:
    """name -> the directory of the file that WINS composition (the last layer to carry it), so a
    row's template resolves beside the row's own file. Tombstones are the caller's concern."""
    origin: dict[str, Path] = {}
    for d in directories:
        for name, (f, _raw) in read_rows(d, key_field="name", error=ExportProfileError).items():
            origin[name] = f.parent
    return origin


def load_export_profiles(
    policy_dir: Path | str | None = None,
    overlay_dirs: list[Path] | None = None,
    *,
    declared: Mapping[str, Any] | None = None,
) -> list[ExportProfile]:
    """Every export profile, composed (ADR-0036) and validated, sorted by `name`.

    NO ROWS IS A VALID ANSWER: the platform seeds none. `declared` is the engine's composed
    measure-verb rows keyed by `measure_id` (a profile may source from one).
    """
    d = Path(policy_dir) if policy_dir is not None else FIN_EXPORT_PROFILE_POLICY_DIR()
    ov = overlay_dirs if overlay_dirs is not None else FIN_EXPORT_PROFILE_OVERLAY_DIRS()
    origin = _origin_dirs([d, *ov])
    return compose_rows(
        d, ov, key_field="name",
        builder=lambda raw: _build(raw, origin[raw["name"]], declared or {}),
        label="export profile", error=ExportProfileError,
    )
