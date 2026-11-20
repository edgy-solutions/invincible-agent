"""The menu-block registry: `<overlay>/menu_blocks/<stem>.yaml`, one row per menu placement.

Architect ruling 2026-11-07: "the overlay row declares its menu placement, the BFF serves it,
cortex reads it." A row is exactly two top-level keys, `declared_by` and `menu`; `menu` holds
exactly `subject`, `archetype`, `persona_fit`, `domain_fit` (the same key set finance's
in-row `menu` block carries; a test keeps the two equal).

There is NO seed directory. `MENU_BLOCK_OVERLAY_DIRS` (os.pathsep-separated) says where to look:

* unset or empty -> `composed: False` ("nobody said where to look", which is not "no blocks");
* a listed dir that does not exist or cannot be listed -> `composed: False`;
* an existing empty dir -> `composed: True, blocks: []`.

A later dir's file with the same stem REPLACES an earlier one (as `review_shapes` composes).
A row that does not validate is an `invalid` entry naming the field, never an exception, so one
bad row cannot take `GET /menu_blocks` down. Two valid rows with the same (subject, archetype)
are BOTH left out and both named invalid: the registry will not pick a winner.

The prefix check is the point of the CURIE rule: an unknown prefix passes verbatim elsewhere
and never matches, so a row with one would be served and silently dead. Keys of
`agent_fleet.utils.mesh_registration._IRI_PREFIXES` carry the colon ("mesh:").

PERSONA AND DOMAIN VOCABULARY IS NOT CHECKED HERE. `policy/personas.yaml` and
`policy/domains.yaml` are not in the BFF image, and `persona_fit` / `domain_fit` only RANK, they
never gate: a stale value mis-ranks and cannot widen access. The shipped rows are checked
against the vocabularies by the repo test (tests/test_menu_blocks_are_served.py).

Cached per overlay list; `clear_cache()` drops it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_OVERLAY_ENV = "MENU_BLOCK_OVERLAY_DIRS"
_ROW_KEYS = frozenset({"declared_by", "menu"})
_MENU_KEYS = frozenset({"subject", "archetype", "persona_fit", "domain_fit"})
_CURIE_FIELDS = ("subject", "archetype")
_LIST_FIELDS = ("persona_fit", "domain_fit")
_CACHE: dict = {}


@dataclass(frozen=True)
class MenuBlocks:
    composed: bool
    blocks: list = field(default_factory=list)
    invalid: list = field(default_factory=list)


def _prefixes() -> frozenset:
    from agent_fleet.utils.mesh_registration import _IRI_PREFIXES
    return frozenset(_IRI_PREFIXES)


def _overlay_dirs() -> list[Path]:
    return [Path(p) for p in os.getenv(_OVERLAY_ENV, "").split(os.pathsep) if p]


def _curie_problem(name: str, value, prefixes) -> str | None:
    if isinstance(value, str) and value:
        prefix, sep, local = value.partition(":")
        if sep and local and "/" not in local and "#" not in local and f"{prefix}:" in prefixes:
            return None
    return f"{name} must be a compact CURIE with a registered prefix"


def _problem(raw, prefixes) -> str | None:
    """The first reason a parsed row is unusable, or None."""
    if not isinstance(raw, dict):
        return "a row is a mapping"
    if set(raw) != _ROW_KEYS:
        return f"row keys are {sorted(raw)}; a row holds exactly {sorted(_ROW_KEYS)}"
    bad = _curie_problem("declared_by", raw["declared_by"], prefixes)
    if bad:
        return bad
    menu = raw["menu"]
    if not isinstance(menu, dict):
        return "menu must be a mapping"
    if set(menu) != _MENU_KEYS:
        return f"menu keys are {sorted(menu)}; menu holds exactly {sorted(_MENU_KEYS)}"
    for name in _CURIE_FIELDS:
        bad = _curie_problem(name, menu[name], prefixes)
        if bad:
            return bad
    for name in _LIST_FIELDS:
        v = menu[name]
        if not (isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)):
            return f"{name} must be a non-empty list of non-empty strings"
    return None


def _read_dir(d: Path, prefixes) -> dict[str, dict]:
    """`{stem: {"block": {...}} | {"reason": str}}`. Raises OSError if the dir cannot be listed."""
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.yaml")):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            out[p.stem] = {"reason": f"unreadable: {type(exc).__name__}"}
            continue
        why = _problem(raw, prefixes)
        if why:
            out[p.stem] = {"reason": why}
            continue
        m = raw["menu"]
        out[p.stem] = {"block": {
            "subject": m["subject"], "archetype": m["archetype"],
            "persona_fit": list(m["persona_fit"]), "domain_fit": list(m["domain_fit"]),
            "declared_by": raw["declared_by"]}}
    return out


def compose() -> MenuBlocks:
    """The blocks, the invalid rows, and whether the registry was read at all. Never raises."""
    dirs = _overlay_dirs()
    key = tuple(str(d) for d in dirs)
    if key in _CACHE:
        return _CACHE[key]
    if not dirs:
        result = MenuBlocks(False)
    else:
        prefixes = _prefixes()
        rows: dict[str, dict] = {}
        try:
            for d in dirs:
                if not d.is_dir():
                    raise OSError(f"{d} is not a directory")
                rows.update(_read_dir(d, prefixes))
        except OSError:
            rows = None
        if rows is None:
            result = MenuBlocks(False)
        else:
            invalid = [{"source": s, "reason": r["reason"]} for s, r in rows.items() if "reason" in r]
            valid = {s: r["block"] for s, r in rows.items() if "block" in r}
            by_pair: dict[tuple, list[str]] = {}
            for s, b in valid.items():
                by_pair.setdefault((b["subject"], b["archetype"]), []).append(s)
            blocks = []
            for s, b in valid.items():
                others = [o for o in by_pair[(b["subject"], b["archetype"])] if o != s]
                if others:
                    invalid.append({"source": s, "reason": (
                        f"ambiguous: {sorted(others)[0]} declares the same subject and archetype")})
                else:
                    blocks.append(b)
            blocks.sort(key=lambda b: (b["subject"], b["archetype"]))
            invalid.sort(key=lambda i: i["source"])
            result = MenuBlocks(True, blocks, invalid)
    _CACHE[key] = result
    return result


def clear_cache() -> None:
    _CACHE.clear()
