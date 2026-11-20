"""Which tables the BFF's `/electric/shape` proxy serves (ADR-0068 s8; policy rows).

`policy/electric_shapes.yaml` is an ALLOW-LIST. A table is streamed to a browser only if a row names
it, byte for byte. Everything else is a policy refusal naming this family. Tasks are not on the list:
a task reaches a person through `GET /me/queue` and `GET /me/needs_you`, where the label rule can be
evaluated; a shape's WHERE cannot evaluate it.

DENY BY DEFAULT. No file, an empty list, or no row for the table serves nothing. A file that exists
and cannot be read raises `ElectricShapesUnreadable`: the caller answers 503, never "serve it".
The file is read on every call (a deployment's own file, mounted at the path, applies at once).

A row is permission to stream, never a filter: the per-caller WHERE is the proxy's, and a listed
table the proxy has no server-side filter for is refused too, so a row cannot open an unfiltered shape.

NO TABLE IS NAMED HERE. Every value is a row a deployment supplies.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

ELECTRIC_SHAPES_FILE_ENV = "ELECTRIC_SHAPES_FILE"
DEFAULT_PATH = "/app/policy/electric_shapes.yaml"
#: The policy family a refusal names (`policy/grantors/electric_shapes.yaml`).
POLICY_FAMILY = "electric_shapes"


class ElectricShapesUnreadable(RuntimeError):
    """The allow-list exists and could not be read or is not the declared shape."""


def _path() -> Path:
    return Path(os.getenv(ELECTRIC_SHAPES_FILE_ENV, DEFAULT_PATH))


def load_rows() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ElectricShapesUnreadable(type(exc).__name__) from exc
    if raw is None:
        return []
    rows = raw.get(POLICY_FAMILY) if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ElectricShapesUnreadable("not the declared shape")
    return rows


def allowed_row(table: str) -> Optional[dict]:
    """The row that lets `table` be streamed, or None. EXACT match: no case folding, no trimming,
    no schema prefix, no quoting -- a name that is not the listed one is a different name."""
    if not isinstance(table, str) or not table:
        return None
    for row in load_rows():
        if row.get("table") == table:
            return row
    return None
