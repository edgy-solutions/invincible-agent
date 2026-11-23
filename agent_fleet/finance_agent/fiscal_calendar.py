"""The fiscal calendar a deployment DECLARES for engine-fin.

The engine holds no calendar. A deployment declares its periods (their labels, their order, their
start and end dates, and the fiscal year, quarter and half each belongs to) as a file, and points
`FIN_CALENDAR_OVERLAY_DIRS` at the directory. With nothing declared the calendar is EMPTY and every
period is outside it: a read refuses `period_outside_calendar`, never an empty answer.

File shape (`*.yaml`, any number per directory, `os.pathsep`-separated directories). Exactly two
keys; an unknown key and a missing key are both refused:

    calendar_id: <non-empty string>
    periods:
      - {label: ..., start: 2025-10-01, end: 2025-10-31, fiscal_year: ..., quarter: ..., half: ...}

THE ORDER IS THE LIST ORDER. Each period has exactly those six keys; `start` and `end` are a YAML
date or an ISO `YYYY-MM-DD` string. Every failure RAISES `FiscalCalendarError` naming the file and
the reason, so the engine does not boot half a declaration.

Calendars are NAMED. Composition: several `calendar_id`s may be declared; a file with the same
`calendar_id` in a later directory replaces the earlier one WHOLE; the same `calendar_id` in two files
of ONE directory is refused. A contract names its calendar (`period.calendar`); a deployment with one
calendar declares one, and it is the default (`default_calendar`). With a dataset configured and no
calendar declared the engine is not ready (`asset_inputs.check_config`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

_ENV = "FIN_CALENDAR_OVERLAY_DIRS"
KIND = "fin_calendar"
_TOP_KEYS = ("calendar_id", "periods")
_PERIOD_KEYS = ("label", "start", "end", "fiscal_year", "quarter", "half")


class FiscalCalendarError(ValueError):
    """A declared fiscal calendar is invalid. Always names the file."""


@dataclass(frozen=True)
class PeriodRow:
    label: str
    start: date
    end: date
    fiscal_year: str
    quarter: str
    half: str


@dataclass(frozen=True)
class FiscalCalendar:
    calendar_id: str
    periods: tuple[PeriodRow, ...]
    source: str

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(p.label for p in self.periods)

    @property
    def order(self) -> dict[str, int]:
        return {p.label: i for i, p in enumerate(self.periods)}

    def row(self, label: str) -> PeriodRow:
        for p in self.periods:
            if p.label == label:
                return p
        raise KeyError(label)


_EMPTY = FiscalCalendar(calendar_id="", periods=(), source="")


def _overlay_dirs() -> list[Path]:
    return [Path(p) for p in os.getenv(_ENV, "").split(os.pathsep) if p]


def _date(f: Path, where: str, key: str, v: Any) -> date:
    if isinstance(v, str) and len(v) == 10:
        try:
            return date.fromisoformat(v)
        except ValueError:
            pass
    elif isinstance(v, date) and not isinstance(v, datetime):
        return v
    raise FiscalCalendarError(f"{f.name}: {where}: `{key}` must be a date (YYYY-MM-DD), got {v!r}")


def _contiguous(f: Path, kind: str, pairs: list[tuple[str, str]]) -> None:
    """Every value of `kind` occupies one run of the list."""
    closed: set[str] = set()
    prev = None
    for label, value in pairs:
        if value != prev:
            if value in closed:
                raise FiscalCalendarError(
                    f"{f.name}: the periods of {kind} {value!r} are not contiguous in the list "
                    f"(split at {label!r})")
            if prev is not None:
                closed.add(prev)
            prev = value


def _parse(f: Path) -> FiscalCalendar:
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise FiscalCalendarError(f"{f.name}: not valid YAML ({type(e).__name__})") from e
    if not isinstance(raw, dict) or set(raw) != set(_TOP_KEYS):
        raise FiscalCalendarError(
            f"{f.name}: the file must be a mapping with exactly the keys {list(_TOP_KEYS)}")
    cid = raw["calendar_id"]
    if not isinstance(cid, str) or not cid.strip():
        raise FiscalCalendarError(f"{f.name}: `calendar_id` must be a non-empty string")
    rows = raw["periods"]
    if not isinstance(rows, list) or not rows:
        raise FiscalCalendarError(f"{f.name}: `periods` must be a non-empty list")
    out: list[PeriodRow] = []
    seen: set[str] = set()
    for n, row in enumerate(rows):
        where = f"period {n}"
        if not isinstance(row, dict):
            raise FiscalCalendarError(f"{f.name}: {where}: a period is a mapping, got {type(row).__name__}")
        missing = [k for k in _PERIOD_KEYS if k not in row]
        if missing:
            raise FiscalCalendarError(f"{f.name}: {where}: missing required key(s) {missing}")
        extra = sorted(set(row) - set(_PERIOD_KEYS), key=str)
        if extra:
            raise FiscalCalendarError(
                f"{f.name}: {where}: unknown key(s) {extra}; the keys are {list(_PERIOD_KEYS)}")
        for k in ("label", "fiscal_year", "quarter", "half"):
            if not isinstance(row[k], str) or not row[k].strip():
                raise FiscalCalendarError(f"{f.name}: {where}: `{k}` must be a non-empty string")
        if row["label"] in seen:
            raise FiscalCalendarError(f"{f.name}: {where}: duplicate label {row['label']!r}")
        seen.add(row["label"])
        start, end = _date(f, where, "start", row["start"]), _date(f, where, "end", row["end"])
        if start > end:
            raise FiscalCalendarError(f"{f.name}: {where}: {row['label']!r} starts after it ends")
        out.append(PeriodRow(row["label"], start, end, row["fiscal_year"], row["quarter"], row["half"]))
    for a, b in zip(out, out[1:]):
        if b.start != a.end + timedelta(days=1):
            kind = "overlaps" if b.start <= a.end else "leaves a gap after"
            raise FiscalCalendarError(
                f"{f.name}: periods are not contiguous: {b.label!r} {kind} {a.label!r}; "
                "each period must start the day after the previous one ends")
    for kind in ("quarter", "half", "fiscal_year"):
        _contiguous(f, kind, [(p.label, getattr(p, kind)) for p in out])
    for kind, parents in (("quarter", ("half", "fiscal_year")), ("half", ("fiscal_year",))):
        for parent in parents:
            owner: dict[str, str] = {}
            for p in out:
                v = owner.setdefault(getattr(p, kind), getattr(p, parent))
                if v != getattr(p, parent):
                    raise FiscalCalendarError(
                        f"{f.name}: {kind} {getattr(p, kind)!r} spans two values of {parent} "
                        f"({v!r} and {getattr(p, parent)!r})")
    return FiscalCalendar(calendar_id=cid, periods=tuple(out), source=f.name)


def load_calendars(overlay_dirs: list[Path] | None = None) -> dict[str, FiscalCalendar]:
    """Every declared calendar, keyed by `calendar_id`. Unset, or no files, is `{}`."""
    dirs = overlay_dirs if overlay_dirs is not None else _overlay_dirs()
    out: dict[str, FiscalCalendar] = {}
    for d in dirs:
        here: dict[str, FiscalCalendar] = {}
        for f in sorted(Path(d).glob("*.yaml")):
            cal = _parse(f)
            if cal.calendar_id in here:
                raise FiscalCalendarError(
                    f"{here[cal.calendar_id].source} and {f.name} declare the same calendar_id "
                    f"{cal.calendar_id!r} in one directory; a calendar is declared once per directory")
            here[cal.calendar_id] = cal
        out.update(here)
    return out


_cache: dict[str, dict[str, FiscalCalendar]] = {}


def declared_calendars() -> dict[str, FiscalCalendar]:
    """The calendars the environment declares, cached by the env var's current value."""
    key = os.getenv(_ENV, "")
    if key not in _cache:
        _cache[key] = load_calendars()
    return _cache[key]


def default_calendar() -> FiscalCalendar:
    """The only declared calendar; EMPTY when none or several are declared."""
    cals = declared_calendars()
    return next(iter(cals.values())) if len(cals) == 1 else _EMPTY


def calendar_for(calendar_id: str | None) -> FiscalCalendar:
    """The calendar a contract names. None is the default, and only when exactly one is declared."""
    cals = declared_calendars()
    if calendar_id is None:
        if len(cals) == 1:
            return next(iter(cals.values()))
        if not cals:
            raise FiscalCalendarError(
                f"no fiscal calendar is declared ({_ENV}); a dataset reads its periods in a declared calendar")
        raise FiscalCalendarError(
            f"{len(cals)} fiscal calendars are declared ({sorted(cals)}) and the contract names none; "
            "a contract names one (`period.calendar`)")
    if calendar_id not in cals:
        raise FiscalCalendarError(
            f"fiscal calendar {calendar_id!r} is not declared; the declared calendars are {sorted(cals)}")
    return cals[calendar_id]
