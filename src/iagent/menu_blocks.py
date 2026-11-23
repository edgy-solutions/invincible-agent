"""The menu-block registry, keyed by VERB. Two sources, one row per menu placement:
`<overlay>/menu_blocks/<stem>.yaml`, and the `menu:` block of each declared measure row
(`MEASURE_VERB_OVERLAY_DIRS`, loaded by finance's `load_measure_verbs`; its verb is the one the
engine registers, `"mesh:" + verb`). Architect ruling 2026-11-22: "/menu_blocks is keyed by verb."

Architect ruling 2026-11-07: "the overlay row declares its menu placement, the BFF serves it,
cortex reads it." A row is exactly two top-level keys, `declared_by` and `menu`; `menu` holds
exactly `subject`, `archetype`, `persona_fit`, `domain_fit` (the same key set finance's
in-row `menu` block carries; a test keeps the two equal).

There is NO seed directory. `MENU_BLOCK_OVERLAY_DIRS` (os.pathsep-separated) says where to look:

* unset or empty -> `composed: False` ("nobody said where to look", which is not "no blocks");
* a listed dir that does not exist or cannot be listed -> `composed: False`;
* an existing empty dir -> `composed: True, blocks: []`;
* `MEASURE_VERB_OVERLAY_DIRS` set and readable also makes `composed: True`; unset, it is not a
  source; a measure load that raises makes `composed: False` with one invalid entry
  `{"source": "measure_verbs", "reason": "unreadable: <ExceptionType>"}`. A measure row with no
  `menu:` is not a placement (and not invalid).

A later dir's file with the same stem REPLACES an earlier one (as `review_shapes` composes).
A row that does not validate is an `invalid` entry naming the field, never an exception, so one
bad row cannot take `GET /menu_blocks` down. Distinct verbs may share (subject, archetype); all
are served, sorted by (subject, archetype, verb). A verb declared by two sources is BOTH left out
and both named invalid: the registry will not pick a winner.

The prefix check is the point of the CURIE rule: an unknown prefix passes verbatim elsewhere
and never matches, so a row with one would be served and silently dead. Keys of
`agent_fleet.utils.mesh_registration._IRI_PREFIXES` carry the colon ("mesh:").

PERSONA AND DOMAIN VOCABULARY IS NOT CHECKED HERE. `policy/personas.yaml` and
`policy/domains.yaml` are not in the BFF image, and `persona_fit` / `domain_fit` only RANK, they
never gate: a stale value mis-ranks and cannot widen access. The shipped rows are checked
against the vocabularies by the repo test (tests/test_menu_blocks_are_served.py).

Cached per the three env values (menu dirs, measure overlay dirs, measure seed dir);
`clear_cache()` drops it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_OVERLAY_ENV = "MENU_BLOCK_OVERLAY_DIRS"
_MEASURE_OVERLAY_ENV = "MEASURE_VERB_OVERLAY_DIRS"
_MEASURE_SEED_ENV = "MEASURE_VERB_POLICY_DIR"
_ROW_KEYS = frozenset({"declared_by", "menu"})
_MENU_KEYS = frozenset({"subject", "archetype", "persona_fit", "domain_fit"})
_CURIE_FIELDS = ("subject", "archetype")
_LIST_FIELDS = ("persona_fit", "domain_fit")
_CACHE: dict = {}
_ROWS_CACHE: dict = {}


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


def _measure_verb(row) -> str:
    """The verb the finance engine registers for a declared measure row: `"mesh:" + row.verb`
    (`agent_fleet/finance_agent/main.py`, the declared-row registration and `/verbs`). The join
    seal in tests/test_menu_blocks_are_keyed_by_verb.py keeps this honest."""
    return "mesh:" + row.verb


def _measure_rows() -> list:
    """The declared measure rows: ONE `load_measure_verbs()` per `_cache_key()`, shared by
    `compose` (placements) and `askable` (discovery). Raises whatever the loader raises; a
    failed load is not cached."""
    key = _cache_key()
    if key not in _ROWS_CACHE:
        from agent_fleet.finance_agent.measure_verbs import load_measure_verbs
        _ROWS_CACHE[key] = list(load_measure_verbs())
    return _ROWS_CACHE[key]


def _measure_blocks() -> dict[str, dict]:
    """`{source: {"block": {...}}}` for every declared measure row that carries a `menu:` block.
    Raises whatever the loader raises; `compose` turns that into an unreadable source."""
    out: dict[str, dict] = {}
    for r in _measure_rows():
        m = r.menu
        if m is None:
            continue
        out[f"measure_verbs/{r.measure_id}"] = {"block": {
            "subject": m["subject"], "archetype": m["archetype"],
            "persona_fit": list(m["persona_fit"]), "domain_fit": list(m["domain_fit"]),
            "declared_by": _measure_verb(r)}}
    return out


def _cache_key() -> tuple:
    return (os.getenv(_OVERLAY_ENV, ""), os.getenv(_MEASURE_OVERLAY_ENV, ""),
            os.getenv(_MEASURE_SEED_ENV, ""))


def compose() -> MenuBlocks:
    """The blocks, the invalid rows, and whether the registry was read at all. Never raises."""
    key = _cache_key()
    if key in _CACHE:
        return _CACHE[key]
    dirs = _overlay_dirs()
    measures = bool(os.getenv(_MEASURE_OVERLAY_ENV, ""))
    if not dirs and not measures:
        result = MenuBlocks(False)
    else:
        rows: dict[str, dict] = {}
        unreadable = False
        if dirs:
            prefixes = _prefixes()
            try:
                for d in dirs:
                    if not d.is_dir():
                        raise OSError(f"{d} is not a directory")
                    rows.update(_read_dir(d, prefixes))
            except OSError:
                unreadable = True
        if unreadable:
            result = MenuBlocks(False)
        else:
            try:
                if measures:
                    rows.update(_measure_blocks())
            except Exception as exc:  # the loader raises MeasureVerbError and others
                result = MenuBlocks(False, [], [
                    {"source": "measure_verbs", "reason": f"unreadable: {type(exc).__name__}"}])
                rows = None
            if rows is not None:
                invalid = [{"source": s, "reason": r["reason"]}
                           for s, r in rows.items() if "reason" in r]
                valid = {s: r["block"] for s, r in rows.items() if "block" in r}
                by_verb: dict[str, list[str]] = {}
                for s, b in valid.items():
                    by_verb.setdefault(b["declared_by"], []).append(s)
                blocks = []
                for s, b in valid.items():
                    others = [o for o in by_verb[b["declared_by"]] if o != s]
                    if others:
                        invalid.append({"source": s, "reason": (
                            f"ambiguous: {sorted(others)[0]} declares the same verb")})
                    else:
                        blocks.append(b)
                blocks.sort(key=lambda b: (b["subject"], b["archetype"], b["declared_by"]))
                invalid.sort(key=lambda i: i["source"])
                result = MenuBlocks(True, blocks, invalid)
    _CACHE[key] = result
    return result


def clear_cache() -> None:
    _CACHE.clear()
    _ROWS_CACHE.clear()


@dataclass(frozen=True)
class AskableMeasures:
    composed: bool
    measures: list = field(default_factory=list)
    invalid: list = field(default_factory=list)


def askable() -> AskableMeasures:
    """Every declared measure row (with or without a `menu:` block), sorted by verb, from the
    same cached load `compose` uses. `shape` is the row's `render.shape`; `unit` is its
    `render.unit` when the render block declares one, else None (never defaulted). Built-in
    measures (code, not declared rows) are not listed. Never raises. `composed: False` is
    "not read"."""
    if not os.getenv(_MEASURE_OVERLAY_ENV, ""):
        return AskableMeasures(False)
    try:
        rows = _measure_rows()
    except Exception as exc:
        return AskableMeasures(False, [], [
            {"source": "measure_verbs", "reason": f"unreadable: {type(exc).__name__}"}])
    measures = [{"verb": _measure_verb(r), "name": r.name, "description": r.description,
                 "phrasings": list(r.synonyms), "cells": sorted(r.cells),
                 "shape": r.archetype,
                 "unit": r.render.get("unit") if isinstance(r.render, dict) else None}
                for r in rows]
    measures.sort(key=lambda m: m["verb"])
    return AskableMeasures(True, measures, [])


def visible_to(measures: list, domains) -> list:
    """The entries whose declared cells the caller holds a domain in: the cell gate the
    measure's own engine refuses on. Both sides are upper-cased (cells also stripped) and
    compared as sets; no held domain sees nothing."""
    # rule: agent_fleet/finance_agent/main.py `_require_cell` / `_held_domains`
    held = {str(d).upper() for d in (domains or [])}
    return [m for m in measures
            if held & {str(c).strip().upper() for c in m["cells"]}]
