"""The review-shape registry: `policy/review_shapes/<shape>.yaml`, one row per card.

A row is the SDK's `iagent_mesh.review_coverage.ReviewShapeRow` (architect ruling 2026-10-30:
the shape -> item_kind map and the per-shape rule lists are config, a platform seed plus an
overlay per deployment). The task's `review_shape` and a content kind's `review_shape` are the
same word and name a row here (Chris, 2026-10-30).

The seed directory is read first, then each overlay directory in order; an overlay row with the
same `review_shape` REPLACES the seed row (as `agent_fleet/utils/answer_exports.py` composes).
A row that does not parse or validate is a `ShapeInvalid` in the result, never an exception, so
one bad row cannot take `GET /review-shapes` down.

Cached per (seed, overlays) like `export_profiles`; `clear_cache()` drops it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import yaml
from iagent_mesh.review_coverage import ReviewShapeRow
from pydantic import ValidationError

_SEED_ENV = "REVIEW_SHAPE_POLICY_DIR"
_OVERLAY_ENV = "REVIEW_SHAPE_OVERLAY_DIRS"
_CACHE: dict = {}


@dataclass(frozen=True)
class ShapeInvalid:
    """A registry entry that could not be used, keyed by its file stem."""
    source: str
    reason: str

    def __str__(self) -> str:
        return f"{self.source}: {self.reason}"


def _seed_dir() -> Path:
    """`REVIEW_SHAPE_POLICY_DIR`, else `<ancestor>/policy/review_shapes` walking up from this
    file (the flattened image has no fixed depth), else `/app/policy/review_shapes`."""
    env = os.getenv(_SEED_ENV)
    if env:
        return Path(env)
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "policy" / "review_shapes"
        if candidate.is_dir():
            return candidate
    return Path("/app/policy/review_shapes")


def _overlay_dirs() -> list[Path]:
    return [Path(p) for p in os.getenv(_OVERLAY_ENV, "").split(os.pathsep) if p]


def _read_dir(d: Path) -> dict[str, Union[ReviewShapeRow, ShapeInvalid]]:
    out: dict[str, Union[ReviewShapeRow, ShapeInvalid]] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            out[p.stem] = ShapeInvalid(str(p), f"unreadable: {type(exc).__name__}")
            continue
        if not isinstance(raw, dict):
            out[p.stem] = ShapeInvalid(str(p), "a row is a mapping")
            continue
        try:
            row = ReviewShapeRow.model_validate(raw)
        except ValidationError as exc:
            out[p.stem] = ShapeInvalid(str(p), f"fails ReviewShapeRow: {exc.error_count()} error(s)")
            continue
        if row.review_shape != p.stem:
            out[p.stem] = ShapeInvalid(
                str(p), f"file stem {p.stem!r} must equal review_shape {row.review_shape!r}")
            continue
        out[row.review_shape] = row
    return out


def load_review_shapes() -> dict[str, Union[ReviewShapeRow, ShapeInvalid]]:
    """`{review_shape: ReviewShapeRow | ShapeInvalid}`: the seed, then each overlay dir in order.
    Never raises on a bad row."""
    seed, overlays = _seed_dir(), _overlay_dirs()
    key = (str(seed), tuple(str(o) for o in overlays))
    if key in _CACHE:
        return _CACHE[key]
    out = _read_dir(seed)
    for d in overlays:
        out.update(_read_dir(d))
    _CACHE[key] = out
    return out


def valid_review_shapes() -> dict[str, ReviewShapeRow]:
    return {k: v for k, v in load_review_shapes().items() if isinstance(v, ReviewShapeRow)}


def is_review_shape(name: str) -> bool:
    return name in valid_review_shapes()


def clear_cache() -> None:
    _CACHE.clear()
