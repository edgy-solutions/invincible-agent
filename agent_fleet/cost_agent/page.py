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


def _cum(units: int, slope: Decimal) -> float:
    """Cumulative touch hours to `units`, in U1-relative terms — Wright's law integrated.

    Mirrors `seed._cum_hours`. `U1` cancels in every ratio taken here, so it is left out.
    """
    import math

    if units <= 0:
        return 0.0
    b = math.log(float(slope)) / math.log(2.0) + 1.0
    return math.pow(units, b) / b


def _touch_factor(lot: int, slope: Decimal, base_slope: Decimal) -> Decimal:
    """How touch labor moves when the learning curve is re-run at a DIFFERENT slope.

    The baseline hours are already `T1 * N^b` with `b = ln(base_slope)/ln 2` — the engine
    applied the curve. So a scenario slope is not a multiplier on that result; it is a
    different exponent over the same cumulative quantity, and the factor is the ratio:

        N^b_scenario / N^b_baseline

    THE FIRST VERSION MULTIPLIED TOUCH COST BY THE SLOPE DIRECTLY. That made the field's label
    a lie (0.92 meant "keep 92% of touch labor", not "assume a 92% curve") and, because the
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
    meta = _lot_meta(lot)
    cum, prev = meta["cumulative_units"], meta["cumulative_units"] - meta["quantity"]
    base = _cum(cum, base_slope) - _cum(prev, base_slope)
    if base == 0:
        return Decimal("1")
    return Decimal(str((_cum(cum, slope) - _cum(prev, slope)) / base))


def composition_view(lot: int) -> list[dict[str, str]]:
    """The price build-up for one lot, FORMATTED HERE.

    The renderer used to print the manifest's raw strings straight into the table, so the
    composition read `6307210.00` two inches from a labor total reading `5,229,210.00` — two
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

    THE SLOPE IS APPLIED TO TOUCH LABOR ONLY, which is where a learning curve acts. Applying
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

# ═══════════════════════════════════════════════════════════════════════════════════════════
# THE ACROSS-LOTS HALF. `labor_view` answers "what is this lot"; these answer "what is the
# program". Same rows, same formatter, same rule — the arithmetic is here and the renderer
# only draws.
# ═══════════════════════════════════════════════════════════════════════════════════════════


def _lot_meta(lot: int) -> dict[str, Any]:
    return next(l for l in _PKG["dataset"]["rows"]["lots"] if l["lot"] == lot)


def program_view() -> dict[str, Any]:
    """Hours by lot x category, for the stacked column chart.

    `max_hours` is returned rather than left to the renderer: the bar heights are a ratio to
    the tallest column, and a ratio is arithmetic. A renderer computing its own maximum could
    silently rescale one chart against another and the seals would never see it.
    """
    series = []
    for lot in _PKG["lots"]:
        labor = {r["sub_config"]: r for r in _rows_for(lot, "labor")}
        segs, total = [], Decimal("0")
        for kind in LABOR_KINDS:
            r = labor.get(kind)
            hours = Decimal(r["hours"]) if r and r["hours"] else Decimal("0")
            total += hours
            segs.append({"key": kind, "value": float(hours), "display": _money(hours)})
        meta = _lot_meta(lot)
        series.append({
            "lot": lot,
            "quantity": meta["quantity"],
            "cumulative_units": meta["cumulative_units"],
            "segments": segs,
            "total": float(total),
            "total_display": _money(total),
        })
    return {
        "kinds": list(LABOR_KINDS),
        "series": series,
        "max_hours": max((s["total"] for s in series), default=0.0),
    }


def _lot_midpoint(avg_unit_hours: float, slope: Decimal) -> float:
    """The cumulative unit whose own cost equals this lot's average — the algebraic midpoint."""
    import math

    u1 = float(_PKG["dataset"]["unit1_hours"])
    b = math.log(float(slope)) / math.log(2.0)
    return math.pow(avg_unit_hours / u1, 1.0 / b)


