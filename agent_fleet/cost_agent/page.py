"""What the package runs IN THE RECIPIENT'S BROWSER. Verification, aggregation, scenarios.

RUNS UNDER PYODIDE, so it imports `pricing` and the standard library and nothing else — no
engine state, no seed, no framework. It is a real module rather than a string inside the
builder so it can be imported and tested natively, which is the only way its arithmetic gets
checked before a customer runs it.

ALL AGGREGATION IS HERE, IN PYTHON. The JavaScript shell renders what this returns and
computes nothing — the renderer never sums. A ratio or a per-unit figure derived in JS would
be arithmetic outside the pinned modules, unverifiable by the manifest and invisible to every
seal, which is the whole failure the export exists to avoid.

THE BASELINE / SCENARIO SPLIT IS ENFORCED HERE, not in the UI. `labor_view` reads only figures
the engine produced and the manifest verified. `scenario_view` recomputes from the recipient's
parameters and returns BOTH numbers so the caller cannot render one without the other. A UI
bug could mislabel them; it cannot make the baseline disappear.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

try:
    import pricing
except ImportError:  # native/test path
    from agent_fleet.cost_agent import pricing

#: Set by `verify`, read by the view functions. Module-level because Pyodide calls these one
#: at a time from JS and there is no object to hold state in.
_PKG: dict[str, Any] = {}

LABOR_KINDS = ("touch", "support", "sepm")

#: The only fields a recipient may edit. See `scenario_view`.
EDITABLE_RATE_KEYS = ("fringe", "overhead", "g_and_a", "cost_of_money", "profit",
                      "escalation")


def _money(d: Decimal) -> str:
    """Group thousands for display. Presentation only — never re-rounds."""
    q = pricing.quantize_money(d)
    whole, _, frac = str(q).partition(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    grouped = "{:,}".format(int(whole))
    return ("-" if neg else "") + grouped + "." + (frac or "00")


def _rateset(r: dict[str, Any]) -> "pricing.RateSet":
    return pricing.RateSet(
        fiscal_year=r["fiscal_year"], vintage=r["vintage"],
        fringe=Decimal(r["fringe"]), overhead=Decimal(r["overhead"]),
        g_and_a=Decimal(r["g_and_a"]), cost_of_money=Decimal(r["cost_of_money"]),
        profit=Decimal(r["profit"]), escalation=Decimal(r["escalation"]))


def _spec(manifest: dict[str, Any]):
    return tuple(
        pricing.StepSpec(name=c["name"], rate_key=c["rate_key"], basis_kind=c["basis_kind"],
                         component=c["component"], plus_steps=tuple(c["plus_steps"]))
        for c in manifest["composition"])


def verify(package_json: str) -> list[str]:
    """Recompute every manifest check. Empty list means the package may render.

    Also stores the package for the view functions — so nothing can render without having
    been verified first, because the only path that populates `_PKG` is this one.
    """
    global _PKG
    _PKG = json.loads(package_json)
    m = _PKG["manifest"]
    spec = _spec(m)
    problems: list[str] = []
    for chk in m["checks"]:
        b = pricing.compose_price(
            direct_labor=Decimal(chk["inputs"]["direct_labor"]),
            material=Decimal(chk["inputs"]["material"]),
            other_direct=Decimal(chk["inputs"]["other_direct"]),
            rates=_rateset(chk["rates"]), spec=spec)
        if str(b.price) != chk["expected"]["price"]:
            problems.append(f"lot {chk['lot']}: price recomputed {b.price}, "
                            f"manifest expects {chk['expected']['price']}")
        for got, want in zip(b.steps, chk["intermediates"]):
            if str(got.amount) != want["amount"]:
                problems.append(
                    f"lot {chk['lot']} step {want['name']}: recomputed {got.amount}, "
                    f"manifest expects {want['amount']}")
    return problems


def _rows_for(lot: int, category: str) -> list[dict[str, Any]]:
    return [r for r in _PKG["dataset"]["rows"]["results"]
            if r["lot"] == lot and r["category"] == category]


def _check_for(lot: int) -> dict[str, Any]:
    for c in _PKG["manifest"]["checks"]:
        if c["lot"] == lot:
            return c
    raise KeyError(f"lot {lot} is not in this package")


def labor_view(lot: int) -> dict[str, Any]:
    """The Labor tab's figures for one lot. BASELINE ONLY — engine figures, manifest-verified.

    Every number here is derived from rows the engine produced; nothing is recomputed from
    recipient parameters, which is what makes it safe to label BASELINE on screen.
    """
    labor = {r["sub_config"]: r for r in _rows_for(lot, "labor")}
    quantity = next(l["quantity"] for l in _PKG["dataset"]["rows"]["lots"] if l["lot"] == lot)

    parts, total_hours, total_cost = [], Decimal("0"), Decimal("0")
    for kind in LABOR_KINDS:
        r = labor.get(kind)
        # A MISSING KIND RENDERS AS ZERO WITH ITS NAME PRESENT, never as a silently shorter
        # chart — a bar with two segments where three are expected reads as a data story
        # rather than as an absence.
        hours = Decimal(r["hours"]) if r and r["hours"] else Decimal("0")
        cost = Decimal(r["price"]) if r else Decimal("0")
        total_hours += hours
        total_cost += cost
        parts.append({"key": kind, "value": float(cost), "display": _money(cost)})

    touch_hours = Decimal(labor["touch"]["hours"]) if "touch" in labor else Decimal("0")
    support_hours = Decimal(labor["support"]["hours"]) if "support" in labor else Decimal("0")
    ratio = (support_hours / touch_hours).quantize(Decimal("0.001")) if touch_hours else None
    unit = next((r["price"] for r in _rows_for(lot, "unit_price")), None)

    return {
        "lot": lot,
        "parts": parts,
        "total_hours": _money(total_hours),
        "total_cost": _money(total_cost),
        "touch_per_unit": _money((touch_hours / quantity).quantize(Decimal("0.01")))
                          if quantity else "n/a",
        "unit_price": _money(Decimal(unit)) if unit else "n/a",
        # `None` when there are no touch hours, rendered as "n/a" — NOT as 0.000, which would
        # claim a measured ratio of zero where the truth is that the denominator is absent.
        "support_touch_ratio": str(ratio) if ratio is not None else "n/a",
    }


def _touch_factor(lot: int, slope: Decimal, base_slope: Decimal) -> Decimal:
    """How touch labour moves when the learning curve is re-run at a DIFFERENT slope.

    The baseline hours are already `T1 * N^b` with `b = ln(base_slope)/ln 2` — the engine
    applied the curve. So a scenario slope is not a multiplier on that result; it is a
    different exponent over the same cumulative quantity, and the factor is the ratio:

        N^b_scenario / N^b_baseline

    THE FIRST VERSION MULTIPLIED TOUCH COST BY THE SLOPE DIRECTLY. That made the field's label
    a lie (0.92 meant "keep 92% of touch labour", not "assume a 92% curve") and, because the
    page defaulted the field to the engine's own slope, an UNTOUCHED scenario came out
    $732,148.44 below the baseline sitting beside it. A package whose two headline numbers
    disagree before the customer touches anything teaches them to distrust the verified one.

    THE IDENTITY SHORT-CIRCUIT IS NOT LOAD-BEARING, and saying otherwise was a fabrication.
    I first wrote that `math.pow` "would return 0.9999999999999998" here — a plausible-sounding
    float complaint I never ran. A bite-check refused to go red without the short-circuit, and
    the measurement says why: at `slope == base_slope` the two `pow` calls are the SAME
    expression over the SAME inputs, so the ratio is `x/x` and IEEE-754 gives exactly 1.0
    (checked at n = 12, 26, 42, 66, 90). The branch is kept because it makes identity a
    property of this function rather than of the arithmetic underneath it — and because the
    reset path should not depend on a float argument at all — but it fixes nothing, and the
    seal that covers identity passes with or without it.
    """
    if slope == base_slope:
        return Decimal("1")
    import math

    n = float(next(l["cumulative_units"] for l in _PKG["dataset"]["rows"]["lots"]
                   if l["lot"] == lot))
    ratio = math.pow(n / 12.0, math.log(float(slope)) / math.log(2.0)) /             math.pow(n / 12.0, math.log(float(base_slope)) / math.log(2.0))
    return Decimal(str(ratio))


def composition_view(lot: int) -> list[dict[str, str]]:
    """The price build-up for one lot, FORMATTED HERE.

    The renderer used to print the manifest's raw strings straight into the table, so the
    composition read `6307210.00` two inches from a labour total reading `5,229,210.00` — two
    money formats on one screen, from one package. Formatting is presentation, and this module
    is where the package's presentation decisions live; putting it in JS would also put it
    outside every seal.

    THE VALUES ARE THE MANIFEST'S, UNCHANGED. `_money` groups and pads; it never re-rounds, so
    a formatted figure still string-compares to the verified one after `.replace(",", "")`.
    """
    return [
        {"name": s["name"],
         "rate": "" if s["rate"] is None else s["rate"],
         "basis": _money(Decimal(s["basis"])),
         "amount": _money(Decimal(s["amount"])),
         "running_total": _money(Decimal(s["running_total"]))}
        for s in _check_for(lot)["intermediates"]
    ]


def scenario_view(lot: int, rates_json: str, slope: str) -> dict[str, Any]:
    """The recipient's parameters, computed BESIDE the baseline. Never replacing it.

    Returns both prices and their difference in one payload, so a caller has no way to display
    the scenario alone. The baseline number is read from the manifest — the verified figure —
    rather than recomputed, so the comparison is always against what was actually asserted.

    THE SLOPE IS APPLIED TO TOUCH LABOUR ONLY, which is where a learning curve acts. Applying
    it to the whole base would be a different (and wrong) model, quietly. It re-runs the curve
    rather than scaling its output — see `_touch_factor` for why that distinction cost $732k.
    """
    chk = _check_for(lot)
    overrides = json.loads(rates_json)
    base_rates = dict(chk["rates"])
    for k, v in overrides.items():
        # EDITABLE KEYS ARE THE RATES, NOT THE LABELS. `chk["rates"]` also carries
        # `fiscal_year` and `vintage`, which name the rate set rather than multiply anything.
        # Accepting those as overrides let a recipient relabel a scenario as a vintage it was
        # not computed from — a provenance lie with no arithmetic tell, since the price would
        # not move. ADR-0048 §7's amendment permits editing disclosed NUMBERS; this keeps the
        # naming out of reach.
        if k in EDITABLE_RATE_KEYS and k in base_rates and str(v).strip():
            base_rates[k] = str(v)

    labor = {r["sub_config"]: r for r in _rows_for(lot, "labor")}
    touch_cost = Decimal(labor["touch"]["price"]) if "touch" in labor else Decimal("0")
    other_labor = Decimal(chk["inputs"]["direct_labor"]) - touch_cost

    # THE BASELINE'S OWN SLOPE IS THE IDENTITY POINT, and both the parse failure and the
    # out-of-range case fall back to IT rather than to 1. Falling back to 1 was a silent
    # divergence: it looks like "no adjustment" and is in fact "no learning at all".
    base_slope = Decimal(str(_PKG["dataset"]["learning_slope"]))
    try:
        s = Decimal(str(slope))
    except Exception:
        s = base_slope
    if not (Decimal("0.5") <= s <= Decimal("1")):
        s = base_slope

    scenario = pricing.compose_price(
        direct_labor=pricing.quantize_money(touch_cost * _touch_factor(lot, s, base_slope))
                     + other_labor,
        material=Decimal(chk["inputs"]["material"]),
        other_direct=Decimal(chk["inputs"]["other_direct"]),
        rates=_rateset(base_rates), spec=_spec(_PKG["manifest"]))

    quantity = next(l["quantity"] for l in _PKG["dataset"]["rows"]["lots"] if l["lot"] == lot)
    baseline_price = Decimal(chk["expected"]["price"])
    return {
        "lot": lot,
        "baseline_price": _money(baseline_price),
        "scenario_price": _money(scenario.price),
        "difference": _money(scenario.price - baseline_price),
        "scenario_unit_price": _money(pricing.unit_price(scenario, quantity)),
        "slope": str(s),
        # THE SCENARIO STATES WHICH RATE SET IT DEPARTED FROM. Same discipline as `verified`:
        # provenance belongs in the payload, not in the renderer's memory. It is also what
        # makes EDITABLE_RATE_KEYS load-bearing rather than merely defensive — without these
        # two fields in the output, a relabelled vintage would change nothing observable and
        # the fence would be guarding something no test could see.
        "rate_vintage": base_rates["vintage"],
        "rate_fiscal_year": base_rates["fiscal_year"],
        # Stated in the payload rather than inferred by the UI: this figure is the
        # recipient's, and nothing has verified it.
        "verified": False,
    }
