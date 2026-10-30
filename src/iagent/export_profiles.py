"""Review export profiles: `policy/exports/<name>.yaml`, validated against what the extraction
route SERVES, rendered from `GET /ingest/{id}/extraction`'s body.

The vocabulary is doc-tools 7f's `batch-column-map.md` (contract_version 1): `granularity` (not
`scope`), the `source` selector (`field` / `row_field` / `absent_row`), `on_unresolvable` /
`landing`, ISO-8601 dates that land rather than being guessed, and the `no_parts` row.

Until 7f's field catalogue (doc-tools #182) lands, a profile is validated against the served set
below, which is DERIVED from the pydantic models in `ingest_api` and never typed. `ROW_FIELDS` is
the one declared list (7f's section 4), sealed by an inline review.json double in the seal test.

Pure: no I/O but the profile directory read in `load_profiles`.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from .ingest_api import Extraction, ExtractionRow, Notice

logger = logging.getLogger(__name__)

COLUMN_MAP_VERSION = 1  # 7f's contract_version

#: Extraction properties that are not notice-level sources.
EXCLUDED = frozenset({"rows", "rows_without_evidence", "review_ref", "relocated_to", "notice"})

NOTICE_FIELDS = frozenset(
    (set(Extraction.model_fields) - EXCLUDED) | {f"notice.{p}" for p in Notice.model_fields})
#: One value per part.
ROW_UNSHARED = frozenset({"part_index", "mpn", "row_index"})
#: Never a source: it is what `row_field` selects on.
ROW_DISCRIMINATOR = "field"
#: Properties several rows of one part share: a source over one REQUIRES `row_field`.
ROW_SHARED = frozenset(set(ExtractionRow.model_fields) - ROW_UNSHARED - {ROW_DISCRIMINATOR})
#: 7f's batch-column-map section 4 list: the per-part fields a `row_field` may name. No tuple in
#: src/ or agent_fleet/ lists them; sealed by an inline review.json double in the seal test.
ROW_FIELDS = ("affected_mpn", "replacement_mpn", "ltb_date")

FORMATS = ("csv", "json")
GRANULARITIES = ("notice_part", "notice")
TRANSFORMS = ("trim", "upper", "lower")
NO_PARTS = "no_parts"

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_ISO_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # fullmatch; never date.fromisoformat alone
_TOP_KEYS = frozenset({"column_map_version", "name", "label", "format", "granularity", "columns"})
_COL_KEYS = frozenset({"output", "source", "format", "on_unresolvable", "landing", "transforms"})
_SRC_KEYS = frozenset({"field", "row_field", "absent_row"})
_ON_UNRESOLVABLE = ("land", "blank", "block")
_ABSENT_ROW = ("empty_cell", "block")


class ProfileInvalid(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


class ExportBlocked(Exception):
    def __init__(self, reason: str, *, notice: Any, part: Any, column: str):
        super().__init__(f"{reason}: notice={notice} part={part} column={column}")
        self.reason, self.notice, self.part, self.column = reason, notice, part, column

    def body(self) -> dict:
        return {"reason": self.reason, "notice": self.notice, "part": self.part,
                "column": self.column}


@dataclass(frozen=True)
class Column:
    output: str
    source: Optional[dict] = None  # None = derived
    format: Optional[str] = None
    on_unresolvable: Optional[str] = None
    landing: Optional[str] = None
    transforms: tuple = ()

    @property
    def derived(self) -> bool:
        return self.source is None


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    format: str
    granularity: str
    columns: tuple = field(default_factory=tuple)

    @property
    def outputs(self) -> list:
        return [c.output for c in self.columns]


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------

def _nonblank(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _column(raw: Any, granularity: str) -> Column:
    if not isinstance(raw, dict):
        raise ProfileInvalid("column_not_a_mapping", repr(raw)[:80])
    extra = set(raw) - _COL_KEYS
    if extra:
        raise ProfileInvalid("unknown_key", f"column key(s) {sorted(extra)}")
    out = raw.get("output")
    if not _nonblank(out):
        raise ProfileInvalid("output_blank", "a column's `output` is required and non-blank")
    src_raw = raw.get("source")
    transforms = raw.get("transforms", [])
    if not isinstance(transforms, list) or any(t not in TRANSFORMS for t in transforms):
        raise ProfileInvalid("transform_unknown", f"{out!r}: transforms must be a list from "
                                                  f"{list(TRANSFORMS)}")
    if src_raw is None and "source" not in raw:
        for k in ("format", "on_unresolvable", "landing", "transforms"):
            if k in raw:
                raise ProfileInvalid("derived_column_has_key", f"{out!r} is derived and takes no {k}")
        if out == NO_PARTS and granularity == "notice":
            raise ProfileInvalid("row_source_at_notice_granularity",
                                 f"{out!r} (no_parts) is meaningless at granularity notice")
        return Column(output=out)
    if not isinstance(src_raw, dict):
        raise ProfileInvalid("source_invalid", f"{out!r}: source must be a mapping")
    extra = set(src_raw) - _SRC_KEYS
    if extra:
        raise ProfileInvalid("unknown_key", f"{out!r}: source key(s) {sorted(extra)}")
    fld = src_raw.get("field")
    served = NOTICE_FIELDS | ROW_UNSHARED | ROW_SHARED
    if fld not in served:
        raise ProfileInvalid("field_not_served", f"{out!r}: {fld!r} is not served by the "
                                                 "extraction route")
    rf = src_raw.get("row_field")
    if fld in ROW_SHARED and rf is None:
        raise ProfileInvalid("row_field_required", f"{out!r}: {fld!r} is shared by several rows")
    if fld not in ROW_SHARED and "row_field" in src_raw:
        raise ProfileInvalid("row_field_refused", f"{out!r}: {fld!r} is not shared; row_field "
                                                  "would silently match nothing")
    if rf is not None and rf not in ROW_FIELDS:
        raise ProfileInvalid("row_field_unknown", f"{out!r}: {rf!r} not in {list(ROW_FIELDS)}")
    absent = src_raw.get("absent_row", "empty_cell")
    if absent not in _ABSENT_ROW:
        raise ProfileInvalid("absent_row_invalid", f"{out!r}: {absent!r}")
    if "absent_row" in src_raw and rf is None:
        raise ProfileInvalid("absent_row_refused", f"{out!r}: absent_row needs row_field")
    if granularity == "notice" and fld not in NOTICE_FIELDS:
        raise ProfileInvalid("row_source_at_notice_granularity",
                             f"{out!r}: {fld!r} is a part-level field")
    fmt = raw.get("format")
    onu = raw.get("on_unresolvable")
    landing = raw.get("landing")
    if fmt is not None and fmt != "iso8601":
        raise ProfileInvalid("format_unsupported", f"{out!r}: only iso8601 is accepted")
    if fmt is not None:
        if onu not in _ON_UNRESOLVABLE:
            raise ProfileInvalid("on_unresolvable_required",
                                 f"{out!r}: a format column declares on_unresolvable "
                                 f"{list(_ON_UNRESOLVABLE)}")
    elif onu is not None:
        raise ProfileInvalid("on_unresolvable_refused", f"{out!r}: only a format column takes it")
    if onu == "land" and not _nonblank(landing):
        raise ProfileInvalid("landing_required", f"{out!r}: on_unresolvable land needs a landing")
    if onu != "land" and landing is not None:
        raise ProfileInvalid("landing_refused", f"{out!r}: landing is for on_unresolvable land")
    source = {"field": fld, "row_field": rf, "absent_row": absent}
    return Column(output=out, source=source, format=fmt, on_unresolvable=onu, landing=landing,
                  transforms=tuple(transforms))


def validate(stem: str, raw: Any) -> Profile:
    """A `Profile`, or raises `ProfileInvalid(reason, detail)`."""
    if not isinstance(raw, dict):
        raise ProfileInvalid("not_a_mapping", "a profile is a YAML mapping")
    extra = set(raw) - _TOP_KEYS
    if extra:
        raise ProfileInvalid("unknown_key", f"header key(s) {sorted(extra)}")
    for k in sorted(_TOP_KEYS):
        if k not in raw:
            raise ProfileInvalid("missing_key", k)
    if raw["column_map_version"] != COLUMN_MAP_VERSION or isinstance(raw["column_map_version"], bool):
        raise ProfileInvalid("version_unsupported", f"column_map_version must be {COLUMN_MAP_VERSION}")
    name = raw["name"]
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ProfileInvalid("name_invalid", repr(name))
    if name != stem:
        raise ProfileInvalid("name_stem_mismatch", f"name {name!r} != file stem {stem!r}")
    if not _nonblank(raw["label"]):
        raise ProfileInvalid("label_blank", "")
    if raw["format"] not in FORMATS:
        raise ProfileInvalid("format_invalid", repr(raw["format"]))
    gran = raw["granularity"]
    if gran not in GRANULARITIES:
        raise ProfileInvalid("granularity_invalid", repr(gran))
    cols_raw = raw["columns"]
    if not isinstance(cols_raw, list) or not cols_raw:
        raise ProfileInvalid("columns_empty", "")
    cols = tuple(_column(c, gran) for c in cols_raw)
    seen: set = set()
    for c in cols:
        if c.output in seen:
            raise ProfileInvalid("output_duplicate", repr(c.output))
        seen.add(c.output)
    by_out = {c.output: c for c in cols}
    landings: dict = {}
    for c in cols:
        if c.landing is None:
            continue
        if c.landing not in by_out:
            raise ProfileInvalid("landing_undeclared", f"{c.output!r} lands in {c.landing!r}")
        if c.landing in landings:
            raise ProfileInvalid("landing_shared", f"{c.landing!r} by {landings[c.landing]!r} "
                                                   f"and {c.output!r}")
        if not by_out[c.landing].derived:
            raise ProfileInvalid("landing_not_derived", f"{c.landing!r} must be a derived column")
        landings[c.landing] = c.output
    for c in cols:
        if c.derived and c.output != NO_PARTS and c.output not in landings:
            raise ProfileInvalid("derived_column_unbound",
                                 f"{c.output!r} is neither no_parts nor any column's landing")
    return Profile(name=name, label=raw["label"].strip(), format=raw["format"], granularity=gran,
                   columns=cols)


# --------------------------------------------------------------------------------------
# The loader
# --------------------------------------------------------------------------------------

_DIR_ENV = "INGEST_EXPORT_PROFILE_DIR"
_CACHE: dict = {}


def _profile_dir() -> Path:
    """`INGEST_EXPORT_PROFILE_DIR`, else `<ancestor>/policy/exports` walking up from this file
    (as fin's loader finds its seed: the flattened image has no fixed depth), else
    `/app/policy/exports`."""
    env = os.getenv(_DIR_ENV)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "policy" / "exports"
        if candidate.is_dir():
            return candidate
    return Path("/app/policy/exports")


def load_profiles() -> dict:
    """`{name: Profile | ProfileInvalid}` for every `*.yaml` in the policy dir, cached per
    directory. A broken file never breaks the others (its key is the file stem)."""
    d = _profile_dir()
    key = str(d)
    if key in _CACHE:
        return _CACHE[key]
    out: dict = {}
    if d.is_dir():
        for p in sorted(d.glob("*.yaml")):
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
                out[p.stem] = ProfileInvalid("yaml_unreadable", type(exc).__name__)
                continue
            try:
                out[p.stem] = validate(p.stem, raw)
            except ProfileInvalid as exc:
                out[p.stem] = exc
    _CACHE[key] = out
    return out


def clear_cache() -> None:
    _CACHE.clear()


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------

def _iso_date(v: Any) -> bool:
    if not isinstance(v, str) or not _ISO_RE.fullmatch(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _transform(v: Any, transforms: tuple) -> Any:
    if not isinstance(v, str):
        return v
    for t in transforms:
        v = v.strip() if t == "trim" else v.upper() if t == "upper" else v.lower()
    return v


def _notice_value(extraction: dict, fld: str) -> Any:
    if fld.startswith("notice."):
        n = extraction.get("notice")
        return n.get(fld[len("notice."):]) if isinstance(n, dict) else None
    return extraction.get(fld)


def render_rows(profile: Profile, extraction: dict) -> list:
    """Pure. One output dict per row, keyed by column `output`, in column order."""
    ingest_id = extraction.get("ingest_id")
    rows = [r for r in (extraction.get("rows") or []) if isinstance(r, dict)]
    if profile.granularity == "notice":
        parts: list = [None]
    else:
        by_part: dict = {}
        for r in rows:
            by_part.setdefault(r.get("part_index"), []).append(r)
        parts = [(pi, by_part[pi]) for pi in sorted(by_part)] or [("no_parts", [])]
    out = []
    for part in parts:
        pi, prows = (None, []) if part is None else part
        no_parts = pi == "no_parts"
        if no_parts:
            pi = None
        cells: dict = {c.output: None for c in profile.columns}
        for c in profile.columns:
            if c.derived:
                continue
            fld, rf = c.source["field"], c.source["row_field"]
            if fld in NOTICE_FIELDS:
                v = _notice_value(extraction, fld)
            elif no_parts:
                v = None
            elif fld in ROW_UNSHARED:
                v = prows[0].get(fld) if prows else None
            else:
                sel = [r for r in prows if r.get("field") == rf]
                if not sel:
                    if c.source["absent_row"] == "block":
                        raise ExportBlocked("absent_row", notice=ingest_id, part=pi, column=c.output)
                    v = None
                elif len(sel) > 1:
                    raise ExportBlocked("row_ambiguous", notice=ingest_id, part=pi, column=c.output)
                else:
                    v = sel[0].get(fld)
            v = _transform(v, c.transforms)
            if c.format == "iso8601" and v is not None and v != "":
                if not _iso_date(v):
                    if c.on_unresolvable == "block":
                        raise ExportBlocked("date_unresolvable", notice=ingest_id, part=pi,
                                            column=c.output)
                    if c.on_unresolvable == "land":
                        cells[c.landing] = v
                    v = None
            elif c.format == "iso8601":
                v = None
            cells[c.output] = v
        if NO_PARTS in cells and any(c.output == NO_PARTS and c.derived for c in profile.columns):
            cells[NO_PARTS] = no_parts
        out.append(cells)
    return out


def _csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    return str(v)


def to_csv(columns: list, rows: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([_csv_cell(r.get(c)) for c in columns])
    return buf.getvalue()


def to_json(profile: Profile, rows: list, **extra: Any) -> dict:
    return {"profile": profile.name, "column_map_version": COLUMN_MAP_VERSION,
            "granularity": profile.granularity, "columns": profile.outputs, "rows": rows,
            **extra}