def learning_curve_view(slope: str | None = None) -> dict[str, Any]:
    """Touch hours per unit against cumulative quantity — the curve, plotted.

    PLOTTED AT THE ALGEBRAIC LOT MIDPOINT, which is what makes the picture agree with the
    label. A lot's figure is an AVERAGE over a range of units, so its honest x is the
    cumulative unit whose individual cost equals that average — `N* = (avg/U1)^(1/b)` — not the
    arithmetic middle of the range. Using the arithmetic midpoint put the points on a line
    implying a 0.9120 slope beside a label reading 0.92: small, wrong, and exactly the kind of
    discrepancy a reader with a calculator finds first.

    THE BASELINE SERIES IS ENGINE OUTPUT, not a fitted line. It is `touch_hours / quantity`
    read off the rows the engine produced, so a curve that does not look like a curve is a
    finding about the engine rather than about the plot.

    The scenario series, when a slope is supplied, is the SAME points scaled by `_touch_factor`
    — which is exactly what the scenario panel does to touch cost. Drawing it any other way
    would put a second model on the page, and the chart would stop being a picture of the
    number beside it.
    """
    base_slope = Decimal(str(_PKG["dataset"]["learning_slope"]))
    baseline, scenario = [], []
    s = None
    if slope is not None:
        try:
            cand = Decimal(str(slope))
            s = cand if Decimal("0.5") <= cand <= Decimal("1") else base_slope
        except Exception:
            s = base_slope

    for lot in _PKG["lots"]:
        labor = {r["sub_config"]: r for r in _rows_for(lot, "labor")}
        if "touch" not in labor or not labor["touch"]["hours"]:
            continue
        meta = _lot_meta(lot)
        per_unit = (Decimal(labor["touch"]["hours"]) / meta["quantity"])
        pt = {"lot": lot, "x": _lot_midpoint(float(per_unit), base_slope),
              "cumulative_units": meta["cumulative_units"], "y": float(per_unit),
              "display": _money(per_unit.quantize(Decimal("0.01")))}
        baseline.append(pt)
        if s is not None:
            adj = per_unit * _touch_factor(lot, s, base_slope)
            scenario.append({"lot": lot, "x": pt["x"],
                             "cumulative_units": meta["cumulative_units"], "y": float(adj),
                             "display": _money(adj.quantize(Decimal("0.01")))})

    ys = [p["y"] for p in baseline] + [p["y"] for p in scenario]
    return {
        "baseline": baseline,
        "scenario": scenario,
        "scenario_slope": str(s) if s is not None else None,
        # STATED, NOT INFERRED. At the engine's own slope the two series coincide exactly, and
        # a reader seeing one line where they expected two deserves to be told why.
        "scenario_is_baseline": s is not None and s == base_slope,
        "base_slope": str(base_slope),
        "y_max": max(ys) if ys else 0.0,
        "y_min": min(ys) if ys else 0.0,
        "x_max": max((p["x"] for p in baseline), default=0),
    }


