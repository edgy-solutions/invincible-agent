"""Who may read another person's task queue, and until when (ADR-0068 s5, s6; policy rows).

`policy/queue_delegates.yaml` is a person-to-person rail. It is not `policy/gateway_delegates.yaml`,
which this does not reuse: that file lets a SERVICE name a person on a route, carries no expiry,
and its rows grant no read; a queue delegation is a PERSON handing a person a bounded view of
their queue, and an unbounded one is the thing ADR-0068 s5 refuses ("an expiry, which is
required").

DENY BY DEFAULT. No file, an empty list, no row for the pair, or a row whose `expires_at` has
passed grants nothing. An expired row is not deleted by this reader; it simply stops counting. A
file that exists and cannot be read raises `QueueDelegatesUnreadable`: the caller answers 503,
never "no delegation" (unknown is not none).

The clock is the caller's: `live_row(..., now=...)` takes the reading it used, and the audit line
records it, so a decision can be replayed.

NO PERSON, KIND OR AUDIENCE IS NAMED HERE. Every value is a row a deployment supplies.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any, Optional

import yaml

QUEUE_DELEGATES_FILE_ENV = "QUEUE_DELEGATES_FILE"
DEFAULT_PATH = "/app/policy/queue_delegates.yaml"
#: The policy family a refusal names (`policy/grantors/queue_delegates.yaml`).
POLICY_FAMILY = "queue_delegates"


class QueueDelegatesUnreadable(RuntimeError):
    """The queue-delegates file exists and could not be read or is not the declared shape."""


def _path() -> Path:
    return Path(os.getenv(QUEUE_DELEGATES_FILE_ENV, DEFAULT_PATH))


def parse_expiry(value: Any) -> Optional[_dt.datetime]:
    """An aware UTC datetime from a row's `expires_at`, or None when it is not one. A naive time
    is refused (None): an expiry with no zone has no clock to be evaluated on."""
    if isinstance(value, _dt.datetime):
        d = value
    elif isinstance(value, str) and value.strip():
        try:
            d = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return d.astimezone(_dt.timezone.utc) if d.tzinfo is not None else None


def load_rows() -> list[dict]:
    """Every row of the file, read on every call (a change applies at once where a deployment
    mounts its own file). Absent file or an empty list: `[]`."""
    p = _path()
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise QueueDelegatesUnreadable(type(exc).__name__) from exc
    if raw is None:
        return []
    rows = raw.get(POLICY_FAMILY) if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise QueueDelegatesUnreadable("not the declared shape")
    return rows


def _row_for(delegator: str, delegate: str) -> Optional[dict]:
    d, e = (delegator or "").strip().casefold(), (delegate or "").strip().casefold()
    if not d or not e:
        return None
    for row in load_rows():
        if (str(row.get("delegator", "")).strip().casefold() == d
                and str(row.get("delegate", "")).strip().casefold() == e):
            return row
    return None


def live_row(delegator: str, delegate: str, *,
             now: Optional[_dt.datetime] = None) -> "tuple[Optional[dict], str]":
    """`(row, why)`: the row that lets `delegate` read `delegator`'s queue at `now`, else
    `(None, why)` with `why` in `absent` or `expired`. A row whose expiry is missing or not an
    aware time is `expired`: no readable expiry is no grant."""
    row = _row_for(delegator, delegate)
    if row is None:
        return None, "absent"
    at = now or _dt.datetime.now(_dt.timezone.utc)
    expiry = parse_expiry(row.get("expires_at"))
    if expiry is None or expiry <= at:
        return None, "expired"
    return row, "live"


def in_scope(row: dict, task: dict) -> bool:
    """True iff the row's scope covers the task: its kind is in `kinds`, or its audience is in
    `audiences`. A row naming neither covers nothing."""
    scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
    kinds = {str(k) for k in (scope.get("kinds") or [])}
    audiences = {str(a) for a in (scope.get("audiences") or [])}
    return str(task.get("kind")) in kinds or str(task.get("audience")) in audiences


def scope_filters(row: dict) -> "tuple[list[str], list[str]]":
    """`(kinds, audiences)` of a row, as lists."""
    scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
    return ([str(k) for k in (scope.get("kinds") or [])],
            [str(a) for a in (scope.get("audiences") or [])])
