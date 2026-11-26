"""The drill: the dataset rows a flow amount was computed from, opened from the amount.

A flow edge (and a sink member) carries `row_count` and, when the read's receipt has an as-of, an
opaque `drill` value. `fin_drill_rows` pages the rows the value names; `POST /drill_rows/download`
serves them as a file. This module is PURE over frames and values: it reads nothing, and every
rule that needs the engine (the caller, the read, the receipt) is `main`'s.

THE VALUE. `"fd1." + base64url(compact JSON, sorted keys, no padding)` of `{as_of, measure,
module_sha256, params, path, members}`. It names NO column, NO URN and NO caller: the engine
rebuilds the predicate from its own declaration of the row (`path[i]` is the value of
`levels[i + 1]`; `levels[0]` is the scope, which `params.program_id` fills), so the value is a
claim about what the engine served, checked on the way back and never trusted. `as_of` is a string
end to end (ruled 2026-11-23/24): it rides inside the value and is compared byte for byte.
`members` is set only on a sink edge: the drill is then the rows under those members, never "the
parent less what is shown". A value is accepted only in the one canonical encoding `encode` writes.
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import re
from decimal import Decimal
from typing import Any, Optional, Sequence

try:  # flat in the image (/app), packaged in the repo
    import measures as _measures
except ImportError:
    from agent_fleet.finance_agent import measures as _measures

DRILL_FN = "fin_drill_rows"
DOWNLOAD_ROUTE = "/drill_rows/download"
PREFIX = "fd1."
DRILL_PAGE_MAX = 500
#: The formats the drill declares, served in `downloads` (cortex has no button of its own).
DOWNLOADS = ({"label": "CSV", "format": "csv"},)
FORMATS = frozenset(d["format"] for d in DOWNLOADS)
PAGE_PARAMS = ("drill", "offset", "limit")
DOWNLOAD_PARAMS = ("drill", "format")
_KEYS = frozenset({"as_of", "measure", "module_sha256", "params", "path", "members"})
_NONE = "None"          # how a null level value reads in a path (`str(None)`), here and in the read
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class DrillInvalid(ValueError):
    """The value is not one this engine served: malformed, or not in the one canonical form."""


def _canonical(doc: dict[str, Any]) -> str:
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode(*, as_of: str, measure: str, module_sha256: str, params: dict[str, str],
           path: Sequence[str], members: Optional[Sequence[Sequence[str]]]) -> str:
    return _canonical({
        "as_of": as_of, "measure": measure, "module_sha256": module_sha256, "params": dict(params),
        "path": list(path), "members": None if members is None else [list(m) for m in members],
    })


def _strings(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def decode(value: Any) -> dict[str, Any]:
    """The value's document, or `DrillInvalid`. Exactly the six keys, each of its type, in the one
    canonical encoding (so a value with whitespace, padding or reordered keys is refused)."""
    try:
        if not isinstance(value, str) or not value.startswith(PREFIX):
            raise DrillInvalid
        body = value[len(PREFIX):]
        doc = json.loads(base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True))
        if not isinstance(doc, dict) or set(doc) != _KEYS:
            raise DrillInvalid
        params = doc["params"]
        ok = (isinstance(doc["as_of"], str) and doc["as_of"] != ""
              and isinstance(doc["measure"], str) and doc["measure"] != ""
              and isinstance(doc["module_sha256"], str)
              and isinstance(params, dict) and all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in params.items())
              and isinstance(params.get("program_id"), str) and params["program_id"] != ""
              and _strings(doc["path"])
              and (doc["members"] is None
                   or (isinstance(doc["members"], list) and all(_strings(m) for m in doc["members"]))))
        if not ok or _canonical(doc) != value:
            raise DrillInvalid
    except DrillInvalid:
        raise
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise DrillInvalid from None
    return doc


def check_depth(doc: dict[str, Any], levels: Sequence[str]) -> None:
    """`path` and every member are paths below the root: none longer than the levels below it, and a
    member is under `path`. Else `DrillInvalid`."""
    deepest = len(levels) - 1
    members = doc["members"]
    if len(doc["path"]) > deepest or any(len(m) > deepest or m[:len(doc["path"])] != doc["path"]
                                          for m in members or ()):
        raise DrillInvalid


# ── the rows under a path ───────────────────────────────────────────────────────────────────

def _key(column: str):
    """A level column as the text the read's paths hold: `str(v)`, a null as `None`."""
    import polars as pl
    return pl.col(column).cast(pl.String).fill_null(_NONE)


def prefix_counts(df: Any, levels: Sequence[str]) -> dict[tuple[str, ...], int]:
    """`{path prefix: rows under it}` over every prefix of every path the frame holds, the empty
    prefix (the root) counting them all. ONE PASS over the frame."""
    below = list(levels[1:])
    if not below:
        return {(): df.height}
    grouped = df.select([_key(c).alias(c) for c in below]).group_by(below).len()
    counts: dict[tuple[str, ...], int] = {}
    for *key, n in grouped.iter_rows():
        for k in range(len(key) + 1):
            prefix = tuple(key[:k])
            counts[prefix] = counts.get(prefix, 0) + n
    return counts