def curve_factor(lot: int) -> dict[str, str]:
    """What the BASELINE's own learning curve did at this lot — the missing label.

    The baseline table showed no slope at all, so a reader could not tell whether the engine
    applied a curve. It does: hours are `T1 * (N/12)^b`. At lot 1, N is 12 and the factor is
    exactly 1 — the curve is present and its effect is nil, which is a different statement from
    "no curve", and the page should make the difference readable.
    """
    base_slope = Decimal(str(_PKG["dataset"]["learning_slope"]))
    n = _lot_meta(lot)["cumulative_units"]
    first = _lot_meta(_PKG["lots"][0])["cumulative_units"]
    if n == first:
        factor, note = Decimal("1"), "no effect at this lot - it is the curve's reference point"
    else:
        import math

        factor = Decimal(str(math.pow(n / float(first),
                                      math.log(float(base_slope)) / math.log(2.0))))
        note = f"{(1 - factor) * 100:.1f}% below the reference lot"
    return {
        "slope": str(base_slope),
        "cumulative_units": str(n),
        "factor": str(factor.quantize(Decimal("0.0001"))),
        "note": note,
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════
# THE ALGORITHM PANEL. "Can I see the arithmetic" answered on the page, not in devtools.
# ═══════════════════════════════════════════════════════════════════════════════════════════


def algorithm_source() -> dict[str, Any]:
    """The pricing module, READ BACK FROM THE FILESYSTEM THE INTERPRETER EXECUTED FROM.

    Not the `<script>` tag, and not a second copy passed in from JS — `open("pricing.py")` is
    the same path `import pricing` resolved. A panel showing a copy could show something the
    interpreter never ran and every check would still agree with itself.

    The hash is computed HERE, on open, over that same text. So the number beside the source is
    a measurement of the source, not a value carried alongside it.

    NOTE ON WHICH HASH THIS IS. The header's `locator` is the content hash of the PACKAGE BODY
    — the manifest, the lots, the dataset — and it does not cover this file's text at all.
    Restating the locator beside the source as though it verified the source would be a false
    claim on the face of the artifact. `manifest.modules` is the one that does.
    """
    import hashlib

    with open("pricing.py", encoding="utf-8") as fh:
        src = fh.read()
    digest = "sha256:" + hashlib.sha256(src.encode("utf-8")).hexdigest()
    expected = _PKG["manifest"].get("modules", {}).get("pricing.py")
    return {
        "source": src,
        "sha256": digest,
        "expected_sha256": expected,
        "matches": expected is not None and digest == expected,
        "line_count": len(src.splitlines()),
        "algorithm_sha": _PKG["algorithm_sha"],
    }


def step_lines() -> dict[str, Any]:
    """Where each composition step is DEFINED, and where every step is EVALUATED.

    HONEST ABOUT WHAT IT CAN POINT AT. There is no per-step code to jump to: the steps are
    data, and one loop applies all of them. Linking "Overhead" to a line implying that line
    computes overhead — and only overhead — would misdescribe the design in the very panel
    built to make the design readable.

    So each step points at its own DECLARATION, and the panel says plainly that the arithmetic
    for every row is the shared evaluator, pointing there too.
    """
    src = algorithm_source()["source"].splitlines()
    steps: dict[str, int] = {}
    for c in _PKG["manifest"]["composition"]:
        # MATCH THE STEP'S NAME AS A STRING LITERAL, however it is passed. The first attempt
        # looked for `name="Fringe"` and found nothing at all: the declarations use positional
        # arguments, `StepSpec("Fringe", "fringe", ...)`. It failed loudly only because this
        # function reports what it could NOT resolve — a linker that silently produced no
        # links would have shipped a panel whose rows quietly did nothing.
        needle = '"' + c["name"] + '"'
        for i, line in enumerate(src, start=1):
            if needle in line and "StepSpec" in line:
                steps[c["name"]] = i
                break
    evaluator = next((i for i, line in enumerate(src, start=1)
                      if line.startswith("def _fold_price")), None)
    entry = next((i for i, line in enumerate(src, start=1)
                  if line.startswith("def compose_price")), None)
    return {"steps": steps, "evaluator": evaluator, "entry": entry,
            "unresolved": [c["name"] for c in _PKG["manifest"]["composition"]
                           if c["name"] not in steps]}


# ═══════════════════════════════════════════════════════════════════════════════════════════
# THE REMAINING TAB SURFACES. SEPM by month, material unit price against the estimate, and
# supplier concentration. All three read rows the engine produced.
# ═══════════════════════════════════════════════════════════════════════════════════════════

DEFAULT_CONCENTRATION_THRESHOLD = Decimal("0.25")


def sepm_monthly_view(lot: int) -> dict[str, Any]:
    """Level-of-effort staffing across the lot's twelve months, with its own average.

    THE AVERAGE IS THE POINT. A total answers "how much"; the average line is what turns the
    series into a judgment, because a month is only heavy or light relative to the run. It is
    computed here rather than by the renderer for the usual reason: a mean is arithmetic.

    RECONCILIATION IS REPORTED, NOT ASSUMED. The monthly rows and the annual labor/sepm row are
    two statements about one quantity, and a view that showed the first without checking it
    against the second would let them drift silently.
    """
    rows = sorted(_rows_for(lot, "sepm_monthly"), key=lambda r: r["period"])
    months, total = [], Decimal("0")
    for r in rows:
        hours = Decimal(r["hours"])
        total += hours
        months.append({"period": r["period"], "value": float(hours),
                       "display": _money(hours), "cost": _money(Decimal(r["price"]))})
    average = (total / len(months)).quantize(Decimal("0.01")) if months else Decimal("0")
    for m in months:
        m["above_average"] = m["value"] > float(average)

    annual = next((Decimal(r["hours"]) for r in _rows_for(lot, "labor")
                   if r["sub_config"] == "sepm" and r["hours"]), None)
    return {
        "lot": lot,
        "months": months,
        "average": _money(average),
        "average_value": float(average),
        "total": _money(total),
        "peak": _money(max((Decimal(r["hours"]) for r in rows), default=Decimal("0"))),
        "annual_total": _money(annual) if annual is not None else "n/a",
        # STATED, so a mismatch is visible on the page rather than only in a test.
        "reconciles": annual is not None and annual == total,
        "months_above_average": sum(1 for m in months if m["above_average"]),
    }


def _rate_set_for(vintage: str, fiscal_year: int) -> dict[str, str]:
    return {r["category"]: r["rate"] for r in _PKG["dataset"]["rows"]["rates"]
            if r["vintage"] == vintage and r["fiscal_year"] == fiscal_year}


def material_view() -> dict[str, Any]:
    """Material cost per unit at each lot, priced at the applied AND the estimating rates.

    WHAT MOVES HERE IS THE BURDEN, NOT THE BUY. The material amount is what it is; the two
    columns differ only where the rate sets differ, so the comparison isolates the effect of
    rate movement on a purchased figure. Presenting it as "material got dearer" would be a
    different and false claim.

    A YEAR WITH ONE VINTAGE HAS NO SEPARATE ESTIMATE, and the row says so. Showing a zero
    difference for such a lot would read as "the estimate was exactly right" when the truth is
    that there is nothing to compare against - the same error as reporting an absent ratio
    as 0.000.
    """
    rows = []
    for lot in _PKG["lots"]:
        meta = _lot_meta(lot)
        material = next((Decimal(r["price"]) for r in _rows_for(lot, "material")), None)
        if material is None or not meta["quantity"]:
            continue
        applied_v, est_v = meta["applied_vintage"], meta["estimating_vintage"]
        applied = _rate_set_for(applied_v, meta["fiscal_year"])
        estimating = _rate_set_for(est_v, meta["fiscal_year"])
        distinct = est_v != applied_v and bool(estimating)

        def burdened(rs):
            # G&A, cost of money and profit reach material; fringe and overhead do not.
            base = material * Decimal(rs["escalation"])
            after_ga = base * (Decimal("1") + Decimal(rs["g_and_a"]))
            after_com = after_ga * (Decimal("1") + Decimal(rs["cost_of_money"]))
            return after_com * (Decimal("1") + Decimal(rs["profit"]))

        unit_applied = (burdened(applied) / meta["quantity"]).quantize(Decimal("0.01"))
        unit_est = ((burdened(estimating) / meta["quantity"]).quantize(Decimal("0.01"))
                    if distinct else None)
        rows.append({
            "lot": lot,
            "quantity": meta["quantity"],
            "material": _money(material),
            "unit_applied": _money(unit_applied),
            "unit_applied_value": float(unit_applied),
            "applied_vintage": applied_v,
            "estimating_vintage": est_v if distinct else None,
            "unit_estimating": _money(unit_est) if distinct else "n/a",
            "unit_estimating_value": float(unit_est) if distinct else None,
            "difference": _money(unit_applied - unit_est) if distinct else "n/a",
            "comparable": bool(distinct),
            "note": "" if distinct else "one rate vintage this year - no separate estimate",
        })
    values = [r["unit_applied_value"] for r in rows] + [
        r["unit_estimating_value"] for r in rows if r["unit_estimating_value"] is not None]
    return {
        "rows": rows,
        "y_max": max(values) if values else 0.0,
        "comparable_lots": sum(1 for r in rows if r["comparable"]),
    }


def supplier_view(lot: int, threshold=None) -> dict[str, Any]:
    """Purchased value by supplier, ranked, against a stated bound.

    THE BOUND TRAVELS WITH THE VERDICT and says whether the caller chose it - the same rule the
    engine verb follows, because "concentrated" is meaningless without the bound it was judged
    against.
    """
    defaulted = threshold is None or not str(threshold).strip()
    try:
        bound = DEFAULT_CONCENTRATION_THRESHOLD if defaulted else Decimal(str(threshold))
    except Exception:
        bound, defaulted = DEFAULT_CONCENTRATION_THRESHOLD, True
    if not (Decimal("0") < bound < Decimal("1")):
        bound, defaulted = DEFAULT_CONCENTRATION_THRESHOLD, True

    rows = _rows_for(lot, "supplier")
    purchased = sum((Decimal(r["price"]) for r in rows), Decimal("0"))
    if purchased <= 0:
        return {"lot": lot, "rows": [], "purchased": "0.00", "threshold": str(bound),
                "threshold_defaulted": defaulted, "above": 0, "largest_share": "n/a"}
    ranked = sorted(rows, key=lambda r: Decimal(r["price"]), reverse=True)
    out = []
    for r in ranked:
        amount = Decimal(r["price"])
        share = (amount / purchased).quantize(Decimal("0.0001"))
        out.append({"supplier": r["sub_config"], "amount": _money(amount),
                    "share": str(share), "share_pct": float(share) * 100,
                    "above_threshold": share > bound})
    return {
        "lot": lot,
        "rows": out,
        "purchased": _money(purchased),
        "threshold": str(bound),
        "threshold_defaulted": defaulted,
        "above": sum(1 for r in out if r["above_threshold"]),
        "largest_share": out[0]["share"] if out else "n/a",
    }
