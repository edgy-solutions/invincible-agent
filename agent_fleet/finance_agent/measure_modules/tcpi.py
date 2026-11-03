"""TCPI, the to-complete performance index (BAC form). ADR-0053.

    TCPI = (BAC - BCWP) / (BAC - ACWP)

The efficiency the REMAINING work must achieve for the program to finish on its budget at
completion. Above 1.00 the rest must be done more efficiently than budgeted; below 1.00, less.

UNDEFINED WHEN THE BUDGET IS SPENT. With `BAC - ACWP <= 0` no efficiency completes the work within
the budget: the denominator is zero (a division) or negative (a ratio that reads as a small
efficiency and means the opposite). Returning a number there is the defect; `None` is the answer,
and the caller carries the reason.

PURE AND DECIMAL. Inputs are `Decimal`, the output is `Decimal` or `None`, nothing is read or
written, and the module imports nothing outside the standard library (the measure-row loader
refuses a module that does). `VERSION` is the string the row must match and the string that travels
beside the figure under ADR-0053 section 5.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

VERSION = "1.0.0"


def tcpi_bac(*, bac: Decimal, bcwp: Decimal, acwp: Decimal) -> Optional[Decimal]:
    """`(bac - bcwp) / (bac - acwp)`, or `None` when `bac - acwp <= 0`."""
    remaining_budget = bac - acwp
    if remaining_budget <= 0:
        return None
    return (bac - bcwp) / remaining_budget
