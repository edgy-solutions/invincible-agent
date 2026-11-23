"""Earned-value series over periods, for a dataset row drawn as MULTI_SERIES. ADR-0053.

    cumulative:  PV(t) = sum BCWS(1..t),  EV(t) = sum BCWP(1..t),  AC(t) = sum ACWP(1..t),  BAC
    eac_trend:   EAC(t) = the EAC the program reported at t,  BAC

THE RUNNING SUM IS COMPUTED HERE, NOT STORED AND NOT DRAWN. The asset carries period amounts; a row
that declares `cumulative: true` on a series states what this module served, and a renderer that
summed again would double-count. It starts at the first period the asset holds for the program, so
a period with no rows is no point at all rather than a point of zero.

THE REPORTED EAC IS A STOCK. It is the estimate as stated at each period's status, already summed
over work packages by the reader; adding it across periods means nothing, so it is passed through.

PURE AND DECIMAL. `periods` is a list of mappings in period order: `period` and each keyword the
row names, as `Decimal`. The result is one mapping per period of exactly the series keys in
`SERIES`, each `Decimal`. `READS` names the keywords each function reads, and the loader holds the
row to it. Nothing is read or written, and nothing outside the standard library is imported.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

VERSION = "1.0.0"

#: The keywords each function reads from a period, and the series keys it returns.
READS = {"cumulative": frozenset({"bcws", "bcwp", "acwp", "bac"}),
         "eac_trend": frozenset({"eac", "bac"})}
SERIES = {"cumulative": ("pv", "ev", "ac", "bac"), "eac_trend": ("eac", "bac")}


def cumulative(*, periods: list[dict[str, Any]]) -> list[dict[str, Decimal]]:
    """Running PV, EV and AC from the first period given, and BAC beside them."""
    pv = ev = ac = Decimal(0)
    out: list[dict[str, Decimal]] = []
    for p in periods:
        pv += p["bcws"]
        ev += p["bcwp"]
        ac += p["acwp"]
        out.append({"pv": pv, "ev": ev, "ac": ac, "bac": p["bac"]})
    return out


def eac_trend(*, periods: list[dict[str, Any]]) -> list[dict[str, Decimal]]:
    """The reported EAC at each period, and BAC beside it."""
    return [{"eac": p["eac"], "bac": p["bac"]} for p in periods]
