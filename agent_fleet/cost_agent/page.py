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
        "touch_per_unit": str((touch_hours / quantity).quantize(Decimal("0.01")))
                          if quantity else "n/a",
        "unit_price": _money(Decimal(unit)) if unit else "n/a",
        # `None` when there are no touch hours, rendered as "n/a" — NOT as 0.000, which would
        # claim a measured ratio of zero where the truth is that the denominator is absent.
        "support_touch_ratio": str(ratio) if ratio is not None else "n/a",
    }


def scenario_view(lot: int, rates_json: str, slope: str) -> dict[str, Any]:
    """The recipient's parameters, computed BESIDE the baseline. Never replacing it.

    Returns both prices and their difference in one payload, so a caller has no way to display
    the scenario alone. The baseline number is read from the manifest — the verified figure —
    rather than recomputed, so the comparison is always against what was actually asserted.

    THE SLOPE IS APPLIED TO TOUCH LABOUR ONLY, which is where a learning curve acts. Applying
    it to the whole base would be a different (and wrong) model, quietly.
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

    try:
        s = Decimal(str(slope))
    except Exception:
        s = Decimal("1")
    if not (Decimal("0.5") <= s <= Decimal("1")):
        s = Decimal("1")

    scenario = pricing.compose_price(
        direct_labor=pricing.quantize_money(touch_cost * s) + other_labor,
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
