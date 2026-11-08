"""VAC, the variance at completion, EAC by the CPI method. ADR-0053.

    VAC = BAC - EAC,  with EAC = BAC / CPI  and  CPI = BCWP / ACWP,  so  VAC = BAC - BAC * ACWP / BCWP

An amount in the program's currency: the budget at completion less the estimate at completion.
Negative means the program is forecast to overrun its budget; positive, to underrun it.

UNDEFINED WHEN NO WORK IS PERFORMED. With `BCWP <= 0` the cost performance index has no value (the
denominator is zero, or negative earned value that means nothing), so there is no estimate to
subtract. Returning a number there is the defect; `None` is the answer, and the caller carries the
reason.

PURE AND DECIMAL. Inputs are `Decimal`, the output is `Decimal` or `None`, nothing is read or
written, and the module imports nothing outside the standard library (the measure-row loader
refuses a module that does). `VERSION` is the string the row must match and the string that travels
beside the figure under ADR-0053 section 5.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

VERSION = "1.0.0"


def vac_cpi(*, bac: Decimal, bcwp: Decimal, acwp: Decimal) -> Optional[Decimal]:
    """`bac - bac * acwp / bcwp`, or `None` when `bcwp <= 0`."""
    if bcwp <= 0:
        return None
    return bac - bac * acwp / bcwp