def annotate(edges: list[dict[str, Any]], df: Any, levels: Sequence[str], *,
             as_of: Optional[str], measure: str, module_sha256: str, params: dict[str, str]) -> None:
    """In place: `row_count` on every edge and every sink member, counted from `df` (the frame the
    amounts were reduced from), and a `drill` on each when `as_of` is a string. A sink edge counts,
    and drills, the rows under ITS MEMBERS (`path` is its parent's, `members` theirs); under
    `per_path: once` the count is still dataset rows, not groups."""
    counts = prefix_counts(df, levels)

    def drill(path: tuple[str, ...], members: Optional[list[tuple[str, ...]]]) -> dict[str, str]:
        if as_of is None:
            return {}
        return {"drill": encode(as_of=as_of, measure=measure, module_sha256=module_sha256,
                                params=params, path=path, members=members)}

    for edge in edges:
        path = tuple(edge["target"][1:])
        if "members" in edge:
            member_paths = [tuple(m["target"][1:]) for m in edge["members"]]
            for m, mp in zip(edge["members"], member_paths):
                m["row_count"] = counts.get(mp, 0)
                m.update(drill(mp, None))
            edge["row_count"] = sum(counts.get(mp, 0) for mp in member_paths)
            edge.update(drill(path[:-1], member_paths))
        else:
            edge["row_count"] = counts.get(path, 0)
            edge.update(drill(path, None))


def select(df: Any, levels: Sequence[str], path: Sequence[str],
           members: Optional[Sequence[Sequence[str]]]) -> Any:
    """The rows of `df` under `path`, or under any of `members` when they are given."""
    import polars as pl
    keys = [_key(c) for c in levels[1:]]
    prefixes = [list(path)] if members is None else [list(m) for m in members]
    cond = pl.lit(False)
    for prefix in prefixes:
        one = pl.lit(True)
        for i, v in enumerate(prefix):
            one = one & (keys[i] == v)
        cond = cond | one
    return df.filter(cond)


def ordered(df: Any, contract: Any) -> Any:
    """The rows in one order a person can page through: by the contract's grain columns, then by
    every remaining selected column (a list column excepted), stable."""
    import polars as pl
    key = [c for c in contract.key if c in df.columns]
    rest = [c for c in df.columns if c not in key
            and not isinstance(df.schema[c], (pl.List, pl.Array))]
    return df.sort([*key, *rest], maintain_order=True, nulls_last=True)


# ── the page and the file ───────────────────────────────────────────────────────────────────

def _numeric(contract: Any, columns: Sequence[str]) -> tuple[str, ...]:
    return tuple(c for c in columns if contract.types.get(c) in ("numeric", "float"))


def columns_of(df: Any, contract: Any) -> list[dict[str, str]]:
    """The contract columns the frame carries, in contract order. A contract declares no label or
    unit today, so `label` is the name and no `unit` is served."""
    return [{"name": c, "label": c} for c in df.columns]


def _cell(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_cell(x) for x in v]
    iso = getattr(v, "isoformat", None)
    return iso() if iso else str(v)


def rows_of(df: Any, contract: Any) -> list[dict[str, Any]]:
    """The frame's rows as JSON. A numeric value is `Decimal(str(x))` emitted by `_emit_money`: the
    cent-quantized float, and a `<name>_exact` string twin."""
    money = _numeric(contract, df.columns)
    rows = []
    for raw in df.iter_rows(named=True):
        row = {c: (Decimal(str(v)) if c in money and v is not None else _cell(v)) for c, v in raw.items()}
        _measures._emit_money([row], money_fields=money)
        rows.append(row)
    return rows


def filename(measure: str, program_id: str) -> str:
    return f"{_FILENAME_UNSAFE.sub('_', measure)}-{_FILENAME_UNSAFE.sub('_', program_id)}-rows.csv"


def _csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v)
    text = str(v) if not isinstance(v, bool) else str(v).lower()
    # a cell a spreadsheet would read as a formula is prefixed, so it is read as text
    return "'" + text if isinstance(v, str) and text.startswith(_FORMULA_LEADERS) else text


def _exact_cell(v: Any) -> str:
    """A money cell: its exact string as it is (a negative amount starts with `-` and is no formula)."""
    return "" if v is None else str(v)


def csv_bytes(df: Any, contract: Any) -> bytes:
    """The header row of column names, then every row: a money column as its EXACT string, a string
    cell that starts like a formula prefixed with `'`. UTF-8, CRLF row ends."""
    money = set(_numeric(contract, df.columns))
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(df.columns)
    for row in rows_of(df, contract):
        writer.writerow([_exact_cell(row.get(f"{c}_exact")) if c in money else _csv_cell(row[c])
                         for c in df.columns])
    return out.getvalue().encode("utf-8")
