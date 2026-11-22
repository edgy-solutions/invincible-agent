"""Instances a deployment DECLARES for engine-fin's `mesh:resolveInstance` provider.

The provider knows the notional seed and nothing else. A deployment that wants a question to name
an instance the seed does not hold (a sandbox's planted refusal programs, say) declares it as a
ROW, in a file, and points `FIN_INSTANCE_OVERLAY_DIRS` at the directory. Adding one needs no code
change: the row's `class` selects the collection, there is no branch on a class or an id.

File shape (`*.yaml`, any number per directory, colon-separated directories):

    instances:
      - class: Program            # local name of a class the engine resolves
        instance_id: ...
        label: ...
        granted_by: ...
        ratified_by: ...
        reason: ...

Every key is required and an unknown key is refused. Every refusal RAISES `InstanceOverlayError`
naming the file and the reason, so the engine does not boot half a declaration.

The seed's own rule is kept, against the seed AND within the overlay: the resolver scores an exact
id or label match 1.0 across every class and the router abstains on a cross-class tie, so an
`instance_id` or `label` equal (case-insensitively) to another entity's id or label is refused.
An overlay instance is never added to the engine's state or to any figure; it is a name the
resolver can answer and nothing more.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

_ENV = "FIN_INSTANCE_OVERLAY_DIRS"
_KEYS = ("class", "instance_id", "label", "granted_by", "ratified_by", "reason")


class InstanceOverlayError(ValueError):
    """A declared instance row is invalid. Always names the file."""


@dataclass(frozen=True)
class InstanceRow:
    class_uri: str
    instance_id: str
    label: str
    granted_by: str
    ratified_by: str
    reason: str


def FIN_INSTANCE_OVERLAY_DIRS() -> list[Path]:  # noqa: N802 -- named like the loaders it parallels
    return [Path(p) for p in os.getenv(_ENV, "").split(os.pathsep) if p]


def load_instances(
    classes: Mapping[str, str],
    seed_names: Iterable[str] = (),
    overlay_dirs: list[Path] | None = None,
) -> tuple[InstanceRow, ...]:
    """Every declared instance, validated, sorted by (class, id). Unset is the empty tuple.

    `classes` maps the local class name a row may carry to the class URI it selects (the engine
    passes what it resolves). `seed_names` is every id and label the seed holds; a row naming one
    of them is refused.
    """
    dirs = overlay_dirs if overlay_dirs is not None else FIN_INSTANCE_OVERLAY_DIRS()
    taken: dict[str, str] = {str(n).lower(): "the seed" for n in seed_names}
    seen: dict[tuple[str, str], str] = {}
    out: list[InstanceRow] = []
    for d in dirs:
        for f in sorted(Path(d).glob("*.yaml")):
            raw = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or set(raw) != {"instances"} or not isinstance(raw["instances"], list):
                raise InstanceOverlayError(f"{f.name}: the file must be a mapping with the single key `instances`, a list of rows")
            for n, row in enumerate(raw["instances"]):
                out.append(_build(f, n, row, classes, taken, seen))
    return tuple(sorted(out, key=lambda r: (r.class_uri, r.instance_id)))


def _build(f: Path, n: int, row: Any, classes: Mapping[str, str], taken: dict[str, str],
           seen: dict[tuple[str, str], str]) -> InstanceRow:
    where = f"{f.name} row {n}"
    if not isinstance(row, dict):
        raise InstanceOverlayError(f"{where}: a row is a mapping, got {type(row).__name__}")
    missing = [k for k in _KEYS if k not in row]
    if missing:
        raise InstanceOverlayError(f"{where}: missing required key(s) {missing}")
    extra = sorted(set(row) - set(_KEYS), key=str)
    if extra:
        raise InstanceOverlayError(f"{where}: unknown key(s) {extra}; the keys are {list(_KEYS)}")
    for k in _KEYS:
        if not isinstance(row[k], str) or not row[k].strip():
            raise InstanceOverlayError(f"{where}: `{k}` must be a non-empty string")
    if row["class"] not in classes:
        raise InstanceOverlayError(
            f"{where}: unknown class {row['class']!r}; the engine resolves {sorted(classes)}")
    uri, iid, label = classes[row["class"]], row["instance_id"], row["label"]
    key = (uri, iid)
    if key in seen:
        raise InstanceOverlayError(f"{where}: ({row['class']}, {iid!r}) is already declared in {seen[key]}")
    seen[key] = f.name
    mine = {iid.lower(), label.lower()}
    for token in sorted(mine):
        owner = taken.get(token)
        if owner is not None:
            raise InstanceOverlayError(
                f"{where}: {token!r} collides case-insensitively with an id or label held by {owner}; "
                "the resolver scores an exact match 1.0 across classes and the router abstains on a tie")
    for token in mine:
        taken[token] = f"{f.name} row {n}"
    return InstanceRow(uri, iid, label, row["granted_by"], row["ratified_by"], row["reason"])
